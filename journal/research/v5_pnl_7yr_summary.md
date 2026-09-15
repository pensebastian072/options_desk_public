# v5 P&L and yearly stats — 7 years (2019-07 to 2026-07)

Date: 2026-07-24. SHADOW research. Source: `journal/scorecards/options_etf_gate_v5.json` +
`options_etf_gate_v5_trades.jsonl` (1,044 trades). v5 = the champion variant (per-symbol
200-day trend gate, POP>=0.51, $1000 per-trade cap, 50%-profit-target exit).
**Prices are Black-Scholes modeled, not real fills -> an UPPER BOUND.**

## Yearly

| year | trades | win% | P&L | PF | exited at target | avg hold |
|---|---:|---:|---:|---:|---:|---:|
| 2019 (part) | 57 | 82% | −$229 | 0.90 | 82% | 29d |
| 2020 | 143 | 85% | +$3,397 | 1.91 | 85% | 32d |
| 2021 | 165 | 84% | +$4,494 | 2.46 | 82% | 32d |
| **2022** | 97 | 69% | **−$2,802** | 0.52 | 68% | 29d |
| 2023 | 176 | 78% | +$1,102 | 1.17 | 77% | 31d |
| 2024 | 181 | 78% | +$2,134 | 1.39 | 78% | 34d |
| 2025 | 159 | 84% | +$2,075 | 1.51 | 81% | 28d |
| 2026 (part) | 66 | 88% | +$2,178 | 2.86 | 88% | 29d |
| **total** | **1,044** | **81%** | **+$12,350** | **1.38** | 80% | 31d |

**6 profitable years of 8** (2019 is a partial stub year, 2026 partial). The only real losing
year is 2022 -- the bear -- even after the v5 trend gate cut it from −$7,025 (v3) to −$2,802.

## Scale — what that P&L was earned on

- Avg max risk per trade **$218** (median $161) — the $1,000 cap rarely binds.
- **Peak concurrent positions: 27; peak capital at risk ~$6,264.**
- **+$12,350 on ~$6,264 peak deployed = ~197% over 7 years ≈ 28%/yr** on peak risk capital.
- Return on cumulative risk deployed: 5.43% (avg 5.48% per trade).
- Best trade +$208, worst −$419. Max drawdown: $1,288 pooled / $1,011 cluster-adjusted.

## Views (independence-adjusted)

| view | n | total | mean/trade | win% | PF | DSR |
|---|---:|---:|---:|---:|---:|---:|
| pooled (all trades) | 1,044 | $12,350 | $11.83 | 81% | 1.38 | −68.8 |
| **cluster-adjusted (headline)** | 373 | $5,111 | $13.70 | 77% | 1.62 | **−37.3** |
| SPY only | 21 | $353 | $16.80 | 86% | 1.35 | −9.6 |

Cluster-adjusted collapses same-date correlated entries into one observation — the honest
count. Pooled overstates independence.

## By structure (7 years)

| structure | P&L |
|---|---:|
| iron condor | **+$9,729** |
| put spread | +$3,534 |
| **call spread** | **−$913** |

Iron condors carried the book. **The bearish call spread lost money over the full 7 years** —
worth flagging: selling upside premium into a mostly-bull decade was a losing structure.

## Honest caveats

1. **Modeled prices.** BS credits with proxied IV, constant-IV repricing for the 50% target.
   Real fills are worse — treat every number above as an upper bound. Confirming this needs
   real option history (OPRA/Polygon), still blocked.
2. **Fails the canonical gate** (DSR −37.3 cluster-adjusted). Profitable ≠ promoted; the
   deflation wall (per-trade Sharpe vs n_trials=93) is documented in
   `qlib_filter_and_dsr_bar.md`. Still SHADOW.
3. **~28%/yr assumes** you actually run up to 27 concurrent positions and take every signal,
   with no slippage/commissions beyond the fixed per-leg cost, and no assignment/early-exercise
   friction.
4. 2019 and 2026 are partial years.

## One-line read
Over 7 years the v5 rule was profitable in 6 of 8 calendar years, +$12,350 modeled on ~$6.3k
peak capital (~28%/yr), carried by iron condors, with one real losing year (2022 bear) and a
losing structure (call spreads) — but it does not clear the overfit gate and the pricing is
modeled, so it stays SHADOW/advisory.
