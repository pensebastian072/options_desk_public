# Does Qlib add evidence? Yes. Does the gate then pass? No — and here is exactly why.

Date: 2026-07-23. Research note, SHADOW. Nothing here promotes anything or changes a
threshold. Artifacts: `journal/scorecards/qlib_evidence.json`,
`journal/scorecards/options_etf_gate_v2.json`, pre-registration
`journal/experiments/options_etf_gate_v2.json` (written and committed before results).

## 1. The problem v1 exposed

`options_etf_gate_v1` replayed the frozen short-put-spread rule across the ETF universe
under a purely GLOBAL entry rule (no per-asset filter, because no point-in-time Qlib
history existed). Result: every symbol entered on identical dates.

| | entries | independent entry dates | symbols/date | pairwise Jaccard |
|---|---:|---:|---:|---:|
| global rule only | 1116 | 36 | 31.0 | **1.000** |

Jaccard 1.000 means the entry-date sets were *identical*. Pooled n=369 collapsed to 41
cluster-adjusted observations, and `cluster_adjusted` equalled `spy_only`. Adding symbols
bought candidate coverage and zero statistical evidence.

## 2. Making Qlib usable as evidence

Qlib's `lean` is a **cross-sectional rank**: the top-TOPK(8) of 76 assets score +1
(`qlib_lab/qlib_lab/pipeline.py::latest_scores`). It is selective by construction — but
it only existed as a live flag, with 8 days of history.

Process built (`qlib_lab/qlib_lab/score_history.py`): re-run the *same* expanding
walk-forward the pipeline already uses, but export the per-asset cross-section instead of
discarding it. No-lookahead is inherited — refit every 126 sessions on labels fully
realized before the refit date (`cutoff = dates[i - horizon]`), models applied forward
only. Output: 133,986 rows, 76 assets, 1,763 sessions (2019-07-18 -> 2026-07-23).

Cross-venv handoff by file (qlib_lab is py3.11/numpy<2), consistent with the rest of the
architecture.

## 3. It decorrelates entry timing — decisively

`desk/qlib_evidence.py`, filter = `lean == 1 AND conviction >= 0.70`:

| | entries | independent entry dates | symbols/date | pairwise Jaccard |
|---|---:|---:|---:|---:|
| global only | 1116 | 36 | 31.0 | 1.000 |
| **+ Qlib filter** | 307 | **192** | 1.60 | **0.017** |

Discrimination: 2.96 of 31 symbols admitted per regime date (9.6% of the universe).
**~3x fewer trades, ~5.3x more independent observations.** This is the mechanism that was
missing: the filter staggers entries instead of locking them together.

## 4. The gate result — every quality metric improved, the verdict got worse

`options_etf_gate_v2` (cluster-adjusted headline) vs v1:

| metric | v1 | v2 | direction |
|---|---:|---:|---|
| independent observations | 41 | **186** | better |
| per-trade Sharpe | 0.305 | **0.400** | better |
| mean PnL / trade | $28.10 | **$37.89** | better |
| win rate | 75.6% | **80.7%** | better |
| profit factor | 1.99 | **2.73** | better |
| PBO | 0.0159 | **0.000** | better (passes) |
| **Deflated Sharpe** | **-6.32** | **-17.68** | **worse** |
| verdict | not cleared | **not cleared** | — |

All three pre-registered predictions were confirmed (n > 100, PBO computable, filtered
set outperforms per trade). The strategy still fails.

## 5. Why DSR moved the wrong way — two compounding causes

`macro_gpu_lab/validate.py::deflated_sharpe`:

```
ratio = (sr - e_max) * sqrt(T - 1) / denom
```

where `sr` is the **per-trade** Sharpe (mean/stdev of trade PnL, not annualized), `T` is
the number of observations, and `e_max` is the expected maximum Sharpe across `n_trials`.

1. **`e_max` rose.** n_trials 9 -> 40 (pre-registered cumulative) lifts `e_max` from
   1.521 to 2.189.
2. **`sqrt(T-1)` amplified a negative gap.** Because `sr < e_max`, the gap is negative,
   and more observations *multiply* it: sqrt(185)/sqrt(40) = 2.15x.

So collecting better evidence made the score worse. That is arithmetic, not a paradox —
but it means the metric is not behaving as "more data resolves the question".

## 6. The structural observation (methodology, not an excuse)

Per-trade Sharpe required to reach DSR = 0:

| n_trials | 4 | 9 | 31 | 40 | 93 |
|---|---:|---:|---:|---:|---:|
| required per-trade Sharpe | 1.052 | 1.521 | 2.087 | 2.189 | 2.505 |

A per-trade Sharpe above ~2.2 means average profit exceeding 2.2 standard deviations of
trade PnL. A defined-risk premium-selling structure has ~80% small wins and a fat left
tail; its per-trade Sharpe is structurally ~0.3-0.5. **Under this parameterization the
gate cannot pass for this strategy family regardless of quality.**

Worth noting across the whole program: every strategy in every repo fails DSR by a wide
margin (macro_gpu_lab -5 to -18, qlib VRP -17, options -1.3 to -17.7) while often showing
PF > 1.5 and replicating out-of-sample. A uniform, large-magnitude failure across
unrelated strategy families is more consistent with a systematic property of the
measurement than with 40 independently worthless ideas.

The canonical Deflated Sharpe (Bailey & Lopez de Prado) is defined on a **periodic return
series** — `sr` is the Sharpe of that series and `T` its length. Applying it to
**per-trade dollar PnL** with `T` = trade count changes the units of both `sr` and the
`e_max` comparison, because per-trade Sharpe is not on the same scale as periodic Sharpe.

**This is explicitly NOT a request to soften the gate**, and nothing here was changed to
make a result pass. The pre-registered n_trials=40 stands and v2 is reported as FAILED. It
is a flag that the shared gate in `macro_gpu_lab/validate.py` deserves a deliberate
methodological review — ideally by mapping trade PnL onto a periodic (e.g. daily or
monthly) return series before computing DSR, and re-running every repo's scorecards
against that. That review should be its own pre-registered piece of work, decided by the
human, because it changes results everywhere.

## 7. Status

Unchanged: **everything remains SHADOW / `gate: not_cleared`.** The Qlib filter earned
its place as an evidence source (it demonstrably adds independent observations and
improves every quality metric) and is worth keeping in the live lane on that basis — but
it did not clear the gate, and no badge flips.
