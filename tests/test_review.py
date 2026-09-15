"""P13: after-close review request/finalize + progress formatter, fail-safe."""
from datetime import datetime, timezone

from desk import review, telegram_notify

NOW = datetime(2026, 7, 24, 20, 30, tzinfo=timezone.utc)


def test_build_request_is_read_only_and_lists_symbols(monkeypatch):
    monkeypatch.setattr(review, "held_symbols", lambda: ["SPY", "XLE"])
    monkeypatch.setattr(review, "qlib_watch", lambda limit=8: [{"symbol": "QQQ", "lean": 1, "conviction": 0.9}])
    req = review.build_review_request(NOW)
    assert req["read_only"] is True
    assert set(req["symbols"]) == {"SPY", "XLE", "QQQ"}
    assert "account" not in __import__("json").dumps(req).lower()


def test_finalize_review_computes_day_change(monkeypatch):
    monkeypatch.setattr(review.shadow, "summary", lambda: {"overall": {"n": 0}})
    monkeypatch.setattr(review, "qlib_watch", lambda limit=8: [])
    payload = {"market": {"SPY": {"close": 561.0, "prior_close": 555.0, "rsi": 58.0}}}
    r = review.finalize_review(payload, NOW)
    row = r["closes"][0]
    assert row["symbol"] == "SPY"
    assert row["day_change_pct"] == round((561/555 - 1) * 100, 2)
    assert r["source"] == "robinhood_read_only"


def test_local_review_never_raises_without_rh(monkeypatch):
    monkeypatch.setattr(review, "held_symbols", lambda: [])
    monkeypatch.setattr(review, "qlib_watch", lambda limit=8: [])
    monkeypatch.setattr(review.shadow, "summary", lambda: {"overall": {"n": 0}})
    r = review.local_review(NOW)
    assert r["status"] == "SHADOW" and r["source"] == "local_qlib_close"


def test_format_review_renders():
    r = {"date": "2026-07-24",
         "closes": [{"symbol": "SPY", "close": 561.0, "day_change_pct": 1.1, "rsi": 58.0}],
         "shadow_performance": {"overall": {"n": 3, "wins": 2, "hit_rate": 0.67,
                                            "total_pnl_usd": 120, "profit_factor": 1.8},
                                "promotion_progress": {"independent_entry_dates": 5,
                                                       "pbo_floor_trades": 40}},
         "tomorrow_watch": [{"symbol": "QQQ", "lean": 1}, {"symbol": "XLE", "lean": -1}]}
    text = telegram_notify.format_review(r)
    assert "AFTER-CLOSE REVIEW" in text
    assert "SPY" in text and "QQQ(+1)" in text and "XLE(-1)" in text


def test_format_progress_open_and_empty():
    filled = telegram_notify.format_progress(
        {"overall": {"n": 2, "wins": 1, "hit_rate": 0.5, "total_pnl_usd": 40, "profit_factor": 1.2},
         "open": {"n": 3, "marked": 2, "unrealized_pnl_usd": 55}}, "2026-07-24")
    assert "RE-CHECK" in filled and "open 3" in filled
    empty = telegram_notify.format_progress({"overall": {"n": 0}, "open": {"n": 0}}, "2026-07-24")
    assert "no open SHADOW positions" in empty
