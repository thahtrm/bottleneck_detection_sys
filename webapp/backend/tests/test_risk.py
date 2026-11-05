from datetime import UTC, datetime, timedelta

from erw.domain.risk import aggregate
from erw.domain.types import Deadline, Factor, Level, ModelSignals, Thresholds

NOW = datetime(2026, 11, 4, tzinfo=UTC)
DL = Deadline("duedate", NOW + timedelta(days=5), "x")
TH = Thresholds()


def F(i):
    return Factor(i, i, "", "changelog")


def MS(p_delay=None, finish=None):
    return ModelSignals(p_delay=p_delay, predicted_finish=finish, is_critical=False, crit_score=None)


def test_no_signals_low():
    assert aggregate([], None, DL, TH, "active") is Level.LOW
    assert aggregate([], MS(0.1), DL, TH, "active") is Level.LOW


def test_overdue_alone_is_high():
    assert aggregate([F("overdue")], None, DL, TH, "active") is Level.HIGH


def test_two_rules_high():
    assert aggregate([F("blocked"), F("stagnant")], None, DL, TH, "active") is Level.HIGH


def test_one_rule_med():
    assert aggregate([F("stagnant")], None, DL, TH, "active") is Level.MED


def test_blocked_long_not_double_counted():
    assert aggregate([F("blocked"), F("blocked_long")], None, DL, TH, "active") is Level.MED


def test_one_rule_plus_overrun_high():
    m = MS(0.1, DL.at + timedelta(days=1))
    assert aggregate([F("stagnant")], m, DL, TH, "active") is Level.HIGH


def test_one_rule_plus_high_p_high():
    assert aggregate([F("stagnant")], MS(0.6), DL, TH, "active") is Level.HIGH
    assert aggregate([F("stagnant")], MS(0.59), DL, TH, "active") is Level.MED


def test_overrun_alone_med():
    assert aggregate([], MS(0.1, DL.at + timedelta(days=1)), DL, TH, "active") is Level.MED
    assert aggregate([], MS(0.1, DL.at), DL, TH, "active") is Level.LOW


def test_p_delay_alone_medium_never_high():
    assert aggregate([], MS(p_delay=0.95), DL, TH, "active") is Level.MED
    assert aggregate([], MS(p_delay=0.39), DL, TH, "active") is Level.MED
    assert aggregate([], MS(p_delay=0.38), DL, TH, "active") is Level.LOW


def test_shadow_mode_ignores_model():
    assert aggregate([], MS(p_delay=0.95), DL, TH, "shadow") is Level.LOW
    assert aggregate([F("stagnant")], MS(0.95), DL, TH, "shadow") is Level.MED


def test_done_or_deleted_is_low():
    from tests.test_rules import tl
    assert aggregate([F("overdue")], MS(0.9), DL, TH, "active", tl=tl(status_category="done")) is Level.LOW
    assert aggregate([F("overdue")], None, DL, TH, "active", tl=tl(deleted_at=NOW)) is Level.LOW
