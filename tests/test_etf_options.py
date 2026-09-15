"""P5 liquid ETF request/finalizer stays deterministic and fail-safe."""
from datetime import datetime, timezone

from desk import etf_options

NOW = datetime(2026, 7, 22, 15, 45, tzinfo=timezone.utc)


def _context(eruption=False, magnitude_pct=0.3, calm_5d=True):
    qlib_assets = {
        "QQQ": {"lean": 1, "conviction": 0.96, "force": "equities", "horizons": {}},
        "SLV": {"lean": 1, "conviction": 1.0, "force": "commodity", "horizons": {}},
    }
    return {
        "qlib": {"ok": True, "age_hours": 1.0,
                 "data": {"promoted": False, "gate": {}, "assets": qlib_assets}},
        "vol": {"ok": True, "shift": {"eruption_predicted": eruption, "calm_5d": calm_5d},
                "magnitude": {"magnitude_pct": magnitude_pct},
                "vrp": {"vrp_pct": 0.82}},
        "hq_macro": {"ok": True, "data": {"regime": {"label": "risk_on"}}},
        "macro_gpu": {"ok": False, "reason": "stale"},
    }


def _request():
    return {
        "request_id": "abc", "generated_at": NOW.isoformat(),
        "status": "READY", "reason": "ready",
        "eligible": [{"symbol": "QQQ", "qlib_asset": "QQQ", "bucket": "broad_equity",
                      "spread_width": 5.0, "qlib_lean": 1, "qlib_conviction": 0.96,
                      "rv20": 0.20, "reference_spot": 700, "data_through": "2026-07-21"}],
        "context": {},
    }


def _leg(strike, bid, ask, delta=None, iv=0.30, oi=1000, volume=100):
    return {"type": "put", "strike": strike, "bid_price": bid, "ask_price": ask,
            "mark_price": (bid + ask) / 2, "bid_size": 10, "ask_size": 10,
            "delta": delta, "implied_volatility": iv, "open_interest": oi,
            "volume": volume, "updated_at": NOW.isoformat(), "instrument_id": str(strike)}


def test_request_uses_frozen_qlib_intersection(monkeypatch):
    monkeypatch.setattr(etf_options, "load_context", lambda now: _context())
    monkeypatch.setattr(etf_options, "realized_vol_20",
                        lambda path, now: {"rv20": 0.2, "reference_spot": 100,
                                           "above_sma200": True, "sma200": 95.0, "mom126": 0.02,
                                           "data_through": "2026-07-21"})
    request = etf_options.build_request(NOW)
    assert request["status"] == "READY"
    assert [row["symbol"] for row in request["eligible"]] == ["SLV", "QQQ"]
    assert request["context"]["qlib"]["promoted"] is False


def test_request_global_eruption_is_hard_no_trade(monkeypatch):
    monkeypatch.setattr(etf_options, "load_context", lambda now: _context(eruption=True))
    request = etf_options.build_request(NOW)
    assert request["status"] == "NO_TRADE" and request["eligible"] == []
    assert "eruption veto" in request["reason"]


def test_high_magnitude_no_longer_vetoes(monkeypatch):
    # v3: today's real regime (mag 0.758, no eruption) must now be READY, not NO_TRADE
    monkeypatch.setattr(etf_options, "load_context",
                        lambda now: _context(magnitude_pct=0.758))
    monkeypatch.setattr(etf_options, "realized_vol_20",
                        lambda path, now: {"rv20": 0.2, "reference_spot": 100,
                                           "above_sma200": True, "sma200": 95.0, "mom126": 0.02,
                                           "data_through": "2026-07-21"})
    request = etf_options.build_request(NOW)
    assert request["status"] == "READY"
    assert request["context"]["advisory"]["size_hint"] == "reduce_size"   # advisory, not a block
    assert request["eligible"][0]["size_hint"] == "reduce_size"


def test_low_magnitude_is_normal_size(monkeypatch):
    monkeypatch.setattr(etf_options, "load_context",
                        lambda now: _context(magnitude_pct=0.30))
    monkeypatch.setattr(etf_options, "realized_vol_20",
                        lambda path, now: {"rv20": 0.2, "reference_spot": 100,
                                           "above_sma200": True, "sma200": 95.0, "mom126": 0.02,
                                           "data_through": "2026-07-21"})
    request = etf_options.build_request(NOW)
    assert request["status"] == "READY"
    assert request["context"]["advisory"]["size_hint"] == "normal"


def test_live_spot_overrides_reference_spot(monkeypatch):
    monkeypatch.setattr(etf_options, "load_context", lambda now: _context())
    monkeypatch.setattr(etf_options, "realized_vol_20",
                        lambda path, now: {"rv20": 0.2, "reference_spot": 100,
                                           "above_sma200": True, "sma200": 95.0, "mom126": 0.02,
                                           "data_through": "2026-07-21"})
    request = etf_options.build_request(NOW, live_quotes={"QQQ": 512.34, "SLV": 51.0})
    rows = {r["symbol"]: r for r in request["eligible"]}
    assert rows["QQQ"]["reference_spot"] == 512.34
    assert rows["QQQ"]["spot_source"] == "live"


def test_per_trade_cap_drops_oversized_candidate():
    from datetime import date
    spec = etf_options.load_spec()
    # a $50-wide 'put spread' with tiny credit -> ~ $5000 risk, over the $1000 cap
    market = {"symbol": "SPY", "expiry": "2026-09-18",
              "short_put": _leg(700, 6.0, 6.2, delta=-0.30),
              "long_put": _leg(650, 1.0, 1.1, delta=-0.05)}   # tight spread, passes liquidity
    row = {"symbol": "SPY", "qlib_asset": "SPY", "bucket": "broad_equity",
           "spread_width": 50.0, "structure": etf_options.PUT_SPREAD, "rv20": 0.16,
           "qlib_lean": 1, "qlib_conviction": 0.9}
    c, err = etf_options._candidate(market, row, spec, NOW)
    assert c is None and "per-trade cap" in err


def test_live_payload_builds_natural_price_defined_risk_candidate():
    payload = {"request_id": "abc", "markets": [{
        "symbol": "QQQ", "spot": 709, "expiry": "2026-09-18",
        "short_put": _leg(680, 2.00, 2.10, delta=-0.30),
        "long_put": _leg(675, 0.70, 0.80, delta=-0.20),
    }]}
    ticket = etf_options.finalize_payload(payload, _request(), NOW)
    assert ticket["action"] == "SELL_PREMIUM"
    candidate = ticket["candidates"][0]
    assert candidate["underlying"] == "QQQ"
    assert candidate["credit_usd"] == 120.0
    assert candidate["max_risk_usd"] == 380.0
    assert candidate["iv_rv_ratio"] == 1.5
    assert candidate["source"] == "robinhood_natural_bid_ask"


def test_wide_or_stale_leg_rejects_candidate():
    short = _leg(680, 1.00, 2.00, delta=-0.30)
    payload = {"request_id": "abc", "markets": [{
        "symbol": "QQQ", "expiry": "2026-09-18", "short_put": short,
        "long_put": _leg(675, 0.70, 0.80, delta=-0.20),
    }]}
    ticket = etf_options.finalize_payload(payload, _request(), NOW)
    assert ticket["action"] == "NO_TRADE" and not ticket["candidates"]
    assert "too wide" in ticket["rejected"][0]["reason"]


def test_payload_request_mismatch_fails_neutral():
    ticket = etf_options.finalize_payload({"request_id": "wrong", "markets": []},
                                          _request(), NOW)
    assert ticket["action"] == "NO_TRADE"
    assert "mismatch" in ticket["reason"]


def test_old_request_fails_neutral():
    request = _request()
    request["generated_at"] = "2026-07-21T15:45:00+00:00"
    ticket = etf_options.finalize_payload({"request_id": "abc", "markets": []}, request, NOW)
    assert ticket["action"] == "NO_TRADE" and "not from today" in ticket["reason"]


def test_diversification_caps_broad_equity_at_two():
    spec = etf_options.load_spec()
    rows = []
    for i, symbol in enumerate(("SPY", "QQQ", "IWM")):
        rows.append({"underlying": symbol, "bucket": "broad_equity",
                     "qlib_conviction": 1 - i / 10, "return_on_risk": 0.2,
                     "max_leg_relative_spread": 0.02})
    assert len(etf_options._diversified(rows, spec)) == 2
