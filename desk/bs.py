"""Black-Scholes helpers — ESTIMATES only, not executable quotes.

Lifted from qlib_lab/qlib_lab/vol_desk.py (put/delta/straddle) and extended with the
call side for jade-lizard construction. Used to size candidate structures and their
risk/breakevens for the paper alert; real fills come from the human (or the P3
read-only Robinhood enrichment). sigma is the underlying IV estimate (VIX/100 for SPY).
"""
from __future__ import annotations

import math

from .config import RISK_FREE


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _d1(spot: float, strike: float, sigma: float, t: float, r: float) -> float:
    return (math.log(spot / strike) + (r + sigma ** 2 / 2) * t) / (sigma * math.sqrt(t))


def bs_put(spot: float, strike: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    if sigma <= 0 or t <= 0:
        return max(strike - spot, 0.0)
    d1 = _d1(spot, strike, sigma, t, r)
    d2 = d1 - sigma * math.sqrt(t)
    return strike * math.exp(-r * t) * ncdf(-d2) - spot * ncdf(-d1)


def bs_call(spot: float, strike: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    if sigma <= 0 or t <= 0:
        return max(spot - strike, 0.0)
    d1 = _d1(spot, strike, sigma, t, r)
    d2 = d1 - sigma * math.sqrt(t)
    return spot * ncdf(d1) - strike * math.exp(-r * t) * ncdf(d2)


def prob_above(spot: float, level: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    """Risk-neutral P(S_T > level) = N(d2). Used for probability-of-profit at expiry."""
    if level <= 0:
        return 1.0
    if sigma <= 0 or t <= 0:
        return 1.0 if spot > level else 0.0
    d2 = _d1(spot, level, sigma, t, r) - sigma * math.sqrt(t)
    return ncdf(d2)


def prob_below(spot: float, level: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    """Risk-neutral P(S_T < level) = 1 - N(d2)."""
    return 1.0 - prob_above(spot, level, sigma, t, r)


def pop_at_expiry(spot: float, sigma: float, t: float, structure: str,
                  put_breakeven: float | None = None,
                  call_breakeven: float | None = None) -> float:
    """Tastytrade-style probability of profit AT EXPIRY: risk-neutral BS probability the
    underlying finishes on the profitable side of the structure's breakeven(s).

      put_spread : P(S_T > put_breakeven)
      call_spread: P(S_T < call_breakeven)
      iron_condor: P(put_breakeven < S_T < call_breakeven)

    Closing at a 50% target realizes profit MORE often than this, so it is conservative.
    """
    if structure == "etf_iron_condor_v1":
        lo = prob_above(spot, put_breakeven, sigma, t) if put_breakeven else 0.0
        hi_below = prob_below(spot, call_breakeven, sigma, t) if call_breakeven else 1.0
        return max(0.0, round(lo + hi_below - 1.0, 6))     # P(lo<S<hi) = P(S>lo)+P(S<hi)-1
    if structure == "etf_short_call_spread_v1":
        return round(prob_below(spot, call_breakeven, sigma, t), 6)
    return round(prob_above(spot, put_breakeven, sigma, t), 6)


def put_delta(spot: float, strike: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    return ncdf(_d1(spot, strike, sigma, t, r)) - 1.0     # in (-1, 0)


def call_delta(spot: float, strike: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    return ncdf(_d1(spot, strike, sigma, t, r))           # in (0, 1)


def bs_straddle(spot: float, strike: float, sigma: float, t: float, r: float = RISK_FREE) -> float:
    put = bs_put(spot, strike, sigma, t, r)
    call = put + spot - strike * math.exp(-r * t)         # put-call parity
    return put + call


def strike_for_put_delta(spot: float, sigma: float, t: float, target: float) -> float:
    """OTM-put strike whose delta ~= target (target negative, e.g. -0.30)."""
    lo, hi = spot * 0.5, spot * 1.1
    for _ in range(60):
        mid = (lo + hi) / 2
        if put_delta(spot, mid, sigma, t) < target:
            hi = mid
        else:
            lo = mid
    return round((lo + hi) / 2)


def strike_for_call_delta(spot: float, sigma: float, t: float, target: float) -> float:
    """OTM-call strike whose delta ~= target (target positive, e.g. 0.20)."""
    lo, hi = spot * 0.9, spot * 1.6
    for _ in range(60):
        mid = (lo + hi) / 2
        if call_delta(spot, mid, sigma, t) > target:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2)
