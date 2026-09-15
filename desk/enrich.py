"""P3 — Robinhood real-chain enrichment (READ-ONLY, Codex-session driven).

The MCP option tools only exist inside a Codex session, so this module does NOT call
them. It (1) turns the published candidate flag into an exact, minimal Robinhood lookup
plan, and (2) merges the real quotes a Codex session fetched back into the ticket,
recomputing credit/debit/max-risk from live mid prices. The Codex "enrich options desk"
flow (see CLAUDE.md) runs the reads and calls `write_enrichment`.

NEVER place or cancel anything. Robinhood is read-only here; the order-guard hook is the
real gate and the human is the only one who ever trades.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from . import config, strategies, ticket

CONTRACT = 100


def quote_key(option_type: str, strike, expiry: str) -> str:
    value = float(strike)
    strike_text = str(int(value)) if value.is_integer() else str(value).rstrip("0").rstrip(".")
    return f"{option_type.lower()}:{strike_text}:{expiry}"


def build_lookup_plan(flag: dict) -> dict:
    """Per-candidate Robinhood read plan. A Codex session resolves it as:
      get_option_chains(underlying_symbol) ->
      get_option_instruments(chain_symbol, expiration_dates, strike_price, type) ->
      get_option_quotes(instrument_ids).  All READ-ONLY."""
    underlying = flag.get("underlying", "SPY")
    legs: list[dict] = []
    for ci, c in enumerate(flag.get("candidates") or []):
        for leg in c.get("legs", []):
            legs.append({"candidate": ci, "strategy": c.get("strategy"),
                         "expiration": c.get("expiry"),
                         "strike": leg["strike"], "type": leg["type"],
                         "side": leg["side"]})
    return {"underlying": underlying, "read_only": True, "legs": legs,
            "steps": ["get_option_chains(underlying_symbol=%s)" % underlying,
                      "get_option_instruments(chain_symbol, expiration_dates, strike_price, type) per leg",
                      "get_option_quotes(instrument_ids=[...])"]}


def write_lookup_request(flag: dict) -> str:
    """Publish a secret-free read request for a live Codex/Robinhood session."""
    request = build_lookup_plan(flag)
    request.update({"requested_at": datetime.now(timezone.utc).isoformat(),
                    "ticket_ts": flag.get("ts"),
                    "candidate_ids": [c.get("candidate_id") for c in flag.get("candidates") or []]})
    config.FLAGS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.ROBINHOOD_REQUEST.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(request, indent=2), encoding="utf-8")
    tmp.replace(config.ROBINHOOD_REQUEST)
    return str(config.ROBINHOOD_REQUEST)


def _mid(q: dict) -> float | None:
    """Mid from a Robinhood option quote dict (bid_price/ask_price or mark_price)."""
    try:
        b, a = q.get("bid_price"), q.get("ask_price")
        if b is not None and a is not None:
            bid, ask = float(b), float(a)
            if 0 <= bid <= ask and ask > 0:
                return (bid + ask) / 2.0
        if q.get("mark_price") is not None:
            return float(q["mark_price"])
        if q.get("last_trade_price") is not None:
            return float(q["last_trade_price"])
    except (TypeError, ValueError):
        return None
    return None


def _fresh(q: dict, now: datetime | None = None) -> bool:
    """Reject explicitly timestamped stale quotes; tolerate fixtures with no timestamp."""
    raw = q.get("updated_at") or q.get("quote_time")
    if not raw:
        return True
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        age_minutes = ((now or datetime.now(timezone.utc)) - stamp).total_seconds() / 60.0
        return -1 <= age_minutes <= config.ROBINHOOD_QUOTE_MAX_AGE_MINUTES
    except (TypeError, ValueError):
        return False


def _signed_credit(legs: list[dict]) -> float:
    """Net premium per share: sold legs add, bought legs subtract (mid prices)."""
    net = 0.0
    for leg in legs:
        m = leg.get("mid")
        if m is None:
            continue
        net += m if leg.get("side") == "sell" else -m
    return net


def _recompute(candidate: dict, net: float) -> bool:
    """Apply live-mid economics and re-check strategy invariants."""
    strategy = candidate.get("strategy")
    legs = candidate.get("legs") or []
    if strategy == "long_vol_straddle":
        if net >= 0:
            return False
        debit = -net * CONTRACT
        strike = float(legs[0]["strike"])
        candidate.pop("credit_usd", None)
        candidate["debit_usd"] = round(debit, 0)
        candidate["max_risk_usd"] = round(debit, 0)
        candidate["breakevens"] = f"{round(strike + net, 2)} / {round(strike - net, 2)}"
        return True
    if net <= 0:
        return False
    credit = net * CONTRACT
    candidate.pop("debit_usd", None)
    candidate["credit_usd"] = round(credit, 0)
    if strategy == "short_put_csp":
        strike = float(legs[0]["strike"])
        candidate["max_risk_usd"] = round(strike * CONTRACT - credit, 0)
        candidate["breakevens"] = f"{round(strike - net, 2)}"
    elif strategy == "short_put_spread":
        short_put = next(leg for leg in legs if leg["side"] == "sell" and leg["type"] == "put")
        long_put = next(leg for leg in legs if leg["side"] == "buy" and leg["type"] == "put")
        width = float(short_put["strike"]) - float(long_put["strike"])
        if credit >= width * CONTRACT:
            return False
        candidate["max_risk_usd"] = round(width * CONTRACT - credit, 0)
        candidate["breakevens"] = f"{round(float(short_put['strike']) - net, 2)}"
    elif strategy == "jade_lizard":
        short_put = next(leg for leg in legs if leg["side"] == "sell" and leg["type"] == "put")
        short_call = next(leg for leg in legs if leg["side"] == "sell" and leg["type"] == "call")
        long_call = next(leg for leg in legs if leg["side"] == "buy" and leg["type"] == "call")
        width = float(long_call["strike"]) - float(short_call["strike"])
        if credit < width * CONTRACT:  # hard no-upside-risk invariant
            return False
        candidate["max_risk_usd"] = round(float(short_put["strike"]) * CONTRACT - credit, 0)
        candidate["breakevens"] = (f"down {round(float(short_put['strike']) - net, 2)} | "
                                     "up none (net credit >= width)")
    return True


def write_enrichment(flag: dict, quotes_by_key: dict) -> dict:
    """Merge live mids into each candidate and recompute economics.
    `quotes_by_key` maps "TYPE:STRIKE:EXPIRY" (e.g. "put:731:2026-09-18") -> quote dict.
    Returns the enriched ticket (also republished to the flag + history)."""
    kept: list[dict] = []
    dropped: list[dict] = []
    quote_times: list[str] = []
    for c in flag.get("candidates") or []:
        got_all = True
        for leg in c.get("legs", []):
            key = quote_key(leg["type"], leg["strike"], c.get("expiry"))
            q = quotes_by_key.get(key)
            m = _mid(q) if q and _fresh(q) else None
            leg["mid"] = round(m, 3) if m is not None else None
            if q:
                for source, dest in (("bid_price", "bid"), ("ask_price", "ask"),
                                     ("open_interest", "open_interest"), ("volume", "volume"),
                                     ("instrument_id", "instrument_id")):
                    if q.get(source) is not None:
                        leg[dest] = q[source]
                qts = q.get("updated_at") or q.get("quote_time")
                if qts:
                    leg["quote_ts"] = qts
                    quote_times.append(str(qts))
            if m is None:
                got_all = False
        if not got_all or not c.get("legs"):
            c["enriched"] = False
            c["source"] = "black_scholes_estimate"
            kept.append(c)
            continue
        net = _signed_credit(c["legs"])
        if not _recompute(c, net):
            dropped.append({"candidate_id": c.get("candidate_id"),
                            "strategy": c.get("strategy"),
                            "reason": "live mids violate structure economics/invariant"})
            continue
        c["enriched"] = True
        c["source"] = "robinhood_mid"
        kept.append(c)
    flag["candidates"] = strategies.rank_candidates(kept)
    flag["enrichment"] = {"source": "robinhood_read_only",
                          "as_of": max(quote_times) if quote_times else datetime.now(timezone.utc).isoformat(),
                          "dropped": dropped,
                          "note": "live mids; still SHADOW / not gate-cleared; human places order"}
    ticket.publish(flag)
    return flag


def main() -> None:
    """CLI: print the read plan for the current flag (Codex session executes the reads)."""
    import json
    f = ticket.load_flag()
    if not f:
        print("no published flag")
        return
    print(json.dumps(build_lookup_plan(f), indent=2))


if __name__ == "__main__":
    main()
