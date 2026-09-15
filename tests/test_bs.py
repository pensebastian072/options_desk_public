"""Black-Scholes helper sanity + put/call parity + delta-solver accuracy."""
import math

from desk import bs
from desk.config import RISK_FREE

T = 45 / 365
S = 750.0
SIG = 0.16


def test_put_and_call_positive_and_parity():
    k = 750.0
    p = bs.bs_put(S, k, SIG, T)
    c = bs.bs_call(S, k, SIG, T)
    assert p > 0 and c > 0
    # put-call parity: C - P == S - K*e^{-rT}
    assert abs((c - p) - (S - k * math.exp(-RISK_FREE * T))) < 1e-6


def test_deltas_in_range_and_signed():
    assert -1 < bs.put_delta(S, 720, SIG, T) < 0
    assert 0 < bs.call_delta(S, 780, SIG, T) < 1


def test_straddle_above_each_leg():
    s = bs.bs_straddle(S, S, SIG, T)
    assert s > bs.bs_put(S, S, SIG, T)
    assert s > bs.bs_call(S, S, SIG, T)


def test_strike_for_put_delta_hits_target():
    k = bs.strike_for_put_delta(S, SIG, T, -0.30)
    assert k < S                                  # OTM put
    assert abs(bs.put_delta(S, k, SIG, T) - (-0.30)) < 0.03


def test_strike_for_call_delta_hits_target():
    k = bs.strike_for_call_delta(S, SIG, T, 0.20)
    assert k > S                                  # OTM call
    assert abs(bs.call_delta(S, k, SIG, T) - 0.20) < 0.03
