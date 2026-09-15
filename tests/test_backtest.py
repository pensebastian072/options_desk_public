from datetime import date

import pandas as pd
import pytest

from desk import backtest


def test_unadjusted_close_undoes_yahoo_factor():
    close = pd.Series([85.0, 100.0])
    factor = pd.Series([0.85, 1.0])
    assert backtest.unadjusted_close(close, factor).tolist() == [100.0, 100.0]


def test_rolling_percentile_is_trailing_only():
    values = pd.Series(range(1, 254), dtype=float)
    pct = backtest.rolling_percentile(values, window=252)
    assert pd.isna(pct.iloc[250])
    assert pct.iloc[251] == 1.0
    changed_future = values.copy()
    changed_future.iloc[252] = -1000
    changed = backtest.rolling_percentile(changed_future, window=252)
    assert changed.iloc[251] == pct.iloc[251]
    assert changed.iloc[252] == pytest.approx(1 / 252)


def test_short_put_payoff_and_cost():
    candidate = {
        "credit_usd": 200,
        "legs": [{"side": "sell", "type": "put", "strike": 100}],
    }
    assert backtest.candidate_pnl(candidate, 110)["pnl_usd"] == 198.0
    assert backtest.candidate_pnl(candidate, 80)["pnl_usd"] == -1802.0


def test_put_spread_payoff_is_bounded():
    candidate = {
        "credit_usd": 150,
        "legs": [
            {"side": "sell", "type": "put", "strike": 100},
            {"side": "buy", "type": "put", "strike": 95},
        ],
    }
    assert backtest.candidate_pnl(candidate, 110)["pnl_usd"] == 146.0
    assert backtest.candidate_pnl(candidate, 80)["pnl_usd"] == -354.0


def test_long_straddle_payoff():
    candidate = {
        "debit_usd": 600,
        "legs": [
            {"side": "buy", "type": "call", "strike": 100},
            {"side": "buy", "type": "put", "strike": 100},
        ],
    }
    assert backtest.candidate_pnl(candidate, 110)["pnl_usd"] == 396.0
    assert backtest.candidate_pnl(candidate, 100)["pnl_usd"] == -604.0


def test_terminal_observation_uses_prior_session_for_holiday():
    index = pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-06"])
    market = pd.DataFrame({"spot": [100.0, 101.0, 102.0]}, index=index)
    terminal = backtest._terminal_observation(
        market, pd.Timestamp("2026-04-01"), date(2026, 4, 3)
    )
    assert terminal == (pd.Timestamp("2026-04-02"), 101.0)


def test_signal_requires_oos_predictions():
    row = pd.Series({"spot": 100, "vix": 20, "vrp_pct": 0.8,
                     "magnitude_pct": 0.2, "calm_5d": True,
                     "calm_21d": True, "eruption_predicted_5d": False,
                     "eruption_predicted_21d": pd.NA})
    assert backtest.signal_from_row(row) is None


def test_trade_ledger_rejects_overlapping_entries():
    market_index = pd.bdate_range("2026-01-02", "2026-06-30")
    market = pd.DataFrame({"spot": 100.0, "vix": 20.0,
                           "vix9d": 18.0, "vix3m": 21.0}, index=market_index)
    signal_index = market_index[30:35]
    signals = pd.DataFrame({
        "spot": 100.0,
        "vix": 20.0,
        "vrp": 100.0,
        "vrp_pct": 0.9,
        "sigma_1d": 0.01,
        "magnitude_pct": 0.2,
        "term_ratio": 0.9,
        "calm_5d": True,
        "calm_21d": True,
        "p_eruption_5d": 0.1,
        "p_eruption_21d": 0.1,
        "eruption_predicted_5d": False,
        "eruption_predicted_21d": False,
    }, index=signal_index)
    ledger, diagnostics = backtest.build_trade_ledger(signals, market)
    short_put_rows = [r for r in ledger if r["strategy"] == "short_put_csp"]
    assert len(short_put_rows) == 1
    assert diagnostics["dropped_overlap"]["short_put_csp"] == 4
