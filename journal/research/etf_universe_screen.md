# ETF universe expansion — screen ~100 candidates, keep only what survives honestly

Date: 2026-07-23. Research method (not yet run). Companion:
`etf_universe_screen_candidates.json` (~108 large US ETFs bucketed by sector/asset class).
Goal: discover which ETFs beyond the frozen 31 are viable "fields" for the options engine.
The frozen v2/v3 (31) stays the operating universe until a screened subset is
**pre-registered**.

## The trap we must not fall into

"Test 100 and keep what's valuable" is, done naively, **guaranteed overfitting**: with 100
symbols and noise, several will backtest beautifully by luck, and they will disappoint live
(this is exactly the survivorship/selection-bias failure the whole program was built to
avoid). Three rules make the expansion honest:

1. **Screen on STRUCTURE, not performance.** The first cut is "can we even sell options here
   well?" -- measured, objective, and independent of backtest PnL. This is the real gate.
2. **Deflate for the full search.** Any performance test of the survivors runs through the
   canonical gate with `n_trials` counting the ENTIRE candidate pool that was looked at --
   not just the survivors. More candidates RAISE the bar.
3. **Pre-register the keepers before they go live.** The selected subset becomes a new
   pre-registered universe spec, ideally validated on data not used for selection.

## AUM is not the gate

The candidate list is drawn from large-AUM ETFs for breadth, but **AUM != option-tradable.**
Buy-and-hold giants (VOO, VTI, BND, VEA, IEFA) have huge AUM and thin, wide options -- they
are listed as *expected screen failures* in the JSON to prove the point. What the engine
needs is **liquid, richly-priced options**, which is what the structural screen measures.

## Phase A -- structural viability screen (measured, no PnL)

For each candidate, over a recent window (reuse the live-lane rules in
`options_etf_universe_v2` `entry_policy.liquidity`), compute and gate on:

1. **Options exist + liquid** (the hard gate): median 30-60 DTE, ~30-delta chain has
   open interest >= 100 OR daily volume >= 20 per leg, and median per-leg relative spread
   <= 0.15. Data via the Alpaca option client (`alpaca.data.historical.option`) snapshots or
   the real option feed from the deep-backtest task.
2. **Premium is there**: median IV/RV >= ~1.0 (something to sell). Reuse `realized_vol_20`
   + option IV.
3. **Signal coverage**: does qlib produce a point-in-time lean for it (in the ~76-ETF model
   universe)? If not -> flag `needs_qlib_coverage` (add to `qlib_lab.data_fetch`) or exclude.
   No signal = no routing = not viable yet.
4. **History**: enough underlying history for the 200-day trend gate, and (for the real-option
   deep test) real option history in the window.

Output: a viability table per symbol (pass/fail per criterion) + a shortlist of structural
survivors. Expect the ~108 pool to collapse to maybe 40-60 truly option-liquid names, many
already in the 31.

## Phase B -- DECORRELATION-weighted selection (the primary discovery metric)

Liquidity (Phase A) is a pass/fail gate. The RANKING that decides what we keep is
**marginal independent-evidence contribution**, i.e. how much a candidate DECORRELATES entry
timing from the set we already have. This directly targets the earlier finding: correlated
names entering on identical dates add coverage, not evidence (pooled n collapses to the
cluster count). Reuse the tooling already built for that lesson --
`desk/qlib_evidence.py::eligible_map / simulate / pairwise_overlap` -- on the point-in-time
lean export.

- **Runs on FULL 2019-2026 daily lean history** (it is about entry TIMING, not option prices),
  so it is NOT limited by Alpaca's short real-option window. Only the Phase-C PnL test needs
  real options.
- Method (greedy forward selection): start from the current 31 (or SPY); repeatedly add the
  Phase-A survivor whose v5 entry-date set most INCREASES the count of independent (cluster-
  adjusted) entry dates -- equivalently, lowest mean Jaccard overlap with the current set.
  Stop at diminishing returns. Report each addition's marginal independent-dates gain and its
  bucket, so the winners are spread across sectors/asset classes rather than equity clones.
- Weight decorrelation, NOT AUM and NOT standalone backtest PnL (PnL-ranking survivors is the
  selection-bias trap).

## Phase C -- deflated PnL confirmation of the decorrelated set

Run the decorrelation-selected set through the v5 harness (`desk/etf_backtest.py`), cluster-
adjusted, canonical gate, with **`n_trials` counting the full candidate pool screened** so
deflation pays for every look. With real fills this is Alpaca-bounded (~2024+); pre-2024 is
BS-modeled or excluded (stated). The set must add value HERE before any keeper is proposed.

## Phase C -- pre-register keepers

Only ETFs that (a) pass Phase A structurally AND (b) add value under the deflated Phase-B
test become a new pre-registered universe (`options_etf_universe_v4` or similar), with widths
frozen and the rationale recorded. Nothing goes live without this. "Take what's valuable"
= this gate, not eyeballing the backtest.

## How this plugs into the deep-backtest task

This screen is **Phase 0.5** of `docs/deep_backtest_task.md`: after the real option-data
source is named, screen the top-100 pool structurally, then the real-option/intraday/GPU
deep test runs over the structural survivors (with deflation across the full pool). Adopt
nothing without pre-registration.

## Status
Research method + candidate list only. Nothing run, nothing adopted. Frozen 31 stays live.
