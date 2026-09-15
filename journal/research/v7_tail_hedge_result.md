# v7 (rolling tail hedge) — it works as insurance, but the carry isn't worth it here

Date: 2026-07-23. SHADOW research note. Pre-registration
`journal/experiments/options_etf_gate_v7.json` (written before results).
Run: `desk.etf_backtest --v7`. Artifact: `options_etf_gate_v7.json`.

## The overlay

v7 = the v5 short-premium book **plus** a rolling long-tail hedge: buy one long SPY put
(~7% OTM, ~45 DTE, VIX-priced) on the first trading day of each month, hold to expiry,
roll monthly, 1 contract. It is a **portfolio risk overlay, not a gate trial** — v5's
per-trade gate verdict is unchanged. Reported at the annual (pooled) level.

## v5 book vs v7 (book + hedge), per year (pooled $)

| year | book | hedge | net | hedge paid months |
|---|---:|---:|---:|---:|
| 2019 | −$229 | −$923 | −$1,152 | 0 |
| 2020 | +$3,397 | **+$2,111** | +$5,508 | 2 (COVID crash) |
| 2021 | +$4,494 | −$3,172 | +$1,322 | 0 |
| **2022** | −$2,802 | **+$1,356** | **−$1,447** | 3 |
| 2023 | +$1,102 | −$1,394 | −$292 | 0 |
| 2024 | +$2,134 | −$1,599 | +$535 | 0 |
| 2025 | +$2,075 | −$1,541 | +$534 | 1 |
| 2026 | +$2,178 | −$1,583 | +$595 | 0 |
| **total** | **+$12,350** | **−$6,747** | **+$5,604** | — |

(Book totals here are pooled/all-trades, not the cluster-adjusted +$5,111.)

## Pre-registered predictions — scored (3 of 3)

1. "2022 net smaller than v5's −$2,802" → **−$1,447. CONFIRMED** (hedge halved the bear loss).
2. "every calm year worse by the carry" → **CONFIRMED** (each calm year dragged −$0.9k to −$3.2k).
3. "hedge total PnL negative" → **−$6,747. CONFIRMED** (tail hedges have negative expected value).

## The honest verdict — insurance that costs too much (at these params)

The hedge **did exactly what a tail hedge does**: it paid in the two stress years (2020
COVID crash +$2,111; 2022 bear +$1,356) and bled a small, steady carry the rest of the
time. It **halved the 2022 loss** (−$2,802 → −$1,447).

**But it is not worth it on this data:**

- **It cut total return roughly in half** (pooled +$12,350 → +$5,604). The −$6,747 of carry
  swallowed more than half the book's profit.
- **It did NOT improve the risk-adjusted profile.** The carry was *lumpy*, not smooth —
  2021 alone bled −$3,172 (a low-vol melt-up where VIX-priced puts were both pricey and
  worthless). So annual volatility barely fell while mean return halved. A hedge is only
  worth it if it cuts variance more than it cuts return; this one does not.
- **2022 was a grind, not a gap.** As flagged in the pre-registration, a 45-DTE 7%-OTM put
  mostly expires worthless in a slow bleed; it paid only 3 of 12 months in 2022. The hedge
  helped 2020 (a real crash) far more than 2022 (the year we were targeting).

## Ranking and recommendation

On total and risk-adjusted return: **v5 (unhedged) > v7 (hedged).** The tail hedge buys
drawdown reduction at a price that is too high with these fixed parameters. **Keep v5.**

A tail hedge *could* pencil out with cheaper structuring (further OTM, financed put
spreads, or a VIX-call sleeve), but finding that would be a **single, separately
pre-registered parameter study** — not a retune bolted onto v7. It is a real future track
only if drawdown, not growth, becomes the objective.

## Where the whole line of research stands

- **v5 (per-symbol 200-day trend gate) is the champion.** It nearly doubled the base and
  cut 2022 by 60% with no carry cost.
- v6 (index overlay) added nothing; v7 (tail hedge) reduces drawdown but costs too much
  return. Both are honest negatives that make v5 look better, not worse.
- The residual ~$1.4-2.8k 2022 loss is the true cost of selling premium in a sustained
  bear. Removing it entirely requires either not trading in a bear (which v5 largely does)
  or a cheaper hedge (a new pre-registered study), not another filter.

Status: SHADOW / advisory / not gate-cleared. Model-priced (upper bound). Live desk
unchanged.
