"""P7 ETF gate backtest: regime veto, structure invariants, and cluster independence."""
import math

import numpy as np
import pandas as pd
import pytest

from desk import etf_backtest as eb


def _row(calm=True, e5=False, e21=False, mag=0.30):
    return pd.Series({"calm_5d": calm, "eruption_predicted_5d": e5,
                      "eruption_predicted_21d": e21, "magnitude_pct": mag})


def test_regime_requires_calm_no_eruption_and_low_magnitude():
    assert eb.global_regime_ok(_row()) is True
    assert eb.global_regime_ok(_row(calm=False)) is False
    assert eb.global_regime_ok(_row(e5=True)) is False
    assert eb.global_regime_ok(_row(e21=True)) is False
    assert eb.global_regime_ok(_row(mag=0.70)) is False      # exclusive bound
    assert eb.global_regime_ok(_row(mag=float("nan"))) is False


def test_regime_missing_field_is_veto():
    assert eb.global_regime_ok(pd.Series({"calm_5d": True})) is False


def test_realized_vol_matches_manual_annualization():
    close = pd.Series(np.linspace(100, 120, 40),
                      index=pd.date_range("2026-01-01", periods=40, freq="B"))
    rv = eb.realized_vol(close, window=20).dropna()
    logret = np.log(close / close.shift(1))
    expected = logret.rolling(20).std().dropna() * math.sqrt(252)
    assert np.allclose(rv.values, expected.values)


def test_build_spread_invariants():
    c = eb.build_spread(spot=500.0, iv=0.20, width=5.0, dte=45, expiry=eb.date(2026, 9, 18))
    assert c is not None
    short = next(l for l in c["legs"] if l["side"] == "sell")
    long = next(l for l in c["legs"] if l["side"] == "buy")
    assert short["strike"] - long["strike"] == 5.0        # exact frozen width
    assert short["strike"] < 500.0                        # OTM put
    assert 0 < c["credit_usd"] < 5.0 * eb.CONTRACT        # credit below width
    assert c["max_risk_usd"] == pytest.approx(5.0 * eb.CONTRACT - c["credit_usd"], abs=0.01)


def test_build_spread_rejects_degenerate_inputs():
    assert eb.build_spread(0.0, 0.2, 5.0, 45, eb.date(2026, 9, 18)) is None
    assert eb.build_spread(500.0, 0.0, 5.0, 45, eb.date(2026, 9, 18)) is None
    # width wider than the underlying cannot produce a positive long strike
    assert eb.build_spread(3.0, 0.2, 5.0, 45, eb.date(2026, 9, 18)) is None


def test_cluster_collapses_same_date_entries():
    ledger = [
        {"entry_date": "2026-03-02", "pnl_usd": 100.0, "symbol": "SPY"},
        {"entry_date": "2026-03-02", "pnl_usd": 200.0, "symbol": "QQQ"},
        {"entry_date": "2026-03-02", "pnl_usd": 300.0, "symbol": "DIA"},
        {"entry_date": "2026-06-01", "pnl_usd": -50.0, "symbol": "SPY"},
    ]
    clustered = eb.cluster_by_date(ledger)
    # four correlated rows -> two independent observations, means preserved
    assert clustered == [200.0, -50.0]


def test_cluster_never_inflates_n_beyond_distinct_dates():
    ledger = [{"entry_date": "2026-01-05", "pnl_usd": float(i), "symbol": f"S{i}"}
              for i in range(9)]
    assert len(eb.cluster_by_date(ledger)) == 1


def test_premium_factor_is_market_wide_scalar():
    idx = pd.date_range("2026-01-01", periods=40, freq="B")
    signals = pd.DataFrame({"spot": np.linspace(400, 440, 40), "vix": 20.0}, index=idx)
    pf = eb.premium_factor(signals).dropna()
    assert not pf.empty
    # one value per date (not per symbol) — the degeneracy declared in the spec
    assert pf.index.is_unique and pf.notna().all()


def test_universe_and_prereg_load_from_frozen_specs():
    universe = eb.load_universe()
    assert set(universe) >= {"SPY", "QQQ", "TLT", "GLD", "XLE"}
    prereg = eb.load_prereg()
    assert prereg["experiment_id"] == "options_etf_gate_v1"
    assert prereg["independence_and_inference"]["headline_view"] == "cluster_adjusted"
    assert prereg["trial_accounting"]["n_trials"] == len(universe)
