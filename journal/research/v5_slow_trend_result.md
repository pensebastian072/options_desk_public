# v5 (200-day trend gate) — the winner: 2022 loss cut 60%, best total

Date: 2026-07-23. SHADOW research note. Pre-registration
`journal/experiments/options_etf_gate_v5.json` (written before results).
Run: `desk.etf_backtest --v5`. Artifacts: `options_etf_gate_v5.{json,_trades.jsonl,_equity.csv}`.

## The one change vs v4

Same trend gate, **slower window: 200-day SMA instead of 50-day.** Do not sell put-side
premium (put spread / iron condor) when the symbol is below its 200-day average. The
50-day let put trades back in on bear-market rallies; the 200-day stays defensive through
the whole bear.

## v3 vs v4 vs v5, per year (cluster-adjusted, same data)

| year | v3 | v4 (50-day) | v5 (200-day) |
|---|---:|---:|---:|
| 2019 | +$696 | −$401 | −$229 |
| 2020 | +$3,597 | +$2,795 | +$3,397 |
| 2021 | +$5,266 | +$4,708 | +$4,494 |
| **2022** | **−$7,025** | −$4,300 | **−$2,802** |
| 2023 | −$1,273 | +$1,739 | +$1,102 |
| 2024 | +$2,976 | +$1,962 | +$2,134 |
| 2025 | +$3,254 | +$3,203 | +$2,075 |
| 2026 | +$2,223 | +$1,707 | +$2,178 |
| **cluster total** | **+$2,830** | +$3,293 | **+$5,111** |
| PF (cluster) | 1.35 | 1.36 | **1.62** |
| DSR (cluster) | −37.2 | −40.7 | **−37.3** |

## Pre-registered predictions — scored

1. "2022 loss smaller than v4's −$4,300" → **−$2,802. CONFIRMED** (60% below v3, vs v4's 39%).
2. "at least one recovery window loses upside vs v4" → **CONFIRMED**: 2023 gave back
   +$1,739 → +$1,102 (the 200-day re-admits put-side late after the Sep-Oct 2023 dip).
3. "cluster-adjusted total ≥ v4 (+$3,293)" → **+$5,111. CONFIRMED** — best of all variants.

**3 of 3 confirmed.** The slower gate is the better trend measure on this data.

## Read

- **v5 is the best variant so far:** highest total (+$5,111 vs +$2,830 v3), highest PF
  (1.62), and the least-bad DSR of the trend variants. It nearly **doubled** v3's total
  while **cutting the 2022 loss 60%**.
- **The 200-day > 50-day** because a bear trends below the slow average continuously,
  while the fast average whipsaws and re-admits risk on relief rallies — exactly the 2022
  mechanism the v3 ledger exposed.
- **Cost paid, as predicted:** 2023 gave up ~$640 of recovery upside (defensive too long
  after the dip), and 2025 softened. Net still far ahead.
- **2022 is smaller but not gone (−$2,802).** Sustained bear premium-selling has an
  irreducible cost; a per-name trend gate cannot fully remove it. Further attack would be
  a **market-wide risk-off overlay** (e.g. SPY < 200-day cuts total exposure) — a new
  pre-registered v6, layered on v5, not a retune.
- **Gate still fails** (DSR −37.3): the deflation wall is structural (per-trade Sharpe
  vs n_trials=93), unchanged by better economics. v5 stays SHADOW.

## Ranking (economic, cluster-adjusted)

**v5 (200-day) > v4 (50-day) > v3 (no gate)** on total, PF, and 2022 drawdown. If a trend
guard goes into the live desk (its own pre-registered change), **the 200-day is the one to
propose.**

## Next (new pre-registered variants only)
- **v6:** market-wide risk-off overlay (index 200-day) on top of the per-name v5 gate.
- A single pre-registered **window sweep** (50/100/150/200) if we want to confirm 200 is
  near-optimal rather than lucky — counting every window as a trial.

Status: SHADOW / advisory / not gate-cleared. Modeled prices (upper bound). Live desk
unchanged.
