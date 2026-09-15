"""UI smoke: routes return 200, /api/state is fail-safe, host is loopback-only."""
from desk import config
from ui import app as ui_app


def _client():
    ui_app.app.config.update(TESTING=True)
    return ui_app.app.test_client()


def test_index_200():
    assert _client().get("/").status_code == 200


def test_api_state_failsafe_when_no_flag():
    r = _client().get("/api/state")
    assert r.status_code == 200
    body = r.get_json()
    # no flag published in a fresh test env -> ok=False, never a 500
    assert "ok" in body


def test_api_history_shape():
    r = _client().get("/api/history")
    assert r.status_code == 200
    assert "rows" in r.get_json()


def test_api_gate_is_failsafe():
    r = _client().get("/api/gate")
    assert r.status_code == 200
    body = r.get_json()
    assert "ok" in body and "strategies" in body


def test_api_performance_is_failsafe():
    r = _client().get("/api/performance")
    assert r.status_code == 200
    body = r.get_json()
    assert "overall" in body and "measurement" in body


def test_api_etf_state_is_failsafe():
    r = _client().get("/api/etf-state")
    assert r.status_code == 200
    assert "ok" in r.get_json()


def test_api_trade_ledger_is_failsafe():
    r = _client().get("/api/trades")
    assert r.status_code == 200
    body = r.get_json()
    assert "open" in body and "settled" in body and "recent_marks" in body


def test_ui_binds_loopback_only():
    assert config.UI_HOST == "127.0.0.1"
