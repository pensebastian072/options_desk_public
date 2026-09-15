"""signal_read fail-safe: missing / corrupt / stale / no-vrp all -> neutral, never raise."""
import json
from datetime import datetime, timedelta, timezone

from desk import signal_read


def _write(tmp_path, obj):
    p = tmp_path / "vol_desk_state.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_missing_file_is_neutral(tmp_path):
    r = signal_read.read_signal(tmp_path / "nope.json")
    assert r["ok"] is False and "missing" in r["reason"]


def test_corrupt_file_is_neutral(tmp_path):
    p = tmp_path / "vol_desk_state.json"
    p.write_text("{not json", encoding="utf-8")
    r = signal_read.read_signal(p)
    assert r["ok"] is False and "unreadable" in r["reason"]


def test_stale_is_neutral(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()
    p = _write(tmp_path, {"ts": old, "vrp": {"spot": 750, "vix": 16}})
    r = signal_read.read_signal(p)
    assert r["ok"] is False and "stale" in r["reason"]


def test_fresh_ok(tmp_path):
    now = datetime.now(timezone.utc).isoformat()
    p = _write(tmp_path, {"ts": now, "underlying": "SPY",
                          "vrp": {"spot": 750.0, "vix": 16.0, "vrp_pct": 0.8},
                          "shift": {"eruption_predicted": False, "calm_5d": True},
                          "magnitude": {"magnitude_pct": 0.3}})
    r = signal_read.read_signal(p)
    assert r["ok"] is True
    assert r["vrp"]["vrp_pct"] == 0.8
    assert r["magnitude"]["magnitude_pct"] == 0.3
