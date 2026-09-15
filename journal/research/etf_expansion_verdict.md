# ETF expansion verdict — decorrelation and liquidity are in tension; only 3 survive both

Date: 2026-07-24. SHADOW research. Sources: `desk/universe_screen.py` (decorrelation, full
2019-2026 lean history) + `desk/yf_liquidity.py` (yfinance current chains). Reports:
`journal/scorecards/etf_universe_screen.json`, `journal/scorecards/yf_option_liquidity.json`.

## Why yfinance

Alpaca's OPRA agreement is unsigned, so its option feed is "indicative": inflated spreads,
no open interest, no greeks -- useless as a liquidity gate. **yfinance returns real current
chains with bid/ask + open interest + volume + IV** (SPY ATM put: 0.64% spread, 570k OI), so
it gates LIQUIDITY properly. It has **no option history**, so it does NOT unblock the
historical real-option deep test -- that still needs OPRA or Polygon.

## Methodology correction (important)

The first run was executed on a **Saturday** and reported absurd spreads (HYG: 1.5M open
interest but an "80% spread"). Quoted spreads outside RTH are stale/wide and meaningless.
Fixed: **open interest and volume are end-of-day settled and reliable at any time; the spread
test is applied only during RTH** and is otherwise recorded as advisory. The depth floor is
calibrated to the frozen 31 (their near-ATM OI 25th percentile ~= 31k). Sanity check after
the fix: **24 of 31** base symbols pass -- consistent with a universe originally chosen for
liquidity.

## The verdict: the best decorrelators are NOT option-liquid

| symbol | +independent dates | near-ATM OI | liquid? |
|---|---:|---:|---|
| UNG | +11 | 4,852 | thin |
| XOP | +8 | 13,393 | thin |
| IWO | +7 | 0 | thin |
| **EMB** | **+6** | 11,143 | **LIQUID** (via volume) |
| DBC | +6 | 33 | thin |
| INDA | +6 | 12,508 | thin |
| SHY | +5 | 2,271 | thin |
| XHB | +5 | 11,317 | thin |
| GDXJ | +4 | 4,487 | thin |
| **XRT** | **+4** | 13,299 | **LIQUID** (via volume) |
| **RSP** | **+4** | 35,155 | **LIQUID** (via OI) |
| IYT / IWN / MUB / BNDX / VLUE | +4/+4/+4/+4/+5 | <300 | thin |

**Only EMB, XRT, RSP pass both.** The top decorrelators -- natural gas (UNG), small-cap
growth (IWO), broad commodities (DBC), India (INDA), homebuilders (XHB), short rates (SHY) --
are exactly the names with no real option market. That is the tension in one table: **the
ETFs that would add independent evidence are the ones you cannot trade options on, and the
ones you can trade are correlated with what we already hold.**

Note the three survivors are marginal: EMB and XRT clear only via the volume route (OI ~11-13k,
below the 31k depth bar), and RSP -- the only one clearing on OI -- is the weakest decorrelator
of the three (an equal-weight S&P clone, +4 dates).

## Recommendation

**Do not expand the universe on this evidence.** The realistic gain is ~+14 independent entry
dates (EMB+XRT+RSP) on a base of 287 -- roughly +5% -- while adding 3 symbols to `n_trials`,
which raises the deflation bar. That is a poor trade: more looks paid for, marginal evidence
gained. The frozen 31 stays the operating universe.

If revisited: EMB and XRT are the only two worth a real-option test (they at least combine
some decorrelation with tradable volume), and only after an RTH spread confirmation and a
pre-registered PnL test. RSP adds liquidity but little independence.

## Status
Frozen 31 unchanged and live. Nothing adopted. The expansion question is answered: **AUM was
never the gate, decorrelation was the right metric, and the honest answer is that the
decorrelated niches are not option-tradable.**
