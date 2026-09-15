"""Fail-safe reader for the offline per-strategy research scorecard.

Gate results affect display labels only. They never enable execution, change sizing,
or alter the desk's SHADOW/advisory status. A missing, corrupt, or stale-spec
scorecard resolves every strategy to ``not_cleared``.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from . import config

PRICED_STRATEGIES = (
    "short_put_csp",
    "short_put_spread",
    "jade_lizard",
    "long_vol_straddle",
)


def current_spec() -> dict:
    """Parameters whose change invalidates an existing research verdict."""
    return {
        "experiment_id": config.GATE_EXPERIMENT_ID,
        "dte": [config.DTE_MIN, config.DTE_TARGET, config.DTE_MAX],
        "risk_free": config.RISK_FREE,
        "short_put_delta": config.SHORT_PUT_DELTA,
        "short_call_delta": config.SHORT_CALL_DELTA,
        "put_spread_width": config.PUT_SPREAD_WIDTH,
        "call_spread_width": config.CALL_SPREAD_WIDTH,
        "vrp_sell_pct": config.VRP_SELL_PCT,
        "vrp_rich_pct": config.VRP_RICH_PCT,
        "magnitude_high_pct": config.MAGNITUDE_HIGH_PCT,
        "term_backwardation": config.TERM_BACKWARDATION,
        "cost_per_leg_round_trip": config.BACKTEST_COST_PER_LEG_RT,
        "n_trials": config.GATE_N_TRIALS,
        "strategies": list(PRICED_STRATEGIES),
    }


def spec_fingerprint() -> str:
    raw = json.dumps(current_spec(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _neutral(reason: str) -> dict:
    return {
        "ok": False,
        "experiment_id": config.GATE_EXPERIMENT_ID,
        "spec_fingerprint": spec_fingerprint(),
        "reason": reason,
        "strategies": {name: "not_cleared" for name in PRICED_STRATEGIES},
    }


def load_gate_status(path: Path | None = None) -> dict:
    p = path or config.GATE_SCORECARD
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return _neutral("gate scorecard missing")
    except Exception as exc:  # noqa: BLE001 - display must fail safe
        return _neutral(f"gate scorecard unreadable: {exc}")

    if raw.get("experiment_id") != config.GATE_EXPERIMENT_ID:
        return _neutral("gate experiment mismatch")
    if raw.get("spec_fingerprint") != spec_fingerprint():
        return _neutral("gate specification changed; rerun required")

    results = raw.get("strategies") or {}
    states = {}
    for name in PRICED_STRATEGIES:
        gate = (results.get(name) or {}).get("gate") or {}
        states[name] = "cleared" if gate.get("passes") is True else "not_cleared"
    return {
        "ok": True,
        "experiment_id": config.GATE_EXPERIMENT_ID,
        "spec_fingerprint": spec_fingerprint(),
        "generated_at": raw.get("generated_at"),
        "reason": "scorecard loaded",
        "strategies": states,
    }


def apply_to_ticket(ticket: dict, path: Path | None = None) -> dict:
    """Return a copy with display-only gate labels applied per candidate."""
    out = copy.deepcopy(ticket)
    status = load_gate_status(path)
    for cand in out.get("candidates") or []:
        cand["gate"] = status["strategies"].get(cand.get("strategy"), "not_cleared")
    out["gate_status"] = {
        "experiment_id": status["experiment_id"],
        "spec_fingerprint": status["spec_fingerprint"],
        "ok": status["ok"],
        "reason": status["reason"],
        "generated_at": status.get("generated_at"),
    }
    return out
