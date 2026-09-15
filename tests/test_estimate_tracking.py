"""Estimate-priced ETF tracking: build without live quotes, then live supersedes it."""
import json
from datetime import datetime, timezone

import pytest

from desk import config, etf_options as eo, shadow


NOW = datetime(2026, 7, 24, 13, 5, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SHADOW_OPEN", tmp_path / "open.json")
    monkeypatch.setattr(config, "ETF_ESTIMATE_FLAG", tmp_path / "est.json")
    monkeypatch.setattr(config, "ETF_OPTIONS_FLAG", tmp_path / "live.json")
    monkeypatch.setattr(config, "JOURNAL_DIR", tmp_path)
    # deterministic market premium factor; skip the qlib CSV read
    monkeypatch.setattr(eo, "_spy_premium_factor", lambda now: 1.30)
    return tmp_path


def _request():
    return {"request_id": "r1", "generated_at": NOW.isoformat(), "status": "READY",
            "eligible": [
                {"symbol": "SPY", "qlib_asset": "SPY", "bucket": "broad_equity",
                 "spread_width": 5.0, "structure": eo.PUT_SPREAD, "rv20": 0.16,
                 "reference_spot": 560.0, "qlib_lean": 1, "qlib_conviction": 0.9},
                {"symbol": "XLE", "qlib_asset": "XLE", "bucket": "sector",
                 "spread_width": 1.0, "structure": eo.CALL_SPREAD, "rv20": 0.28,
                 "reference_spot": 92.0, "qlib_lean": -1, "qlib_conviction": 0.8},
            ]}


def test_estimate_finalizer_builds_defined_risk_candidates():
    t = eo.finalize_estimate(_request(), NOW)
    assert t["action"] == "SELL_PREMIUM"
    assert t["pricing"] == "black_scholes_estimate"
    for c in t["candidates"]:
        assert c["source"] == "black_scholes_estimate" and c["enriched"] is False
        assert 0 < c["credit_usd"] < c["max_risk_usd"] + c["credit_usd"]
        assert c["gate"] == "not_cleared"


def test_estimate_publish_tracks_in_shadow_open():
    t = eo.finalize_estimate(_request(), NOW)
    eo.publish_estimate(t)
    opened = json.loads((config.SHADOW_OPEN).read_text())
    assert len(opened) == len(t["candidates"])
    assert all(row["entry_live"] is False for row in opened.values())
    assert all(row["entry_source"] == "black_scholes_estimate" for row in opened.values())


def test_no_ready_request_tracks_nothing():
    t = eo.finalize_estimate({"status": "NO_TRADE", "reason": "veto"}, NOW)
    assert t["action"] == "NO_TRADE" and t["candidates"] == []


def _live_ticket():
    # a live-quoted SPY put spread with DIFFERENT strikes than the BS estimate
    return {"date": "2026-07-24", "ts": NOW.isoformat(), "underlying": "LIQUID_ETF_UNIVERSE",
            "research_experiment": "options_etf_universe_v2",
            "candidates": [{
                "underlying": "SPY", "strategy": eo.PUT_SPREAD, "expiry": "2026-09-18",
                "credit_usd": 150.0, "max_risk_usd": 350.0, "enriched": True,
                "source": "robinhood_natural_bid_ask", "research_experiment": "options_etf_universe_v2",
                "legs": [{"side": "sell", "type": "put", "strike": 555},
                         {"side": "buy", "type": "put", "strike": 550}]}]}


def test_live_supersedes_same_day_estimate_positions():
    # 1) estimate track for the day (SPY + XLE)
    eo.publish_estimate(eo.finalize_estimate(_request(), NOW))
    before = json.loads(config.SHADOW_OPEN.read_text())
    assert len(before) == 2

    # 2) live run publishes a real SPY spread (different strikes -> different id)
    eo.publish(_live_ticket())
    after = json.loads(config.SHADOW_OPEN.read_text())

    live = [r for r in after.values() if r["entry_live"]]
    estimates = [r for r in after.values() if not r["entry_live"]]
    assert len(live) == 1 and live[0]["underlying"] == "SPY"
    # SPY estimate superseded by the live SPY fill; XLE estimate (no live) survives
    assert {r["underlying"] for r in estimates} == {"XLE"}


def test_supersede_scoped_to_etf_experiment_only():
    """A non-ETF (SPY-lane) estimate open must never be superseded by an ETF live run."""
    spy_lane = {"candidate_id": "spy1", "entry_live": False, "signal_date": "2026-07-24",
                "research_experiment": None, "underlying": "SPY"}
    config.SHADOW_OPEN.write_text(json.dumps({"spy1": spy_lane}), encoding="utf-8")
    eo.publish(_live_ticket())
    after = json.loads(config.SHADOW_OPEN.read_text())
    assert "spy1" in after      # untouched


def test_late_authoritative_veto_retracts_same_day_etf_openings():
    eo.publish_estimate(eo.finalize_estimate(_request(), NOW))
    eo.publish(_live_ticket())
    opened = json.loads(config.SHADOW_OPEN.read_text())
    assert any(row.get("research_experiment") == "options_etf_universe_v2"
               for row in opened.values())

    veto = {"date": "2026-07-24", "ts": NOW.isoformat(),
            "underlying": "LIQUID_ETF_UNIVERSE", "action": "NO_TRADE",
            "reason": "fresh eruption veto", "candidates": [],
            "research_experiment": "options_etf_universe_v2"}
    eo.publish(veto)
    after = json.loads(config.SHADOW_OPEN.read_text())

    assert not any(row.get("research_experiment") == "options_etf_universe_v2"
                   for row in after.values())
