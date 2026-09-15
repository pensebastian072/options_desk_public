# v8 (drop bearish call spreads) — better headline, worse in the bear. Real tradeoff.

Date: 2026-07-24. SHADOW research. Pre-registration `journal/experiments/options_etf_gate_v8.json`
(written before results, **including an explicit selection-bias disclosure**). Run:
`desk.etf_backtest --v8`.

## The change

v8 = v5 with the bearish **short call spread removed**: on a bearish Qlib lean the desk
simply does not trade. Put spreads (bullish) and iron condors (neutral) unchanged, as are
the 200-day trend gate, POP>=0.51, $1,000 cap, eruption veto, 50%-target exit.

**Origin disclosed:** the idea came from seeing call spreads lose −$913 over 7 years in the
v5 breakdown — an in-sample observation. It is defensible only because there is an a priori
mechanism: **US equity ETFs have positive long-run drift, so selling upside premium fights
the equity risk premium.** The prediction follows from the mechanism, not just the fit.

## Result

| | v5 | v8 | delta |
|---|---:|---:|---|
| cluster-adjusted total | $5,111 | **$5,593** | +$482 |
| cluster PF | 1.62 | **1.75** | better |
| cluster DSR | −37.3 | **−33.8** | less bad |
| trades | 1,044 | 854 | −18% |
| pooled total | $12,350 | **$13,570** | +$1,220 |

Per year:

| year | v5 | v8 | delta |
|---|---:|---:|---|
| 2019 | −$229 | +$522 | +$751 |
| 2020 | +$3,397 | +$3,722 | +$325 |
| 2021 | +$4,494 | +$3,717 | −$777 |
| **2022** | −$2,802 | **−$3,027** | **−$225** |
| 2023 | +$1,102 | +$1,896 | +$793 |
| 2024 | +$2,134 | +$3,564 | +$1,430 |
| 2025 | +$2,075 | +$2,081 | +$6 |
| 2026 | +$2,178 | +$1,096 | −$1,083 |

## Pre-registered predictions — scored

1. "cluster total improves vs $5,111" -> **$5,593. CONFIRMED.**
2. "2022 gets WORSE or unchanged (short calls are the one structure that should help in a
   bear)" -> **−$2,802 -> −$3,027, worse. CONFIRMED — and this is the important one.**
3. "trade count falls ~26%" -> fell **18%** (1,044 -> 854). Roughly right, slightly off
   (removing bearish days frees the non-overlap slot for later trades).

Prediction 2 confirming is what separates this from curve-fitting: the call spreads WERE
doing real work in the downtrend. Their 7-year loss came from the bull years, exactly as the
positive-drift mechanism predicts — they were paying for bear insurance that mostly did not
get used.

## Honest verdict

v8 is better on every headline number (total, PF, DSR) **but it removes the only structure
that helps when the market falls.** The remaining book is put spreads + iron condors: both
carry short-put (long-equity-ish) exposure. That is a **more concentrated, more
directionally one-sided book** — the 2022 column is the price, and in a worse or longer bear
than 2022 that concentration would hurt more than the −$225 shown here.

So this is a genuine risk/return tradeoff, not a free win:

- want maximum modeled return -> v8
- want the book to have any structure that benefits from a decline -> keep v5

**Recommendation: keep v5 as the champion.** The v8 gain (+$482 cluster, ~9%) is not worth
deleting the book's only bear-side structure, especially when the whole program's known
weakness is the bear tail. Also unchanged: **v8 still fails the canonical gate** (DSR −33.8),
prices are modeled (upper bound), and the idea's in-sample origin means the improvement is
partly guaranteed by construction.

## Status
SHADOW / advisory / not gate-cleared. Live desk unchanged (still routes bearish leans to
call spreads). If revisited, the honest test is real-option data and an out-of-sample window.
