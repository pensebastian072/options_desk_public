# Options Desk System Overview

## Purpose

Options Desk is a read-only, SHADOW options research system. It combines local
Qlib and macro-volatility signals with live Robinhood market quotes, selects up
to five liquid ETF option ideas, sends the result to Telegram, and tracks the
hypothetical results. It never places, changes, or cancels an order.

## Morning timeline

```text
08:55  Qlib PreOpenVolDesk refreshes the market and volatility signal
  |
09:05  OptionsDeskDaily publishes the original SPY pre-open assessment
  |
09:35  Codex Options Desk Morning automation
        1. Marks existing SHADOW candidates with current option quotes
        2. Applies the current signal, freshness, and risk vetoes
        3. Fetches read-only Robinhood chains and quotes when allowed
        4. Runs the deterministic validator and ranker
        5. Sends the SHADOW or NO_TRADE result to Telegram
  |
Daily marks -> expiration settlement -> hit-rate and P&L statistics
```

The 09:35 workflow runs after the option market opens so it can use current
listed-option quotes. Codex gathers permitted market data, but local Python code
owns every filter, calculation, ranking rule, and veto.

## Strategy lanes

### Original SPY research lane

The broader SPY research desk can evaluate cash-secured short puts, defined-risk
put spreads, jade lizards, long-volatility straddles, and a VIX/IV diagnostic.
Its pre-open alert may use clearly labeled Black-Scholes estimates when live
quotes are not yet available.

### Liquid-ETF live-quote lane

The live Robinhood-priced universe is frozen to:

`SPY, QQQ, IWM, DIA, TLT, GLD, SLV, XLF, XLE`

This lane currently searches for defined-risk bullish put spreads. For each
eligible ETF, it:

1. Selects the expiration nearest 45 DTE inside the 30-60 DTE window.
2. Selects a short put nearest -0.30 delta inside [-0.35, -0.25].
3. Selects the same-expiration long put at the exact configured spread width.
4. Checks quote age, bid/ask quality, liquidity, open interest, volume, and IV/RV.
5. Prices the spread at natural executable sides rather than the midpoint.
6. Applies deterministic diversification and ranking rules.
7. Returns no more than five candidates and never forces the list to contain five.

## Signal and veto hierarchy

- Qlib supplies directional eligibility and ETF ranking.
- The macro-volatility layer supplies stress, eruption, and magnitude warnings.
- Local realized volatility is compared with live option implied volatility.
- Robinhood supplies read-only equity quotes, option chains, instruments, Greeks,
  and option quotes.
- Deterministic local finalizers decide whether a candidate survives.

A global eruption or excessive-magnitude condition vetoes short-volatility
candidates. Missing, stale, corrupt, incomplete, or contradictory data also
fails neutral to `NO_TRADE`. The workflow never queries around a veto.

## Telegram result

The morning message contains up to five eligible candidates with the ETF,
strategy, expiration, strikes, natural entry credit, maximum risk, volatility
and liquidity context, rationale, and explicit `SHADOW / not gate-cleared`
status. If nothing qualifies, Telegram sends the deterministic `NO_TRADE`
reason instead.

## SHADOW trade ledger

Each published candidate receives a stable ID. The immutable entry snapshot
records the option instrument IDs, per-leg bid and ask, midpoint, delta, implied
volatility, open interest, volume, quote timestamp, entry cash, and maximum risk.

For a short vertical:

```text
entry credit = (short bid - long ask) * 100
exit debit   = (short ask - long bid) * 100
marked P&L   = entry cash + natural closing cash - fixed round-trip costs
```

Each weekday, the 09:35 workflow requests fresh quotes only for the stored
instrument IDs. Valid natural-side marks are appended to the ledger and update
unrealized P&L, return on risk, holding days, DTE, MFE, and MAE. A mark is an
observation only; it never closes a candidate.

The canonical outcome remains hold-to-expiration. At expiration, the system
uses the last completed local Qlib underlying close on or before expiration,
calculates each leg's intrinsic value, subtracts fixed costs, and records final
P&L and whether the candidate was a hit. Aggregate reporting includes hit rate,
average and total P&L, profit factor, and per-strategy results.

Tracked values are model entry and liquidation prices, not the user's actual
broker fills. Actual-fill tracking would require a separate manual import
because brokerage accounts, positions, and orders are deliberately excluded.

## Promotion status

All strategies remain SHADOW. Existing backtests contain only 16-24 trades per
strategy, have negative Deflated Sharpe results, and do not have enough trades
for reliable PBO. A high raw profit factor cannot override the failed validation
gate. New exit policies, including profit targets, stop-losses, or DTE exits,
must be separately pre-registered and tested before use.

## Hard safety boundaries

The system may not place or cancel orders, read brokerage positions or balances,
modify watchlists, arm an order guard, override a veto, promote itself out of
SHADOW, or expose the dashboard publicly. Robinhood usage is market-data-only.
The dashboard binds only to `127.0.0.1:8078`.

## Durable references

- `HANDOFF.md`: implementation status, commands, invariants, and current results.
- `CLAUDE.md`: repository operating runbook.
- `journal/experiments/options_shadow_ledger_v1.json`: frozen measurement schema.
- `journal/research/options_execution_ledger_reference.md`: external design research.
- `journal/shadow_open.json`: currently open SHADOW candidates.
- `journal/shadow_marks.jsonl`: append-only natural-side daily marks.
- `journal/shadow_pnl.jsonl`: settled expiration results.

