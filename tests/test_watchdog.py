"""P9 watchdog: miss detection, veto-vs-miss discrimination, and no-trade-ideas policy."""
import json
from datetime import datetime, timezone

import pytest

from desk import watchdog

FRIDAY = datetime(2026, 7, 24, 14, 30, tzinfo=timezone.utc)     # weekday, after 09:35 NY
BEFORE_LOCAL = datetime(2026, 7, 24, 13, 4, tzinfo=timezone.utc)
BEFORE_LIVE_DEADLINE = datetime(2026, 7, 24, 13, 45, tzinfo=timezone.utc)
SATURDAY = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog.config, "FLAGS_DIR", tmp_path)
    monkeypatch.setattr(watchdog.config, "ETF_OPTIONS_REQUEST", tmp_path / "req.json")
    monkeypatch.setattr(watchdog.config, "ETF_OPTIONS_FLAG", tmp_path / "flag.json")
    monkeypatch.setattr(watchdog, "STAMP", tmp_path / "stamp.json")
    return tmp_path


def _write(path, obj):
    path.write_text(json.dumps(obj), encoding="utf-8")


def _req(status="READY", when="2026-07-24T13:05:00+00:00", rid="r1", eligible=("SPY",)):
    return {"request_id": rid, "generated_at": when, "status": status,
            "reason": "test", "eligible": [{"symbol": s} for s in eligible]}


def _flag(when="2026-07-24T13:40:00+00:00", rid="r1", action="SELL_PREMIUM"):
    return {"ts": when, "request_id": rid, "action": action, "reason": "ok"}


def test_weekend_is_skipped(_isolate):
    assert watchdog.check(SATURDAY)["status"] == watchdog.SKIP


def test_missing_request_is_a_miss(_isolate):
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.MISS and r["stage"] == "local_request"


def test_missing_request_before_local_deadline_is_pending(_isolate):
    r = watchdog.check(BEFORE_LOCAL)
    assert r["status"] == watchdog.PENDING and r["stage"] == "local_request"


def test_stale_request_is_a_miss(_isolate):
    _write(_isolate / "req.json", _req(when="2026-07-20T13:05:00+00:00"))
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.MISS and "not today" in r["reason"]


def test_deterministic_veto_with_published_flag_is_ok(_isolate):
    """A local NO_TRADE veto legitimately completes the lane - not a miss."""
    _write(_isolate / "req.json", _req(status="NO_TRADE"))
    _write(_isolate / "flag.json", _flag(action="NO_TRADE"))
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.OK and r["stage"] == "local_veto"


def test_veto_without_published_flag_is_a_miss(_isolate):
    _write(_isolate / "req.json", _req(status="NO_TRADE"))
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.MISS and r["stage"] == "local_publish"


def test_ready_without_result_is_a_live_miss(_isolate):
    _write(_isolate / "req.json", _req(status="READY", eligible=("SLV", "QQQ")))
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.MISS and r["stage"] == "live_validation"
    assert r["eligible"] == ["SLV", "QQQ"]


def test_ready_without_result_before_live_deadline_is_pending(_isolate):
    _write(_isolate / "req.json", _req(status="READY", eligible=("SLV", "QQQ")))
    r = watchdog.check(BEFORE_LIVE_DEADLINE)
    assert r["status"] == watchdog.PENDING and r["stage"] == "live_validation"
    assert r["eligible"] == ["SLV", "QQQ"]


def test_ready_with_mismatched_request_id_is_a_miss(_isolate):
    _write(_isolate / "req.json", _req(rid="r2"))
    _write(_isolate / "flag.json", _flag(rid="r1"))
    r = watchdog.check(FRIDAY)
    assert r["status"] == watchdog.MISS and "stale request" in r["reason"]


def test_completed_live_run_is_ok(_isolate):
    _write(_isolate / "req.json", _req())
    _write(_isolate / "flag.json", _flag())
    assert watchdog.check(FRIDAY)["status"] == watchdog.OK


def test_corrupt_files_do_not_raise(_isolate):
    (_isolate / "req.json").write_text("{not json", encoding="utf-8")
    assert watchdog.check(FRIDAY)["status"] == watchdog.MISS


def test_miss_alert_contains_no_trade_ideas(_isolate):
    _write(_isolate / "req.json", _req(status="READY", eligible=("SLV",)))
    text = watchdog.format_miss(watchdog.check(FRIDAY))
    assert "MISSED RUN" in text
    assert "No trade ideas are included" in text
    # never leak strikes/prices/credits into a miss alert
    for banned in ("credit", "strike", "$"):
        assert banned not in text.lower()


def test_miss_alert_is_idempotent_per_day(_isolate, monkeypatch):
    _write(_isolate / "req.json", _req(status="READY"))
    sent = []
    monkeypatch.setattr(watchdog, "telegram_notify", None, raising=False)
    import desk.telegram_notify as tn
    monkeypatch.setattr(tn, "send_message", lambda text, **kw: (sent.append(text), (True, None))[1])
    first = watchdog.run(FRIDAY, telegram=True)
    second = watchdog.run(FRIDAY, telegram=True)
    assert first["notified"] == "sent"
    assert "suppressed" in second["notified"]
    assert len(sent) == 1


def test_ok_status_never_notifies(_isolate, monkeypatch):
    _write(_isolate / "req.json", _req())
    _write(_isolate / "flag.json", _flag())
    import desk.telegram_notify as tn
    monkeypatch.setattr(tn, "send_message", lambda *a, **k: pytest.fail("must not notify on OK"))
    assert watchdog.run(FRIDAY, telegram=True)["status"] == watchdog.OK
