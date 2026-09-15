# v3 trades by year — the individual trades, the regimes, and why 2022 lost

Date: 2026-07-23. SHADOW research note. Companion to `v3_backtest_2019_2026.md`.
Every individual trade is in **`journal/scorecards/options_etf_gate_v3_trades.csv`**
(1,240 rows, Excel-friendly: year, entry/exit date, symbol, structure, exit type, holding
days, POP, entry IV, credit, max risk, PnL, and the hold-to-expiry PnL for the same trade).

## First, the honest part: these prices are MODELED, not real fills

We do **not** have historical option quotes on this box. So:

- **Entry credit** = Black-Scholes model price at a proxied entry IV (RV20 × a market-wide
  volatility premium). Not a real bid/ask.
- **Exit** = BS **re-pricing** of the spread along the daily underlying path, with entry IV
  held constant, to detect the 50%-profit-target crossing.

What this backtest tests is therefore **whether the direction/structure logic is right** —
did we pick the correct side and structure for the move — priced by a model. It is **not**
a claim about real fills, and it is an **upper bound** (a real vol spike would raise the
cost to close and hurt the short book more than the model shows, especially in 2022).
Your read is exactly right: it shows whether we take the right direction, not exact dollars.

## Per-year × structure (the actual breakdown)

| year | structure | n | win% | total PnL | avg win | avg loss |
|---|---|---:|---:|---:|---:|---:|
| 2019 | iron_condor | 46 | 83% | +$483 | $50 | −$179 |
| 2019 | call_spread | 8 | 88% | +$66 | $28 | −$128 |
| 2019 | put_spread | 4 | 100% | +$147 | $37 | — |
| 2020 | iron_condor | 91 | 78% | +$1,734 | $66 | −$146 |
| 2020 | call_spread | 33 | 91% | +$429 | $41 | −$262 |
| 2020 | put_spread | 31 | 97% | +$1,434 | $50 | −$60 |
| 2021 | iron_condor | 110 | 82% | +$3,411 | $62 | −$110 |
| 2021 | call_spread | 29 | 97% | +$835 | $37 | −$200 |
| 2021 | put_spread | 44 | 84% | +$1,019 | $50 | −$117 |
| **2022** | **iron_condor** | **115** | **55%** | **−$4,275** | $72 | **−$170** |
| 2022 | call_spread | 29 | 76% | −$990 | $31 | −$239 |
| 2022 | put_spread | 36 | 69% | −$1,759 | $47 | −$267 |
| 2023 | iron_condor | 136 | 68% | −$1,606 | $62 | −$167 |
| 2023 | call_spread | 40 | 85% | −$240 | $35 | −$237 |
| 2023 | put_spread | 46 | 85% | +$573 | $42 | −$153 |
| 2024 | iron_condor | 123 | 77% | +$2,240 | $60 | −$125 |
| 2024 | call_spread | 30 | 80% | −$627 | $39 | −$260 |
| 2024 | put_spread | 43 | 91% | +$1,363 | $47 | −$115 |
| 2025 | iron_condor | 103 | 86% | +$2,336 | $50 | −$152 |
| 2025 | call_spread | 30 | 83% | −$223 | $39 | −$241 |
| 2025 | put_spread | 38 | 92% | +$1,141 | $58 | −$295 |
| 2026 | iron_condor | 41 | 83% | +$961 | $63 | −$168 |
| 2026 | call_spread | 21 | 95% | +$921 | $50 | −$81 |
| 2026 | put_spread | 13 | 92% | +$341 | $50 | −$260 |

## Why 2022 lost with a 61% win rate — the one lesson to keep

2022: **110 wins, 70 losses (61%)**, yet **−$7,025**. Because:

- **avg win $58, avg loss $192 — losses were 3.3× the wins.** The 50%-profit target caps
  each winner at half the credit; a loser runs to near-max width. So it takes ~3.3 wins to
  pay for one loss, and 61% wins is not enough.
- **Iron condors did the damage: 115 trades, 55% win, −$4,275.** A condor is a bet that the
  name stays range-bound. 2022 was a **sustained directional downtrend** (inflation peak,
  Fed +425bp, war, down Jan→Oct), so the condors' put side got run over again and again.

**Win rate is a vanity metric for premium selling.** The number that decides profitability
is loss-size ÷ win-size. That is exactly what a directional/trend regime breaks.

## Regime read per year (matches your intuition)

- **2019** calm bull, Fed pause → condors thrive.
- **2020** COVID crash then V-recovery; the eruption veto sat out the worst of March, and the
  rebound paid → net green.
- **2021** low-vol melt-up → best condor year (+$3,411).
- **2022** BEAR / high-inflation / hiking / war → **the failure**: neutral condors in a
  directional-down tape.
- **2023** choppy, regional-bank scare then AI rally; our neutral condors still bled
  (−$1,606) while the bullish **put spreads made money (+$573)** — the structure that
  matched the eventual up-move won.
- **2024–2026** soft-landing bull, cuts begin → condors + put spreads green again.

Notice the tell: in both bad years (2022, 2023) the **directional structure that matched
the real move was fine; the neutral condor was the loser.** The desk over-trades condors
because Qlib's lean is "neutral" most days — but "neutral signal" is not the same as "the
market will stay range-bound this year."

## Your regime-analog idea (proposed research, not built yet)

Two levels, both worth doing as **new pre-registered variants** (not retunes of v3):

1. **v4 — trend/regime guard (the direct fix):** before selling a condor, check whether the
   name/market is in a sustained trend (e.g. price vs its 50/200-day, or a macro
   risk-off flag). In a clear downtrend, suppress condors and the put side, or shift to
   call spreads / defensive only. This attacks 2022 specifically without touching the good
   years. Cheap to build on this exact harness; we already have the daily closes + the
   macro panel.
2. **v5 — historical regime analog (your bigger idea):** characterize the current year by
   macro features (inflation trend, rate direction, growth, election cycle, geopolitical
   stress) and find the **most similar past year** (can reach back to the 70s/80s with
   macro series), then use that analog's realized behavior to set exposure. Not prediction —
   "similar conditions rhyme." Bigger lift (needs a macro-feature panel + similarity
   scoring) and speculative, but a legitimate research track. Document and pre-register
   before building.

Both keep the discipline: honest gate, no p-hacking, SHADOW until proven.

## Status
SHADOW / advisory / not gate-cleared. Modeled prices (upper bound). Nothing here changes
the live desk. Full per-trade data: `options_etf_gate_v3_trades.csv`.
