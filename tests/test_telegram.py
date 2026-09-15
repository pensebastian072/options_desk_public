"""Telegram alert labels candidate cap, pricing source, and SHADOW results."""
from desk import telegram_notify


def test_alert_shows_top_cap_live_source_and_hit_rate():
    ticket = {
        "date": "2026-07-22", "underlying": "SPY", "candidates": [{
            "strategy": "short_put_spread", "dte": 45, "legs_short": "-100P/+95P",
            "gate": "not_cleared", "credit_usd": 150, "max_risk_usd": 350,
            "pop": 0.7, "breakevens": "98.5", "rationale": "test", "enriched": True,
        }],
        "shadow_performance": {"overall": {
            "n": 4, "wins": 3, "hit_rate": 0.75, "total_pnl_usd": 250,
            "profit_factor": 1.5,
        }},
    }
    alert = telegram_notify.format_alert(ticket)
    assert "TOP 1 ELIGIBLE (cap 5; never forced)" in alert
    assert "3/4 hits (75%)" in alert
    assert "Robinhood read-only live mids" in alert


def test_no_trade_alert_does_not_claim_robinhood_live_quotes():
    alert = telegram_notify.format_alert({"date": "2026-07-22", "candidates": [],
                                          "reason": "no edge"})
    assert "NO_TRADE" in alert
    assert "BS fallback estimates" in alert


def test_etf_no_trade_alert_says_robinhood_lookup_was_skipped():
    alert = telegram_notify.format_alert({
        "date": "2026-07-22",
        "candidates": [],
        "reason": "global eruption veto",
        "research_experiment": "options_etf_universe_v1",
    })
    assert "NO_TRADE" in alert
    assert "Robinhood lookup skipped" in alert
    assert "BS fallback estimates" not in alert


def test_alert_includes_open_shadow_natural_exit_mark():
    alert = telegram_notify.format_alert({
        "date": "2026-07-23", "candidates": [], "reason": "veto",
        "research_experiment": "options_etf_universe_v1",
        "shadow_performance": {"open": {
            "n": 2, "marked": 2, "unrealized_pnl_usd": 81.25,
        }},
    })
    assert "OPEN SHADOW: 2 | marked 2 | natural-exit P&L $81" in alert
