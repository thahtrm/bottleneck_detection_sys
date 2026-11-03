import httpx
import pytest
import respx

from erw.domain.types import Level
from erw.integrations.slack import SlackError, SlackSender, escape, format_alert
from erw.models import Issue, RiskState
from erw.pipeline.alerts import AlertSpec


@pytest.fixture
def S(settings):
    return settings.model_copy(update={"pm_name_by_project": {"DEMO": "Trần PM"}})


def issue(summary="Fix", assignee_name="Nguyễn Văn An", assignee_id="u1"):
    return Issue(key="DEMO-1", project_key="DEMO", summary=summary, assignee_name=assignee_name, assignee_id=assignee_id)


def rs(delay=0.81, factors=None):
    return RiskState(
        issue_key="DEMO-1", level="HIGH", delay_value=delay, deadline_label="Trễ sprint Sprint 24 (04/11)",
        factors=factors if factors is not None else [{"id": "a", "label": "Lâu", "value": "5 ngày", "source": "rule"}],
    )


def spec(kind="risk_new"):
    return AlertSpec(kind, "DEMO-1", "DEMO", Level.HIGH, f"{kind}:DEMO-1:HIGH")


def test_escape():
    assert escape("a & <b>") == "a &amp; &lt;b&gt;"


def test_format_escapes_slack_control_chars(S):
    t = format_alert(spec(), issue(summary="Fix <b> & 🚀 lỗi đối soát"), rs(), S)
    assert "&lt;b&gt; &amp; 🚀 lỗi đối soát" in t and t.startswith("[Nguy cơ trễ][DEMO]")
    assert "<https://example.atlassian.net/browse/DEMO-1|DEMO-1>" in t
    assert "Cao 81%" in t
    assert "Lý do: Lâu 5 ngày" in t
    assert "<http://localhost:8000/issues/DEMO-1|Mở trên Early Risk>" in t


def test_format_contains_deadline_label_and_mention(S):
    t = format_alert(spec(), issue(), rs(), S)
    assert "Trễ sprint Sprint 24 (04/11)" in t and "@Nguyễn Văn An" in t


def test_no_percent_when_no_model_value(S):
    t = format_alert(spec(), issue(), rs(delay=None), S)
    assert "%" not in t and "Cao ·" in t


def test_unassigned(S):
    t = format_alert(spec(), issue(assignee_name=None, assignee_id=None), rs(), S)
    assert "@chưa giao" in t


def test_pm_mention_for_risk_up_and_missing_pm(S, settings):
    assert "@Trần PM" in format_alert(spec("risk_up"), issue(), rs(), S)
    assert "@Nguyễn Văn An" not in format_alert(spec("critical"), issue(), rs(), S)
    t = format_alert(spec("critical"), issue(), rs(), settings)
    assert t.startswith("[Quan trọng]") and "@" not in t.split("\n")[0]


def test_max_three_factors(S):
    fs = [{"id": str(i), "label": f"L{i}", "value": "v", "source": "r"} for i in range(5)]
    t = format_alert(spec(), issue(), rs(factors=fs), S)
    assert "L2 v" in t and "L3" not in t


@respx.mock
def test_sender_posts_json():
    r = respx.post("https://h.test/x").mock(return_value=httpx.Response(200))
    SlackSender("https://h.test/x").post("hi")
    import json

    assert json.loads(r.calls[0].request.content) == {"text": "hi"}


@respx.mock
def test_sender_retries_then_succeeds():
    r = respx.post("https://h.test/x").mock(side_effect=[httpx.Response(429), httpx.Response(503), httpx.Response(200)])
    SlackSender("https://h.test/x", backoff=0).post("hi")
    assert r.call_count == 3


@respx.mock
def test_sender_gives_up_after_three():
    r = respx.post("https://h.test/x").mock(return_value=httpx.Response(500))
    with pytest.raises(SlackError):
        SlackSender("https://h.test/x", backoff=0).post("hi")
    assert r.call_count == 3


@respx.mock
def test_sender_no_retry_on_400():
    r = respx.post("https://h.test/x").mock(return_value=httpx.Response(400))
    with pytest.raises(SlackError):
        SlackSender("https://h.test/x", backoff=0).post("hi")
    assert r.call_count == 1
