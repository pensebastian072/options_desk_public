# v5 meta-model (GPU) — weak, unstable signal; encouraging but not an edge yet

Date: 2026-07-24. SHADOW research. Pre-registration `journal/experiments/deep_v5_meta_v1.json`
(before results). Feature build `desk/meta_features.py`; GPU trainer
`alpaca_gpu_lab/src/research/meta_model.py`; result
`alpaca_gpu_lab/journal/scorecards/deep_v5_meta_v1.json`.

## What it is

A GPU XGBoost-CUDA meta-model that predicts which v5 entries win, from 19 point-in-time
features (pop, entry IV, return-on-risk, IV/RV, trend distance vs 50/200-day, magnitude,
vrp, term, eruption probs, structure, calendar). Expanding walk-forward over the 1044 v5
trades (2019-2026). Then trade only the top-decile predicted-win entries and gate the
filtered book. **Labels are BS-MODELED v5 PnL (no OPRA yet) -- an upper bound.**

## Result (out-of-sample)

| | n | win rate | mean PnL | DSR (n_trials=1) |
|---|---:|---:|---:|---:|
| unfiltered v5 (scored) | 865 | 80% | $10.87 | 2.51 |
| top-decile filtered | 87 | 87% | $21.71 | 1.48 |

- **OOS rank-IC = 0.031**, per fold `[nan, -0.024, +0.130, -0.040, +0.059]`.
- All three pre-registered predictions technically CONFIRMED: top-decile win > base (87 vs
  80%), filtered mean > unfiltered ($21.7 vs $10.9), rank-IC > 0.

## The honest read -- do NOT trust this yet

- **The signal is weak and UNSTABLE.** A mean rank-IC of 0.031 is essentially noise, and it
  is carried by ONE fold (+0.13); the other three are ~0 or negative. That is the fingerprint
  of luck, not a durable edge.
- **Small n.** 87 trades in the top decile -- the win-rate/mean-PnL improvement has wide error
  bars and could be one good period (a single fold) doing the work.
- **DSR looks positive only because n_trials=1.** This is the meta-model's own single
  pre-registered config; it does NOT re-pay the v5 universe's 93-trial deflation, and it does
  not survive if the fold instability is penalized. Read it as "one filter, lenient bar," not
  a pass.
- **Labels are modeled.** Real option fills (post-OPRA) would very likely shrink this further.

## Verdict

Direction is mildly encouraging -- the top-decile filter did lift OOS win rate and mean PnL --
but the per-fold instability + small n + modeled labels mean this is **not a real edge**. It
is a reason to RE-RUN on real-option labels with more data once OPRA is signed, not to adopt
an ML filter now. GPU worked (engaged, ~12% util) but is not the bottleneck at 1044 rows; it
earns its keep only at the intraday x real-option scale.

## Next (post-OPRA)
Re-label with real-option PnL, expand samples via intraday entries, and re-check whether the
rank-IC becomes consistent across folds. If it stays one-fold-carried, drop the ML overlay.
SHADOW throughout; v5 (unfiltered) remains the champion.
