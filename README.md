# options_desk — advisory options research desk (SHADOW / paper only)

A daily **pre-open option-trade alert** system for liquid US ETFs, plus the research
harness that produced its rules. It reads a volatility/regime signal, routes each symbol to
one defined-risk option structure, validates candidates against liquidity and probability
floors, and pushes an advisory Telegram alert with a loopback dashboard.

> **Advisory only. This software never places an order.** There is no execution code and no
> broker write path anywhere in this repository. Every alert is a suggestion for a human who
> decides and trades manually. Nothing here is investment advice.

## Honest status

- Every strategy variant **FAILS** the canonical overfit gate (deflated Sharpe < 0). The
  research is reported as failing, not massaged into passing.
- All backtest pricing is **Black-Scholes modeled with proxied implied volatility**, not
  real option fills, so results are an **upper bound**. Real-option validation is pending.
- The desk runs in **SHADOW**: it tracks every alerted candidate hold-to-expiry so live
  results accumulate against the same yardstick.

## What it does

```
qlib-style signal (08:55)  ->  request build (09:05, silent)
                           ->  live read-only quote validation (09:35) -> Telegram alert
                           ->  intraday re-check (10:00) -> progress + advisory CLOSE signals
                           ->  after-close review (16:15) -> day summary + tomorrow's watch
```

Structures: short put spread (bullish), short call spread (bearish), iron condor (neutral),
routed by a per-asset directional lean. Entry gates: predicted-eruption veto, 200-day trend
gate on put-side premium, 6-month momentum gate on call-side premium, IV/RV richness,
probability-of-profit >= 0.51, and a hard per-trade max-risk cap.

## Requirements

- Python 3.11+
- `pip install -r requirements.txt` (research extras: `requirements-research.txt`)
- A market-data source for the underlying price history (the code reads daily CSVs with
  `date,close,factor` columns from a configurable directory)
- Optional: a Telegram bot for alerts; a read-only broker/market-data session for live quotes

## Setup

1. Copy `.env.example` to `.env` and fill in what you use.
2. Copy `secrets/telegram.json.example` to `secrets/telegram.json` and add your bot token
   and chat id. **`secrets/` is gitignored — never commit it.**
3. Point `QLIB_LAB_DIR` (or the config paths in `desk/config.py`) at your price-CSV
   directory and signal flag.
4. `python -m pytest` to verify.

## Usage

```bash
python -m desk.run_desk --once          # build + publish today's request (silent)
python -m desk.run_desk --once --telegram --status-only
python -m desk.etf_options --request    # build the ETF candidate request
python -m desk.shadow --progress        # open-position progress + advisory exit signals
python -m desk.review --local           # after-close review
python -m ui.app                        # dashboard on 127.0.0.1:8078
```

Research harness (offline, no broker):

```bash
python -m desk.etf_backtest --v5    # 200-day trend gate
python -m desk.etf_backtest --v10   # + call momentum gate  (best variant)
python -m desk.etf_backtest --v11   # + 2x-credit stop-loss
python -m desk.etf_backtest --v12   # 16-delta strikes
```

## Research discipline

Every variant is **pre-registered before results** in `journal/experiments/`, evaluated with
a canonical overfit gate (PBO + deflated Sharpe), and reported honestly including failures.
Correlated same-day entries are **clustered** into single observations so the trade count is
not inflated. Negative results are kept in `journal/research/` deliberately — several of the
most useful findings are things that did **not** work.

## Safety design

- No broker credentials, no order placement, no automated execution.
- Any broker integration is **read-only** market data.
- The dashboard binds `127.0.0.1` only.
- Secrets live in gitignored files and are never logged or sent to the browser.

## License / disclaimer

Provided as-is for research and education. Options trading involves substantial risk of
loss. Backtested results are modeled, not achieved, and do not predict future returns. You
are responsible for your own trading decisions.
