"""ETF universe expansion screen -- DECORRELATION selection (research, SHADOW).

Measures which candidate ETFs (beyond the frozen 31) add INDEPENDENT evidence, i.e. enter
on dates the current set does not already cover. This is the honest selection metric (not
AUM, not standalone PnL): correlated names entering on identical dates add coverage, not
evidence -- see journal/research/qlib_filter_and_dsr_bar.md and etf_universe_screen.md.

Runs on the FULL 2019-2026 point-in-time lean history (entry TIMING only), so it is NOT
limited by Alpaca's short real-option window. It does NOT price options; the liquidity gate
(Alpaca) and the real-option PnL test are separate, later phases.

Entry timing per symbol = the v5 rule WITHOUT pricing: eruption veto + Qlib lean routing +
conviction + IV/RV proxy + 200-day per-symbol trend gate + non-overlap. Reuses
desk/etf_backtest.py so the timing matches the real backtest.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timezone

import numpy as np
import pandas as pd

from . import backtest, config, etf_backtest as eb, qlib_evidence

ALIAS = {"GLD": "GOLD"}          # ticker -> qlib asset name
CANDIDATES = config.BASE_DIR / "journal" / "research" / "etf_universe_screen_candidates.json"
REPORT = config.SCORECARDS_DIR / "etf_universe_screen.json"


def covered_candidates() -> tuple[dict, list[str]]:
    """Return {symbol: bucket} for candidates that HAVE a qlib lean, + the base-31 list."""
    cand = json.loads(CANDIDATES.read_text(encoding="utf-8"))
    have = set(qlib_evidence.load_scores()["asset"].unique())
    covered = {}
    for bucket, syms in cand["buckets"].items():
        for s in syms:
            if ALIAS.get(s, s) in have:
                covered[s] = bucket
    return covered, cand["already_in_v2_universe"]


def _universe(symbols: dict) -> dict:
    """Minimal universe map for etf_backtest loaders (width is a dummy; timing only)."""
    return {s: {"qlib_asset": ALIAS.get(s, s), "bucket": b, "spread_width": 1.0}
            for s, b in symbols.items()}


def entry_dates(signals: pd.DataFrame, histories: dict, universe: dict,
                eligible: dict) -> dict[str, set]:
    """Per-symbol set of v5 entry dates (no pricing), matching build_ledger_v3 timing."""
    factor = eb.premium_factor(signals)
    regime_ok = {d.date() for d, row in signals.iterrows() if eb.eruption_veto_ok(row)}
    factor_by_day = {d.date(): factor.get(d) for d in signals.index}
    out: dict[str, set] = {}
    for symbol, dated in eligible.items():
        frame = histories.get(symbol)
        if frame is None:
            continue
        last_expiry = None
        dates: set = set()
        for day, structure in sorted(dated):
            if day not in regime_ok:
                continue
            if last_expiry is not None and day <= last_expiry:
                continue
            stamp = pd.Timestamp(day)
            if stamp not in frame.index:
                continue
            pf = factor_by_day.get(day)
            if pf is None or not np.isfinite(pf) or pf < eb.IV_RV_FLOOR:
                continue
            row = frame.loc[stamp]
            spot = float(row["spot"])
            if spot <= 0 or float(row["rv20"]) <= 0:
                continue
            # v5 trend gate: put-side needs price >= 200-day SMA
            if structure in eb.PUT_SIDE:
                sma = row.get("sma200")
                if sma is None or pd.isna(sma) or spot < float(sma):
                    continue
            now = datetime.combine(day, time(9, 5), tzinfo=timezone.utc)
            expiry, _ = eb.strategies.target_expiry(now)   # a datetime.date
            dates.add(day)
            last_expiry = expiry
        out[symbol] = dates
    return out


def run() -> dict:
    covered, base = covered_candidates()
    base = [s for s in base if s in covered or s in base]     # keep base-31 order
    new = {s: b for s, b in covered.items() if s not in base}

    universe = _universe({**{s: covered.get(s, "base") for s in base}, **new})
    scores = qlib_evidence.load_scores()
    market = backtest.load_market_history()
    replay, _, _ = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)
    lo, hi = scores["date"].min(), scores["date"].max()
    signals = signals.loc[(signals.index >= lo) & (signals.index <= hi)]
    histories = eb.load_symbol_history(universe)
    eligible = eb.v3_eligible(scores, universe)
    dates = entry_dates(signals, histories, universe, eligible)

    base_dates = set().union(*[dates.get(s, set()) for s in base]) if base else set()

    def independent(dset: set) -> int:
        return len(dset)

    # one-round marginal contribution of each NEW candidate over the base set
    rows = []
    for s, b in new.items():
        own = dates.get(s, set())
        added = len(base_dates | own) - len(base_dates)
        overlap = (len(base_dates & own) / len(base_dates | own)) if (base_dates | own) else 0.0
        rows.append({"symbol": s, "bucket": b, "own_entry_dates": len(own),
                     "new_independent_dates": added,
                     "jaccard_vs_base": round(overlap, 4),
                     "decorrelation": round(1 - overlap, 4)})
    rows.sort(key=lambda r: (-r["new_independent_dates"], -r["decorrelation"], r["symbol"]))

    # greedy cumulative selection: keep adding the highest marginal-gain candidate
    greedy = []
    cur = set(base_dates)
    remaining = dict(new)
    while remaining:
        best, best_gain = None, -1
        for s in remaining:
            g = len(cur | dates.get(s, set())) - len(cur)
            if g > best_gain:
                best, best_gain = s, g
        if best is None or best_gain <= 0:
            break
        greedy.append({"symbol": best, "bucket": new[best], "marginal_new_dates": best_gain,
                       "cumulative_independent_dates": len(cur | dates.get(best, set()))})
        cur |= dates.get(best, set())
        remaining.pop(best)

    return {
        "id": "etf_universe_screen", "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW research; decorrelation selection only; no liquidity/PnL yet",
        "window": [str(lo.date()), str(hi.date())],
        "base_symbols": len(base), "base_independent_entry_dates": len(base_dates),
        "new_covered_candidates": len(new),
        "note": ("Ranks NEW candidates by INDEPENDENT entry dates added over the current 31 "
                 "(decorrelation), on full lean history. Liquidity (Alpaca) + real-option PnL "
                 "come next; adopt nothing without pre-registration."),
        "marginal_ranking": rows,
        "greedy_selection": greedy,
    }


def main() -> None:
    report = run()
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"etf_universe_screen -> {REPORT}")
    print(f"base {report['base_symbols']} symbols = {report['base_independent_entry_dates']} "
          f"independent entry dates | {report['new_covered_candidates']} new covered candidates")
    print("top new candidates by INDEPENDENT dates added (decorrelation):")
    for r in report["marginal_ranking"][:18]:
        print(f"  {r['symbol']:5s} {r['bucket']:22s} +{r['new_independent_dates']:3d} new dates "
              f"| decorr {r['decorrelation']:.2f} | own {r['own_entry_dates']}")
    print("greedy cumulative pickup (first 12):")
    for g in report["greedy_selection"][:12]:
        print(f"  +{g['symbol']:5s} ({g['bucket']}) +{g['marginal_new_dates']} -> "
              f"{g['cumulative_independent_dates']} independent dates")


if __name__ == "__main__":
    main()
