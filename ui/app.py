"""options_desk dashboard — Flask, 127.0.0.1 ONLY.

Read-only view of the current candidate flag + recent history. Binds loopback only
(never 0.0.0.0, never tunnelled). No secret is ever read or served here — the flag
carries none. Fail-safe: missing/corrupt flag renders a neutral "no signal" state.

Run: .venv/Scripts/python.exe -m ui.app
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from flask import Flask, jsonify, render_template

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk import config, etf_options, gate_status, shadow, ticket, watchdog  # noqa: E402

app = Flask(__name__, template_folder="templates")


def _recent_history(days: int = 20) -> list[dict]:
    """Last N ticket records across the monthly JSONL files (newest first)."""
    rows: list[dict] = []
    # Monthly ticket history only; exclude shadow_pnl.jsonl and research ledgers.
    for p in sorted(config.JOURNAL_DIR.glob("????-??.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        except Exception:  # noqa: BLE001
            continue
    return rows[-days:][::-1]


@app.route("/")
def index():
    return render_template("index.html", port=config.UI_PORT)


@app.route("/api/state")
def api_state():
    flag = ticket.load_flag()
    if not flag:
        return jsonify({"ok": False, "reason": "no published flag yet"})
    flag.pop("secret", None)   # defensive; the flag never carries one
    return jsonify({"ok": True, "ticket": gate_status.apply_to_ticket(flag)})


@app.route("/api/history")
def api_history():
    return jsonify({"rows": _recent_history()})


@app.route("/api/gate")
def api_gate():
    return jsonify(gate_status.load_gate_status())


@app.route("/api/performance")
def api_performance():
    return jsonify(shadow.summary())


@app.route("/api/etf-state")
def api_etf_state():
    flag = etf_options.load_flag()
    if not flag:
        return jsonify({"ok": False, "reason": "no P5 ETF result yet"})
    return jsonify({"ok": True, "ticket": flag})


@app.route("/api/trades")
def api_trades():
    return jsonify(shadow.trade_ledger())


@app.route("/api/watchdog")
def api_watchdog():
    """Lane health: did today's live run actually complete? Read-only, never notifies."""
    return jsonify(watchdog.check())


def main() -> None:
    # Loopback only. debug/reloader off (runs headless under autostart).
    app.run(host=config.UI_HOST, port=config.UI_PORT, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
