"""Publish the desk candidate flag + append monthly history — atomic, fail-safe.

The flag (`journal/flags/options_desk_state.json`) is the single source the UI and any
downstream reader consumes; readers must treat missing/stale as neutral. History
(`journal/<YYYY-MM>.jsonl`) is the append-only audit trail / shadow-P&L substrate.
No secret is ever written here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config, shadow

DESK_DIR = config.JOURNAL_DIR


def publish(ticket: dict) -> str:
    shadow.assign_candidate_ids(ticket)
    config.FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.DESK_FLAG.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(ticket, indent=2), encoding="utf-8")
    tmp.replace(config.DESK_FLAG)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with (DESK_DIR / f"{month}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket) + "\n")
    # Tracking is best-effort and must never suppress the alert/flag.
    try:
        shadow.record_ticket(ticket)
        shadow.retract_same_day_on_veto(ticket)
    except Exception:  # noqa: BLE001
        pass
    return str(config.DESK_FLAG)


def load_flag() -> dict | None:
    try:
        return json.loads(config.DESK_FLAG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
