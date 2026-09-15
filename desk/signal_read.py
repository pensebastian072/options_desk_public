"""Read the upstream qlib_lab vol_desk signal flag — fail-safe.

The desk never blocks or fabricates on a missing/stale/corrupt signal: it returns a
neutral snapshot with ``ok=False`` and the reason, and the strategy layer emits a
NO_TRADE alert. This is the flag-file consumer half of the paper-trading invariant
(readers fail-safe to neutral; models never on a hot path).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from . import config


def _neutral(reason: str) -> dict:
    return {"ok": False, "reason": reason, "vrp": None, "shift": None,
            "magnitude": None, "vrp_forward": None, "vol_surface": None}


def read_signal(path: Path | None = None, now: datetime | None = None) -> dict:
    """Return the qlib vol_desk flag as a dict with an ``ok`` gate and staleness check.
    Never raises."""
    p = path or config.SIGNAL_FLAG
    now = now or datetime.now(timezone.utc)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _neutral(f"signal flag missing: {p}")
    except Exception as e:  # noqa: BLE001
        return _neutral(f"signal flag unreadable: {e}")

    ts = raw.get("ts")
    try:
        age_h = (now - datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except Exception:  # noqa: BLE001
        return _neutral("signal flag has no valid ts")
    if age_h > config.SIGNAL_STALE_HOURS:
        return _neutral(f"signal stale ({age_h:.1f}h > {config.SIGNAL_STALE_HOURS}h)")

    vrp = raw.get("vrp")
    if not vrp or vrp.get("spot") is None or vrp.get("vix") is None:
        return _neutral("signal has no VRP/spot data")

    return {"ok": True, "reason": "fresh", "age_hours": round(age_h, 2),
            "ts": ts, "underlying": raw.get("underlying", "SPY"),
            "vrp": vrp,
            "shift": raw.get("shift"),
            "magnitude": raw.get("magnitude") or vrp.get("magnitude"),
            "vrp_forward": raw.get("vrp_forward"),
            "vol_surface": raw.get("vol_surface")}
