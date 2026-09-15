"""P3 enrichment: lookup-plan shape + credit/debit recompute from live mids."""
import json

from desk import enrich


def _flag():
    return {"underlying": "SPY", "candidates": [
        {"strategy": "short_put_spread", "expiry": "2026-09-18",
         "credit_usd": 149.0, "max_risk_usd": 351.0,
         "legs": [{"side": "sell", "type": "put", "strike": 731},
                  {"side": "buy", "type": "put", "strike": 726}]},
        {"strategy": "long_vol_straddle", "expiry": "2026-09-18", "debit_usd": 5000.0,
         "legs": [{"side": "buy", "type": "call", "strike": 750},
                  {"side": "buy", "type": "put", "strike": 750}]},
    ]}


def test_lookup_plan_is_read_only_and_covers_all_legs():
    plan = enrich.build_lookup_plan(_flag())
    assert plan["read_only"] is True
    assert len(plan["legs"]) == 4
    assert all("strike" in leg and "type" in leg for leg in plan["legs"])
    assert enrich.quote_key("PUT", 731.0, "2026-09-18") == "put:731:2026-09-18"


def test_enrichment_recomputes_credit_from_mids(tmp_path, monkeypatch):
    # keep publish from writing into the real journal
    monkeypatch.setattr(enrich.ticket, "publish", lambda t: "ok")
    q = {
        "put:731:2026-09-18": {"bid_price": "3.00", "ask_price": "3.20"},   # sell +3.10
        "put:726:2026-09-18": {"bid_price": "1.00", "ask_price": "1.20"},   # buy  -1.10
        "call:750:2026-09-18": {"bid_price": "8.00", "ask_price": "8.40"},  # buy  -8.20
        "put:750:2026-09-18": {"bid_price": "7.60", "ask_price": "8.00"},   # buy  -7.80
    }
    out = enrich.write_enrichment(_flag(), q)
    spread, straddle = out["candidates"]
    assert spread["enriched"] is True
    assert spread["credit_usd"] == round((3.10 - 1.10) * 100, 0)     # 200
    assert straddle["enriched"] is True
    assert straddle["debit_usd"] == round((8.20 + 7.80) * 100, 0)    # 1600
    assert "credit_usd" not in straddle


def test_missing_quote_marks_not_enriched(monkeypatch):
    monkeypatch.setattr(enrich.ticket, "publish", lambda t: "ok")
    out = enrich.write_enrichment(_flag(), {})   # no quotes
    assert all(c["enriched"] is False for c in out["candidates"])


def test_stale_timestamped_quote_stays_fallback(monkeypatch):
    monkeypatch.setattr(enrich.ticket, "publish", lambda t: "ok")
    q = {"put:731:2026-09-18": {"bid_price": "3", "ask_price": "3.2",
                                      "updated_at": "2020-01-01T10:00:00Z"}}
    out = enrich.write_enrichment(_flag(), q)
    assert all(c["enriched"] is False for c in out["candidates"])


def test_live_spread_recomputes_risk_and_breakeven(monkeypatch):
    monkeypatch.setattr(enrich.ticket, "publish", lambda t: "ok")
    q = {
        "put:731:2026-09-18": {"bid_price": "3.00", "ask_price": "3.20"},
        "put:726:2026-09-18": {"bid_price": "1.00", "ask_price": "1.20"},
    }
    out = enrich.write_enrichment(_flag(), q)
    spread = next(c for c in out["candidates"] if c["strategy"] == "short_put_spread")
    assert spread["max_risk_usd"] == 300.0
    assert spread["breakevens"] == "729.0"


def test_lookup_request_is_secret_free(tmp_path, monkeypatch):
    target = tmp_path / "request.json"
    monkeypatch.setattr(enrich.config, "ROBINHOOD_REQUEST", target)
    monkeypatch.setattr(enrich.config, "FLAGS_DIR", tmp_path)
    enrich.write_lookup_request(_flag())
    request = json.loads(target.read_text(encoding="utf-8"))
    assert request["read_only"] is True and len(request["legs"]) == 4
    assert "account" not in json.dumps(request).lower()
