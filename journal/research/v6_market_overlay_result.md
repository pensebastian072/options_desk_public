# v6 (market risk-off overlay) — honest result: it did NOT beat v5

Date: 2026-07-23. SHADOW research note. Pre-registration
`journal/experiments/options_etf_gate_v6.json` (written before results).
Run: `desk.etf_backtest --v6`. Artifacts: `options_etf_gate_v6.{json,_trades.jsonl,_equity.csv}`.

## The change

v6 = v5 (per-symbol 200-day gate) **plus** an index-level overlay: when **SPY is below its
own 200-day SMA** (market bearish), suppress ALL put-side premium across the whole
universe, not just per name. Call spreads stay exempt. The user's framing: price above the
long average = bullish (ok to sell premium); below = bearish (stand down the put side).

## v5 vs v6, per year (cluster-adjusted)

| year | v5 (per-name 200d) | v6 (+ SPY-200d overlay) | change |
|---|---:|---:|---|
| 2019 | −$229 | −$229 | 0 |
| 2020 | +$3,397 | +$2,454 | **−$943** (sat out early recovery) |
| 2021 | +$4,494 | +$4,494 | 0 |
| 2022 | −$2,802 | **−$3,056** | **−$254 (worse)** |
| 2023 | +$1,102 | +$1,702 | +$600 (sat out the Sep-Oct dip) |
| 2024 | +$2,134 | +$2,134 | 0 |
| 2025 | +$2,075 | +$2,284 | +$209 |
| 2026 | +$2,178 | +$1,547 | −$631 |
| **cluster total** | **+$5,111** | **+$5,010** | **−$101** |
| PF | 1.62 | 1.63 | ~same |
| DSR | −37.3 | −36.5 | ~same |

Overlay dropped 316 put-side trades in market risk-off (on top of v5's per-name 3,130).

## Pre-registered predictions — scored

1. "2022 loss smaller than v5's −$2,802" → **−$3,056, LARGER. FALSIFIED.**
2. "2020 and/or 2023 give up more upside" → 2020 gave up $943. **CONFIRMED.**
3. "total within ±25% of v5" → +$5,010 vs +$5,111 (−2%). **CONFIRMED.**

The key prediction (1) failed. The overlay made 2022 slightly *worse*, not better.

## Why the index overlay didn't help — the real lesson

**The per-name 200-day gate already captures the regime.** When SPY is below its 200-day,
most individual names are already below their own 200-day too, so v5 has already blocked
those put-side trades. The market overlay then mostly removes trades v5 already handled —
plus a few that would have *won* (bear-market rallies where a condor hit its 50% target
before the next leg down). Net: it strips some winners without removing new losers, so
2022 nudged worse and 2020 gave up recovery premium. **Redundant and slightly blunt.**

## Verdict / ranking (cluster-adjusted, economic)

**v5 ≈ v6 > v4 > v3.** v5 wins on total (+$5,111 vs +$5,010); v6 is a hair better on DSR
(−36.5 vs −37.3) — a wash. The extra index overlay is **not worth the complexity**: it
does not beat the simpler per-name 200-day gate.

**Keep v5 as the best variant.** If a trend guard ever goes live, propose the per-symbol
200-day (v5) — the market overlay adds machinery without a payoff on this data.

Gate still fails (DSR −36.5): structural deflation wall, unchanged. SHADOW throughout.

## What this closes and what remains
- The trend-guard line of research is essentially settled: slower (200d) per-name is best;
  an index overlay adds nothing. Further window/index tuning would be p-hacking.
- The irreducible ~$2,800 2022 loss is the cost of selling premium at all in a sustained
  bear; only a structurally different idea (long-tail hedge, or standing fully down in a
  bear) would remove it — a genuinely new hypothesis, not a filter tweak.

Modeled prices (upper bound). Live desk unchanged.
