"""P10: per-strategy analytics, excursion metrics, and promotion-progress accounting."""
from desk import shadow


def _row(strategy="etf_short_put_spread_v1", underlying="SPY", pnl=100.0,
         mfe=None, mae=None, days=None, risk=None, entry="2026-03-02"):
    row = {"strategy": strategy, "underlying": underlying, "pnl_usd": pnl,
           "entry_date": entry}
    if mfe is not None:
        row["mfe_usd"] = mfe
    if mae is not None:
        row["mae_usd"] = mae
    if days is not None:
        row["holding_days"] = days
    if risk is not None:
        row["max_risk_usd"] = risk
    return row


def test_stats_reports_excursions_and_holding():
    rows = [_row(pnl=100, mfe=150, mae=-40, days=30, risk=400),
            _row(pnl=-50, mfe=20, mae=-200, days=44, risk=400)]
    s = shadow._stats(rows)
    assert s["n"] == 2 and s["wins"] == 1 and s["hit_rate"] == 0.5
    assert s["avg_mfe_usd"] == 85.0
    assert s["avg_mae_usd"] == -120.0
    assert s["avg_holding_days"] == 37.0
    assert s["best_usd"] == 100.0 and s["worst_usd"] == -50.0
    # mean of (100/400) and (-50/400)
    assert s["avg_return_on_max_risk"] == 0.0625


def test_stats_tolerates_missing_optional_fields():
    s = shadow._stats([_row(pnl=10.0)])
    assert s["n"] == 1
    assert s["avg_mfe_usd"] is None and s["avg_holding_days"] is None


def test_stats_empty_is_safe():
    s = shadow._stats([])
    assert s["n"] == 0 and s["hit_rate"] is None and s["profit_factor"] is None


def test_promotion_progress_counts_independent_dates_not_rows():
    """Concurrent same-day positions are correlated; they must not inflate progress."""
    rows = [_row(underlying=u, entry="2026-03-02") for u in ("SPY", "QQQ", "IWM", "DIA")]
    rows.append(_row(underlying="SPY", entry="2026-06-01"))
    p = shadow.promotion_progress(rows)
    assert p["settled_trades"] == 5
    assert p["independent_entry_dates"] == 2        # not 5
    assert p["remaining_to_floor"] == shadow.PBO_FLOOR_TRADES - 2
    assert p["gate_decidable"] is False


def test_promotion_progress_flags_decidable_at_floor():
    rows = [_row(entry=f"2026-01-{d:02d}") for d in range(1, shadow.PBO_FLOOR_TRADES + 1)]
    p = shadow.promotion_progress(rows)
    assert p["independent_entry_dates"] == shadow.PBO_FLOOR_TRADES
    assert p["gate_decidable"] is True and p["remaining_to_floor"] == 0
    assert "not a pass" in p["note"]


def test_summary_exposes_by_underlying_and_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(shadow, "load_results",
                        lambda path=None: [_row(underlying="SPY"), _row(underlying="QQQ", pnl=-20)])
    monkeypatch.setattr(shadow, "_load_open", lambda path=None: {})
    s = shadow.summary()
    assert set(s["by_underlying"]) == {"SPY", "QQQ"}
    assert s["by_underlying"]["QQQ"]["total_pnl_usd"] == -20.0
    assert s["promotion_progress"]["pbo_floor_trades"] == shadow.PBO_FLOOR_TRADES
    assert "by_strategy" in s and "overall" in s
