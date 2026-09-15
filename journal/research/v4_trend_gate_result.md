# v4 trend gate — the 2022/2023 fix: partial win, honestly

Date: 2026-07-23. SHADOW research note. Pre-registration
`journal/experiments/options_etf_gate_v4.json` (written before results).
Run: `desk.etf_backtest --v4`. Artifacts: `options_etf_gate_v4.{json,_trades.jsonl,_equity.csv}`.

## The one change

v4 = v3 + a **per-symbol trend gate**: do NOT sell put-side premium (put spread or iron
condor) when the underlying is **below its 50-day moving average**. Bearish call spreads
are still allowed. Everything else is identical to v3. This came directly from the v3
trade ledger, which showed the losses were concentrated in sharp directional-down months
(2022 Jan/Apr/Jul/Aug; 2023 Sep/Oct), selling puts into falling names.

## v3 vs v4, per year (cluster-adjusted engine, same data)

| year | v3 PnL | v4 PnL | change |
|---|---:|---:|---|
| 2019 | +$696 | −$401 | worse |
| 2020 | +$3,597 | +$2,795 | −$802 |
| 2021 | +$5,266 | +$4,708 | −$558 |
| **2022** | **−$7,025** | **−$4,300** | **+$2,725 (−39% loss)** |
| **2023** | **−$1,273** | **+$1,739** | **+$3,012 → profitable** |
| 2024 | +$2,976 | +$1,962 | −$1,014 |
| 2025 | +$3,254 | +$3,203 | ~flat |
| 2026 | +$2,223 | +$1,707 | −$516 |
| **cluster total** | **+$2,830** | **+$3,293** | **+$463** |

Dropped 2,617 put-side entries on trend (below SMA50). Structure mix shifted toward call
spreads (271 vs 220) and away from put spreads (175 vs 255).

## Pre-registered predictions — scored honestly

1. "2022 loss shrinks by at least half" → **−39%, NOT half. FALSIFIED.**
2. "2023 turns profitable or near-flat" → **+$1,739, profitable. CONFIRMED.**
3. "profitable years lose < 25% of their v3 PnL" → **FALSIFIED**: 2019 went negative and
   2024 dropped ~34%. The gate binds in choppy-but-up years too.
4. "cluster-adjusted total improves" → **+$463. CONFIRMED.**

Two of four confirmed. That is what a real pre-registration looks like — the trend gate
helped, but not as much as hoped, and it cost something in the good years.

## What it means

- **2023 was the clean win** — the fix turned a −$1,273 year into +$1,739 by refusing to
  sell puts into the Sep-Oct selloff.
- **2022 only halved, not solved.** Bear-market *rallies* poke back above the 50-day, and
  the gate lets put-side trades back in right before the downtrend resumes. A **slower
  trend measure (200-day SMA, or 50/200 cross)** would stay defensive through the whole
  bear and likely catch more of 2022 — but that is a **v5 hypothesis**, pre-registered
  separately, NOT a retune of v4.
- **The good years paid a small tax** (2019, 2024). Net across all years still positive
  (+$463), so the trade was worth it, but a per-name gate is blunt.
- **Gate still fails** (DSR −40.7) — same deflation wall; the improvement is economic, not
  a promotion.

## Next (as new pre-registered variants, not retunes)

- **v5:** slower/︎dual trend (200-day, or price below 50-day AND 50<200) to hold defense
  through a full bear like 2022.
- Consider a **market-wide risk-off kill switch** (SPY < 200-day) layered on the per-name
  gate — "what kind of year is it" at the index level.

Status: SHADOW / advisory / not gate-cleared. Modeled prices (upper bound). Live desk
unchanged; this informs whether a trend guard earns a place there.
