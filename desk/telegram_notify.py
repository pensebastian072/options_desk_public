"""Telegram notifier — stdlib only, fail-safe (a send failure never blocks the desk).

Secrets in gitignored secrets/telegram.json: {"bot_token": "...", "chat_id": "..."}
(same bot as robinhood_desk). ssl.create_default_context() uses the Windows cert
store, so the box's TLS-intercepting proxy verifies cleanly without extra bundles.

Advisory only: this pushes a paper alert for a human to read pre-open. It never
places an order and holds no broker keys.
"""
from __future__ import annotations

import json
import ssl
import threading
import urllib.request
from pathlib import Path

from . import config


def _load_secrets(path: Path | None = None):
    try:
        data = json.loads((path or config.TELEGRAM_SECRETS_PATH).read_text(encoding="utf-8"))
        token, chat_id = data.get("bot_token"), data.get("chat_id")
        if token and chat_id:
            return {"bot_token": token, "chat_id": str(chat_id)}, None
        return None, "telegram.json missing bot_token/chat_id"
    except Exception as e:  # noqa: BLE001
        return None, f"unavailable: {e}"


def send_message(text: str, secrets_path: Path | None = None, timeout: int = 15):
    """POST sendMessage with a hard wall-clock timeout. Never raises.

    ``urlopen(timeout=...)`` normally bounds socket operations, but Windows DNS/TLS
    setup can stall outside that socket timeout. Run the complete network operation
    in a daemon thread so an unhealthy notification path can never keep the daily
    advisory runner alive indefinitely.
    """
    secrets, err = _load_secrets(secrets_path)
    if secrets is None:
        return False, err

    result: list[tuple[bool, str | None]] = []

    def _post() -> None:
        try:
            url = f"https://api.telegram.org/bot{secrets['bot_token']}/sendMessage"
            payload = json.dumps({"chat_id": secrets["chat_id"], "text": text}).encode("utf-8")
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json", "Connection": "close"},
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                ok = 200 <= resp.status < 300
                result.append((ok, None if ok else f"http {resp.status}"))
        except Exception as e:  # noqa: BLE001
            result.append((False, f"send failed: {e}"))

    worker = threading.Thread(target=_post, name="telegram-send", daemon=True)
    worker.start()
    worker.join(max(float(timeout), 0.1))
    if worker.is_alive():
        return False, f"send timed out after {timeout}s"
    return result[0] if result else (False, "send failed: no result")


def format_status(ticket: dict) -> str:
    """Terse pre-open status for the UNATTENDED 09:05 task.

    Deliberately omits strikes and economics: that run cannot reach session-scoped
    Robinhood MCP, so its prices are Black-Scholes estimates. Presenting them like
    actionable fills is what this mode exists to prevent - the live 09:35 run owns
    the candidate alert, and the watchdog covers a miss.
    """
    sig = ticket.get("signal") or {}
    cands = ticket.get("candidates") or []
    lines = [f"PRE-OPEN STATUS {ticket.get('underlying', 'SPY')} - {ticket.get('date', '')}",
             f"{ticket.get('action', 'NO_TRADE')} - {ticket.get('reason', '')}"]
    if sig.get("spot") is not None:
        hint = ticket.get("size_hint") or "normal"
        lines.append(
            f"spot {sig.get('spot')} | VIX {sig.get('vix')} | "
            f"VRP pct {sig.get('vrp_pct')} | mag pct {sig.get('magnitude_pct')} (advisory, size={hint})"
        )
    if cands:
        lines.append(f"{len(cands)} estimate-priced candidate(s) staged; "
                     "awaiting live read-only validation before any are shown.")
    lines.append("Status only - no actionable prices. Live candidates come from the "
                 "09:35 read-only run.")
    return "\n".join(lines)


def format_progress(summary: dict, day: str = "") -> str:
    """10:00 intraday re-check: how the open SHADOW positions are developing. No new ideas."""
    overall = summary.get("overall") or {}
    openp = summary.get("open") or {}
    lines = [f"OPTIONS DESK RE-CHECK {day}".rstrip()]
    if openp.get("n"):
        lines.append(
            f"open {openp['n']} | marked {openp.get('marked', 0)} | "
            f"natural-exit P&L ${openp.get('unrealized_pnl_usd', 0):.0f}"
        )
    else:
        lines.append("no open SHADOW positions to mark")
    if overall.get("n"):
        lines.append(
            f"settled to date: {overall['wins']}/{overall['n']} hits "
            f"({overall.get('hit_rate', 0):.0%}) | P&L ${overall.get('total_pnl_usd', 0):.0f} | "
            f"PF {overall.get('profit_factor')}"
        )
    acts = summary.get("exit_signals") or {}
    if acts.get("CLOSE_TARGET") or acts.get("CLOSE_STOP"):
        parts = []
        if acts.get("CLOSE_TARGET"):
            parts.append(f"{len(acts['CLOSE_TARGET'])} at 50% TARGET: {', '.join(acts['CLOSE_TARGET'])}")
        if acts.get("CLOSE_STOP"):
            parts.append(f"{len(acts['CLOSE_STOP'])} at STOP (2x credit): {', '.join(acts['CLOSE_STOP'])}")
        lines.append("SUGGESTED CLOSES -> " + " | ".join(parts))
    lines.append("marks are observations; suggested closes are ADVISORY - you place any order.")
    return "\n".join(lines)


def format_review(review: dict) -> str:
    """After-close day review: how held names closed, updated stats, tomorrow's watch."""
    day = review.get("date", "")
    lines = [f"OPTIONS DESK AFTER-CLOSE REVIEW {day}"]
    closes = review.get("closes") or []
    for c in closes[:12]:
        chg = c.get("day_change_pct")
        chg_s = f"{chg:+.1f}%" if isinstance(chg, (int, float)) else "n/a"
        rsi = c.get("rsi")
        lines.append(f"  {c.get('symbol'):5s} close {c.get('close')} ({chg_s})"
                     + (f" RSI {rsi:.0f}" if isinstance(rsi, (int, float)) else ""))
    perf = review.get("shadow_performance") or {}
    overall = perf.get("overall") or {}
    if overall.get("n"):
        lines.append(f"SHADOW: {overall['wins']}/{overall['n']} hits "
                     f"({overall.get('hit_rate', 0):.0%}) | P&L ${overall.get('total_pnl_usd', 0):.0f} | "
                     f"PF {overall.get('profit_factor')}")
    prog = perf.get("promotion_progress") or {}
    if prog:
        lines.append(f"toward gate-decidable: {prog.get('independent_entry_dates', 0)}/"
                     f"{prog.get('pbo_floor_trades', 40)} independent dates")
    watch = review.get("tomorrow_watch") or []
    if watch:
        lines.append("tomorrow's watch (Qlib lean, from today's close): "
                     + ", ".join(f"{w['symbol']}({w['lean']:+d})" for w in watch[:8]))
    lines.append(review.get("note", "advisory SHADOW review; read-only; continuity into tomorrow's open"))
    return "\n".join(lines)


def format_alert(ticket: dict) -> str:
    """One pre-open Telegram message from a desk ticket (candidate set)."""
    sig = ticket.get("signal") or {}
    cands = ticket.get("candidates") or []
    day = ticket.get("date", "")
    lines = [f"PRE-OPEN OPTIONS DESK {ticket.get('underlying', 'SPY')} - {day} (SHADOW)"]

    if sig.get("spot") is not None:
        lines.append(
            f"spot {sig.get('spot'):.2f} | VIX {sig.get('vix'):.1f} | "
            f"VRP pct {sig.get('vrp_pct', 0):.0%} | mag pct {sig.get('magnitude_pct', 0):.0%}"
            + (f" | term {sig.get('term_ratio'):.2f}" if sig.get("term_ratio") is not None else "")
        )
    if not cands:
        lines.append(f"NO_TRADE - {ticket.get('reason', 'no edge')}")
    else:
        lines.append(f"TOP {len(cands)} ELIGIBLE (cap {config.MAX_CANDIDATES}; never forced)")
        for i, c in enumerate(cands, 1):
            label = f"{c.get('underlying')} " if c.get("underlying") else ""
            lines.append(
                f"{i}. {label}{c['strategy']} ({c.get('dte')}DTE) {c.get('legs_short', '')} "
                f"[{c.get('gate', 'not_cleared')}]"
            )
            econ = c.get("credit_usd")
            if econ is not None:
                lines.append(
                    f"   credit ${econ} | max risk ${c.get('max_risk_usd')} | "
                    f"POP ~{c.get('pop', 0):.0%} | BE {c.get('breakevens')}"
                )
            else:
                lines.append(
                    f"   debit ${c.get('debit_usd')} | max risk ${c.get('max_risk_usd')} | "
                    f"BE {c.get('breakevens')}"
                )
            lines.append(f"   why: {c.get('rationale', '')}")
    perf = (ticket.get("shadow_performance") or {}).get("overall") or {}
    if perf.get("n"):
        lines.append(
            f"SHADOW RESULTS: {perf['wins']}/{perf['n']} hits "
            f"({perf.get('hit_rate', 0):.0%}) | P&L ${perf.get('total_pnl_usd', 0):.0f} | "
            f"PF {perf.get('profit_factor')}"
        )
    open_perf = (ticket.get("shadow_performance") or {}).get("open") or {}
    if open_perf.get("n"):
        lines.append(
            f"OPEN SHADOW: {open_perf['n']} | marked {open_perf.get('marked', 0)} | "
            f"natural-exit P&L ${open_perf.get('unrealized_pnl_usd', 0):.0f}"
        )
    enriched = [c for c in cands if c.get("enriched")]
    # Match any ETF universe spec version: tickets published under an earlier spec
    # stay in the journal and must keep rendering correctly after a version bump.
    if not cands and str(ticket.get("research_experiment", "")).startswith("options_etf_universe"):
        pricing = "no eligible ETF today (eruption block or no Qlib discovery); Robinhood lookup skipped"
    elif cands and all(c.get("source") == "robinhood_natural_bid_ask" for c in cands):
        pricing = "Robinhood read-only executable-side bid/ask"
    elif cands and len(enriched) == len(cands):
        pricing = "Robinhood read-only live mids"
    elif enriched:
        pricing = "mixed Robinhood mids / BS fallback"
    else:
        pricing = "BS fallback estimates; Robinhood enrichment needs a live Codex session"
    lines.append(f"advisory paper alert - {pricing}; research gate applies; human places any order")
    return "\n".join(lines)
