"""P5 liquid-ETF options research lane (SHADOW, advisory, read-only quotes).

The local phase produces a deterministic request from fresh Qlib/global flags and
completed daily CSVs. A Codex session resolves that request with read-only Robinhood
chain/quote tools, then this module validates the returned payload and publishes up
to five defined-risk candidates. No broker action exists here.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import bs, config, shadow, signal_read, strategies

NY = ZoneInfo("America/New_York")
CONTRACT = 100
SHORT_PUT_DELTA = -0.30
SHORT_CALL_DELTA = 0.30


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def load_spec(path: Path | None = None) -> dict:
    spec = _read_json(path or config.ETF_EXPERIMENT)
    if not spec or spec.get("experiment_id") != config.ETF_EXPERIMENT_ID:
        raise ValueError("ETF experiment specification missing or invalid")
    return spec


def _parse_ts(raw) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp
    except Exception:  # noqa: BLE001
        return None


def _flag_status(path: Path, timestamp_keys: tuple[str, ...], max_age_hours: float,
                 now: datetime) -> dict:
    raw = _read_json(path)
    if raw is None:
        return {"ok": False, "reason": f"missing/unreadable: {path}"}
    stamp = next((_parse_ts(raw.get(key)) for key in timestamp_keys if raw.get(key)), None)
    if stamp is None:
        return {"ok": False, "reason": "no valid timestamp"}
    age = (now - stamp).total_seconds() / 3600.0
    if age < -1 or age > max_age_hours or raw.get("stale") is True:
        return {"ok": False, "reason": f"stale ({age:.1f}h)", "age_hours": round(age, 2)}
    return {"ok": True, "age_hours": round(age, 2), "data": raw}


def _completed_closes(path: Path, now: datetime) -> list[tuple[date, float]]:
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
    local = now.astimezone(NY)
    if local.time() < time(16, 15):
        rows = [row for row in rows if row[0] < local.date()]
    else:
        rows = [row for row in rows if row[0] <= local.date()]
    return rows


def realized_vol_20(path: Path, now: datetime) -> dict | None:
    rows = _completed_closes(path, now)
    if len(rows) < 21:
        return None
    tail = rows[-21:]
    returns = [math.log(tail[i][1] / tail[i - 1][1]) for i in range(1, len(tail))
               if tail[i][1] > 0 and tail[i - 1][1] > 0]
    if len(returns) < 20:
        return None
    closes = [c for _, c in rows]
    spot = tail[-1][1]
    # v4-live: trend + momentum context from the SAME completed-close series (no lookahead).
    sma200 = (sum(closes[-200:]) / 200.0) if len(closes) >= 200 else None
    mom126 = (spot / closes[-127] - 1.0) if len(closes) >= 127 and closes[-127] > 0 else None
    return {"rv20": round(statistics.stdev(returns) * math.sqrt(252), 6),
            "reference_spot": round(spot, 4),
            "sma200": round(sma200, 4) if sma200 else None,
            "above_sma200": (spot >= sma200) if sma200 else None,
            "mom126": round(mom126, 6) if mom126 is not None else None,
            "data_through": tail[-1][0].isoformat()}


def load_context(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    qlib = _flag_status(config.QLIB_STATE_FLAG, ("as_of",),
                        config.QLIB_STATE_STALE_DAYS * 24, now)
    hq = _flag_status(config.HQ_MACRO_STATE_FLAG, ("generated_at",), 1.0, now)
    gpu = _flag_status(config.MACRO_GPU_STATE_FLAG, ("as_of",), 4 * 24, now)
    return {"qlib": qlib, "vol": signal_read.read_signal(now=now),
            "hq_macro": hq, "macro_gpu": gpu}


def _hard_veto(vol: dict, spec: dict) -> str | None:
    """v3: the ONLY hard blocks are a predicted vol eruption and missing/stale signal.
    Magnitude and calm are advisory (see _advisory) and never block. The eruption block
    is the genuine 'do not sell premium into a coming blowup' protection and is never
    relaxed. Backward-compatible with a v2-style global_veto spec if present."""
    if not vol.get("ok"):
        return f"global vol signal unavailable: {vol.get('reason')}"
    shift = vol.get("shift") or {}
    rules = spec["entry_policy"].get("hard_veto") or spec["entry_policy"].get("global_veto") or {}
    if bool(shift.get("eruption_predicted")) != bool(rules.get("eruption_predicted", False)):
        return "eruption veto: predicted vol eruption - do not sell premium"
    return None


def _advisory(vol: dict, spec: dict) -> dict:
    """Non-blocking regime context: magnitude percentile -> size hint, plus calm/VRP."""
    magnitude = vol.get("magnitude") or {}
    shift = vol.get("shift") or {}
    vrp = vol.get("vrp") or {}
    high = float((spec["entry_policy"].get("advisory_sizing") or {}).get(
        "magnitude_pct_high", config.MAGNITUDE_ADVISORY_HIGH))
    mag = magnitude.get("magnitude_pct")
    size_hint = "normal"
    if mag is not None and float(mag) >= high:
        size_hint = "reduce_size"      # advisory only: high expected-move regime
    return {"magnitude_pct": mag, "size_hint": size_hint,
            "calm_5d": shift.get("calm_5d"), "calm_21d": shift.get("calm_21d"),
            "vrp_pct": vrp.get("vrp_pct"),
            "note": "advisory only - magnitude/calm/VRP inform sizing, they do not block"}


def _live_spot(symbol: str, live_quotes: dict | None) -> float | None:
    """Live Robinhood equity price for `symbol` from a same-session snapshot, if present."""
    if not live_quotes:
        return None
    entry = live_quotes.get(symbol) or live_quotes.get(symbol.upper())
    if entry is None:
        return None
    if isinstance(entry, dict):
        entry = entry.get("last_trade_price") or entry.get("price") or entry.get("mark_price")
    return _number(entry)


def build_request(now: datetime | None = None, live_quotes: dict | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    spec = load_spec()
    context = load_context(now)
    veto = _hard_veto(context["vol"], spec)
    advisory = _advisory(context["vol"], spec)
    qlib_status = context["qlib"]
    reasons: list[str] = []
    eligible: list[dict] = []
    rejected_gate: list[dict] = []
    if veto:
        reasons.append(veto)
    if not qlib_status.get("ok"):
        reasons.append(f"Qlib unavailable: {qlib_status.get('reason')}")
    if not reasons:
        qlib = qlib_status["data"]
        assets = qlib.get("assets") or {}
        qrules = spec["entry_policy"]["qlib"]
        routing = spec["entry_policy"]["structure_routing"]
        min_directional = float(qrules["minimum_conviction_directional"])
        for symbol, policy in spec["scope"]["candidate_universe"].items():
            qasset = assets.get(policy["qlib_asset"]) or {}
            structure = route_structure(qasset.get("lean"), routing)
            if structure is None:
                continue
            conviction = qasset.get("conviction")
            if structure != IRON_CONDOR:
                # Directional structures must clear the conviction bar.
                if conviction is None or float(conviction) < min_directional:
                    continue
            vol = realized_vol_20(config.QLIB_CSV_DIR / f"{policy['qlib_asset']}.csv", now)
            if not vol or vol["rv20"] <= 0:
                continue
            # v5 trend gate: never sell PUT-side premium below the 200-day (downtrend).
            if structure in PUT_SIDE_STRUCTURES:
                if not vol.get("above_sma200"):
                    rejected_gate.append({"symbol": symbol, "structure": structure,
                                          "reason": "below 200-day SMA (put-side trend gate)"})
                    continue
            # v10 momentum gate: never sell CALL premium on a high-momentum symbol.
            if structure == CALL_SPREAD:
                mom = vol.get("mom126")
                if mom is None or float(mom) > config.CALL_MOMENTUM_MAX:
                    rejected_gate.append({"symbol": symbol, "structure": structure,
                                          "reason": f"126d momentum {mom} > {config.CALL_MOMENTUM_MAX}"})
                    continue
            # P12: live Robinhood spot refreshes the price anchor (strike selection /
            # moneyness); RV stays historical. spot_source is recorded for audit.
            live = _live_spot(symbol, live_quotes)
            spot_source = "prior_close"
            if live is not None and live > 0:
                vol = {**vol, "reference_spot": round(live, 4)}
                spot_source = "live"
            eligible.append({
                "symbol": symbol, "qlib_asset": policy["qlib_asset"],
                "bucket": policy["bucket"], "spread_width": policy["spread_width"],
                "structure": structure,
                "minimum_iv_rv_ratio": _min_iv_rv(structure, spec["entry_policy"]),
                "qlib_lean": qasset.get("lean"),
                "qlib_conviction": float(conviction) if conviction is not None else 0.0,
                "qlib_force": qasset.get("force"), "horizons": qasset.get("horizons"),
                "spot_source": spot_source, "size_hint": advisory["size_hint"],
                **vol,
            })
        eligible.sort(key=lambda row: (-row["qlib_conviction"], row["symbol"]))
        if not eligible:
            reasons.append("no frozen-universe ETF clears the Qlib discovery threshold")
    context_summary = {
        "qlib": {"ok": qlib_status.get("ok"), "age_hours": qlib_status.get("age_hours"),
                 "promoted": (qlib_status.get("data") or {}).get("promoted"),
                 "gate": (qlib_status.get("data") or {}).get("gate")},
        "hq_macro": {"ok": context["hq_macro"].get("ok"),
                     "reason": context["hq_macro"].get("reason"),
                     "regime": ((context["hq_macro"].get("data") or {}).get("regime") or {}).get("label")},
        "macro_gpu": {"ok": context["macro_gpu"].get("ok"),
                      "reason": context["macro_gpu"].get("reason")},
        "global_vol": {"ok": context["vol"].get("ok"),
                       "shift": context["vol"].get("shift"),
                       "magnitude": context["vol"].get("magnitude")},
        "advisory": advisory,
    }
    fingerprint = hashlib.sha256(json.dumps(spec, sort_keys=True).encode("utf-8")).hexdigest()[:16]
    request_seed = {"date": now.astimezone(NY).date().isoformat(), "spec": fingerprint,
                    "eligible": [row["symbol"] for row in eligible]}
    request_id = hashlib.sha256(json.dumps(request_seed, sort_keys=True).encode("utf-8")).hexdigest()[:20]
    return {
        "request_id": request_id, "generated_at": now.isoformat(),
        "experiment_id": spec["experiment_id"], "spec_fingerprint": fingerprint,
        "status": "READY" if eligible and not reasons else "NO_TRADE",
        "reason": "; ".join(reasons) if reasons else "eligible ETFs require live Robinhood validation",
        "read_only": True, "eligible": eligible, "context": context_summary,
        "rejected_by_gate": rejected_gate,
        "robinhood_steps": [
            "READ-ONLY: get_equity_quotes for eligible symbols",
            "get_option_chains and choose the actual expiry nearest 45 DTE within 30-60",
            "build ONLY the structure named in each eligible row - never substitute another",
            f"{PUT_SPREAD}: short put near -0.30 delta, long put exactly spread_width lower "
            "-> payload keys short_put/long_put",
            f"{CALL_SPREAD}: short call near +0.30 delta, long call exactly spread_width higher "
            "-> payload keys short_call/long_call",
            f"{IRON_CONDOR}: both sides above at one expiry -> all four keys",
            "get_option_quotes for every leg and write the payload contract",
        ],
    }


def write_request(request: dict | None = None) -> str:
    value = request or build_request()
    _atomic_json(config.ETF_OPTIONS_REQUEST, value)
    return str(config.ETF_OPTIONS_REQUEST)


def load_request() -> dict | None:
    return _read_json(config.ETF_OPTIONS_REQUEST)


def _number(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


PUT_SPREAD = "etf_short_put_spread_v1"
CALL_SPREAD = "etf_short_call_spread_v1"
IRON_CONDOR = "etf_iron_condor_v1"
PUT_SIDE_STRUCTURES = {PUT_SPREAD, IRON_CONDOR}   # carry short-put exposure (v5 trend gate)


def route_structure(lean, routing: dict) -> str | None:
    """Qlib directional lean -> exactly one structure. Unknown lean = no candidate.

    The finalizer never retries a different structure for a symbol; structure
    shopping would manufacture candidates the pre-registration does not allow.
    """
    if lean is None:
        return None
    try:
        value = int(lean)
    except (TypeError, ValueError):
        return None
    return {1: routing["bullish_lean_1"],
            -1: routing["bearish_lean_minus_1"],
            0: routing["neutral_lean_0"]}.get(value)


def _min_iv_rv(structure: str, rules: dict) -> float:
    vol = rules["asset_volatility"]
    key = ("minimum_iv_rv_ratio_iron_condor" if structure == IRON_CONDOR
           else "minimum_iv_rv_ratio_directional")
    return float(vol[key])


def _leg_check(leg: dict, rules: dict, now: datetime) -> tuple[dict | None, str | None]:
    bid, ask = _number(leg.get("bid_price")), _number(leg.get("ask_price"))
    if bid is None or ask is None or bid <= 0 or ask < bid:
        return None, "invalid/non-positive market"
    mark = _number(leg.get("mark_price")) or ((bid + ask) / 2.0)
    if mark <= 0:
        return None, "invalid mark"
    relative_spread = (ask - bid) / mark
    if relative_spread > float(rules["maximum_relative_spread_per_leg"]):
        return None, f"relative spread {relative_spread:.1%} too wide"
    oi = int(_number(leg.get("open_interest")) or 0)
    volume = int(_number(leg.get("volume")) or 0)
    if oi < int(rules["minimum_open_interest"]) and volume < int(rules["or_minimum_daily_volume"]):
        return None, f"OI {oi} and volume {volume} below thresholds"
    for field in ("bid_size", "ask_size"):
        if leg.get(field) is not None and int(_number(leg.get(field)) or 0) < int(rules["minimum_bid_and_ask_size_when_reported"]):
            return None, f"{field} below threshold"
    stamp = _parse_ts(leg.get("updated_at"))
    if stamp is None:
        return None, "missing quote timestamp"
    age = (now - stamp).total_seconds() / 60.0
    if age < -1 or age > float(rules["quote_max_age_minutes"]):
        return None, f"stale quote ({age:.1f}m)"
    normalized = dict(leg)
    normalized.update({"bid": round(bid, 4), "ask": round(ask, 4),
                       "mid": round(mark, 4), "relative_spread": round(relative_spread, 6),
                       "open_interest": oi, "volume": volume, "quote_ts": stamp.isoformat()})
    return normalized, None


def _side(market: dict, kind: str, request_row: dict, rules: dict,
          now: datetime) -> tuple[dict | None, str | None]:
    """Validate one vertical credit side ('put' or 'call'). Returns normalized parts."""
    short = market.get(f"short_{kind}") or {}
    long = market.get(f"long_{kind}") or {}
    short_q, err = _leg_check(short, rules["liquidity"], now)
    if err:
        return None, f"short {kind}: {err}"
    long_q, err = _leg_check(long, rules["liquidity"], now)
    if err:
        return None, f"long {kind}: {err}"
    if str(short.get("type", kind)).lower() != kind or str(long.get("type", kind)).lower() != kind:
        return None, f"both legs must be {kind}s"
    short_k, long_k = _number(short.get("strike")), _number(long.get("strike"))
    if short_k is None or long_k is None:
        return None, "missing strike"
    # A short put spread is long the LOWER strike; a short call spread the HIGHER.
    if kind == "put" and short_k <= long_k:
        return None, "invalid strike ordering"
    if kind == "call" and long_k <= short_k:
        return None, "invalid strike ordering"
    width = abs(short_k - long_k)
    if abs(width - float(request_row["spread_width"])) > 1e-6:
        return None, f"spread width {width} differs from frozen width {request_row['spread_width']}"
    contracts = rules["contracts"]
    delta = _number(short.get("delta"))
    lo = float(contracts[f"short_{kind}_delta_min"])
    hi = float(contracts[f"short_{kind}_delta_max"])
    if delta is None or not lo <= delta <= hi:
        return None, f"short {kind} delta {delta} outside frozen range"
    credit = short_q["bid"] - long_q["ask"]
    if credit <= 0:
        return None, f"{kind} side natural credit is non-positive"
    tag = "P" if kind == "put" else "C"
    return {
        "kind": kind, "width": width, "credit": credit, "delta": delta,
        "short_strike": short_k, "long_strike": long_k,
        "iv": _number(short.get("implied_volatility")),
        "max_relative_spread": max(short_q["relative_spread"], long_q["relative_spread"]),
        "legs": [dict(short_q, side="sell", type=kind, strike=short_k),
                 dict(long_q, side="buy", type=kind, strike=long_k)],
        "label": f"-{short_k:g}{tag}/+{long_k:g}{tag}",
    }, None


def _candidate(market: dict, request_row: dict, spec: dict, now: datetime) -> tuple[dict | None, str | None]:
    """Build the ONE structure this symbol was routed to. No structure shopping."""
    rules = spec["entry_policy"]
    structure = request_row.get("structure", PUT_SPREAD)
    contracts = rules["contracts"]

    try:
        expiry = date.fromisoformat(str(market["expiry"]))
    except Exception:  # noqa: BLE001
        return None, "invalid expiry"
    dte = (expiry - now.astimezone(NY).date()).days
    if not int(contracts["dte_min"]) <= dte <= int(contracts["dte_max"]):
        return None, f"DTE {dte} outside frozen range"

    kinds = {PUT_SPREAD: ("put",), CALL_SPREAD: ("call",),
             IRON_CONDOR: ("put", "call")}.get(structure)
    if kinds is None:
        return None, f"unknown structure {structure}"

    sides: list[dict] = []
    for kind in kinds:
        side, err = _side(market, kind, request_row, rules, now)
        if err:
            return None, err
        sides.append(side)

    credit = sum(side["credit"] for side in sides)
    # Only one side of an iron condor can finish ITM, so risk is the widest side.
    width = max(side["width"] for side in sides)
    if credit >= width:
        return None, "natural credit exceeds structure width"

    rv = float(request_row["rv20"])
    ivs = [side["iv"] for side in sides if side["iv"] is not None]
    iv = min(ivs) if ivs else None
    ratio = iv / rv if iv is not None and rv > 0 else None
    floor = _min_iv_rv(structure, rules)
    if ratio is None or ratio < floor:
        return None, f"IV/RV {ratio} below frozen threshold {floor}"

    credit_usd = round(credit * CONTRACT, 2)
    max_risk = round((width - credit) * CONTRACT, 2)
    if max_risk > config.MAX_TRADE_RISK_USD:
        return None, f"max risk ${max_risk} exceeds ${config.MAX_TRADE_RISK_USD} per-trade cap"
    legs = [leg for side in sides for leg in side["legs"]]
    symbol = request_row["symbol"]
    by_kind = {side["kind"]: side for side in sides}
    if structure == IRON_CONDOR:
        breakevens = (f"down {round(by_kind['put']['short_strike'] - credit, 2)} | "
                      f"up {round(by_kind['call']['short_strike'] + credit, 2)}")
        pop = round(max(0.0, 1 - abs(by_kind["put"]["delta"]) - abs(by_kind["call"]["delta"])), 4)
        rationale = ("Qlib neutral lean + calm global regime + richer IV vs RV; "
                     "defined risk on both wings")
    elif structure == CALL_SPREAD:
        breakevens = f"{round(by_kind['call']['short_strike'] + credit, 2)}"
        pop = round(1 - abs(by_kind["call"]["delta"]), 4)
        rationale = "Qlib bearish discovery + calm global regime + asset IV rich vs RV; defined risk"
    else:
        breakevens = f"{round(by_kind['put']['short_strike'] - credit, 2)}"
        pop = round(1 - abs(by_kind["put"]["delta"]), 4)
        rationale = "Qlib bullish discovery + calm global regime + asset IV rich vs RV; defined risk"

    return {
        "underlying": symbol, "qlib_asset": request_row["qlib_asset"],
        "bucket": request_row["bucket"],
        "strategy": structure, "dte": dte, "expiry": expiry.isoformat(),
        "legs": legs,
        "legs_short": f"{symbol} " + " ".join(side["label"] for side in sides),
        "credit_usd": credit_usd, "max_risk_usd": max_risk,
        "breakevens": breakevens,
        "pop": pop, "return_on_risk": round(credit_usd / max_risk, 6),
        "qlib_conviction": request_row["qlib_conviction"], "qlib_lean": request_row["qlib_lean"],
        "rv20": rv, "short_iv": iv, "iv_rv_ratio": round(ratio, 4),
        "max_leg_relative_spread": round(max(side["max_relative_spread"] for side in sides), 6),
        "rationale": rationale,
        "size_hint": request_row.get("size_hint", "normal"),
        "spot_source": request_row.get("spot_source", "prior_close"),
        "source": "robinhood_natural_bid_ask", "enriched": True,
        "gate": "not_cleared", "research_experiment": spec["experiment_id"],
    }, None


def _diversified(candidates: list[dict], spec: dict) -> list[dict]:
    candidates.sort(key=lambda row: (-row["qlib_conviction"], -row["return_on_risk"],
                                     row["max_leg_relative_spread"], row["underlying"]))
    caps = spec["portfolio_policy"]["bucket_caps"]
    counts: dict[str, int] = {}
    chosen: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        symbol, bucket = candidate["underlying"], candidate["bucket"]
        if symbol in seen or counts.get(bucket, 0) >= int(caps[bucket]):
            continue
        chosen.append(candidate)
        seen.add(symbol)
        counts[bucket] = counts.get(bucket, 0) + 1
        if len(chosen) >= int(spec["portfolio_policy"]["maximum_candidates"]):
            break
    return chosen


def _spy_premium_factor(now: datetime) -> float | None:
    """Market-wide IV/RV premium = (VIX/100) / RV20(SPY). Same proxy the v2 backtest
    used; declared in the prereg as a market-wide scalar, never per-asset observed IV."""
    signal = signal_read.read_signal(now=now)
    vix = (signal.get("vrp") or {}).get("vix") if signal.get("ok") else None
    spy = realized_vol_20(config.QLIB_CSV_DIR / "SPY.csv", now)
    if vix is None or not spy or spy["rv20"] <= 0:
        return None
    return (float(vix) / 100.0) / spy["rv20"]


def _estimate_candidate(row: dict, spec: dict, factor: float,
                        expiry: date, dte: int) -> dict | None:
    """Build one structure with Black-Scholes ESTIMATES (no live quotes).

    Mirrors the v2 backtest pricing exactly: entry IV = rv20 * market premium factor,
    strikes solved from BS delta, natural-model credit. Tagged as an estimate so the
    shadow tracker (and any live enrichment) can tell it apart from a real fill.
    """
    structure = row.get("structure", PUT_SPREAD)
    spot = _number(row.get("reference_spot"))
    rv = _number(row.get("rv20"))
    if spot is None or rv is None or spot <= 0 or rv <= 0 or factor <= 0:
        return None
    iv = rv * factor
    t = max(dte, 1) / 365.0
    width = float(row["spread_width"])

    def _put_side():
        sk = bs.strike_for_put_delta(spot, iv, t, SHORT_PUT_DELTA)
        lk = sk - width
        if lk <= 0:
            return None
        c = bs.bs_put(spot, sk, iv, t) - bs.bs_put(spot, lk, iv, t)
        return (sk, lk, c, [{"side": "sell", "type": "put", "strike": sk},
                            {"side": "buy", "type": "put", "strike": lk}])

    def _call_side():
        sk = bs.strike_for_call_delta(spot, iv, t, SHORT_CALL_DELTA)
        lk = sk + width
        c = bs.bs_call(spot, sk, iv, t) - bs.bs_call(spot, lk, iv, t)
        return (sk, lk, c, [{"side": "sell", "type": "call", "strike": sk},
                            {"side": "buy", "type": "call", "strike": lk}])

    legs: list[dict] = []
    credit = 0.0
    put_k = call_k = None
    if structure in (PUT_SPREAD, IRON_CONDOR):
        side = _put_side()
        if side is None:
            return None
        put_k, _, c, ls = side
        credit += c
        legs += ls
    if structure in (CALL_SPREAD, IRON_CONDOR):
        call_k, _, c, ls = _call_side()
        credit += c
        legs += ls
    if credit <= 0 or credit >= width:
        return None

    credit_usd = round(credit * CONTRACT, 2)
    max_risk = round((width - credit) * CONTRACT, 2)
    if max_risk > config.MAX_TRADE_RISK_USD:
        return None      # per-trade $1000 cap (advisory tracking still honors the rail)
    if structure == IRON_CONDOR:
        breakevens = f"down {round(put_k - credit, 2)} | up {round(call_k + credit, 2)}"
    elif structure == CALL_SPREAD:
        breakevens = f"{round(call_k + credit, 2)}"
    else:
        breakevens = f"{round(put_k - credit, 2)}"
    return {
        "underlying": row["symbol"], "qlib_asset": row["qlib_asset"],
        "bucket": row["bucket"], "strategy": structure, "dte": dte,
        "expiry": expiry.isoformat(), "legs": legs,
        "legs_short": f"{row['symbol']} est {structure}",
        "credit_usd": credit_usd, "max_risk_usd": max_risk,
        "breakevens": breakevens,
        "size_hint": row.get("size_hint", "normal"),
        "spot_source": row.get("spot_source", "prior_close"),
        "return_on_risk": round(credit_usd / max_risk, 6) if max_risk else 0.0,
        "qlib_conviction": row["qlib_conviction"], "qlib_lean": row["qlib_lean"],
        "rv20": rv, "short_iv": round(iv, 6), "iv_rv_ratio": round(factor, 4),
        "max_leg_relative_spread": 0.0,
        "rationale": "BS-estimate track entry (no live quotes); upgrades to live mids if the Codex run finalizes",
        "source": "black_scholes_estimate", "enriched": False,
        "gate": "not_cleared", "research_experiment": spec["experiment_id"],
    }


def finalize_estimate(request: dict | None = None, now: datetime | None = None) -> dict:
    """Offline BS-priced finalizer: builds + tracks the v2 candidates WITHOUT a live
    Codex/Robinhood session, so the strategy accumulates a SHADOW record every day it
    fires. Never actionable (estimates, not quotes); the live 09:35 run replaces these
    with real mids when it runs."""
    now = now or datetime.now(timezone.utc)
    spec = load_spec()
    request = request or load_request()
    if not request or request.get("status") != "READY":
        return _no_trade(now, (request or {}).get("reason", "no ready ETF request"), request)
    factor = _spy_premium_factor(now)
    if factor is None:
        return _no_trade(now, "cannot compute market IV/RV premium factor for estimates", request)
    expiry, dte = strategies.target_expiry(now)
    built: list[dict] = []
    for row in request.get("eligible") or []:
        candidate = _estimate_candidate(row, spec, factor, expiry, dte)
        if candidate is not None:
            built.append(candidate)
    chosen = _diversified(built, spec)
    return {
        "date": now.astimezone(NY).date().isoformat(), "ts": now.isoformat(),
        "underlying": "LIQUID_ETF_UNIVERSE", "status": "SHADOW",
        "action": "SELL_PREMIUM" if chosen else "NO_TRADE",
        "reason": (f"{len(chosen)} BS-estimate ETF candidate(s) tracked (awaiting live validation)"
                   if chosen else "no ETF candidate built from estimates"),
        "candidates": chosen, "rejected": [],
        "request_id": request.get("request_id"), "context": request.get("context"),
        "research_experiment": spec["experiment_id"],
        "pricing": "black_scholes_estimate",
        "shadow_performance": shadow.summary(),
        "disclaimer": "advisory SHADOW research; estimate-priced tracking, NOT actionable; no order placement",
    }


def finalize_payload(payload: dict, request: dict | None = None,
                     now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    spec = load_spec()
    request = request or load_request()
    if not request:
        return _no_trade(now, "ETF request missing")
    if payload.get("request_id") != request.get("request_id"):
        return _no_trade(now, "live payload request_id mismatch", request)
    request_ts = _parse_ts(request.get("generated_at"))
    if request_ts is None or request_ts.astimezone(NY).date() != now.astimezone(NY).date():
        return _no_trade(now, "ETF request is missing or not from today", request)
    if request.get("status") != "READY":
        return _no_trade(now, request.get("reason", "request not ready"), request)
    by_symbol = {row["symbol"]: row for row in request.get("eligible") or []}
    accepted: list[dict] = []
    rejected: list[dict] = []
    for market in payload.get("markets") or []:
        symbol = str(market.get("symbol", "")).upper()
        row = by_symbol.get(symbol)
        if row is None:
            rejected.append({"symbol": symbol, "reason": "not in frozen eligible request"})
            continue
        candidate, reason = _candidate(market, row, spec, now)
        if candidate is None:
            rejected.append({"symbol": symbol, "reason": reason})
        else:
            accepted.append(candidate)
    chosen = _diversified(accepted, spec)
    ticket = {
        "date": now.astimezone(NY).date().isoformat(), "ts": now.isoformat(),
        "underlying": "LIQUID_ETF_UNIVERSE", "status": "SHADOW",
        "action": "SELL_PREMIUM" if chosen else "NO_TRADE",
        "reason": (f"{len(chosen)} liquid ETF candidate(s) cleared P5"
                   if chosen else "no ETF candidate cleared live liquidity/IV validation"),
        "candidates": chosen, "rejected": rejected,
        "request_id": request.get("request_id"), "context": request.get("context"),
        "research_experiment": spec["experiment_id"],
        "shadow_performance": shadow.summary(),
        "disclaimer": "advisory SHADOW research; no order placement; human review required",
    }
    return ticket


def _no_trade(now: datetime, reason: str, request: dict | None = None) -> dict:
    return {"date": now.astimezone(NY).date().isoformat(), "ts": now.isoformat(),
            "underlying": "LIQUID_ETF_UNIVERSE", "status": "SHADOW",
            "action": "NO_TRADE", "reason": reason, "candidates": [],
            "request_id": (request or {}).get("request_id"),
            "context": (request or {}).get("context"),
            "shadow_performance": shadow.summary(),
            "research_experiment": config.ETF_EXPERIMENT_ID,
            "disclaimer": "advisory SHADOW research; no order placement; human review required"}


def publish(ticket: dict) -> str:
    """Publish the CANONICAL (live/veto) ETF result. A live-quoted ticket also
    supersedes any estimate-only opens the tracker holds for the same day."""
    shadow.assign_candidate_ids(ticket)
    _atomic_json(config.ETF_OPTIONS_FLAG, ticket)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    history = config.JOURNAL_DIR / f"etf-options-{month}.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ticket) + "\n")
    try:
        shadow.record_ticket(ticket)
        shadow.supersede_estimate_openings(ticket)
        shadow.retract_same_day_on_veto(ticket)
    except Exception:  # noqa: BLE001
        pass
    return str(config.ETF_OPTIONS_FLAG)


def publish_estimate(ticket: dict) -> str:
    """Publish + track the BS-estimate ETF candidates to a SEPARATE flag, so tracking
    accumulates without a live session while the canonical flag stays owned by the live
    run (and the watchdog keeps detecting a missed live validation)."""
    shadow.assign_candidate_ids(ticket)
    _atomic_json(config.ETF_ESTIMATE_FLAG, ticket)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    history = config.JOURNAL_DIR / f"etf-estimate-{month}.jsonl"
    with history.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ticket) + "\n")
    try:
        shadow.record_ticket(ticket)
        shadow.retract_same_day_on_veto(ticket)
    except Exception:  # noqa: BLE001
        pass
    return str(config.ETF_ESTIMATE_FLAG)


def load_flag() -> dict | None:
    return _read_json(config.ETF_OPTIONS_FLAG)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", action="store_true", help="build/write the P5 request")
    parser.add_argument("--finalize", type=Path, help="validate a Codex/Robinhood payload JSON")
    parser.add_argument("--finalize-estimate", action="store_true",
                        help="build + track BS-estimate candidates for today's request (no live session)")
    parser.add_argument("--live-market", type=Path,
                        help="secret-free live Robinhood equity-quote snapshot {symbol: price}; "
                             "uses live spot as the price anchor")
    parser.add_argument("--telegram", action="store_true", help="send finalized SHADOW alert")
    args = parser.parse_args()
    live_quotes = _read_json(args.live_market) if args.live_market else None
    if args.finalize_estimate:
        result = finalize_estimate()
        path = publish_estimate(result)
        print(f"estimate {result['action']}: {result['reason']}")
        print(f"estimate flag -> {path}")
        return
    if args.finalize:
        payload = _read_json(args.finalize)
        result = finalize_payload(payload or {})
        path = publish(result)
        print(json.dumps(result, indent=2))
        print(f"flag -> {path}")
        if args.telegram:
            from . import telegram_notify
            ok, err = telegram_notify.send_message(telegram_notify.format_alert(result))
            print(f"telegram: {'sent' if ok else 'skipped - ' + str(err)}")
        return
    request = build_request(live_quotes=live_quotes)
    path = write_request(request)
    print(json.dumps(request, indent=2))
    print(f"request -> {path}")
    if args.telegram and request.get("status") != "READY":
        result = _no_trade(datetime.now(timezone.utc), request.get("reason", "request not ready"), request)
        flag_path = publish(result)
        from . import telegram_notify
        ok, err = telegram_notify.send_message(telegram_notify.format_alert(result))
        print(f"flag -> {flag_path}")
        print(f"telegram: {'sent' if ok else 'skipped - ' + str(err)}")


if __name__ == "__main__":
    main()
