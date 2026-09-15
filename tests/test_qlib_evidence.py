"""Qlib evidence diagnostic: filter semantics, staggering measurement, and the
non-overlap simulation that decides whether entries are independent."""
from datetime import date

import pandas as pd
import pytest

from desk import qlib_evidence as qe


def _scores(rows):
    return pd.DataFrame([{"date": pd.Timestamp(d), "asset": a, "lean": l,
                          "conviction": c} for d, a, l, c in rows])


UNIVERSE = {"SPY": {"qlib_asset": "SPY", "bucket": "broad_equity", "spread_width": 5.0},
            "GLD": {"qlib_asset": "GOLD", "bucket": "metals", "spread_width": 5.0}}


def test_eligible_map_requires_bullish_lean_and_conviction():
    scores = _scores([
        ("2026-03-02", "SPY", 1, 0.90),     # admitted
        ("2026-03-03", "SPY", 1, 0.50),     # conviction too low
        ("2026-03-04", "SPY", -1, 0.95),    # bearish
        ("2026-03-05", "SPY", 0, 0.95),     # neutral
        ("2026-03-02", "GOLD", 1, 0.80),    # admitted, mapped GOLD -> GLD
    ])
    out = qe.eligible_map(scores, UNIVERSE)
    assert out["SPY"] == {date(2026, 3, 2)}
    assert out["GLD"] == {date(2026, 3, 2)}


def test_eligible_map_ignores_assets_outside_universe():
    scores = _scores([("2026-03-02", "TSLA", 1, 0.99)])
    out = qe.eligible_map(scores, UNIVERSE)
    assert out == {"SPY": set(), "GLD": set()}


def test_simulate_baseline_locks_symbols_to_same_dates():
    """No filter: every symbol enters on every regime date -> Jaccard 1.0."""
    regime = [date(2026, 1, 5), date(2026, 6, 1)]
    out = qe.simulate(regime, ["SPY", "GLD"], None)
    assert out["n_entries"] == 4
    assert out["independent_entry_dates"] == 2
    assert out["mean_symbols_per_entry_date"] == 2.0
    assert qe.pairwise_overlap(out["_sets"])["mean_jaccard"] == 1.0


def test_simulate_filter_staggers_entries():
    """Different admitted dates per symbol -> more independent dates, low overlap."""
    regime = [date(2026, 1, 5), date(2026, 6, 1)]
    eligible = {"SPY": {date(2026, 1, 5)}, "GLD": {date(2026, 6, 1)}}
    out = qe.simulate(regime, ["SPY", "GLD"], eligible)
    assert out["n_entries"] == 2
    assert out["independent_entry_dates"] == 2
    assert out["mean_symbols_per_entry_date"] == 1.0
    assert qe.pairwise_overlap(out["_sets"])["mean_jaccard"] == 0.0


def test_simulate_respects_non_overlap_per_symbol():
    """Consecutive days cannot both enter: the first position is still open."""
    regime = [date(2026, 1, 5), date(2026, 1, 6), date(2026, 1, 7)]
    out = qe.simulate(regime, ["SPY"], None)
    assert out["n_entries"] == 1


def test_simulate_skips_symbols_never_admitted():
    regime = [date(2026, 1, 5)]
    out = qe.simulate(regime, ["SPY", "GLD"], {"SPY": {date(2026, 1, 5)}, "GLD": set()})
    assert out["symbols_that_traded"] == 1
    assert "GLD" not in out["per_symbol_entry_counts"]


def test_pairwise_overlap_handles_single_symbol():
    assert qe.pairwise_overlap({"SPY": {date(2026, 1, 5)}})["mean_jaccard"] is None


def test_missing_export_raises_actionable_error(tmp_path):
    with pytest.raises(RuntimeError, match="score_history"):
        qe.load_scores(tmp_path / "nope.parquet")


def test_gate_v2_prereg_locked_before_results():
    prereg = qe.json.loads(
        (qe.config.EXPERIMENTS_DIR / "options_etf_gate_v2.json").read_text(encoding="utf-8"))
    assert prereg["entry_policy"]["qlib_filter"]["lean"] == qe.BULLISH_LEAN
    assert prereg["entry_policy"]["qlib_filter"]["minimum_conviction"] == qe.MIN_CONVICTION
    # cumulative trial accounting: this run's 31 plus the 9 already spent in v1
    assert prereg["trial_accounting"]["n_trials"] == 40
    assert prereg["independence_and_inference"]["headline_view"] == "cluster_adjusted"
