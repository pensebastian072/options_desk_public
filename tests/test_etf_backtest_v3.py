"""P14 v3 backtest: structures, POP, eruption-only veto, lean routing, 50%-target exit."""
from datetime import date

import numpy as np
import pandas as pd
import pytest

from desk import bs, etf_backtest as eb

EXP = date(2026, 9, 18)
DTE = 57


def test_pop_at_expiry_30delta_put_spread_above_floor():
    c = eb.build_structure(eb.PUT_SPREAD, 500.0, 0.20, 5.0, DTE, EXP)
    assert c is not None
    # a ~30-delta short put spread should clear the 51% POP floor comfortably
    assert c["pop"] >= 0.51
    assert "put" in c["breakevens"]


def test_call_spread_economics_and_breakeven():
    c = eb.build_call_spread(500.0, 0.20, 5.0, DTE, EXP)
    assert c is not None and c["strategy"] == eb.CALL_SPREAD
    short = next(l for l in c["legs"] if l["side"] == "sell")
    long = next(l for l in c["legs"] if l["side"] == "buy")
    assert long["strike"] - short["strike"] == 5.0        # long higher for a call spread
    assert 0 < c["credit_usd"] < 5.0 * eb.CONTRACT
    assert c["max_risk_usd"] == pytest.approx(5.0 * eb.CONTRACT - c["credit_usd"], abs=0.01)


def test_iron_condor_30delta_filtered_by_pop_floor():
    # HONEST CONSEQUENCE: a 30-delta iron condor has ~40% at-expiry POP, below the 51%
    # floor, so build_structure drops it. Condors effectively do not trade under POP>=0.51.
    c = eb.build_structure(eb.IRON_CONDOR, 500.0, 0.22, 5.0, DTE, EXP)
    assert c is None


def test_iron_condor_math_when_pop_bypassed(monkeypatch):
    # verify the 4-leg structure/risk math independent of the POP filter
    monkeypatch.setattr(eb, "MIN_POP", 0.0)
    c = eb.build_iron_condor(500.0, 0.22, 5.0, DTE, EXP)
    assert c is not None and len(c["legs"]) == 4
    assert c["max_risk_usd"] == pytest.approx(5.0 * eb.CONTRACT - c["credit_usd"], abs=0.5)
    assert "put" in c["breakevens"] and "call" in c["breakevens"]


def test_pop_floor_drops_low_probability_structure():
    # extremely wide, near-the-money-ish deep structure -> lower POP; force with tiny width/high IV
    c = eb.build_structure(eb.PUT_SPREAD, 100.0, 1.5, 1.0, DTE, EXP)
    # very high IV pushes breakeven far but POP may fall; just assert the filter is wired:
    assert c is None or c["pop"] >= eb.MIN_POP


def test_cap_drops_oversized():
    c = eb.build_structure(eb.PUT_SPREAD, 500.0, 0.20, 50.0, DTE, EXP)  # $5000 risk > $1000
    assert c is None


def test_eruption_veto_only_blocks_on_eruption():
    ok = pd.Series({"eruption_predicted_5d": False, "eruption_predicted_21d": False,
                    "magnitude_pct": 0.95, "calm_5d": False})   # high mag + not calm still OK
    assert eb.eruption_veto_ok(ok) is True
    erupt = pd.Series({"eruption_predicted_5d": True, "eruption_predicted_21d": False})
    assert eb.eruption_veto_ok(erupt) is False
    missing = pd.Series({"eruption_predicted_5d": float("nan"), "eruption_predicted_21d": False})
    assert eb.eruption_veto_ok(missing) is False


def test_route_from_lean():
    assert eb.route_from_lean(1, 0.9) == eb.PUT_SPREAD
    assert eb.route_from_lean(-1, 0.9) == eb.CALL_SPREAD
    assert eb.route_from_lean(0, 0.0) == eb.IRON_CONDOR       # no conviction bar for condor
    assert eb.route_from_lean(1, 0.5) is None                 # below directional conviction
    assert eb.route_from_lean(None, 0.9) is None


def _frame(prices):
    idx = pd.bdate_range("2026-07-24", periods=len(prices))
    return pd.DataFrame({"spot": prices}, index=idx)


def test_exit_hits_50pct_target_on_favorable_decay():
    # target can be hit before expiry even if the frame does not reach expiry
    c = eb.build_structure(eb.PUT_SPREAD, 100.0, 0.25, 5.0, DTE, date(2026, 10, 16))
    assert c is not None
    frame = _frame(np.linspace(100, 120, 40))   # rallies away from the short put -> value decays
    econ = eb.simulate_exit(c, frame, frame.index[0], date(2026, 10, 16))
    assert econ["exit"] == "target"
    assert econ["pnl_usd"] > 0 and econ["holding_days"] >= 1


def test_exit_falls_back_to_expiry_when_target_never_hit():
    c = eb.build_structure(eb.PUT_SPREAD, 100.0, 0.25, 5.0, DTE, date(2026, 9, 18))
    frame = _frame(np.linspace(100, 60, 45))    # crashes through the spread -> max loss, no target
    econ = eb.simulate_exit(c, frame, frame.index[0], date(2026, 9, 18))
    assert econ["exit"] == "expiry"


def _signals_one_day(day, magnitude=0.3):
    idx = pd.DatetimeIndex([pd.Timestamp(day)])
    return pd.DataFrame({"eruption_predicted_5d": [False], "eruption_predicted_21d": [False],
                         "magnitude_pct": [magnitude], "vix": [16.0], "spot": [100.0]}, index=idx)


def test_v4_trend_gate_drops_putside_below_sma(monkeypatch):
    # one bullish-lean symbol, one entry day; toggle spot above/below its SMA50
    day = pd.Timestamp("2024-06-03")
    monkeypatch.setattr(eb, "premium_factor", lambda s: pd.Series({day: 1.3}))
    universe = {"SPY": {"qlib_asset": "SPY", "bucket": "broad_equity", "spread_width": 5.0}}
    eligible = {"SPY": [(day.date(), eb.PUT_SPREAD)]}

    def _frame(spot, sma):
        return pd.DataFrame({"spot": [spot], "rv20": [0.18], "sma50": [sma]},
                            index=pd.DatetimeIndex([day]))

    sig = _signals_one_day(day)
    # below SMA -> put spread dropped by the trend gate
    led_below, diag_below = eb.build_ledger_v3(sig, {"SPY": _frame(480.0, 500.0)},
                                               universe, eligible, trend_filter=True)
    assert led_below == [] and diag_below["dropped_trend"] == 1
    # above SMA -> allowed (may still drop on censored data, but not on the trend gate)
    _, diag_above = eb.build_ledger_v3(sig, {"SPY": _frame(520.0, 500.0)},
                                       universe, eligible, trend_filter=True)
    assert diag_above["dropped_trend"] == 0


def test_v6_market_risk_off_days_flags_below_sma():
    idx = pd.bdate_range("2024-01-01", periods=260)
    # 250 up days then a drop below the 200-day
    prices = list(range(100, 350)) + [150] * 10
    sig = pd.DataFrame({"spot": prices[:len(idx)]}, index=idx)
    off = eb.market_risk_off_days(sig, 200)
    assert idx[-1].date() in off          # the low tail is below its 200-day
    assert idx[205].date() not in off     # still in the uptrend


def test_v6_market_overlay_drops_putside_universe_wide(monkeypatch):
    day = pd.Timestamp("2024-06-03")
    monkeypatch.setattr(eb, "premium_factor", lambda s: pd.Series({day: 1.3}))
    universe = {"SPY": {"qlib_asset": "SPY", "bucket": "broad_equity", "spread_width": 5.0}}
    eligible = {"SPY": [(day.date(), eb.PUT_SPREAD)]}
    # symbol ABOVE its own 200-day (per-name gate passes), but market flagged risk-off
    frame = pd.DataFrame({"spot": [520.0], "rv20": [0.18], "sma50": [500.0], "sma200": [500.0]},
                         index=pd.DatetimeIndex([day]))
    sig = _signals_one_day(day)
    _, diag = eb.build_ledger_v3(sig, {"SPY": frame}, universe, eligible,
                                 trend_filter=True, trend_col="sma200",
                                 market_risk_off={day.date()})
    assert diag["dropped_market"] == 1


def test_v7_tail_hedge_pays_on_a_crash_and_carries_otherwise():
    idx = pd.bdate_range("2024-01-01", periods=200)
    prices = [500.0] * 100 + list(np.linspace(500, 350, 100))   # second half crashes
    mkt = pd.DataFrame({"spot": prices, "vix": [18.0] * 200}, index=idx)
    rows = eb.tail_hedge_ledger(mkt)
    assert rows and all("pnl_usd" in r and r["cost_usd"] > 0 for r in rows)
    # at least one monthly put opened before the crash pays off (payoff > 0)
    assert any(r["payoff_usd"] > 0 for r in rows)
    by = eb._hedge_by_year(rows)
    assert "2024" in by and by["2024"]["n"] == len(rows)


def test_prob_above_below_consistency():
    a = bs.prob_above(100, 95, 0.2, 0.2)
    b = bs.prob_below(100, 95, 0.2, 0.2)
    assert abs(a + b - 1.0) < 1e-9 and 0 < a < 1
