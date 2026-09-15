"""v4 live promotion: trend gate, momentum gate, and advisory exit signals."""
import pytest

from desk import config, etf_options as eo, shadow


def test_live_spec_is_v4():
    spec = eo.load_spec()
    assert spec["experiment_id"] == "options_etf_universe_v4"
    assert spec["promotion_scope"].startswith("ADVISORY ONLY")


def test_put_side_structures_defined():
    assert eo.PUT_SPREAD in eo.PUT_SIDE_STRUCTURES
    assert eo.IRON_CONDOR in eo.PUT_SIDE_STRUCTURES
    assert eo.CALL_SPREAD not in eo.PUT_SIDE_STRUCTURES


def _ctx(lean, conviction=0.9, eruption=False):
    return {
        "qlib": {"ok": True, "age_hours": 1.0,
                 "data": {"promoted": False, "gate": {},
                          "assets": {"SPY": {"lean": lean, "conviction": conviction,
                                             "force": "equities", "horizons": {}}}}},
        "vol": {"ok": True, "shift": {"eruption_predicted": eruption, "calm_5d": True},
                "magnitude": {"magnitude_pct": 0.3}, "vrp": {"vrp_pct": 0.8}},
        "hq_macro": {"ok": True, "data": {}}, "macro_gpu": {"ok": False, "reason": "stale"},
    }


def _vol(above_sma=True, mom=0.02):
    return {"rv20": 0.2, "reference_spot": 100.0, "sma200": 95.0,
            "above_sma200": above_sma, "mom126": mom, "data_through": "2026-07-23"}


def test_trend_gate_blocks_put_side_below_sma200(monkeypatch):
    monkeypatch.setattr(eo, "load_context", lambda now=None: _ctx(1))
    monkeypatch.setattr(eo, "realized_vol_20", lambda p, n: _vol(above_sma=False))
    req = eo.build_request()
    assert req["status"] == "NO_TRADE"
    assert any("200-day" in r["reason"] for r in req["rejected_by_gate"])


def test_trend_gate_allows_put_side_above_sma200(monkeypatch):
    monkeypatch.setattr(eo, "load_context", lambda now=None: _ctx(1))
    monkeypatch.setattr(eo, "realized_vol_20", lambda p, n: _vol(above_sma=True))
    req = eo.build_request()
    assert req["status"] == "READY"
    assert req["eligible"][0]["structure"] == eo.PUT_SPREAD


def test_momentum_gate_blocks_calls_on_high_momentum(monkeypatch):
    monkeypatch.setattr(eo, "load_context", lambda now=None: _ctx(-1))
    monkeypatch.setattr(eo, "realized_vol_20", lambda p, n: _vol(mom=0.25))  # +25% > 10%
    req = eo.build_request()
    assert req["status"] == "NO_TRADE"
    assert any("momentum" in r["reason"] for r in req["rejected_by_gate"])


def test_momentum_gate_allows_calls_on_low_momentum(monkeypatch):
    monkeypatch.setattr(eo, "load_context", lambda now=None: _ctx(-1))
    monkeypatch.setattr(eo, "realized_vol_20", lambda p, n: _vol(mom=-0.05))
    req = eo.build_request()
    assert req["status"] == "READY"
    assert req["eligible"][0]["structure"] == eo.CALL_SPREAD


def test_exit_signal_target_stop_and_hold():
    assert shadow.exit_signal(100, -40)["action"] == "CLOSE_TARGET"   # buy back at 40% of credit
    assert shadow.exit_signal(100, -80)["action"] == "HOLD"
    assert shadow.exit_signal(100, -310)["action"] == "CLOSE_STOP"    # >= 3x credit
    assert shadow.exit_signal(-100, -40)["action"] == "HOLD"          # debit position: n/a


def test_exit_signal_thresholds_match_config():
    credit = 200.0
    at_target = -config.PROFIT_TARGET_FRAC * credit
    assert shadow.exit_signal(credit, at_target)["action"] == "CLOSE_TARGET"
    at_stop = -(1 + config.STOP_LOSS_MULT) * credit
    assert shadow.exit_signal(credit, at_stop)["action"] == "CLOSE_STOP"


def test_summary_exposes_exit_signals():
    assert "exit_signals" in shadow.summary()
