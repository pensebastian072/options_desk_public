# options_desk — agent guide

Daily **pre-open option-trade alert desk** (paper/advisory only). Reads the qlib_lab
vol_desk signal flag (VRP richness + surprise-shift + magnitude proxy + vol surface)
fail-safe, builds a ranked multi-strategy option candidate set with Black-Scholes
ESTIMATES, publishes a candidate flag + JSONL history, pushes a Telegram alert, and
serves a 127.0.0.1 UI. **Nothing here touches a broker.** Output is advisory: the
human reads the alert and places any order themselves.

Two-layer, flag-file coupled (keeps the constrained qlib py3.11/numpy<2 venv isolated):
`qlib_lab` PreOpenVolDesk (08:55) writes `vol_desk_state.json` -> this desk
(OptionsDeskDaily ~09:05) reads it and alerts.

Skills: load `paper-trading-guardrails` before touching flag/publish/alert code,
`quant-research-gate` before any strategy backtest/gate work, `win-quant-env` before
installs/git/PS/Task Scheduler.

## Hard rules

1. **Paper / advisory only.** No broker keys, no execution, ever. The alert is text;
   the human decides and places. Robinhood enrichment (P3) is **read-only** (chains/
   quotes) — never `place_/cancel_`; the `robinhood-order-guard` hook is the real gate
   and the agent never arms it.
2. **Fail-safe consumer.** A missing/stale/corrupt qlib signal -> neutral NO_TRADE
   alert, never a fabricated trade. `SIGNAL_STALE_HOURS` bounds freshness.
3. **Everything ships SHADOW / "not gate-cleared".** No strategy sizes real money
   until it clears the canonical overfit gate (PBO<0.5 & DSR>0). `OPTIONS_DESK_ENFORCE`
   (default `no`) only ever governs FUTURE sizing — never the advisory alert.
4. **UI binds 127.0.0.1 ONLY** (port 8078). Never 0.0.0.0, never tunnelled. No secret
   ever reaches the browser.
5. **Telegram fail-safe.** Notify failure never blocks a run. `secrets/telegram.json`
   (gitignored) = `{bot_token, chat_id}` (same bot as robinhood_desk).
6. **Jade-lizard invariant:** net credit >= short-call-spread width (no upside risk).
   Enforced in the builder + a unit test.

## Layout

- `desk/config.py` — paths, DTE window (30-60, target 45), delta/width targets, thresholds, UI.
- `desk/signal_read.py` — fail-safe read of the qlib vol_desk flag.
- `desk/bs.py` — Black-Scholes estimates (put/call/straddle, deltas, strike solvers).
- `desk/strategies.py` — 5 builders (short put, put spread, jade lizard, long vol,
  VIX/IV pairs) + selection matrix -> ranked candidates. [P1]
- `desk/ticket.py` — assemble/publish candidate flag + history. [P1]
- `desk/shadow.py` — stable candidate IDs, open-paper state, expiry settlement, hit-rate/P&L.
- `desk/telegram_notify.py` — stdlib fail-safe sender + `format_alert`.
- `desk/run_desk.py` — CLI: `--once --telegram --dry-run --summary`. [P1]
- `desk/etf_options.py` — P5 frozen liquid-ETF request + deterministic live payload finalizer.
- `desk/backtest.py` — P4 offline point-in-time parametric expiry backtest; canonical gate.
- `desk/gate_status.py` — fail-safe display-only reader for per-strategy gate badges.
- `ui/app.py` — Flask 127.0.0.1 dashboard. [P2]
- `scripts/` — task registration + hidden vbs launchers + autostart. [P1/P2]

## "enrich options desk" flow (Codex session, READ-ONLY Robinhood)

The daily task prices candidates with Black-Scholes estimates. To replace those with
live Robinhood mids, a Codex session runs this (never autonomous — MCP is session-only):

1. `.venv\Scripts\python.exe -m desk.enrich` -> prints the read plan (underlying, per-leg
   expiration/strike/type). Empty candidates -> nothing to do.
2. Resolve READ-ONLY: `get_option_chains(underlying_symbol="SPY")` ->
   `get_option_instruments(chain_symbol, expiration_dates, strike_price, type)` per leg ->
   `get_option_quotes(instrument_ids=[...])`. NEVER `place_/cancel_` — RH <your-brokerage-account> is real
   money; the order-guard hook is the gate and is never armed for this desk.
3. Build `quotes_by_key` = `{"type:strike:expiry": quote}` and call
   `desk.enrich.write_enrichment(flag, quotes_by_key)` -> republishes the enriched flag
   (live mids, recomputed credit/debit; still SHADOW / not gate-cleared).
4. Optionally resend: `-m desk.run_desk --summary --telegram`.

The Windows 09:05 task cannot invoke the session-scoped Robinhood MCP. It therefore
sends a clearly labeled Black-Scholes fallback and leaves a secret-free request at
`journal/flags/robinhood_quote_request.json`. Live listed-option quotes only exist after
the 09:30 market open; never describe pre-open/prior-close quotes as live.

## P5 liquid ETF lane

`journal/experiments/options_etf_universe_v1.json` is the frozen specification and
trial count. `-m desk.etf_options --request` intersects fresh Qlib bullish discovery
with the nine-ETF allowlist and the global premium-selling veto. A Codex session uses
the `options-desk-morning` skill to fetch only read-only Robinhood data and writes the
documented payload. `--finalize <payload> --telegram` applies all liquidity, IV/RV,
structure, diversification, ranking, and SHADOW checks locally. Do not hand-rank,
substitute contracts, or query around a `NO_TRADE` request.

## Environment

- uv-managed `.venv`, real interpreter `.venv\Scripts\python.exe` (bare `python` =
  Store stub). Install: `uv pip install --python .venv\Scripts\python.exe --native-tls -r requirements.txt`.
- Keep `.ps1` ASCII-only (PS 5.1). Norton locks `.git/objects` -> retry git add/commit.
  Commit per-identity to `main`: `git -c user.email=... -c user.name=...`.

## Verification

- Tests: `.venv\Scripts\python.exe -m pytest` (59/59 after P5)
- Research deps: `uv pip install --python .venv\Scripts\python.exe --native-tls -r requirements-research.txt`
- P4 gate: `.venv\Scripts\python.exe -m desk.backtest`
- Dry run: `.venv\Scripts\python.exe -m desk.run_desk --dry-run`
- Alert:   `.venv\Scripts\python.exe -m desk.run_desk --once --telegram`
- UI:      browse http://127.0.0.1:8078/
