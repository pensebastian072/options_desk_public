"""Central config for options_desk — paths, DTE window, strike targets, thresholds.

Pure stdlib (no qlib import): this repo has its own venv and reads the qlib_lab
signal purely through the flag file, fail-safe. Nothing here is a broker credential.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[1]
JOURNAL_DIR = BASE_DIR / "journal"
FLAGS_DIR = JOURNAL_DIR / "flags"
RUNS_DIR = JOURNAL_DIR / "runs"
EXPERIMENTS_DIR = JOURNAL_DIR / "experiments"
SCORECARDS_DIR = JOURNAL_DIR / "scorecards"
DATA_DIR = BASE_DIR / "data"
SECRETS_DIR = BASE_DIR / "secrets"

DESK_FLAG = FLAGS_DIR / "options_desk_state.json"       # today's candidate set
SHADOW_PNL = JOURNAL_DIR / "shadow_pnl.jsonl"           # paper P&L continuity
SHADOW_OPEN = JOURNAL_DIR / "shadow_open.json"          # unsettled paper candidates
SHADOW_MARKS = JOURNAL_DIR / "shadow_marks.jsonl"        # append-only daily exit marks
SHADOW_MARK_REQUEST = FLAGS_DIR / "shadow_mark_request.json"  # read-only quote plan
ROBINHOOD_REQUEST = FLAGS_DIR / "robinhood_quote_request.json"  # read-only handoff
ETF_OPTIONS_REQUEST = FLAGS_DIR / "etf_options_request.json"     # P5 Codex read plan
ETF_OPTIONS_FLAG = FLAGS_DIR / "etf_options_state.json"          # P5 live shadow result
ETF_ESTIMATE_FLAG = FLAGS_DIR / "etf_options_estimate_state.json"  # BS-estimate track (no live session)
TELEGRAM_SECRETS_PATH = SECRETS_DIR / "telegram.json"   # {bot_token, chat_id}, gitignored

# Upstream qlib_lab signal flag (produced by PreOpenVolDesk ~08:55, fail-safe read).
QLIB_LAB_DIR = Path(os.environ.get("QLIB_LAB_DIR", r"C:\Users\<you>\qlib_lab"))
QLIB_CSV_DIR = QLIB_LAB_DIR / "csv"
SIGNAL_FLAG = QLIB_LAB_DIR / "journal" / "flags" / "vol_desk_state.json"
QLIB_STATE_FLAG = QLIB_LAB_DIR / "journal" / "flags" / "qlib_state.json"
SIGNAL_STALE_HOURS = 30        # a pre-open flag older than this = neutral (weekend-tolerant)
QLIB_STATE_STALE_DAYS = 2

# Offline research dependencies. The daily desk never imports these packages.
MACRO_GPU_LAB_DIR = Path(os.environ.get("MACRO_GPU_LAB_DIR", r"C:\Users\<you>\macro_gpu_lab"))
MACRO_GPU_STATE_FLAG = MACRO_GPU_LAB_DIR / "journal" / "flags" / "macro_gpu_state.json"
HQ_TRADING_DIR = Path(os.environ.get("HQ_TRADING_DIR", r"C:\Users\<you>\hq-trading-system"))
HQ_MACRO_STATE_FLAG = HQ_TRADING_DIR / "journal" / "macro" / "macro_state.json"
ETF_EXPERIMENT_ID = "options_etf_universe_v4"   # v1/v2 kept as audit records for their results
MAX_TRADE_RISK_USD = 1000        # hard per-trade rail: drop any candidate with larger defined risk
MAGNITUDE_ADVISORY_HIGH = 0.70
# v4-live promotion (research v5/v10/v11):
CALL_MOMENTUM_MAX = 0.10     # do not sell CALL premium when 126-session momentum exceeds this
PROFIT_TARGET_FRAC = 0.50    # advisory CLOSE signal at 50% of entry credit captured
STOP_LOSS_MULT = 2.0         # advisory CLOSE signal when the loss reaches 2x entry credit
ETF_EXPERIMENT = EXPERIMENTS_DIR / f"{ETF_EXPERIMENT_ID}.json"
GATE_EXPERIMENT_ID = "options_gate_v1"
GATE_N_TRIALS = 4              # four priced structures; vix_iv_pairs is diagnostic only
BACKTEST_COST_PER_LEG_RT = 2.0
GATE_SCORECARD = SCORECARDS_DIR / f"{GATE_EXPERIMENT_ID}.json"
GATE_LEDGER = SCORECARDS_DIR / f"{GATE_EXPERIMENT_ID}_trades.jsonl"

# ── Contract selection ───────────────────────────────────────────────
DTE_MIN = 30
DTE_MAX = 60
DTE_TARGET = 45                # aim here; expiry rolls to nearest monthly (3rd Friday)
RISK_FREE = 0.04

SHORT_PUT_DELTA = -0.30        # ~30-delta short put (both CSP and spread short leg)
SHORT_CALL_DELTA = 0.20        # jade-lizard short call (further OTM)
PUT_SPREAD_WIDTH = 5.0         # $ width, defined-risk put credit spread
CALL_SPREAD_WIDTH = 5.0        # $ width, jade-lizard short call spread

# ── Regime thresholds (mirror qlib_lab vol_desk matrix; kept in sync) ─
VRP_SELL_PCT = 0.70            # premium rich enough to sell
VRP_RICH_PCT = 0.60           # too rich to buy vol
MAGNITUDE_HIGH_PCT = 0.70     # big-move regime -> do not sell premium
# VIX term-structure ratio (VIX9D / VIX3M): < 1 contango (calm), > 1 backwardation (stress)
TERM_BACKWARDATION = 1.00

MAX_CANDIDATES = 5            # cap only: never force trades to fill the list
ROBINHOOD_QUOTE_MAX_AGE_MINUTES = 15

# ── Promotion flag (default SHADOW — never auto-flips) ───────────────
# Advisory alerts always ship; this only ever governs FUTURE sizing, never the alert.
OPTIONS_DESK_ENFORCE = os.environ.get("OPTIONS_DESK_ENFORCE", "no").strip().lower()

# ── UI (loopback ONLY — never bind 0.0.0.0, never tunnel) ────────────
UI_HOST = "127.0.0.1"
UI_PORT = 8078          # distinct from HQ :8099, copper :8077, hq webhook :8090

for _d in (JOURNAL_DIR, FLAGS_DIR, RUNS_DIR, EXPERIMENTS_DIR, SCORECARDS_DIR, DATA_DIR):
    _d.mkdir(parents=True, exist_ok=True)
