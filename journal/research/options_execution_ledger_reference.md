# Options execution-ledger reference

Recorded 2026-07-22 for P6 of `options_desk`. This is a design reference, not an
execution dependency. The desk remains advisory SHADOW research and Robinhood remains
read-only.

## Selected design

- Preserve immutable per-leg entry bid, ask, midpoint, instrument ID, delta, IV,
  liquidity fields, and quote time.
- Mark open candidates with the natural closing side: buy short legs at ask and sell
  long legs at bid. Store append-only daily marks plus MFE/MAE in the open snapshot.
- Keep hold-to-expiry intrinsic settlement as the canonical outcome. Daily marks never
  close a candidate. Any profit target, stop loss, or DTE exit is a new hypothesis that
  must be pre-registered and added to `n_trials`.
- Track estimated SHADOW economics separately from any human broker fill. Do not use
  Robinhood account, order, position, cancellation, or watchlist tools.

## External repositories reviewed

### Goldspan Labs Optopsy

Repository: https://github.com/goldspanlabs/optopsy

Useful concepts: raw trade log, explicit entry/exit fields, natural-spread and other
slippage models, per-contract commissions, early-exit reason labels, position limits,
and portfolio equity curves. It is the closest options-specific research reference.
Its AGPL-3.0 code is not copied or vendored here. Historical option bid/ask data would
still be required before using it to compare exit-policy hypotheses.

### OptionLab

Repository: https://github.com/rgaveiga/optionlab

Useful as an independent payoff, probability-of-profit, and Greeks cross-check. It is
not used as the ledger or as a source of live quotes.

### QuantLib

Repository: https://github.com/lballabio/QuantLib

Useful as a mature independent pricing, calendar, and risk-validation reference. It is
too heavy for the stdlib daily path and is not added as a runtime dependency.

### QuantConnect LEAN

Repository: https://github.com/QuantConnect/Lean

Useful as an architectural reference for event-driven fills, holdings, and reporting.
Replacing this small deterministic desk with the full engine would add unnecessary
runtime and data complexity, so it is not integrated.

## Frozen accounting formulas

For one short put vertical with contract multiplier 100:

```text
entry_credit = (short_bid_entry - long_ask_entry) * 100
exit_debit_t = (short_ask_t - long_bid_t) * 100
marked_pnl_t = entry_credit - exit_debit_t - round_trip_costs
max_risk = width * 100 - entry_credit
return_on_risk_t = marked_pnl_t / max_risk

expiry_value = (max(short_strike - terminal_spot, 0)
                - max(long_strike - terminal_spot, 0)) * 100
expiry_pnl = entry_credit - expiry_value - round_trip_costs
```

The general multi-leg implementation treats original short legs as closing purchases
at ask and original long legs as closing sales at bid. Missing or stale quotes produce
no mark rather than a synthetic price.
