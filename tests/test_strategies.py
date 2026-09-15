"""Strategy builders (economics sanity + jade-lizard invariant) and selection matrix."""
from datetime import datetime, timezone

from desk import config, strategies as S

EXP, DTE = S.target_expiry(datetime(2026, 7, 21, tzinfo=timezone.utc))
SPOT, SIG = 750.0, 0.16


def _sig(vrp_pct=0.8, mag_pct=0.3, erupt=False, calm5=True, calm21=True, term=0.95):
    return {"ok": True, "reason": "fresh",
            "vrp": {"spot": SPOT, "vix": 16.0, "vrp_pct": vrp_pct},
            "shift": {"eruption_predicted": erupt, "calm_5d": calm5, "calm_21d": calm21},
            "magnitude": {"magnitude_pct": mag_pct, "expected_move_usd": 7.5},
            "vol_surface": {"term_ratio": term}}


def _sel(sig):
    """Select under the v3 LIVE policy (magnitude advisory, $1000 cap) that run_desk uses."""
    return S.select(sig, magnitude_blocks=False, risk_cap=config.MAX_TRADE_RISK_USD)


def test_target_expiry_in_window():
    for m in range(1, 13):
        exp, dte = S.target_expiry(datetime(2026, m, 10, tzinfo=timezone.utc))
        assert config.DTE_MIN <= dte <= config.DTE_MAX


def test_short_put_economics():
    c = S.build_short_put(SPOT, SIG, DTE, EXP)
    assert c["credit_usd"] > 0 and c["max_risk_usd"] > 0
    assert float(c["breakevens"]) < c["legs"][0]["strike"] < SPOT   # OTM put, BE below strike


def test_put_spread_risk_bounded_by_width():
    c = S.build_short_put_spread(SPOT, SIG, DTE, EXP)
    assert c["credit_usd"] > 0
    assert c["max_risk_usd"] <= config.PUT_SPREAD_WIDTH * S.CONTRACT


def test_jade_lizard_no_upside_risk_invariant():
    c = S.build_jade_lizard(SPOT, SIG, DTE, EXP)
    # If emitted, net credit MUST cover the short-call-spread width (no upside risk).
    if c is not None:
        assert c["credit_usd"] >= config.CALL_SPREAD_WIDTH * S.CONTRACT
        assert "up none" in c["breakevens"]


def test_jade_lizard_dropped_when_invariant_impossible():
    # near-zero IV -> premiums collapse -> net credit < width -> must return None
    assert S.build_jade_lizard(SPOT, 0.01, DTE, EXP) is None


def test_long_vol_debit_equals_risk():
    c = S.build_long_vol(SPOT, SIG, DTE, EXP, 7.5)
    assert c["debit_usd"] > 0 and c["max_risk_usd"] == c["debit_usd"]


def test_select_sell_premium_keeps_only_capped_defined_risk():
    t = _sel(_sig(vrp_pct=0.85, mag_pct=0.30))
    assert t["action"] == "SELL_PREMIUM"
    strats = {c["strategy"] for c in t["candidates"]}
    # $1000 cap drops the cash-secured put (~strike*100 risk); the spread survives
    assert "short_put_spread" in strats
    assert "short_put_csp" not in strats
    assert all(c["max_risk_usd"] <= S.config.MAX_TRADE_RISK_USD for c in t["candidates"])
    assert t["size_hint"] == "normal"


def test_select_big_move_advises_reduce_size_not_veto():
    # v3: high magnitude no longer blocks; it advises smaller size
    t = _sel(_sig(vrp_pct=0.85, mag_pct=0.92))
    assert t["action"] == "SELL_PREMIUM"
    assert t["size_hint"] == "reduce_size"
    assert "reduce size" in t["reason"]


def test_select_eruption_still_blocks_premium_selling():
    t = _sel(_sig(vrp_pct=0.85, mag_pct=0.30, erupt=True, calm21=True))
    assert t["action"] != "SELL_PREMIUM"     # eruption path never sells premium


def test_select_long_vol_on_eruption_cheap():
    t = _sel(_sig(vrp_pct=0.30, erupt=True, calm21=True))
    # LONG_VOL is selected, but an ATM straddle debit exceeds the $1000 cap, so the
    # capped desk honestly reports NO_TRADE rather than a trade it would size past the cap.
    assert t["action"] == "NO_TRADE" and "per-trade cap" in t["reason"]


def test_select_neutral_when_signal_not_ok():
    t = _sel({"ok": False, "reason": "signal stale (100h)"})
    assert t["action"] == "NO_TRADE" and "stale" in t["reason"]


def test_backwardation_tilts_long_vol():
    t = _sel(_sig(erupt=True, vrp_pct=0.3, term=1.15))
    assert t["pairs_tilt"]["tilt"] == "long_vol"
