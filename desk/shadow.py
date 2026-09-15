"""Immutable SHADOW entry, daily-mark, and expiry-outcome tracking.

Published advisory candidates are recorded once. Positions with stored Robinhood
instrument IDs can receive read-only natural-side liquidation marks; marks never
close a position. Canonical outcomes remain hold-to-expiry intrinsic settlement.
No broker positions, accounts, orders, or discretionary exits are used.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

CONTRACT = 100
NY = ZoneInfo("America/New_York")


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _parse_ts(raw) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except Exception:  # noqa: BLE001
        return None


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _candidate_id(ticket: dict, candidate: dict) -> str:
    identity = {
        "date": ticket.get("date"),
        "underlying": candidate.get("underlying", ticket.get("underlying", "SPY")),
        "strategy": candidate.get("strategy"),
        "expiry": candidate.get("expiry"),
        "legs": [
            {"side": leg.get("side"), "type": leg.get("type"),
             "strike": leg.get("strike")}
            for leg in candidate.get("legs") or []
        ],
    }
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:20]


def assign_candidate_ids(ticket: dict) -> dict:
    """Add stable IDs in-place so base and Robinhood-enriched copies deduplicate."""
    for candidate in ticket.get("candidates") or []:
        if candidate.get("legs") and candidate.get("expiry"):
            candidate.setdefault("candidate_id", _candidate_id(ticket, candidate))
    return ticket


def _load_open(path: Path | None = None) -> dict[str, dict]:
    try:
        raw = json.loads((path or config.SHADOW_OPEN).read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001 - fail neutral on missing/corrupt tracker state
        return {}


def _entry(ticket: dict, candidate: dict) -> dict:
    enriched = bool(candidate.get("enriched"))
    leg_keys = (
        "side", "type", "strike", "instrument_id", "bid", "ask", "mid",
        "delta", "implied_volatility", "open_interest", "volume", "quote_ts",
    )
    credit = candidate.get("credit_usd")
    debit = candidate.get("debit_usd")
    entry_cash = float(credit or 0.0) - float(debit or 0.0)
    source = candidate.get("source") or (
        "robinhood_mid" if enriched else "black_scholes_estimate")
    return {
        "candidate_id": candidate["candidate_id"],
        "status": "open",
        "opened_at": ticket.get("ts"),
        "signal_date": ticket.get("date"),
        "underlying": candidate.get("underlying", ticket.get("underlying", "SPY")),
        "qlib_asset": candidate.get("qlib_asset"),
        "strategy": candidate.get("strategy"),
        "expiry": candidate.get("expiry"),
        "legs": [
            {k: leg.get(k) for k in leg_keys if leg.get(k) is not None}
            for leg in candidate.get("legs") or []
        ],
        "entry_spot": (ticket.get("signal") or {}).get("spot"),
        "credit_usd": credit,
        "debit_usd": debit,
        "entry_cash_usd": round(entry_cash, 2),
        "max_risk_usd": candidate.get("max_risk_usd"),
        "entry_source": source,
        "entry_live": enriched,
        "gate": candidate.get("gate", "not_cleared"),
        "research_experiment": candidate.get("research_experiment"),
        "exit_policy": "hold_to_expiry",
        "measurement": "hold_to_expiry_intrinsic_net_fixed_cost",
    }


def record_ticket(ticket: dict, path: Path | None = None) -> int:
    """Upsert eligible candidates into the open-paper state; return changed count.

    A same-day Robinhood enrichment replaces its earlier BS entry economics.  A
    later fallback never overwrites a live-mid entry.
    """
    assign_candidate_ids(ticket)
    target = path or config.SHADOW_OPEN
    opened = _load_open(target)
    changed = 0
    for candidate in ticket.get("candidates") or []:
        cid = candidate.get("candidate_id")
        if not cid or not candidate.get("legs") or not candidate.get("expiry"):
            continue
        fresh = _entry(ticket, candidate)
        existing = opened.get(cid)
        if existing is None:
            opened[cid] = fresh
            changed += 1
        elif fresh["entry_live"] and not existing.get("entry_live"):
            fresh["opened_at"] = existing.get("opened_at") or fresh["opened_at"]
            fresh["repriced_at"] = datetime.now(timezone.utc).isoformat()
            opened[cid] = fresh
            changed += 1
    if changed:
        _atomic_json(target, opened)
    return changed


def supersede_estimate_openings(ticket: dict, path: Path | None = None) -> int:
    """When a LIVE-quoted ETF ticket is published, drop that day's estimate-only opens
    for the same experiment that the live run did not itself upgrade.

    Estimate and live builds may pick different strikes (BS-solved vs listed), so they
    get different candidate_ids and would otherwise both be tracked. This keeps exactly
    one tracked position per (date, underlying, strategy): live when the Codex session
    ran, estimate otherwise. Scoped to the ETF experiment so the SPY lane is untouched.
    """
    live = [c for c in ticket.get("candidates") or [] if c.get("enriched")]
    if not live or not str(ticket.get("research_experiment") or "").startswith("options_etf"):
        return 0
    day = ticket.get("date")
    live_ids = {c.get("candidate_id") for c in live}
    # Only supersede an estimate whose (underlying, strategy) actually got a live fill
    # today; an estimate with no live counterpart (Codex didn't quote it) survives.
    live_keys = {(c.get("underlying"), c.get("strategy")) for c in live}
    target = path or config.SHADOW_OPEN
    opened = _load_open(target)
    drop = [cid for cid, row in opened.items()
            if cid not in live_ids
            and not row.get("entry_live")
            and row.get("signal_date") == day
            and str(row.get("research_experiment") or "").startswith("options_etf")
            and (row.get("underlying"), row.get("strategy")) in live_keys]
    for cid in drop:
        opened.pop(cid, None)
    if drop:
        _atomic_json(target, opened)
    return len(drop)


def retract_same_day_on_veto(ticket: dict, path: Path | None = None) -> int:
    """Remove same-day staged openings superseded by an authoritative NO_TRADE.

    Ticket/history JSONL remains the immutable audit trail. This only corrects the
    mutable open-position tracker when a late fresh signal vetoes candidates staged
    from an older still-within-TTL snapshot.
    """
    if ticket.get("action") != "NO_TRADE" or ticket.get("candidates"):
        return 0
    day = ticket.get("date")
    if not day:
        return 0
    experiment = ticket.get("research_experiment")
    underlying = ticket.get("underlying")
    target = path or config.SHADOW_OPEN
    opened = _load_open(target)

    def superseded(row: dict) -> bool:
        if row.get("signal_date") != day:
            return False
        if str(experiment or "").startswith("options_etf"):
            return row.get("research_experiment") == experiment
        return (row.get("research_experiment") is None
                and row.get("underlying") == underlying)

    drop = [cid for cid, row in opened.items() if superseded(row)]
    for cid in drop:
        opened.pop(cid, None)
    if drop:
        _atomic_json(target, opened)
    return len(drop)


def terminal_option_value(candidate: dict, terminal_spot: float) -> float:
    total = 0.0
    for leg in candidate.get("legs") or []:
        strike = float(leg["strike"])
        intrinsic = (max(terminal_spot - strike, 0.0)
                     if leg["type"] == "call"
                     else max(strike - terminal_spot, 0.0))
        total += intrinsic * CONTRACT * (1.0 if leg["side"] == "buy" else -1.0)
    return total


def candidate_pnl(candidate: dict, terminal_spot: float,
                  cost_per_leg: float | None = None) -> dict:
    entry_cash = float(candidate.get("credit_usd") or 0.0)
    if candidate.get("debit_usd") is not None:
        entry_cash -= float(candidate["debit_usd"])
    terminal = terminal_option_value(candidate, terminal_spot)
    cost_rate = (config.BACKTEST_COST_PER_LEG_RT
                 if cost_per_leg is None else float(cost_per_leg))
    cost = float(cost_rate) * len(candidate.get("legs") or [])
    return {
        "entry_cash_usd": round(entry_cash, 2),
        "terminal_value_usd": round(terminal, 2),
        "cost_usd": round(cost, 2),
        "pnl_usd": round(entry_cash + terminal - cost, 2),
    }



def exit_signal(entry_cash: float, close_cash: float) -> dict:
    """v11 ADVISORY exit management (research: v10 -> v11 cut the 2022 loss $568 at equal total).

    A short-premium position opens for a CREDIT (entry_cash > 0) and is closed by paying a
    debit. Signals:
      CLOSE_TARGET -- buy-back cost <= 50% of the credit received (half the max profit taken)
      CLOSE_STOP   -- buy-back cost >= 3x the credit (a realized loss of 2x credit)
    Advisory only: this never closes anything. The human decides; hold-to-expiry remains the
    canonical MEASUREMENT so the shadow ledger stays comparable across all research.
    """
    credit = float(entry_cash or 0.0)
    if credit <= 0:
        return {"action": "HOLD", "reason": "not a net-credit position"}
    cost_to_close = -float(close_cash)          # close_cash is negative when we must pay
    if cost_to_close <= config.PROFIT_TARGET_FRAC * credit:
        return {"action": "CLOSE_TARGET",
                "reason": f"buy-back ${cost_to_close:.0f} <= {config.PROFIT_TARGET_FRAC:.0%} of ${credit:.0f} credit",
                "captured_pct": round(1 - cost_to_close / credit, 4)}
    if cost_to_close >= (1.0 + config.STOP_LOSS_MULT) * credit:
        return {"action": "CLOSE_STOP",
                "reason": f"buy-back ${cost_to_close:.0f} >= {1 + config.STOP_LOSS_MULT:.0f}x ${credit:.0f} credit (loss {config.STOP_LOSS_MULT:.0f}x)",
                "loss_multiple": round(cost_to_close / credit - 1, 2)}
    return {"action": "HOLD", "reason": "between target and stop"}


def build_mark_request(now: datetime | None = None,
                       open_path: Path | None = None) -> dict:
    """Build a secret-free quote request for open candidates with instrument IDs."""
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(NY).date()
    positions: list[dict] = []
    skipped: list[dict] = []
    for cid, position in sorted(_load_open(open_path).items()):
        try:
            expiry = date.fromisoformat(str(position["expiry"]))
        except (KeyError, TypeError, ValueError):
            skipped.append({"candidate_id": cid, "reason": "invalid expiry"})
            continue
        if expiry < today:
            skipped.append({"candidate_id": cid, "reason": "past expiry; awaiting settlement"})
            continue
        legs = position.get("legs") or []
        if not legs or any(not leg.get("instrument_id") for leg in legs):
            skipped.append({"candidate_id": cid, "reason": "no stored Robinhood instrument IDs"})
            continue
        positions.append({
            "candidate_id": cid,
            "underlying": position.get("underlying"),
            "strategy": position.get("strategy"),
            "expiry": position.get("expiry"),
            "legs": [{"side": leg.get("side"), "type": leg.get("type"),
                      "strike": leg.get("strike"),
                      "instrument_id": leg.get("instrument_id")} for leg in legs],
        })
    seed = {"date": today.isoformat(), "positions": positions}
    request_id = hashlib.sha256(
        json.dumps(seed, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "request_id": request_id,
        "generated_at": now.isoformat(),
        "status": "READY" if positions else "NO_OPEN_POSITIONS",
        "reason": (f"{len(positions)} open candidate(s) require read-only marks"
                   if positions else "no quoteable open SHADOW candidates"),
        "read_only": True,
        "positions": positions,
        "skipped": skipped,
    }


def write_mark_request(request: dict | None = None,
                       path: Path | None = None) -> str:
    target = path or config.SHADOW_MARK_REQUEST
    _atomic_json(target, request or build_mark_request())
    return str(target)


def load_mark_request(path: Path | None = None) -> dict | None:
    return _read_json(path or config.SHADOW_MARK_REQUEST)


def _mark_quote(raw: dict, now: datetime) -> tuple[dict | None, str | None]:
    bid = _number(raw.get("bid_price", raw.get("bid")))
    ask = _number(raw.get("ask_price", raw.get("ask")))
    if bid is None or ask is None or bid < 0 or ask < bid or ask <= 0:
        return None, "invalid bid/ask"
    stamp = _parse_ts(raw.get("updated_at") or raw.get("quote_ts"))
    if stamp is None:
        return None, "missing quote timestamp"
    age = (now - stamp).total_seconds() / 60.0
    if age < -1 or age > config.ROBINHOOD_QUOTE_MAX_AGE_MINUTES:
        return None, f"stale quote ({age:.1f}m)"
    return {
        "instrument_id": str(raw.get("instrument_id") or ""),
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "mid": round((bid + ask) / 2.0, 4),
        "delta": _number(raw.get("delta")),
        "implied_volatility": _number(raw.get("implied_volatility")),
        "open_interest": int(_number(raw.get("open_interest")) or 0),
        "volume": int(_number(raw.get("volume")) or 0),
        "quote_ts": stamp.isoformat(),
        "age_minutes": round(age, 2),
    }, None


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if isinstance(row, dict):
                    rows.append(row)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return rows


def finalize_marks(payload: dict, request: dict | None = None,
                   now: datetime | None = None, open_path: Path | None = None,
                   marks_path: Path | None = None) -> dict:
    """Validate live quotes and append natural-side marks; never close positions."""
    now = now or datetime.now(timezone.utc)
    request = request or load_mark_request()
    target_open = open_path or config.SHADOW_OPEN
    target_marks = marks_path or config.SHADOW_MARKS
    report = {"status": "NO_MARKS", "marked_at": now.isoformat(),
              "accepted": [], "rejected": []}
    if not request:
        report["reason"] = "mark request missing"
        return report
    if payload.get("request_id") != request.get("request_id"):
        report["reason"] = "mark payload request_id mismatch"
        return report
    request_ts = _parse_ts(request.get("generated_at"))
    if request_ts is None or request_ts.astimezone(NY).date() != now.astimezone(NY).date():
        report["reason"] = "mark request is missing or not from today"
        return report
    if request.get("status") != "READY":
        report["reason"] = request.get("reason", "mark request not ready")
        return report

    quote_map: dict[str, dict] = {}
    for raw in payload.get("quotes") or []:
        instrument_id = str(raw.get("instrument_id") or "")
        if instrument_id:
            quote_map[instrument_id] = raw
    opened = _load_open(target_open)
    existing_mark_ids = {row.get("mark_id") for row in _load_jsonl(target_marks)}
    appended: list[dict] = []
    for requested in request.get("positions") or []:
        cid = requested.get("candidate_id")
        position = opened.get(cid)
        if position is None:
            report["rejected"].append({"candidate_id": cid, "reason": "position no longer open"})
            continue
        requested_ids = [str(leg.get("instrument_id") or "")
                         for leg in requested.get("legs") or []]
        open_ids = [str(leg.get("instrument_id") or "")
                    for leg in position.get("legs") or []]
        if not requested_ids or requested_ids != open_ids:
            report["rejected"].append({
                "candidate_id": cid,
                "reason": "requested instruments no longer match the open position",
            })
            continue
        mark_legs: list[dict] = []
        close_cash = 0.0
        reason = None
        for leg in position.get("legs") or []:
            iid = str(leg.get("instrument_id") or "")
            quote, err = _mark_quote(quote_map.get(iid) or {}, now)
            if err:
                reason = f"{iid or 'missing instrument'}: {err}"
                break
            side = leg.get("side")
            if side == "sell":
                close_side, close_price, leg_cash = "buy", quote["ask"], -quote["ask"] * CONTRACT
            elif side == "buy":
                close_side, close_price, leg_cash = "sell", quote["bid"], quote["bid"] * CONTRACT
            else:
                reason = f"{iid}: invalid original side"
                break
            close_cash += leg_cash
            mark_legs.append({**quote, "original_side": side, "type": leg.get("type"),
                              "strike": leg.get("strike"), "close_side": close_side,
                              "close_price": close_price,
                              "close_cash_usd": round(leg_cash, 2)})
        if reason:
            report["rejected"].append({"candidate_id": cid, "reason": reason})
            continue
        entry_cash = float(position.get("entry_cash_usd") if position.get("entry_cash_usd") is not None
                           else (float(position.get("credit_usd") or 0.0)
                                 - float(position.get("debit_usd") or 0.0)))
        cost = config.BACKTEST_COST_PER_LEG_RT * len(mark_legs)
        pnl = entry_cash + close_cash - cost
        max_risk = _number(position.get("max_risk_usd"))
        try:
            expiry = date.fromisoformat(str(position["expiry"]))
            opened_day = date.fromisoformat(str(position["signal_date"]))
            dte = (expiry - now.astimezone(NY).date()).days
            hold_days = (now.astimezone(NY).date() - opened_day).days
        except (KeyError, TypeError, ValueError):
            dte, hold_days = None, None
        quote_fingerprint = [(leg["instrument_id"], leg["quote_ts"]) for leg in mark_legs]
        mark_id = hashlib.sha256(json.dumps(
            {"candidate_id": cid, "quotes": quote_fingerprint}, sort_keys=True
        ).encode("utf-8")).hexdigest()[:20]
        mark = {
            "mark_id": mark_id, "candidate_id": cid,
            "underlying": position.get("underlying"),
            "strategy": position.get("strategy"), "expiry": position.get("expiry"),
            "marked_at": now.isoformat(), "dte": dte, "holding_days": hold_days,
            "entry_source": position.get("entry_source"),
            "entry_cash_usd": round(entry_cash, 2),
            "exit_debit_usd": round(max(-close_cash, 0.0), 2),
            "exit_credit_usd": round(max(close_cash, 0.0), 2),
            "close_cash_usd": round(close_cash, 2),
            "estimated_round_trip_cost_usd": round(cost, 2),
            "unrealized_pnl_usd": round(pnl, 2),
            "return_on_risk": (round(pnl / max_risk, 6) if max_risk and max_risk > 0 else None),
            "quote_source": "robinhood_natural_exit",
            "legs": mark_legs,
        }
        mark["exit_signal"] = exit_signal(entry_cash, close_cash)
        duplicate = mark_id in existing_mark_ids
        mark["duplicate"] = duplicate
        report["accepted"].append(mark)
        if not duplicate:
            appended.append(mark)
            existing_mark_ids.add(mark_id)
            prior_mfe = _number(position.get("mfe_pnl_usd"))
            prior_mae = _number(position.get("mae_pnl_usd"))
            position["last_mark"] = mark
            position["mfe_pnl_usd"] = round(max(pnl, prior_mfe if prior_mfe is not None else pnl), 2)
            position["mae_pnl_usd"] = round(min(pnl, prior_mae if prior_mae is not None else pnl), 2)
            position["mark_count"] = int(position.get("mark_count") or 0) + 1
    if appended:
        target_marks.parent.mkdir(parents=True, exist_ok=True)
        with target_marks.open("a", encoding="utf-8") as handle:
            for mark in appended:
                handle.write(json.dumps(mark) + "\n")
        _atomic_json(target_open, opened)
    report["status"] = "MARKED" if report["accepted"] else "NO_MARKS"
    report["reason"] = (f"{len(appended)} new mark(s); "
                        f"{sum(bool(row.get('duplicate')) for row in report['accepted'])} duplicate(s)"
                        if report["accepted"] else "no open position received a valid mark")
    return report


def _daily_closes(path: Path) -> list[tuple[date, float]]:
    rows: list[tuple[date, float]] = []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    rows.append((date.fromisoformat(row["date"]), float(row["close"])))
                except (KeyError, TypeError, ValueError):
                    continue
    except Exception:  # noqa: BLE001
        return []
    return rows


def settle_expired(csv_path: Path | None = None, open_path: Path | None = None,
                   pnl_path: Path | None = None) -> int:
    """Settle expired candidates from each underlying's local Qlib daily close."""
    target_open = open_path or config.SHADOW_OPEN
    target_pnl = pnl_path or config.SHADOW_PNL
    opened = _load_open(target_open)
    closes_cache: dict[Path, list[tuple[date, float]]] = {}
    settled: list[dict] = []
    for cid, position in list(opened.items()):
        qlib_asset = position.get("qlib_asset") or position.get("underlying") or "SPY"
        source = csv_path or (config.QLIB_CSV_DIR / f"{qlib_asset}.csv")
        if source not in closes_cache:
            closes_cache[source] = _daily_closes(source)
        closes = closes_cache[source]
        if not closes:
            continue
        try:
            expiry = date.fromisoformat(position["expiry"])
            entry_day = date.fromisoformat(position["signal_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if closes[-1][0] < expiry:
            continue
        eligible = [(day, close) for day, close in closes if entry_day <= day <= expiry]
        if not eligible:
            continue
        terminal_day, terminal_spot = eligible[-1]
        economics = candidate_pnl(position, terminal_spot)
        exit_legs: list[dict] = []
        for leg in position.get("legs") or []:
            strike = float(leg["strike"])
            intrinsic = (max(terminal_spot - strike, 0.0)
                         if leg["type"] == "call"
                         else max(strike - terminal_spot, 0.0))
            cash = intrinsic * CONTRACT * (1.0 if leg["side"] == "buy" else -1.0)
            exit_legs.append({"side": leg.get("side"), "type": leg.get("type"),
                              "strike": strike, "settlement_price": round(intrinsic, 4),
                              "settlement_cash_usd": round(cash, 2)})
        result = dict(position)
        result.update(economics)
        result.update({
            "status": "settled",
            "settled_at": datetime.now(timezone.utc).isoformat(),
            "terminal_date": terminal_day.isoformat(),
            "terminal_spot": round(terminal_spot, 4),
            "exit_at": terminal_day.isoformat(),
            "exit_reason": "expiration",
            "exit_source": "intrinsic_from_underlying_close",
            "exit_legs": exit_legs,
            "exit_cash_usd": economics["terminal_value_usd"],
            "exit_debit_usd": round(max(-economics["terminal_value_usd"], 0.0), 2),
            "exit_credit_usd": round(max(economics["terminal_value_usd"], 0.0), 2),
            "holding_days": (terminal_day - entry_day).days,
            "hit": economics["pnl_usd"] > 0,
        })
        settled.append(result)
        del opened[cid]
    if not settled:
        return 0
    target_pnl.parent.mkdir(parents=True, exist_ok=True)
    with target_pnl.open("a", encoding="utf-8") as handle:
        for result in settled:
            handle.write(json.dumps(result) + "\n")
    _atomic_json(target_open, opened)
    return len(settled)


def load_results(path: Path | None = None) -> list[dict]:
    rows: list[dict] = []
    try:
        for line in (path or config.SHADOW_PNL).read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
                if row.get("status") == "settled":
                    rows.append(row)
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return rows


def load_marks(path: Path | None = None, limit: int | None = None) -> list[dict]:
    rows = _load_jsonl(path or config.SHADOW_MARKS)
    return rows[-limit:] if limit else rows


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _stats(rows: list[dict]) -> dict:
    pnls = [float(row.get("pnl_usd") or 0.0) for row in rows]
    wins = sum(value > 0 for value in pnls)
    gains = sum(value for value in pnls if value > 0)
    losses = -sum(value for value in pnls if value < 0)
    mfe = [v for v in (_number(row.get("mfe_usd")) for row in rows) if v is not None]
    mae = [v for v in (_number(row.get("mae_usd")) for row in rows) if v is not None]
    held = [v for v in (_number(row.get("holding_days")) for row in rows) if v is not None]
    risk = [v for v in (_number(row.get("max_risk_usd")) for row in rows) if v is not None]
    ror = None
    if risk and pnls and len(risk) == len(pnls):
        ratios = [p / r for p, r in zip(pnls, risk) if r]
        ror = round(sum(ratios) / len(ratios), 4) if ratios else None
    return {
        "n": len(pnls),
        "wins": wins,
        "hit_rate": round(wins / len(pnls), 4) if pnls else None,
        "total_pnl_usd": round(sum(pnls), 2),
        "avg_pnl_usd": _mean(pnls),
        "best_usd": round(max(pnls), 2) if pnls else None,
        "worst_usd": round(min(pnls), 2) if pnls else None,
        "profit_factor": (round(gains / losses, 4) if losses else (None if not gains else "inf")),
        "avg_mfe_usd": _mean(mfe),
        "avg_mae_usd": _mean(mae),
        "avg_holding_days": _mean(held),
        "avg_return_on_max_risk": ror,
    }


# Canonical PBO needs at least this many non-overlapping observations before the gate
# can render a verdict at all (see options_etf_gate_v1). Surfaced so the distance to a
# real decision is visible instead of implicit.
PBO_FLOOR_TRADES = 40


def promotion_progress(rows: list[dict]) -> dict:
    """How far the settled SHADOW record is from being gate-decidable.

    Counts DISTINCT settlement dates, not raw rows: concurrent positions opened on the
    same day are correlated and must not be counted as independent evidence.
    """
    settled = len(rows)
    dates = {str(row.get("entry_date") or row.get("opened_at") or "")[:10]
             for row in rows if row.get("entry_date") or row.get("opened_at")}
    dates.discard("")
    independent = len(dates)
    return {
        "settled_trades": settled,
        "independent_entry_dates": independent,
        "pbo_floor_trades": PBO_FLOOR_TRADES,
        "remaining_to_floor": max(PBO_FLOOR_TRADES - independent, 0),
        "gate_decidable": independent >= PBO_FLOOR_TRADES,
        "note": ("Reaching the floor only makes a verdict POSSIBLE; it is not a pass. "
                 "Promotion still requires PBO < 0.5 AND Deflated Sharpe > 0."),
    }



def _open_exit_signals(opened: dict) -> dict:
    """Group open positions by their latest advisory exit signal (v11)."""
    out: dict[str, list[str]] = {}
    for row in (opened or {}).values():
        sig = ((row.get("last_mark") or {}).get("exit_signal") or {}).get("action")
        if sig and sig != "HOLD":
            out.setdefault(sig, []).append(str(row.get("underlying") or row.get("candidate_id"))[:12])
    return out


def summary(path: Path | None = None, open_path: Path | None = None) -> dict:
    rows = load_results(path)
    strategies = sorted({row.get("strategy") for row in rows if row.get("strategy")})
    opened = _load_open(open_path) if (open_path is not None or path is None) else {}
    marked = [row.get("last_mark") for row in opened.values() if row.get("last_mark")]
    underlyings = sorted({row.get("underlying") for row in rows if row.get("underlying")})
    return {
        "measurement": "hold_to_expiry; PnL > 0 after fixed per-leg cost",
        "overall": _stats(rows),
        "by_strategy": {name: _stats([row for row in rows if row.get("strategy") == name])
                        for name in strategies},
        "by_underlying": {name: _stats([row for row in rows if row.get("underlying") == name])
                          for name in underlyings},
        "promotion_progress": promotion_progress(rows),
        "open": {
            "n": len(opened),
            "marked": len(marked),
            "unrealized_pnl_usd": round(sum(
                float(row.get("unrealized_pnl_usd") or 0.0) for row in marked), 2),
            "quote_source": "robinhood_natural_exit",
        },
        "exit_signals": _open_exit_signals(opened),
    }


def trade_ledger(open_path: Path | None = None, pnl_path: Path | None = None,
                 marks_path: Path | None = None, mark_limit: int = 100) -> dict:
    """Return the local SHADOW ledger for the loopback dashboard."""
    opened = list(_load_open(open_path).values())
    settled: list[dict] = []
    for historical in load_results(pnl_path):
        row = dict(historical)
        entry_cash = _number(row.get("entry_cash_usd"))
        if entry_cash is None:
            entry_cash = float(row.get("credit_usd") or 0.0) - float(row.get("debit_usd") or 0.0)
            row["entry_cash_usd"] = round(entry_cash, 2)
        exit_cash = _number(row.get("exit_cash_usd"))
        if exit_cash is None:
            exit_cash = _number(row.get("terminal_value_usd"))
        if exit_cash is not None:
            row.setdefault("exit_cash_usd", round(exit_cash, 2))
            row.setdefault("exit_debit_usd", round(max(-exit_cash, 0.0), 2))
            row.setdefault("exit_credit_usd", round(max(exit_cash, 0.0), 2))
        row.setdefault("exit_reason", "expiration")
        row.setdefault("exit_source", "intrinsic_from_underlying_close")
        settled.append(row)
    opened.sort(key=lambda row: str(row.get("opened_at") or ""), reverse=True)
    settled.sort(key=lambda row: str(row.get("settled_at") or ""), reverse=True)
    return {
        "measurement": "model candidates, not broker fills; hold-to-expiry canonical",
        "open": opened,
        "settled": settled,
        "recent_marks": load_marks(marks_path, mark_limit),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mark-request", action="store_true",
                        help="write the read-only request for open-position quotes")
    parser.add_argument("--finalize-marks", type=Path,
                        help="validate a read-only Robinhood mark payload")
    parser.add_argument("--ledger", action="store_true", help="print the SHADOW ledger")
    parser.add_argument("--progress", action="store_true",
                        help="10:00 re-check: summarize open-position progress")
    parser.add_argument("--telegram", action="store_true", help="also send the progress line")
    args = parser.parse_args()
    if args.finalize_marks:
        payload = _read_json(args.finalize_marks) or {}
        result = finalize_marks(payload)
        print(json.dumps(result, indent=2))
        return
    if args.ledger:
        print(json.dumps(trade_ledger(), indent=2))
        return
    if args.progress:
        from datetime import date
        from . import telegram_notify
        text = telegram_notify.format_progress(summary(), date.today().isoformat())
        print(text)
        if args.telegram:
            ok, err = telegram_notify.send_message(text)
            print(f"telegram: {'sent' if ok else 'skipped - ' + str(err)}")
        return
    request = build_mark_request()
    path = write_mark_request(request)
    print(json.dumps(request, indent=2))
    print(f"mark request -> {path}")


if __name__ == "__main__":
    main()
