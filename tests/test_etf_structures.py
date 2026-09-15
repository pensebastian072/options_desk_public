"""P8: regime routing + call-spread / iron-condor structures and their invariants."""
from datetime import datetime, timezone

import pytest

from desk import etf_options as eo

NOW = datetime(2026, 7, 23, 14, 0, tzinfo=timezone.utc)
EXPIRY = "2026-09-18"


def _spec():
    return eo.load_spec()


def _routing():
    return _spec()["entry_policy"]["structure_routing"]


def _leg(strike, kind, bid, ask, delta, iv=0.30):
    return {"strike": strike, "type": kind, "bid_price": bid, "ask_price": ask,
            "delta": delta, "implied_volatility": iv, "open_interest": 5000,
            "volume": 500, "updated_at": NOW.isoformat()}


def _row(structure, width=5.0, rv=0.20):
    return {"symbol": "SPY", "qlib_asset": "SPY", "bucket": "broad_equity",
            "spread_width": width, "structure": structure, "rv20": rv,
            "qlib_lean": 1, "qlib_conviction": 0.9}


# ── routing ──────────────────────────────────────────────────────────

def test_routing_maps_lean_to_one_structure():
    r = _routing()
    assert eo.route_structure(1, r) == eo.PUT_SPREAD
    assert eo.route_structure(-1, r) == eo.CALL_SPREAD
    assert eo.route_structure(0, r) == eo.IRON_CONDOR


def test_routing_rejects_unknown_lean():
    r = _routing()
    assert eo.route_structure(None, r) is None
    assert eo.route_structure("up", r) is None
    assert eo.route_structure(7, r) is None


def test_iron_condor_requires_richer_iv_than_directional():
    rules = _spec()["entry_policy"]
    assert eo._min_iv_rv(eo.IRON_CONDOR, rules) > eo._min_iv_rv(eo.PUT_SPREAD, rules)


# ── call spread ──────────────────────────────────────────────────────

def test_call_spread_builds_and_prices_naturally():
    market = {"symbol": "SPY", "expiry": EXPIRY,
              "short_call": _leg(760, "call", 6.00, 6.20, 0.30),
              "long_call": _leg(765, "call", 4.00, 4.20, 0.24)}
    c, err = eo._candidate(market, _row(eo.CALL_SPREAD), _spec(), NOW)
    assert err is None and c is not None
    assert c["strategy"] == eo.CALL_SPREAD
    # natural credit = short bid - long ask = 6.00 - 4.20
    assert c["credit_usd"] == pytest.approx(180.0, abs=0.5)
    assert c["max_risk_usd"] == pytest.approx(5.0 * 100 - 180.0, abs=0.5)
    assert float(c["breakevens"]) > 760            # breakeven above the short call


def test_call_spread_rejects_inverted_strikes():
    market = {"symbol": "SPY", "expiry": EXPIRY,
              "short_call": _leg(760, "call", 6.00, 6.20, 0.30),
              "long_call": _leg(755, "call", 8.00, 8.20, 0.36)}
    c, err = eo._candidate(market, _row(eo.CALL_SPREAD), _spec(), NOW)
    assert c is None and "strike ordering" in err


def test_call_spread_delta_band_enforced():
    market = {"symbol": "SPY", "expiry": EXPIRY,
              "short_call": _leg(760, "call", 6.00, 6.20, 0.55),   # too deep
              "long_call": _leg(765, "call", 4.00, 4.20, 0.40)}
    c, err = eo._candidate(market, _row(eo.CALL_SPREAD), _spec(), NOW)
    assert c is None and "delta" in err


# ── iron condor ──────────────────────────────────────────────────────

def _condor_market():
    return {"symbol": "SPY", "expiry": EXPIRY,
            "short_put": _leg(720, "put", 5.00, 5.20, -0.30, iv=0.30),
            "long_put": _leg(715, "put", 3.50, 3.70, -0.24, iv=0.30),
            "short_call": _leg(770, "call", 5.00, 5.20, 0.30, iv=0.30),
            "long_call": _leg(775, "call", 3.50, 3.70, 0.24, iv=0.30)}


def test_iron_condor_risk_is_widest_side_not_sum():
    c, err = eo._candidate(_condor_market(), _row(eo.IRON_CONDOR), _spec(), NOW)
    assert err is None and c is not None
    assert len(c["legs"]) == 4
    # both sides credit 5.00 - 3.70 = 1.30 -> total 2.60; only one side can lose
    assert c["credit_usd"] == pytest.approx(260.0, abs=1.0)
    assert c["max_risk_usd"] == pytest.approx(5.0 * 100 - 260.0, abs=1.0)
    assert "down" in c["breakevens"] and "up" in c["breakevens"]


def test_iron_condor_rejected_when_credit_exceeds_width():
    market = _condor_market()
    market["short_put"] = _leg(720, "put", 9.00, 9.20, -0.30)
    market["short_call"] = _leg(770, "call", 9.00, 9.20, 0.30)
    c, err = eo._candidate(market, _row(eo.IRON_CONDOR), _spec(), NOW)
    assert c is None and "exceeds structure width" in err


def test_iron_condor_uses_stricter_iv_rv_floor():
    market = _condor_market()
    # IV 0.21 vs RV 0.20 -> ratio 1.05, clears nothing; below the 1.20 condor floor
    for key in ("short_put", "long_put", "short_call", "long_call"):
        market[key]["implied_volatility"] = 0.21
    c, err = eo._candidate(market, _row(eo.IRON_CONDOR), _spec(), NOW)
    assert c is None and "IV/RV" in err


# ── no structure shopping ────────────────────────────────────────────

def test_routed_structure_is_not_substituted():
    """A symbol routed to a call spread must fail if only put legs are supplied."""
    market = {"symbol": "SPY", "expiry": EXPIRY,
              "short_put": _leg(720, "put", 5.00, 5.20, -0.30),
              "long_put": _leg(715, "put", 3.50, 3.70, -0.24)}
    c, err = eo._candidate(market, _row(eo.CALL_SPREAD), _spec(), NOW)
    assert c is None and "call" in err


def test_put_spread_still_works_after_refactor():
    market = {"symbol": "SPY", "expiry": EXPIRY,
              "short_put": _leg(720, "put", 5.00, 5.20, -0.30),
              "long_put": _leg(715, "put", 3.50, 3.70, -0.24)}
    c, err = eo._candidate(market, _row(eo.PUT_SPREAD), _spec(), NOW)
    assert err is None and c["strategy"] == eo.PUT_SPREAD
    assert c["credit_usd"] == pytest.approx(130.0, abs=0.5)
    assert float(c["breakevens"]) < 720


def test_v2_frozen_universe_audit_record():
    import json
    from desk import config
    v2 = json.loads((config.EXPERIMENTS_DIR / "options_etf_universe_v2.json").read_text(encoding="utf-8"))
    universe = v2["scope"]["candidate_universe"]
    assert v2["experiment_id"] == "options_etf_universe_v2"
    assert len(universe) == 31
    structures = v2["scope"]["structures"]
    assert v2["trial_accounting"]["n_trials"] == len(universe) * len(structures)
    assert universe["SLV"]["spread_width"] == 1.0
    assert universe["XLF"]["spread_width"] == 1.0
    assert universe["TLT"]["spread_width"] == 2.0


def test_active_spec_is_v4_with_advisory_veto_cap_and_live_gates():
    spec = _spec()   # load_spec() -> the ACTIVE experiment (v4, the live promotion)
    assert spec["experiment_id"] == "options_etf_universe_v4"
    # v4 promotes the researched gates into the live lane
    assert "trend_gate" in spec["entry_policy"] and "call_momentum_gate" in spec["entry_policy"]
    assert spec["exit_policy"]["advisory_only"] is True
    assert len(spec["scope"]["candidate_universe"]) == 31          # same frozen universe
    ep = spec["entry_policy"]
    assert "global_veto" not in ep and "hard_veto" in ep          # magnitude no longer a hard block
    assert ep["hard_veto"]["eruption_predicted"] is False
    assert spec["portfolio_policy"]["max_trade_risk_usd"] == 1000
