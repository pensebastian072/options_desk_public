# ETF expansion — decorrelation screen result (entry-timing, 2019-2026)

Date: 2026-07-23. SHADOW research. Ran `desk.universe_screen` on the full point-in-time lean
history (no option data needed -- this measures entry TIMING, not prices). Report:
`journal/scorecards/etf_universe_screen.json`. Liquidity (Alpaca) + real-option PnL are the
next phases; adopt nothing without pre-registration.

## What it measures

For each candidate ETF that qlib already covers (62 of 112; the 50 missing are mostly the
AUM-duplicate / thin-option names we expected to reject anyway), how many NEW independent
(cluster-adjusted) v5 entry dates it adds over the current 31. High = decorrelates entry
timing = adds evidence; low = a clone of what we already trade. This is the honest selection
metric (not AUM, not standalone PnL).

## Result: decorrelation comes from DIFFERENT asset classes, not equity clones

Base 31 = **287** independent entry dates. Top new candidates by independent dates added:

| symbol | bucket | +indep dates | decorr |
|---|---|---:|---:|
| UNG | commodities (nat gas) | +11 | 0.92 |
| XOP | energy E&P | +8 | 0.89 |
| IWO | small-cap growth | +7 | 0.89 |
| EMB | EM bonds | +6 | 0.90 |
| DBC | broad commodities | +6 | 0.90 |
| INDA | India | +6 | 0.89 |
| SHY | short treasuries | +5 | 0.91 |
| XHB | homebuilders | +5 | 0.89 |
| VLUE | value factor | +5 | 0.89 |
| GDXJ | jr gold miners | +4 | 0.88 |
| XRT | retail | +4 | 0.88 |
| IYT | transports | +4 | 0.87 |

Greedy cumulative pickup of the best ~12 takes independent dates **287 -> 351 (+22%)**. The
large-cap-equity adds (RSP +3, IWF +3) contribute least -- they move with the SPY/QQQ we
already hold. **This is the "decorrelation, not AUM" thesis confirmed on data:** the value is
in natural gas, energy, commodities, EM bonds, India, homebuilders, short rates -- niches
that enter on different dates than the core equity/rates/metals book.

## Honest caveats (what this is NOT yet)

- **Entry-timing only. No liquidity, no PnL.** Some top decorrelators (UNG, XOP, DBC, GDXJ,
  XRT, XHB) have decent options; others (INDA, EWY, BNDX, MUB, SHY) likely have THIN options
  and will FAIL tomorrow's Alpaca liquidity gate. Liquidity is the next filter.
- **Modest, not transformative.** +22% independent dates from a ~12-ETF expansion -- the 31
  is already fairly decorrelated. Meaningful evidence, not a step-change.
- **Adds LOOKS, so it raises the deflation bar.** Every added symbol counts in `n_trials`;
  the real-option PnL test must clear the higher bar, not just show more trades.

## Next (tomorrow, in order)

1. Alpaca options **liquidity gate** on the top decorrelators -> drop the thin ones.
2. Real-option/intraday/GPU deep test (2024+) on the liquid decorrelated survivors.
3. Pre-register only the keepers as a new universe spec. Frozen 31 stays live until then.
