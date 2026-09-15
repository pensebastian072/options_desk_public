# TASK (run tomorrow) — deep real-option, intraday, GPU backtest of v5 + ML trade-quality model

Prepared 2026-07-23. Everything SHADOW / pre-registered / no p-hacking.

## STATUS 2026-07-24 -- BLOCKED ON OPRA

P0 started. Alpaca option access confirmed (OptionHistoricalDataClient works, 13.5k SPY
contracts with live bid/ask), CUDA up (RTX 3050, torch cu121). **HARD BLOCKER: the OPRA
agreement is NOT signed on the Alpaca account** (`get_option_chain(feed="opra")` ->
`"OPRA agreement is not signed"`). Without OPRA we are on the **indicative feed**: spreads
are inflated/unreliable and greeks are None. This blocks BOTH a reliable liquidity gate
(P0.5) AND the real-option pricing deep test (P1) -- the entire "real option data" premise.

**USER ACTION REQUIRED:** sign the OPRA (options data) agreement in the Alpaca dashboard
(Account -> market data / options data). Non-professional real-time OPRA may require a paid
data subscription -- check the Alpaca plan. Once signed, re-probe `feed="opra"` and continue.

Preliminary indicative-feed liquidity read (`alpaca_gpu_lab/journal/option_liquidity.json`,
`src/research/option_liquidity.py`): most top decorrelators are thin on options
(EMB/BNDX/EWU/IWN/IWO/DBC near-zero volume); a few (MDY/EWY/IWF/XHB/GDXJ) are near the
base-31 median -- NOT definitive on the indicative feed. Confirm with OPRA before adopting.

## Why

The v3-v7 backtests are model-priced (Black-Scholes on qlib DAILY closes, CPU). v5 (200-day
per-symbol trend gate) is the proven best (+$5,111 cluster, cut 2022 60%). This task tests
how v5 would REALLY have done with **real option chains + intraday minute bars + GPU**, adds
a **GPU ML trade-quality model**, then audits our math vs reputable repos.

Decisions: real option chains; intraday minute 2022-2026; GPU also trains an ML model;
output = aggregate stats (no per-day calendar lookup).

## On the box (verified)

- `alpaca_gpu_lab/market_data/raw/bars_{1Min..1Hour}/symbol=X/year=Y/` — real intraday EQUITY
  bars, ~22 ETFs, 2022-2026. GPU: RTX 3050, torch cu121, XGBoost-CUDA
  (`src/models/magnitude.py`, `src/gpu.py`, `src/models/evaluate.py::run_battery`,
  `src/experiments/registry.py`, gate via `macro_gpu_lab/validate.py`).
- **NO real option chains on disk.** Alpaca SDK has `alpaca.data.historical.option` but
  **Alpaca option history starts ~2024** — 2022 needs Polygon/ORATS/CBOE.
- v5 rule reusable: `options_desk/desk/etf_backtest.py` (`v3_eligible`, `route_from_lean`,
  `build_structure`, PUT_SIDE 200-day gate, `simulate_exit`, `cluster_by_date`, `evaluate`);
  `desk/bs.py`; qlib leans `qlib_lab/journal/exports/qlib_score_history.parquet`.

## Where it runs

Build in **alpaca_gpu_lab** (owns intraday data + GPU venv + XGBoost-CUDA + gate). Port the
small v5 entry rule in. options_desk stays the live desk; alpaca_gpu_lab is its deep bench.

## Phases

- **P0 (blocks all):** provider = **ALPACA** (confirmed 2026-07-23), same keys as
  alpaca_gpu_lab, `alpaca.data.historical.option`. **Real option history ~Feb 2024+**, so the
  real-fill deep test is a **2024->2026 window and CANNOT reach the 2022 bear** — state this
  plainly; pre-2024 stays BS-modeled or excluded, never presented as real. Write ingestion
  adapter -> normalized parquet
  `option_bars(symbol,expiry,strike,type,ts,bid,ask,mid,iv,delta,oi,volume)` under
  `market_data/raw/option_bars/`. Backfill missing ETF intraday equity via `alpaca_backfill.py`.
- **P0.5 (universe expansion screen):** the ~112-ETF top-AUM-by-sector pool
  (`journal/research/etf_universe_screen_candidates.json`, method in `etf_universe_screen.md`).
  (A) STRUCTURAL liquidity gate via Alpaca option snapshots (OI/volume/spread) + IV/RV + qlib
  coverage -- pass/fail, AUM is not the gate. (B) **Select by DECORRELATION** -- rank
  survivors by marginal independent-entry-date gain (greedy, lowest Jaccard overlap) using
  `desk/qlib_evidence.py` on the FULL 2019-2026 lean history (not Alpaca-bounded, since it is
  entry-timing not option prices); weight decorrelation, NOT AUM or standalone PnL. Only the
  decorrelated survivors enter P1, and P1/P2 deflation `n_trials` counts the FULL pool
  screened. Adopt nothing without a pre-registered keeper universe. Guards against the
  test-100-cherry-pick-winners selection-bias trap.
- **P1 (pre-reg `deep_v5_real_v1`):** replay v5 with REAL option bid/ask, entries timed on
  intraday bars, real quotes for the 50%-target exit + expiry settle. No BS. Cluster same-date
  entries; canonical gate. GPU vectorizes the quote-joins/repricing (batch to 6 GB). Report
  aggregate stats + gate + the BS-vs-real gap (how optimistic was BS).
- **P2 (pre-reg `deep_v5_meta_v1`):** NEW hypothesis (not a v5 retune). Meta-label = did the
  v5 entry win (real PnL>0). Features intraday point-in-time (IV/RV, term, trend distance,
  Qlib lean/conviction, magnitude, time-of-day, credit/width, POP). XGBoost-CUDA walk-forward
  (magnitude.py pattern), purged/embargoed. Trade top-decile only -> filtered v5; gate it with
  deflation counting the ML trials. Report vs unfiltered v5. Prior: gate likely still bites.
- **P3:** aggregate per-year/overall report (real-option v5 + ML-filtered v5), cluster gate,
  BS-vs-real gap. Note under alpaca_gpu_lab/journal/ + options_desk/journal/research/.
- **P4 (after our test):** audit math vs 2-3 reputable repos — options/greeks/POP
  (QuantLib-Python / vollib / lets_be_rational), PBO/DSR (Bailey & Lopez de Prado ref;
  reconcile the per-trade-vs-periodic Sharpe DSR wall in `qlib_filter_and_dsr_bar.md`),
  trend/regime. WebSearch/WebFetch, cite files, list discrepancies; do NOT vendor blindly.

## Verify (tomorrow)

`-m src.gpu` CUDA smoke first. P0: spot-check a SPY expiry's bid/ask vs broker. P1: real
credits <= BS credits (real fills worse); honest gate. P2: `nvidia-smi` shows the 3050
engaged; deflation counts ML trials. Both preregs committed BEFORE results.

## Constraints

SHADOW/paper only; broker read-only; every experiment pre-registered before results; no
p-hacking. GPU used because intraday x real chains is genuinely large. v5/v6 for all years
already computed (`options_etf_gate_v5.json`/`_v6.json`) — no re-run.
