"""Does the Qlib per-asset filter actually earn its place as evidence?

`options_etf_gate_v1` showed that under a purely GLOBAL entry rule every ETF entered on
identical dates: pooled n=369 collapsed to 41 cluster-adjusted observations, and the
cluster view equalled the SPY-only view. Widening the universe bought coverage, not
evidence. The only mechanism that could change that is a filter which makes different
symbols enter on DIFFERENT dates.

Qlib's `lean` is a cross-sectional rank (top-TOPK of 76 assets score +1), so it is
selective by construction. This module measures whether that selectivity actually
decorrelates entry timing, using the point-in-time export from
`qlib_lab.score_history` (walk-forward, no lookahead).

It answers three questions with numbers, not assertions:
  1. discrimination - on a given date, how much of the universe does the filter admit?
  2. staggering     - do symbols enter on different dates (pairwise overlap of entry sets)?
  3. evidence       - does the filter increase the count of INDEPENDENT entry dates,
                      which is what the canonical gate can actually use?

Diagnostic only: publishes no flag, places no order, promotes nothing.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timezone
from pathlib import Path

import pandas as pd

from . import backtest, config, etf_backtest, strategies

# Point-in-time export produced by qlib_lab.score_history (separate venv, file handoff).
SCORE_HISTORY = config.QLIB_LAB_DIR / "journal" / "exports" / "qlib_score_history.parquet"
REPORT_PATH = config.SCORECARDS_DIR / "qlib_evidence.json"

# Live directional bar, mirrored from options_etf_universe_v2.
MIN_CONVICTION = 0.70
BULLISH_LEAN = 1


def load_scores(path: Path | None = None) -> pd.DataFrame:
    target = path or SCORE_HISTORY
    if not target.exists():
        raise RuntimeError(
            f"score history missing: {target}\n"
            "Generate it first in the qlib_lab venv:\n"
            "  .venv\\Scripts\\python.exe -m qlib_lab.score_history")
    frame = pd.read_parquet(target)
    frame["date"] = pd.to_datetime(frame["date"])
    return frame


def load_universe(spec_id: str = "options_etf_universe_v2") -> dict:
    spec = json.loads((config.EXPERIMENTS_DIR / f"{spec_id}.json").read_text(encoding="utf-8"))
    return spec["scope"]["candidate_universe"]


def eligible_map(scores: pd.DataFrame, universe: dict) -> dict[str, set]:
    """symbol -> set of dates where Qlib says bullish with enough conviction."""
    wanted = {policy["qlib_asset"]: symbol for symbol, policy in universe.items()}
    subset = scores[scores["asset"].isin(wanted)]
    ok = subset[(subset["lean"] == BULLISH_LEAN)
                & (subset["conviction"] >= MIN_CONVICTION)]
    out: dict[str, set] = {symbol: set() for symbol in universe}
    for asset, group in ok.groupby("asset"):
        out[wanted[str(asset)]] = {ts.date() for ts in group["date"]}
    return out


def regime_dates(signals: pd.DataFrame) -> list[date]:
    """Dates passing the same global veto the live lane and P7 backtest use."""
    factor = etf_backtest.premium_factor(signals)
    out: list[date] = []
    for stamp, row in signals.iterrows():
        if not etf_backtest.global_regime_ok(row):
            continue
        pf = factor.get(stamp, float("nan"))
        if not (pf == pf) or pf < etf_backtest.IV_RV_FLOOR:   # NaN-safe
            continue
        out.append(stamp.date())
    return out


def simulate(regime: list[date], symbols: list[str],
             eligible: dict[str, set] | None) -> dict:
    """Replay per-symbol non-overlapping entries.

    `eligible=None` reproduces the P7 baseline (global rule only). Otherwise a symbol
    may only enter on a date Qlib admitted it. Non-overlap is per symbol: one open
    position at a time, released after its expiry.
    """
    last_expiry: dict[str, date] = {}
    entries: list[tuple[date, str]] = []
    for day in regime:
        now = datetime.combine(day, time(9, 5), tzinfo=timezone.utc)
        expiry, _ = strategies.target_expiry(now)
        for symbol in symbols:
            if symbol in last_expiry and day <= last_expiry[symbol]:
                continue
            if eligible is not None and day not in eligible.get(symbol, set()):
                continue
            entries.append((day, symbol))
            last_expiry[symbol] = expiry
    dates = sorted({day for day, _ in entries})
    per_symbol = {symbol: sorted({d for d, s in entries if s == symbol}) for symbol in symbols}
    per_symbol = {k: v for k, v in per_symbol.items() if v}
    return {
        "n_entries": len(entries),
        "independent_entry_dates": len(dates),
        "symbols_that_traded": len(per_symbol),
        "mean_symbols_per_entry_date": (round(len(entries) / len(dates), 3) if dates else 0.0),
        "per_symbol_entry_counts": {k: len(v) for k, v in sorted(per_symbol.items())},
        "_sets": {k: set(v) for k, v in per_symbol.items()},
    }


def pairwise_overlap(sets: dict[str, set]) -> dict:
    """Mean Jaccard overlap of entry-date sets. 1.0 = perfectly locked together."""
    names = sorted(sets)
    scores = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            union = sets[a] | sets[b]
            if union:
                scores.append(len(sets[a] & sets[b]) / len(union))
    if not scores:
        return {"pairs": 0, "mean_jaccard": None, "max_jaccard": None}
    return {"pairs": len(scores),
            "mean_jaccard": round(sum(scores) / len(scores), 4),
            "max_jaccard": round(max(scores), 4)}


def discrimination(scores: pd.DataFrame, universe: dict, regime: list[date]) -> dict:
    """How much of the universe does the filter admit on a regime-ok date?"""
    wanted = {policy["qlib_asset"] for policy in universe.values()}
    subset = scores[scores["asset"].isin(wanted)].copy()
    subset["day"] = subset["date"].dt.date
    on_regime = subset[subset["day"].isin(set(regime))]
    if on_regime.empty:
        return {"regime_dates_with_scores": 0}
    admitted = on_regime[(on_regime["lean"] == BULLISH_LEAN)
                         & (on_regime["conviction"] >= MIN_CONVICTION)]
    per_day = admitted.groupby("day").size()
    covered = on_regime["day"].nunique()
    return {
        "regime_dates_with_scores": int(covered),
        "universe_size": len(universe),
        "mean_admitted_per_date": round(float(per_day.sum()) / covered, 3),
        "max_admitted_on_a_date": int(per_day.max()) if len(per_day) else 0,
        "dates_with_zero_admitted": int(covered - per_day.count()),
        "admitted_fraction_of_universe": round(float(per_day.sum()) / (covered * len(universe)), 4),
    }


def run(scores_path: Path | None = None, spec_id: str = "options_etf_universe_v2") -> dict:
    scores = load_scores(scores_path)
    universe = load_universe(spec_id)
    market = backtest.load_market_history()
    replay, _, _ = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)
    regime = regime_dates(signals)

    # Restrict to the window the score export actually covers (no extrapolation).
    lo, hi = scores["date"].min().date(), scores["date"].max().date()
    regime = [d for d in regime if lo <= d <= hi]

    eligible = eligible_map(scores, universe)
    symbols = sorted(universe)
    baseline = simulate(regime, symbols, None)
    filtered = simulate(regime, symbols, eligible)

    base_sets, filt_sets = baseline.pop("_sets"), filtered.pop("_sets")
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "question": "Does the Qlib per-asset filter add independent evidence?",
        "score_export": {"path": str(scores_path or SCORE_HISTORY),
                         "rows": int(len(scores)),
                         "window": [str(lo), str(hi)]},
        "spec": spec_id,
        "regime_ok_dates_in_window": len(regime),
        "filter": {"lean": BULLISH_LEAN, "minimum_conviction": MIN_CONVICTION},
        "discrimination": discrimination(scores, universe, regime),
        "baseline_global_only": {**baseline, "overlap": pairwise_overlap(base_sets)},
        "qlib_filtered": {**filtered, "overlap": pairwise_overlap(filt_sets)},
    }
    base_n = baseline["independent_entry_dates"]
    filt_n = filtered["independent_entry_dates"]
    report["verdict"] = {
        "independent_dates_baseline": base_n,
        "independent_dates_filtered": filt_n,
        "delta": filt_n - base_n,
        "pbo_floor": etf_backtest.__dict__.get("PBO_FLOOR", 40),
        "adds_independent_evidence": filt_n > base_n,
        "note": ("A filter only adds evidence if it DECORRELATES entry timing, raising the "
                 "count of independent entry dates. Fewer trades at the same dates is not "
                 "evidence. This is a diagnostic, not a promotion."),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure whether Qlib adds independent evidence")
    parser.add_argument("--scores", type=Path, default=None)
    parser.add_argument("--spec", default="options_etf_universe_v2")
    parser.add_argument("--out", type=Path, default=REPORT_PATH)
    args = parser.parse_args()
    report = run(args.scores, args.spec)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")

    d = report["discrimination"]
    b, f, v = report["baseline_global_only"], report["qlib_filtered"], report["verdict"]
    print(f"window {report['score_export']['window'][0]} -> {report['score_export']['window'][1]}"
          f"  regime-ok dates={report['regime_ok_dates_in_window']}")
    print(f"discrimination: {d.get('mean_admitted_per_date')} of {d.get('universe_size')} "
          f"symbols admitted per regime date "
          f"({d.get('admitted_fraction_of_universe')} of universe)")
    print(f"baseline  entries={b['n_entries']:5d} independent dates={b['independent_entry_dates']:4d} "
          f"mean symbols/date={b['mean_symbols_per_entry_date']} "
          f"jaccard={b['overlap']['mean_jaccard']}")
    print(f"qlib      entries={f['n_entries']:5d} independent dates={f['independent_entry_dates']:4d} "
          f"mean symbols/date={f['mean_symbols_per_entry_date']} "
          f"jaccard={f['overlap']['mean_jaccard']}")
    print(f"VERDICT: adds independent evidence = {v['adds_independent_evidence']} "
          f"({v['delta']:+d} independent dates)")
    print(f"report -> {args.out}")


if __name__ == "__main__":
    main()
