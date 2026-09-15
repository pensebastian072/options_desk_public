# options_desk — Codex handoff / working plan

Source-of-truth resume pointer for continued work. **Paper/advisory only. No broker
execution, ever. Robinhood is read-only. The human places every order.** Read
`CLAUDE.md` (repo runbook) and the `paper-options-desk` skill before editing.
For a plain-language explanation of the complete system, read `SYSTEM_OVERVIEW.md`.

## Mission

Daily **pre-open option-trade alert** (30–60 DTE) on SPY: read the qlib_lab vol_desk
signal, build a ranked set of option-structure candidates, push a Telegram alert +
serve a loopback UI. Two layers, flag-file coupled:

```
qlib_lab PreOpenVolDesk (08:55) --journal/flags/vol_desk_state.json-->
    options_desk OptionsDeskDaily (09:05): strategies -> flag + Telegram + UI(:8078)
                                           [enrich] Codex session -> real RH mids
```

## Status (2026-07-22)

- **P0–P6 built; top-five cap + execution-quality shadow tracking; 66/66 tests green.** Commits: P0 `2c3f9de`, P1
  `4b0513f`, P2 `208bd15`, P3 `b7dbc43`, P4 pre-registration `826924f`, P4
  implementation/result `81797a9`. qlib_lab signal layer `be0c1ec` (12/12).
- Telegram secret in place (`secrets/telegram.json`, gitignored) — live send verified.
- **Operational activation complete:** `PreOpenVolDesk` and `OptionsDeskDaily` are
  registered for weekdays at 08:55/09:05; both manually returned Task Scheduler result
  0. UI autostart is installed and the live server was verified on 127.0.0.1:8078.
- **P4 complete:** point-in-time parametric expiry backtest, canonical gate scorecard,
  trade ledger, and fail-safe per-strategy UI badges. All four strategies honestly
  remain SHADOW: 16–24 trades each, negative DSR, and insufficient PBO samples.
- Morning alerts now cap at **up to five eligible candidates** (never force five or
  override `NO_TRADE`). Each candidate gets a stable ID and is tracked hold-to-expiry
  in `journal/shadow_pnl.jsonl`; Telegram and `/api/performance` show hit rate plus P&L/PF.
- The 09:05 local task writes `journal/flags/robinhood_quote_request.json`. A live Codex
  session can fulfill it with read-only Robinhood chains/quotes, re-price/re-rank, and
  resend. The unattended task cannot call session-scoped MCP, so its alert is explicitly
  labeled BS fallback. Listed option quotes are not live before the 09:30 open.
- **P5 liquid-ETF research lane:** frozen nine-ETF universe (`SPY QQQ IWM DIA TLT GLD
  SLV XLF XLE`), Qlib bullish discovery threshold, global eruption/magnitude veto,
  per-asset 20d RV, live IV/RV and per-leg liquidity validation, natural bid/ask pricing,
  bucket caps, and up-to-five ranking. Pre-registration commit `c18e096`. It is a separate
  SHADOW flag (`etf_options_state.json`) and never changes the proven SPY lane.
- Codex skill installed at `C:\Users\<you>\.codex\skills\options-desk-morning`; its
  independent dry run honored today's eruption veto and made no Robinhood call.
- **P6 SHADOW execution ledger:** immutable natural-side entry fields, stored instrument
  IDs, daily natural closing marks, MFE/MAE, explicit expiry exit fields, per-trade UI,
  and append-only `shadow_marks.jsonl`. Hold-to-expiry remains canonical; no take-profit,
  stop-loss, DTE exit, account read, or broker action was added. Measurement pre-registration
  is `options_shadow_ledger_v1`; GitHub design notes live under `journal/research/`.
- The standalone local-project `Options Desk Morning` Codex automation is active at
  09:35 America/New_York on weekdays. It marks open candidates before checking new entries.

## P7-P10 (2026-07-23) — review pass

- **P7 `desk/etf_backtest.py`** (`280b758`): replays the frozen put-spread rule across the
  v1 nine-ETF universe. Pre-registration `options_etf_gate_v1` written BEFORE results.
  **PBO is now computable** (headline n=41 >= 40 floor, PBO 0.0159 passes) but
  **DSR -6.32 FAILS** -> still SHADOW. Sharpe 0.305, PF 1.99, win rate 76%.
  - **Key finding:** every symbol entered on IDENTICAL dates (entry rule is purely
    global, no per-asset discrimination), so pooled n=369 collapses to 41 cluster
    observations and `cluster_adjusted` == `spy_only`. **Widening the universe adds
    candidate coverage but ~zero independent evidence.** Only a real per-asset filter
    (Qlib lean) would change that.
  - Declared deviations: no Qlib filter (superset population), IV proxied from SPY's
    volatility premium (so the per-asset IV/RV test degenerates market-wide), model
    credit instead of natural bid/ask. Results are an UPPER BOUND on live edge.
  - Pinned to `options_etf_universe_v1` on purpose so the scorecard stays reproducible;
    it does NOT follow `config.ETF_EXPERIMENT_ID`. A wider backtest needs its own prereg.
- **P8 universe v2 + structures** (`b4c4a14`): `options_etf_universe_v2` (v1 untouched as
  audit record). 31 symbols x 3 structures. Qlib lean routes each symbol to exactly ONE
  structure: bullish -> `etf_short_put_spread_v1`, bearish -> `etf_short_call_spread_v1`,
  neutral -> `etf_iron_condor_v1` (stricter 1.20 IV/RV floor; no conviction bar, so the
  looser directional test cannot become a back door). **No structure shopping** — a
  routed structure that fails validation rejects the symbol. Global eruption/magnitude
  veto still applies to ALL structures and is never relaxed to find trades.
  - **n_trials 9 -> 93.** This RAISES the deflated-Sharpe bar. Finding more candidates
    does not make promotion easier; it makes each pay for more looks. Do not soften.
- **P9 `desk/watchdog.py`** (`863fa30`): distinguishes a legitimate deterministic veto
  (NO_TRADE request + published flag = SUCCESS) from a real miss (READY request with no
  matching-`request_id` result). Miss alert explains what did not run and carries **zero
  trade ideas**; idempotent (one per day), fail-safe. Verified against the real
  2026-07-23 miss (correctly flagged SLV/QQQ awaiting validation).
  - Alert hygiene: `run_desk --status-only`, now used by the 09:05 task, so the
    unattended run publishes flags/requests and sends a terse status line instead of
    presenting BS estimates as actionable prices. The 09:35 live run owns candidates.
- **P10 analytics** (`e0dae58`): MFE/MAE, holding days, return-on-max-risk, per-strategy
  and per-underlying tables, `/api/watchdog`, UI lane-health banner and a progress bar to
  the 40-observation floor. `promotion_progress` counts DISTINCT entry dates, not rows.
- 105/105 tests.

## Qlib as an evidence source (2026-07-23) — process + result

**The process** (this is the reusable part):
1. `qlib_lab`: `.venv\Scripts\python.exe -m qlib_lab.score_history` re-runs the SAME
   expanding walk-forward the pipeline uses and exports the per-asset cross-section to
   `qlib_lab/journal/exports/qlib_score_history.parquet` (133,986 rows, 76 assets,
   1763 sessions, 2019-07-18 ->). No-lookahead inherited from the pipeline. ~10 min.
2. `options_desk`: `-m desk.qlib_evidence` measures discrimination + staggering.
3. `-m desk.etf_backtest --v2` runs the Qlib-filtered gate.
Re-run step 1 when you want the export extended; steps 2-3 are cheap.

**Does Qlib add evidence? YES — decisively.**

| | entries | independent dates | symbols/date | Jaccard |
|---|---:|---:|---:|---:|
| global only (v1) | 1116 | 36 | 31.0 | 1.000 |
| + Qlib filter | 307 | **192** | 1.60 | **0.017** |

Jaccard 1.000 = every symbol entered on identical dates (why v1 pooled n=369 -> 41).
The filter admits 2.96 of 31 symbols per regime date and staggers entries: ~3x fewer
trades, ~5.3x more independent observations. **Keep the Qlib filter in the live lane.**

**Does the gate now pass? NO.** `options_etf_gate_v2` cluster-adjusted vs v1:
independent obs 41->186, per-trade Sharpe 0.305->0.400, mean PnL $28->$38, win rate
76%->81%, PF 1.99->2.73, PBO 0.0159->0.000 (passes) — but **DSR -6.32 -> -17.68, NOT
CLEARED**. All three pre-registered predictions confirmed; it still fails.

**Why better evidence scored worse** (`ratio = (sr - e_max)*sqrt(T-1)/denom`): `e_max`
rose with n_trials 9->40 (1.52->2.19), and since `sr < e_max` the `sqrt(T-1)` term
AMPLIFIES the negative gap (2.15x). Passing needs a **per-trade** Sharpe > ~2.2; a
premium-selling payoff (~80% small wins, fat left tail) is structurally ~0.3-0.5.

**Open methodology question — human decision, do NOT self-serve:** the canonical DSR is
defined on a periodic return series, but this gate applies it to per-trade dollar PnL
with T = trade count. Every strategy in every repo fails DSR by a wide margin while often
showing PF > 1.5 and replicating OOS. That pattern is worth a deliberate, pre-registered
review of `macro_gpu_lab/validate.py` (map trade PnL to a periodic series, re-run all
scorecards). **Nothing was softened and n_trials=40 stands; v2 is reported FAILED.**
Full write-up: `journal/research/qlib_filter_and_dsr_bar.md`.

## Does it need a live Codex session? (operating model, 2026-07-23)

**No — for TRACKING. Yes — for actionable REAL prices.** Two separate things:

- **Tracking the v2 strategy is headless.** The 09:05 task now runs
  `etf_options.finalize_estimate` -> `publish_estimate`: BS-estimate candidates for
  today's eligible ETFs are built and shadow-tracked every day the lane fires, no session
  needed. They go to `etf_options_estimate_state.json` (separate from the live flag) and
  are labeled `source=black_scholes_estimate, enriched=False, gate=not_cleared`.
- **Real executable-side prices need the live Codex session** (the 09:35 "Options Desk
  Morning" automation). Robinhood MCP is session-scoped — the box's headless python
  cannot call it, which is also the safety boundary (no headless broker access). The live
  run pulls read-only chains/quotes, finalizes to the canonical `etf_options_state.json`,
  sends the actionable Telegram alert, AND upgrades the tracked estimate positions to real
  mids (`shadow.supersede_estimate_openings` replaces same day+underlying+strategy).
- **A missed live run is not a lost day:** the watchdog still alerts the miss (live quotes
  didn't confirm) while the estimate record keeps accumulating. Live upgrades estimates
  when it runs; estimates with no live counterpart survive and settle as estimates.

So the v2 strategy (accepted as an operating SHADOW strategy despite failing the gate)
tracks continuously; the live session only adds real pricing and the actionable alert.

## P11-P13 (2026-07-23) — trade more, capped, live-spot, re-check/review

- **v3 spec `options_etf_universe_v3`** (v1/v2 frozen). Magnitude/VRP/calm are now
  ADVISORY (a `size_hint`), not hard blocks. The ONLY hard vetoes: predicted eruption +
  missing/stale data. Verified: today's real signal (VRP 82%, mag 76%, no eruption)
  flips NO_TRADE -> READY (8 ETFs, size=reduce_size). `desk/etf_options.py::_hard_veto` +
  `_advisory`.
- **$1000 per-trade cap** (`config.MAX_TRADE_RISK_USD`): drops any candidate with defined
  max risk > $1000 (naked/CSP ~strike*100, oversized long-vol). Enforced in `_candidate`,
  `_estimate_candidate`, and the SPY lane.
- **`select()` is parameterized** (`magnitude_blocks`, `risk_cap`): DEFAULTS reproduce the
  FROZEN P4 behavior so `options_gate_v1` stays reproducible; `run_desk` passes
  `magnitude_blocks=False, risk_cap=1000` for the live v3 policy. Do not change the
  defaults or the P4 backtest changes.
- **Live-spot (RH-first)**: `build_request(live_quotes=...)` uses live Robinhood equity
  price as `reference_spot` (records `spot_source`); CLI `--live-market <file>`. Morning
  skill fetches `get_equity_quotes` first and passes the snapshot.
- **10:00 re-check**: `desk.shadow --progress [--telegram]` (open-position progress; marks
  never close a trade). **After-close review**: `desk/review.py` (`--request`/`--finalize
  <payload>`/`--local`) -> Telegram with held+watch closes, shadow stats, tomorrow's Qlib
  watch. Both are read-only Codex runs; skill refs `recheck.md` + `after-close-review.md`.
- **USER STEP**: register two Codex automations from `docs/codex-automations.md` -
  `Options Desk Re-check` (weekdays 10:00) and `Options Desk Review` (weekdays 16:15).
- v3 is an operating SHADOW strategy (accepted despite the gate); a v3 gate backtest is an
  optional follow-up. 130 tests.

## P14 (2026-07-23) — v3 backtest over 2019-2026 (commit e2c16d1)

`desk.etf_backtest --v3` (pre-reg `options_etf_gate_v3`). 3 structures routed by
point-in-time Qlib lean, tastytrade **POP-at-expiry >= 0.51** floor (`bs.pop_at_expiry`),
eruption-only veto, **50%-profit-target exit** via daily BS repricing (entry IV held
constant = declared upper-bound deviation). Also added POP>=0.51 to the LIVE lane.

**Results (cluster-adjusted, 302 obs):** profitable **6 of 8 years**, total **+$2830**,
PF 1.35, ~80% win. **BUT 2022 (bear) = -$7025** (PF 0.48) - short premium gets run over in
sustained selloffs; that tail is THE risk. **The 50% target made LESS than hold-to-expiry**
($2830 vs $5210) - it caps winners while losers run (raises win rate + capital efficiency,
lowers raw total). **Fails the gate** (DSR -37, same deflation issue). Condors dominate
(765 of 1240; neutral lean most common, clear POP only when premium is rich).

**What to fix (as a NEW pre-registered v4, not by retuning v3):** the 2022 bear tail -
a trend/regime filter or long-tail hedge. And reconsider the 50% target (hold-to-expiry
beat it here). Artifacts: `journal/scorecards/options_etf_gate_v3.json` + `_trades.jsonl`
+ `_equity.csv`.

## Trend-guard research arc (P14-P18, 2026-07-23) — v5 is the path

Backtested the v3 rule over 2019-2026 (modeled BS prices, cluster-adjusted, honest gate).
Ran a full variant ladder, each PRE-REGISTERED before results, no p-hacking. Cluster-
adjusted totals / 2022 loss:

- **v3** (no gate): +$2,830 / 2022 −$7,025. Bled in directional-down months (condors run over).
- **v4** (50-day per-name gate): +$3,293 / −$4,300. Fast MA whipsawed on bear rallies.
- **v5** (200-day per-name gate): **+$5,111 / −$2,802. THE WINNER.** Slow MA holds defense
  through a bear. Nearly doubled the base, cut 2022 60%, ZERO carry cost. PF 1.62.
- **v6** (v5 + SPY-200d index overlay): +$5,010 / −$3,056. Added NOTHING (redundant with
  per-name); honest negative.
- **v7** (v5 + monthly SPY-put tail hedge): halved 2022 (−$1,447) but carry cut total ~half
  and didn't improve risk-adjusted return. Insurance, not growth; honest negative.

**RECOMMENDATION (user-confirmed 2026-07-23): v5 = the per-symbol 200-day trend gate is
the path.** Rule: do NOT sell put-side premium (put spread / iron condor) when the symbol
is below its 200-day SMA; call spreads still allowed.

**NOT YET LIVE.** Adopting v5 in the live lane is its OWN pre-registered change (new
`options_etf_universe` spec + a v-live gate run + human review) — do not flip the live
desk without it. Everything above is SHADOW research, modeled prices = upper bound, none
gate-cleared (DSR still <0, structural deflation). Research: `journal/research/v3..v7*.md`.
Every strategy fails the canonical gate; that finding is documented in
`qlib_filter_and_dsr_bar.md` (per-trade Sharpe vs n_trials deflation).

## Telegram cadence (fixed 2026-07-23)

The 09:05 OptionsDeskDaily task is now **SILENT** (`run_desk --once`, no `--telegram`) -- it
still publishes the flag, writes the Robinhood request for Codex, and tracks estimates,
but sends no message. Rationale: it is unattended and CANNOT reach the Robinhood MCP, so
its old "PRE-OPEN STATUS ... status only" line was redundant noise and the source of the
"why is Robinhood skipped" confusion. **Robinhood is only ever used by the 09:35 Codex
live run** (when the day is READY, i.e. not eruption-vetoed). Morning cadence is now:
**09:35 Codex = the ONE live-Robinhood alert (candidates or honest NO_TRADE); 10:00 =
progress re-check; 16:15 = evening review; watchdog = only on a miss.** "Robinhood lookup
skipped" appears ONLY on genuine NO_TRADE days (eruption veto or no Qlib discovery) --
correct, not a bug. If message count is still high, it is the Codex skill retrying a
`--telegram` step, not the Windows tasks.

## Variant ladder — v5 live, v10 the leading candidate (2026-07-24)

**v10 is NOT a rival to v5 — it is v5 plus one filter** (do not sell CALL premium when a
symbol's 126-session momentum > +10%). Same base: 200-day per-symbol put-side trend gate,
POP >= 0.51, $1,000 per-trade cap, eruption veto, 50%-profit-target exit.

| variant | cluster total | PF | maxDD | 2022 | note |
|---|---:|---:|---:|---:|---|
| v3 (no gates) | $2,830 | 1.35 | — | −$7,025 | base |
| v4 (50-day gate) | $3,293 | 1.36 | — | −$4,300 | fast MA whipsaws |
| **v5 (200-day gate)** | $5,111 | 1.62 | −$1,011 | −$2,802 | **LIVE / proven base** |
| v6 (+ index overlay) | $5,010 | 1.63 | — | −$3,056 | redundant, no gain |
| v7 (+ tail hedge) | — | — | — | −$1,447 | halves bear, carry too costly |
| v8 (drop calls) | $5,593 | 1.75 | — | −$3,027 | rejected: deletes bear structure |
| v9 (symmetric trend) | $5,433 | 1.65 | — | −$2,917 | FAILED: calls −$913 -> −$1,929 |
| **v10 (+ momentum gate on calls)** | **$6,231** | **1.78** | **−$709** | −$2,880 | **BEST — leading candidate** |

v10 DOMINATES v5: higher total (+22%), higher PF, LOWER drawdown, MORE independent
observations (385 vs 373), and 2022 essentially unchanged (bear-side structure retained).
No tradeoff, unlike v8.

**Status: v5 stays live. v10 is not yet promoted** because (a) all pricing is modeled (BS,
proxied IV) = an upper bound, (b) it still fails the canonical gate (DSR −36.5), and (c) its
advantage is in-sample. Promoting v10 to the live desk is its own pre-registered change,
ideally after real-option confirmation (blocked on OPRA/Polygon).

Call-spread post-mortem and both experiments: `journal/research/v9_v10_call_fix_result.md`.

## Hard invariants (do not violate)

1. Advisory/paper only; no broker keys or order code in this repo.
2. Robinhood READ-ONLY (chains/quotes), Codex-session only; never `place_/cancel_`;
   never arm the `robinhood-order-guard` hook. RH <your-brokerage-account> is real money.
3. Fail-safe consumer: stale/missing/corrupt signal -> neutral NO_TRADE.
4. Everything SHADOW / "not gate-cleared" until it passes the canonical gate;
   `OPTIONS_DESK_ENFORCE` (default no) only governs FUTURE sizing, never the alert.
5. UI binds 127.0.0.1:8078 ONLY. No secret to the browser. No tunnel.
6. Jade-lizard invariant: net credit >= call-spread width (no upside risk) — dropped if unmet.
7. Selection matrix is pre-registered (mirrors qlib vol_desk); magnitude veto stays.

## Layout

`desk/`: config · signal_read (fail-safe) · bs (BS estimates) · strategies (5 builders +
`select()`) · ticket (publish) · shadow (paper result ledger) · telegram_notify ·
run_desk (CLI) · enrich (P3 read-only) · etf_options (P5 request/live finalizer)
· backtest + gate_status (P4 offline research/display-only gate).
`ui/app.py` + `ui/templates/index.html` (Flask loopback). `scripts/` (task reg + autostart).
`tests/` (119 current; 66 after P6). Upstream signal produced by `qlib_lab/qlib_lab/vol_desk.py`.

## Commands (always `.venv\Scripts\python.exe`; bare `python` = Store stub)

- Tests: `.venv\Scripts\python.exe -m pytest`
- Dry run: `-m desk.run_desk --dry-run`   Publish+alert: `-m desk.run_desk --once --telegram`
- Re-alert last flag: `-m desk.run_desk --summary --telegram`
- Enrich plan: `-m desk.enrich`   UI: `-m ui.app` -> http://127.0.0.1:8078/
- P5 request: `-m desk.etf_options --request`; final: `-m desk.etf_options --finalize <payload> --telegram`
- P6 marks: `-m desk.shadow --mark-request`; final: `-m desk.shadow --finalize-marks <payload>`
- Research deps: `uv pip install --python .venv\Scripts\python.exe --native-tls -r requirements-research.txt`
- P4 gate: `.venv\Scripts\python.exe -m desk.backtest`
- P7 ETF gate: `.venv\Scripts\python.exe -m desk.etf_backtest`
- P9 watchdog: `-m desk.watchdog` (add `--telegram` to alert; once/day, no trade ideas)
- P9 status-only alert (what the 09:05 task now runs): `-m desk.run_desk --once --telegram --status-only`

## P4 result (complete; no promotion)

Pre-registration: `journal/experiments/options_gate_v1.json` (committed before results).
Scorecard: `journal/scorecards/options_gate_v1.json`; the audit ledger is beside it.

| strategy | n | DSR | PBO | PF | verdict |
|---|---:|---:|---:|---:|---|
| short_put_csp | 24 | -3.7297 | unavailable | 1.5096 | not cleared |
| short_put_spread | 24 | -1.3058 | unavailable | 3.4904 | not cleared |
| jade_lizard | 16 | -2.8667 | unavailable | 1.6282 | not cleared |
| long_vol_straddle | 16 | -7.5922 | unavailable | 0.1130 | not cleared |

Canonical PBO needs at least 40 trades. Thresholds were not softened; a high raw PF
does not override failed DSR/insufficient PBO. `vix_iv_pairs` remains a non-priced
diagnostic selector and is not counted as a gate trial.

## Remaining work

### Open items from the P7-P10 pass
- **Register the watchdog** (user step): `powershell -ExecutionPolicy Bypass -File
  scripts\register_watchdog.ps1` -> `OptionsDeskWatchdog`, weekdays 10:15.
- **Restart the UI** so :8078 picks up `/api/watchdog` and the new analytics — the
  autostart process is still serving pre-P10 code until it is restarted or you log in again.
- **The v2 lane has no backtest yet.** `options_etf_gate_v1` validated only the v1 put
  spread. The call spread and iron condor are live-eligible but UNBACKTESTED; they carry
  `gate: not_cleared` and must keep it until a `options_etf_gate_v2` prereg + run exists.
  Per the P7 finding, expect the wider universe to add coverage, not evidence — the
  structures are what may add genuinely different payoffs.
- **Qlib per-asset filter is unvalidated.** It is the only thing that could make symbols
  enter on different dates (and so add independent observations). Worth measuring directly:
  does lean/conviction actually discriminate, or does every symbol lean together?
- `AGENTS.md` is still untracked — commit or ignore it.

### Polish (optional, lower priority)
- Add weekly expiries option (currently monthly 3rd-Friday only) if the user wants tighter 45-DTE.
- After historical option bid/ask data is acquired, pre-register and compare 50% profit,
  -100% stop, and 21-DTE exits offline. Each variant increases `n_trials`; do not infer
  an exit policy from the daily marks.

## Activation status

1. DONE: `secrets/telegram.json` (bot 8607…, chat <your-telegram-chat-id>) — verified sending.
2. DONE: qlib `PreOpenVolDesk` at 08:55 and options `OptionsDeskDaily` at 09:05;
   manual end-to-end run refreshed both flags and sent the Telegram alert.
3. DONE: UI Startup shortcut installed; loopback listener and HTTP 200 verified.
4. DONE: Robinhood MCP attached for the read-only enrich flow (see CLAUDE.md
   "enrich options desk"). Never use it for order placement or cancellation.
5. DONE: per-user Startup shortcut launches the installed OpenAI Codex desktop app,
   which hosts the local runner for the weekday 09:35 automation. The host launcher
   does not run the workflow itself or change its read-only permissions.

## Env gotchas (this box)

- `.venv\Scripts\python.exe` only. `.ps1` ASCII-only (PS 5.1). Norton locks `.git/objects`
  -> retry `git add`/`commit`. No global git identity — commit per-identity to `main`:
  `git -c user.email='<your-git-email>' -c user.name='<your-git-name>' commit ...`.
- TLS-intercepting proxy: pip `--use-feature=truststore`, uv `--native-tls`. See `win-quant-env`.
