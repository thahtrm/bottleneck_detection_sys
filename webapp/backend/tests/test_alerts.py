from datetime import UTC, datetime, timedelta

from erw.domain.types import Level
from erw.models import Issue, Notification, RiskState
from erw.pipeline import evaluate
from erw.pipeline.alerts import AlertSpec, alerts_for, dispatch, notify
from erw.pipeline.evaluate import RiskChange

NOW = datetime(2026, 11, 4, 3, 0, tzinfo=UTC)


class FakeSender:
    def __init__(self, fail=False):
        self.texts, self.fail = [], fail

    @property
    def calls(self):
        return len(self.texts)

    def post(self, text):
        if self.fail:
            raise RuntimeError("boom")
        self.texts.append(text)


def chg(prev=None, lvl=Level.HIGH, is_new=False, nb=False, cc=False, key="DEMO-1"):
    return RiskChange(key, "DEMO", prev, lvl, is_new, nb, cc)


def spec(key="DEMO-1", kind="risk_new", dedup=None):
    return AlertSpec(kind, key, "DEMO", Level.HIGH, dedup or f"{kind}:{key}:HIGH")


def test_alerts_for_level_up():
    assert [a.kind for a in alerts_for(chg(prev=Level.MED))] == ["risk_up"]


def test_alerts_for_new_high_and_medium():
    assert [a.kind for a in alerts_for(chg(is_new=True))] == ["risk_new"]
    assert alerts_for(chg(is_new=True, lvl=Level.MED)) == []


def test_alerts_for_no_change_and_decrease():
    assert alerts_for(chg(prev=Level.HIGH)) == []
    assert alerts_for(chg(prev=Level.HIGH, lvl=Level.MED)) == []


def test_alerts_for_blocked_and_critical():
    out = alerts_for(chg(prev=Level.HIGH, nb=True, cc=True))
    assert [a.kind for a in out] == ["blocked", "critical"]
    assert out[1].dedup_key == "critical:DEMO-1:HIGH"


def test_duplicate_alert_suppressed(session):
    s = FakeSender()
    assert notify(session, spec(), "x", s, NOW, 20) == "sent"
    assert notify(session, spec(), "x", s, NOW, 20) == "duplicate" and s.calls == 1


def test_rate_limit(session):
    s = FakeSender()
    assert notify(session, spec("A-1"), "x", s, NOW, 2) == "sent"
    assert notify(session, spec("A-2"), "x", s, NOW, 2) == "sent"
    assert notify(session, spec("A-3"), "x", s, NOW, 2) == "rate_limited"
    assert s.calls == 2
    row = session.query(Notification).filter_by(issue_key="A-3").one()
    assert row.status == "rate_limited"
    # an hour later the window is free again
    assert notify(session, spec("A-4"), "x", s, NOW + timedelta(minutes=61), 2) == "sent"


def test_failed_send_recorded_and_retried(session):
    assert notify(session, spec(), "x", FakeSender(fail=True), NOW, 20) == "failed"
    assert session.query(Notification).one().status == "failed"
    ok = FakeSender()
    assert notify(session, spec(), "x", ok, NOW, 20) == "sent" and ok.calls == 1
    assert session.query(Notification).one().status == "sent"


def test_disabled_without_url(session):
    assert notify(session, spec(), "x", None, NOW, 20) == "disabled"
    assert session.query(Notification).one().status == "disabled"


def _seed(session, key="DEMO-1", level="HIGH", factors=None):
    session.add(Issue(key=key, project_key="DEMO", summary="S"))
    session.add(RiskState(issue_key=key, level=level, factors=factors or [], deadline_label="d"))
    session.flush()


def test_dispatch_sends_and_updates_last_alerted(session, settings):
    _seed(session)
    s = FakeSender()
    dispatch(session, [chg(is_new=True)], NOW, settings, sender=s)
    assert s.calls == 1 and s.texts[0].startswith("[Nguy cơ trễ][DEMO]")
    assert session.get(RiskState, "DEMO-1").last_alerted_level == "HIGH"
    dispatch(session, [chg(is_new=True)], NOW, settings, sender=s)
    assert s.calls == 1


def test_dispatch_blocked_dedup_uses_blocker_keys(session, settings):
    f = [{"id": "blocked", "label": "Bị block", "value": "DEMO-9,DEMO-2", "source": "rule"}]
    _seed(session, factors=f)
    s = FakeSender()
    dispatch(session, [chg(prev=Level.HIGH, nb=True)], NOW, settings, sender=s)
    assert session.query(Notification).one().dedup_key == "blocked:DEMO-1:DEMO-9,DEMO-2"


def test_dispatch_not_updated_when_failed(session, settings):
    _seed(session)
    dispatch(session, [chg(is_new=True)], NOW, settings, sender=FakeSender(fail=True))
    assert session.get(RiskState, "DEMO-1").last_alerted_level is None


def test_dispatch_without_webhook_url_disabled(session, settings):
    _seed(session)
    dispatch(session, [chg(is_new=True)], NOW, settings.model_copy(update={"slack_webhook_url": ""}))
    assert session.query(Notification).one().status == "disabled"
    assert session.get(RiskState, "DEMO-1").last_alerted_level is None


def test_create_app_registers_dispatch(client):
    from erw.pipeline import alerts

    assert evaluate._dispatch is alerts.dispatch
