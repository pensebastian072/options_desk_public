"""Strategy builders + selection matrix -> ranked option candidates (ESTIMATES).

Five families off the qlib vol_desk signal:
  short_put (CSP), short_put_spread, jade_lizard, long_vol (straddle), vix_iv_pairs.

The selection matrix mirrors the pre-registered qlib_lab vol_desk logic (no per-run
tuning) and carries the magnitude veto (do not sell premium in a big-move regime).
Every candidate is priced with Black-Scholes estimates and tagged gate="not_cleared"
(SHADOW): advisory only, the human places any order. All economics are per 1 contract.

Jade-lizard invariant: net credit >= short-call-spread width => no upside risk. A
construction that cannot satisfy it is dropped, never emitted.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import bs, config, gate_status

CONTRACT = 100  # option multiplier


# ── expiry selection: nearest monthly 3rd-Friday within [DTE_MIN, DTE_MAX] ──

def _third_friday(year: int, month: int) -> date:
    d = date(year, month, 1)
    # weekday(): Mon=0..Fri=4; first Friday then +14 days
    first_friday = d + timedelta(days=(4 - d.weekday()) % 7)
    return first_friday + timedelta(days=14)


def target_expiry(now: datetime | None = None) -> tuple[date, int]:
    """Pick the monthly (3rd-Friday) expiry whose DTE is closest to DTE_TARGET and
    inside [DTE_MIN, DTE_MAX]. Fallback: today+DTE_TARGET rolled to Friday."""
    today = (now or datetime.now(timezone.utc)).date()
    cands: list[tuple[int, date]] = []
    for k in range(0, 4):
        m = today.month + k
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        exp = _third_friday(y, m)
        dte = (exp - today).days
        if config.DTE_MIN <= dte <= config.DTE_MAX:
            cands.append((abs(dte - config.DTE_TARGET), exp))
    if cands:
        cands.sort()
        exp = cands[0][1]
        return exp, (exp - today).days
    exp = today + timedelta(days=config.DTE_TARGET)
    exp = exp + timedelta(days=(4 - exp.weekday()) % 7)   # roll to Friday
    return exp, (exp - today).days


def _t_years(dte: int) -> float:
    return max(dte, 1) / 365.0


# ── individual builders (return a candidate dict, or None if infeasible) ──

def build_short_put(spot, sigma, dte, expiry) -> dict:
    t = _t_years(dte)
    k = bs.strike_for_put_delta(spot, sigma, t, config.SHORT_PUT_DELTA)
    prem = bs.bs_put(spot, k, sigma, t)
    credit = round(prem * CONTRACT, 0)
    # cash-secured worst case (underlying -> 0): (strike - credit_per_share) * 100
    max_risk = round((k - prem) * CONTRACT, 0)
    return {
        "strategy": "short_put_csp", "dte": dte, "expiry": str(expiry),
        "legs": [{"side": "sell", "type": "put", "strike": k}],
        "legs_short": f"-{k}P",
        "credit_usd": credit, "max_risk_usd": max_risk,
        "breakevens": f"{round(k - prem, 2)}",
        "pop": round(1 - abs(config.SHORT_PUT_DELTA), 2),
        "rationale": "rich VRP + calm: collect premium, cash-secured",
        "gate": "not_cleared",
    }


def build_short_put_spread(spot, sigma, dte, expiry) -> dict:
    t = _t_years(dte)
    short_k = bs.strike_for_put_delta(spot, sigma, t, config.SHORT_PUT_DELTA)
    long_k = short_k - config.PUT_SPREAD_WIDTH
    prem = bs.bs_put(spot, short_k, sigma, t) - bs.bs_put(spot, long_k, sigma, t)
    credit = round(prem * CONTRACT, 0)
    max_risk = round((config.PUT_SPREAD_WIDTH - prem) * CONTRACT, 0)
    return {
        "strategy": "short_put_spread", "dte": dte, "expiry": str(expiry),
        "legs": [{"side": "sell", "type": "put", "strike": short_k},
                 {"side": "buy", "type": "put", "strike": long_k}],
        "legs_short": f"-{short_k}P/+{long_k}P",
        "credit_usd": credit, "max_risk_usd": max_risk,
        "breakevens": f"{round(short_k - prem, 2)}",
        "pop": round(1 - abs(config.SHORT_PUT_DELTA), 2),
        "rationale": "rich VRP + calm: defined-risk put credit spread",
        "gate": "not_cleared",
    }


def build_jade_lizard(spot, sigma, dte, expiry) -> dict | None:
    """Short put + short call spread; enforce net credit >= call-spread width so
    there is NO upside risk. Returns None if that invariant cannot be met."""
    t = _t_years(dte)
    put_k = bs.strike_for_put_delta(spot, sigma, t, config.SHORT_PUT_DELTA)
    sc_k = bs.strike_for_call_delta(spot, sigma, t, config.SHORT_CALL_DELTA)
    lc_k = sc_k + config.CALL_SPREAD_WIDTH
    put_prem = bs.bs_put(spot, put_k, sigma, t)
    call_spread_prem = bs.bs_call(spot, sc_k, sigma, t) - bs.bs_call(spot, lc_k, sigma, t)
    net = put_prem + call_spread_prem
    if net < config.CALL_SPREAD_WIDTH:
        return None   # would carry upside risk — drop, never emit
    credit = round(net * CONTRACT, 0)
    max_risk_down = round((put_k - net) * CONTRACT, 0)
    return {
        "strategy": "jade_lizard", "dte": dte, "expiry": str(expiry),
        "legs": [{"side": "sell", "type": "put", "strike": put_k},
                 {"side": "sell", "type": "call", "strike": sc_k},
                 {"side": "buy", "type": "call", "strike": lc_k}],
        "legs_short": f"-{put_k}P -{sc_k}C/+{lc_k}C",
        "credit_usd": credit, "max_risk_usd": max_risk_down,
        "breakevens": f"down {round(put_k - net, 2)} | up none (net credit >= width)",
        "pop": round(max(0.0, 1 - abs(config.SHORT_PUT_DELTA) - config.SHORT_CALL_DELTA), 2),
        "rationale": "rich IV, neutral-bullish: no upside risk (credit >= call width)",
        "gate": "not_cleared",
    }


def build_long_vol(spot, sigma, dte, expiry, exp_move_usd=None) -> dict:
    t = _t_years(dte)
    k = round(spot)
    prem = bs.bs_straddle(spot, k, sigma, t)
    debit = round(prem * CONTRACT, 0)
    return {
        "strategy": "long_vol_straddle", "dte": dte, "expiry": str(expiry),
        "legs": [{"side": "buy", "type": "call", "strike": k},
                 {"side": "buy", "type": "put", "strike": k}],
        "legs_short": f"+{k}C +{k}P",
        "debit_usd": debit, "max_risk_usd": debit,
        "breakevens": f"{round(k - prem, 2)} / {round(k + prem, 2)}",
        "pop": None,
        "rationale": ("eruption-from-calm + vol not rich: own convexity"
                      + (f"; ~1d move ${exp_move_usd}" if exp_move_usd else "")),
        "gate": "not_cleared",
    }


def build_vix_iv_pairs(vol_surface, vrp_pct) -> dict | None:
    """Term-structure regime tilt (a selector/note, not a priced option chain).
    Contango + rich VRP => short-vol tilt; backwardation/stress => long-vol tilt."""
    if not vol_surface or vol_surface.get("term_ratio") is None:
        return None
    ratio = vol_surface["term_ratio"]          # VIX9D / VIX3M
    backwardation = ratio >= config.TERM_BACKWARDATION
    if backwardation:
        tilt, note = "long_vol", "VIX term backwardation (near > far): stress — favor owning vol"
    else:
        rich = vrp_pct is not None and vrp_pct >= config.VRP_SELL_PCT
        tilt = "short_vol" if rich else "neutral"
        note = (f"VIX term contango (ratio {ratio:.2f})"
                + (" + VRP rich: favor selling premium" if rich else ": no premium edge"))
    return {
        "strategy": "vix_iv_pairs", "dte": None, "expiry": None,
        "legs": [], "legs_short": f"tilt={tilt}",
        "credit_usd": None, "debit_usd": None, "max_risk_usd": None,
        "breakevens": "-", "pop": None,
        "rationale": note, "tilt": tilt, "term_ratio": round(ratio, 3),
        "gate": "not_cleared",
    }


# ── selection matrix ─────────────────────────────────────────────────

def rank_candidates(cands: list[dict]) -> list[dict]:
    """Premium sellers by return-on-risk (credit/max_risk) desc; others appended."""
    def key(c):
        cr, mr = c.get("credit_usd"), c.get("max_risk_usd")
        return (cr / mr) if (cr and mr) else -1
    priced = [c for c in cands if c.get("credit_usd")]
    other = [c for c in cands if not c.get("credit_usd")]
    priced.sort(key=key, reverse=True)
    return (priced + other)[: config.MAX_CANDIDATES]


def select(signal: dict, now: datetime | None = None, apply_gate: bool = True,
           magnitude_blocks: bool = True, risk_cap: float | None = None) -> dict:
    """Build the SPY-lane ticket.

    Defaults reproduce the FROZEN pre-registered behavior (magnitude is a hard veto, no
    dollar cap) so the P4 gate backtest stays reproducible. The live run passes
    magnitude_blocks=False + risk_cap=$1000 for the v3 policy (magnitude advisory, capped).
    """
    now = now or datetime.now(timezone.utc)
    day = now.date().isoformat()
    ticket = {"date": day, "ts": now.isoformat(), "underlying": "SPY",
              "status": "SHADOW", "action": "NO_TRADE", "reason": None,
              "signal": None, "candidates": []}

    if not signal.get("ok"):
        ticket["reason"] = signal.get("reason", "signal not ok")
        return gate_status.apply_to_ticket(ticket) if apply_gate else ticket

    vrp = signal["vrp"]
    spot, sigma = float(vrp["spot"]), float(vrp["vix"]) / 100.0
    vrp_pct = vrp.get("vrp_pct")
    mag = signal.get("magnitude") or {}
    mag_pct = mag.get("magnitude_pct")
    surf = signal.get("vol_surface")
    shift = signal.get("shift") or {}
    erupting = bool(shift.get("eruption_predicted"))
    calm5 = bool(shift.get("calm_5d"))
    calm21 = bool(shift.get("calm_21d"))
    big_move = mag_pct is not None and mag_pct >= config.MAGNITUDE_HIGH_PCT

    expiry, dte = target_expiry(now)
    ticket["expiry"], ticket["dte"] = str(expiry), dte

    term_ratio = (surf or {}).get("term_ratio")
    ticket["signal"] = {"spot": round(spot, 2), "vix": round(sigma * 100, 2),
                        "vrp_pct": vrp_pct, "magnitude_pct": mag_pct,
                        "term_ratio": round(term_ratio, 3) if term_ratio is not None else None,
                        "eruption": erupting, "calm_5d": calm5, "calm_21d": calm21}

    pairs = build_vix_iv_pairs(surf, vrp_pct)
    cands: list[dict] = []

    if erupting and calm21 and (vrp_pct is None or vrp_pct < config.VRP_RICH_PCT):
        ticket["action"] = "LONG_VOL"
        ticket["reason"] = "eruption predicted from calm + vol not rich"
        cands.append(build_long_vol(spot, sigma, dte, expiry, mag.get("expected_move_usd")))
    elif erupting:
        ticket["reason"] = (f"eruption predicted but VRP pct "
                            f"{(vrp_pct or 0):.0%} >= {config.VRP_RICH_PCT:.0%} — vol too rich to buy")
    elif (not erupting) and magnitude_blocks and calm5 and \
            (vrp_pct is not None and vrp_pct >= config.VRP_SELL_PCT) and big_move:
        # FROZEN behavior (backtest): magnitude is a hard veto in a big-move regime.
        ticket["reason"] = (f"calm + VRP pct {vrp_pct:.0%} rich but magnitude pct "
                            f"{mag_pct:.0%} >= {config.MAGNITUDE_HIGH_PCT:.0%} "
                            f"(big-move regime) — do not sell premium")
    elif (not erupting) and (vrp_pct is not None and vrp_pct >= config.VRP_SELL_PCT) and \
            (magnitude_blocks is False or calm5):
        # v3 live policy: magnitude no longer blocks. Rich VRP + no eruption -> sell
        # premium; a big-move regime only advises smaller size. Calm is context.
        ticket["action"] = "SELL_PREMIUM"
        ticket["size_hint"] = "reduce_size" if big_move else "normal"
        ticket["reason"] = (f"no eruption + VRP pct {vrp_pct:.0%} rich (premium)"
                            + (f"; magnitude {mag_pct:.0%} high -> reduce size" if big_move else ""))
        cands.append(build_short_put(spot, sigma, dte, expiry))
        cands.append(build_short_put_spread(spot, sigma, dte, expiry))
        jl = build_jade_lizard(spot, sigma, dte, expiry)
        if jl:
            cands.append(jl)
    else:
        ticket["reason"] = (f"no edge: eruption={erupting} calm5d={calm5} "
                            f"vrp_pct={(f'{vrp_pct:.0%}' if vrp_pct is not None else 'na')}")

    # v3 live hard rail (risk_cap set): only structures within the per-trade cap survive
    # (drops cash-secured/naked puts ~strike*100 and any long-vol debit above the cap).
    # The backtest passes risk_cap=None so its frozen population is unchanged.
    if risk_cap is not None:
        n_before = len(cands)
        cands = [c for c in cands if (c.get("max_risk_usd") or 0) <= risk_cap]
        if n_before and not cands and ticket["action"] != "NO_TRADE":
            ticket["action"] = "NO_TRADE"
            ticket["reason"] = (f"{ticket['reason']} - but every structure exceeds the "
                                f"${risk_cap:.0f} per-trade cap")
    ticket["candidates"] = rank_candidates(cands)
    if pairs:
        ticket["pairs_tilt"] = pairs
    return gate_status.apply_to_ticket(ticket) if apply_gate else ticket
