# Why the call spreads failed — and the fix that worked (v9 negative, v10 positive)

Date: 2026-07-24. SHADOW research. Pre-registrations `options_etf_gate_v9.json` /
`options_etf_gate_v10.json` (both written before results).

## The post-mortem: why calls lost

v5 call spreads: **−$913 over 7 years at an 85% win rate.** Avg win $35, avg loss **$217
(6x)**. The losses were concentrated in the era's highest-momentum names:

| worst | | best | |
|---|---:|---|---:|
| SMH | −$629 | SPY | +$417 |
| GLD | −$597 | TLT | +$339 |
| XLY | −$419 | XLV | +$210 |
| QQQ | −$266 | LQD | +$202 |
| XBI | −$227 | GDX | +$191 |

AI/semis, the gold bull, Nasdaq, biotech — sustained uptrends that ran straight through the
short strikes. Slow/defensive names were fine. **The user's hypothesis (selling calls on
high-growth/high-optimism sectors is the losing side) is exactly what the ledger shows.**

## v9 — symmetric trend gate: FAILED (useful negative)

Idea: v5 refuses to sell PUT premium below the 200-day; mirror it and refuse to sell CALL
premium above the 200-day. Seemed like the obvious missing half.

**Result: call PnL got WORSE, −$913 -> −$1,929.** The book total rose slightly (+$322) only
because it traded 47% fewer calls, not because calls improved.

**Why it failed:** selling calls only below the 200-day means selling into *downtrends* —
i.e. right into **violent bear-market rallies**, the sharpest upside moves there are. So
short calls lose in uptrends (trend grinds through) AND in downtrends (bounce spikes).
Direction alone is not the filter. Prediction 1 falsified.

## v10 — momentum gate (the user's idea): WORKED

Rule: do not sell call premium on a symbol whose **126-session (6-month) momentum > +10%**.
Momentum is the market's aggregate pricing of earnings/growth/optimism — the measurable
proxy for "this sector keeps going."

| metric | v5 | v9 | **v10** |
|---|---:|---:|---:|
| call-spread PnL | −$913 | −$1,929 | **−$454** |
| call losing trades | 45 | 29 | 31 |
| call PnL per trade | −$3.08 | −$12.21 | **−$2.15** |
| **cluster total** | $5,111 | $5,433 | **$6,231** |
| cluster PF | 1.62 | 1.65 | **1.78** |
| cluster DSR | −37.3 | −37.9 | **−36.5** |
| max drawdown | −$1,011 | — | **−$709** |
| 2022 | −$2,802 | −$2,917 | −$2,880 |

All four pre-registered predictions confirmed. **v10 is the best variant produced so far:**
highest total (+22% over v5), highest PF, lowest drawdown, and 2022 essentially unchanged
(the bear-side structure is retained, unlike v8 which deleted it).

Note the side effect: cluster-adjusted n went UP (373 -> 385) even though pooled trades fell
(1,044 -> 1,008) — skipping high-momentum call trades freed non-overlap slots for entries on
*different* dates, which adds independent observations.

## Honest limits

- **Calls are still unprofitable (−$454).** The momentum gate cut the loss ~50% and improved
  per-trade economics ~30%, but it did not turn the structure positive. The book improves
  mostly by trading the bad structure less.
- **Still fails the gate** (DSR −36.5). Modeled prices (upper bound). SHADOW.
- The +10% / 126-session parameters were fixed before running and NOT swept; a sweep would
  be a separate pre-registration counting every combination.

## The news idea — measured and rejected on data grounds

The user's first proposal was per-sector **news article COUNT** as an optimism proxy. Tested
the data: the Alpaca news feed tags market-wide names, not sector ETFs. Over a 6-month
sample: SPY **7,657** tagged articles, FXI 1,432 — but **SMH=1, XBI=1, XLC=1, XLY=2**.
Per-sector counts are far too sparse to gate anything. Reported rather than forced. (A
market-wide attention regime from SPY counts is feasible and remains untested.)

## Where this leaves the ladder

**v10 > v5 > v8 > v9 ≈ v6 ≈ v4 > v3** on cluster total/PF/drawdown. v10 is the first variant
that both improves returns AND lowers drawdown without sacrificing bear-side structure.

Next candidates (untested, each needs its own pre-registration):
1. **Momentum gate on the condor's call wing** (v10 only gates the pure call spread).
2. **Market-wide news-attention regime** from SPY article counts (the one usable slice).
3. **Replace the call spread with a put-side-only book in high-momentum regimes** rather than
   skipping the trade entirely.
4. Earnings-season calendar gate (sector ETFs move on constituent earnings clusters).

Status: SHADOW / advisory / not gate-cleared. Live desk unchanged (still v5-style routing).
