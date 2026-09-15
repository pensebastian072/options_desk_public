"""SHADOW ledger: stable IDs, live repricing, expiry settlement, and hit rate."""
import json
from datetime import datetime, timezone
from pathlib import Path

from desk import shadow


def _ticket(enriched=False):
    candidate = {
        "strategy": "short_put_spread", "expiry": "2026-08-21",
        "legs": [{"side": "sell", "type": "put", "strike": 100},
                 {"side": "buy", "type": "put", "strike": 95}],
        "credit_usd": 150.0, "max_risk_usd": 350.0,
        "gate": "not_cleared",
    }
    if enriched:
        candidate["enriched"] = True
        candidate["source"] = "robinhood_natural_bid_ask"
        candidate["credit_usd"] = 175.0
        candidate["legs"] = [
            {"side": "sell", "type": "put", "strike": 100,
             "instrument_id": "short-id", "bid": 2.00, "ask": 2.10,
             "mid": 2.05, "delta": -0.30, "implied_volatility": 0.25,
             "quote_ts": "2026-07-22T13:35:00+00:00"},
            {"side": "buy", "type": "put", "strike": 95,
             "instrument_id": "long-id", "bid": 0.20, "ask": 0.25,
             "mid": 0.225, "delta": -0.15, "implied_volatility": 0.27,
             "quote_ts": "2026-07-22T13:35:00+00:00"},
        ]
    return {"date": "2026-07-22", "ts": "2026-07-22T09:05:00+00:00",
            "underlying": "SPY", "signal": {"spot": 101.0},
            "candidates": [candidate]}


def test_record_deduplicates_and_live_mid_reprices(tmp_path):
    path = tmp_path / "open.json"
    base = _ticket()
    assert shadow.record_ticket(base, path) == 1
    assert shadow.record_ticket(_ticket(), path) == 0
    live = _ticket(enriched=True)
    assert shadow.record_ticket(live, path) == 1
    row = next(iter(json.loads(path.read_text(encoding="utf-8")).values()))
    assert row["entry_source"] == "robinhood_natural_bid_ask"
    assert row["entry_cash_usd"] == 175.0
    assert row["legs"][0]["instrument_id"] == "short-id"
    assert row["credit_usd"] == 175.0
    assert base["candidates"][0]["candidate_id"] == live["candidates"][0]["candidate_id"]


def test_base_veto_retracts_only_same_day_same_lane(tmp_path):
    path = tmp_path / "open.json"
    shadow.record_ticket(_ticket(), path)
    opened = json.loads(path.read_text(encoding="utf-8"))
    opened["other"] = {"candidate_id": "other", "signal_date": "2026-07-22",
                       "underlying": "QQQ", "research_experiment": None}
    path.write_text(json.dumps(opened), encoding="utf-8")

    veto = {"date": "2026-07-22", "underlying": "SPY", "action": "NO_TRADE",
            "candidates": []}
    assert shadow.retract_same_day_on_veto(veto, path) == 1
    after = json.loads(path.read_text(encoding="utf-8"))
    assert set(after) == {"other"}


def test_settle_and_summary(tmp_path):
    open_path = tmp_path / "open.json"
    pnl_path = tmp_path / "pnl.jsonl"
    csv_path = tmp_path / "SPY.csv"
    shadow.record_ticket(_ticket(), open_path)
    csv_path.write_text(
        "date,open,high,low,close,volume,factor\n"
        "2026-08-20,101,101,100,101,1,1\n"
        "2026-08-21,102,102,101,102,1,1\n", encoding="utf-8")
    assert shadow.settle_expired(csv_path, open_path, pnl_path) == 1
    assert json.loads(open_path.read_text(encoding="utf-8")) == {}
    stats = shadow.summary(pnl_path)["overall"]
    assert stats["n"] == 1 and stats["wins"] == 1 and stats["hit_rate"] == 1.0
    assert stats["total_pnl_usd"] == 146.0  # $150 credit - $4 two-leg RT cost
    result = shadow.load_results(pnl_path)[0]
    assert result["exit_reason"] == "expiration"
    assert result["exit_source"] == "intrinsic_from_underlying_close"
    assert result["exit_debit_usd"] == 0.0
    assert result["exit_legs"][0]["settlement_price"] == 0.0


def test_settlement_defers_until_expiry_data_exists(tmp_path):
    open_path = tmp_path / "open.json"
    pnl_path = tmp_path / "pnl.jsonl"
    csv_path = tmp_path / "SPY.csv"
    shadow.record_ticket(_ticket(), open_path)
    csv_path.write_text("date,close\n2026-08-20,101\n", encoding="utf-8")
    assert shadow.settle_expired(csv_path, open_path, pnl_path) == 0
    assert Path(open_path).exists()


def test_multi_underlying_uses_candidate_qlib_csv(tmp_path, monkeypatch):
    open_path = tmp_path / "open.json"
    pnl_path = tmp_path / "pnl.jsonl"
    ticket = _ticket()
    candidate = ticket["candidates"][0]
    candidate["underlying"] = "QQQ"
    candidate["qlib_asset"] = "QQQ"
    shadow.record_ticket(ticket, open_path)
    (tmp_path / "QQQ.csv").write_text(
        "date,close\n2026-08-21,102\n", encoding="utf-8")
    monkeypatch.setattr(shadow.config, "QLIB_CSV_DIR", tmp_path)
    assert shadow.settle_expired(open_path=open_path, pnl_path=pnl_path) == 1
    row = shadow.load_results(pnl_path)[0]
    assert row["underlying"] == "QQQ" and row["terminal_spot"] == 102.0


def test_mark_request_and_natural_exit_mark_are_append_only(tmp_path):
    open_path = tmp_path / "open.json"
    marks_path = tmp_path / "marks.jsonl"
    shadow.record_ticket(_ticket(enriched=True), open_path)
    now = datetime(2026, 7, 23, 13, 35, tzinfo=timezone.utc)
    request = shadow.build_mark_request(now, open_path)
    assert request["status"] == "READY"
    assert {leg["instrument_id"] for leg in request["positions"][0]["legs"]} == {
        "short-id", "long-id"}
    serialized = json.dumps(request).lower()
    assert "account" not in serialized and "secret" not in serialized and "token" not in serialized
    payload = {"request_id": request["request_id"], "quotes": [
        {"instrument_id": "short-id", "bid_price": 1.10, "ask_price": 1.20,
         "updated_at": now.isoformat(), "delta": -0.25, "implied_volatility": 0.24},
        {"instrument_id": "long-id", "bid_price": 0.30, "ask_price": 0.35,
         "updated_at": now.isoformat(), "delta": -0.12, "implied_volatility": 0.26},
    ]}
    report = shadow.finalize_marks(payload, request, now, open_path, marks_path)
    assert report["status"] == "MARKED"
    mark = report["accepted"][0]
    assert mark["exit_debit_usd"] == 90.0  # buy short at ask, sell long at bid
    assert mark["unrealized_pnl_usd"] == 81.0  # $175 - $90 - $4 RT costs
    opened = next(iter(json.loads(open_path.read_text(encoding="utf-8")).values()))
    assert opened["last_mark"]["mark_id"] == mark["mark_id"]
    assert opened["mfe_pnl_usd"] == 81.0 and opened["mae_pnl_usd"] == 81.0
    assert len(shadow.load_marks(marks_path)) == 1
    duplicate = shadow.finalize_marks(payload, request, now, open_path, marks_path)
    assert duplicate["accepted"][0]["duplicate"] is True
    assert len(shadow.load_marks(marks_path)) == 1


def test_stale_or_mismatched_mark_payload_fails_neutral(tmp_path):
    open_path = tmp_path / "open.json"
    marks_path = tmp_path / "marks.jsonl"
    shadow.record_ticket(_ticket(enriched=True), open_path)
    now = datetime(2026, 7, 23, 13, 35, tzinfo=timezone.utc)
    request = shadow.build_mark_request(now, open_path)
    mismatch = shadow.finalize_marks({"request_id": "wrong", "quotes": []},
                                     request, now, open_path, marks_path)
    assert mismatch["status"] == "NO_MARKS" and "mismatch" in mismatch["reason"]
    payload = {"request_id": request["request_id"], "quotes": [
        {"instrument_id": "short-id", "bid_price": 1.10, "ask_price": 1.20,
         "updated_at": "2026-07-23T12:00:00+00:00"},
        {"instrument_id": "long-id", "bid_price": 0.30, "ask_price": 0.35,
         "updated_at": now.isoformat()},
    ]}
    stale = shadow.finalize_marks(payload, request, now, open_path, marks_path)
    assert stale["status"] == "NO_MARKS" and "stale quote" in stale["rejected"][0]["reason"]
    assert not marks_path.exists()


def test_changed_open_instruments_reject_mark_request(tmp_path):
    open_path = tmp_path / "open.json"
    marks_path = tmp_path / "marks.jsonl"
    shadow.record_ticket(_ticket(enriched=True), open_path)
    now = datetime(2026, 7, 23, 13, 35, tzinfo=timezone.utc)
    request = shadow.build_mark_request(now, open_path)
    opened = json.loads(open_path.read_text(encoding="utf-8"))
    next(iter(opened.values()))["legs"][0]["instrument_id"] = "changed-id"
    open_path.write_text(json.dumps(opened), encoding="utf-8")
    report = shadow.finalize_marks(
        {"request_id": request["request_id"], "quotes": []},
        request, now, open_path, marks_path,
    )
    assert report["status"] == "NO_MARKS"
    assert "no longer match" in report["rejected"][0]["reason"]
    assert not marks_path.exists()


def test_unenriched_candidate_is_not_quoteable(tmp_path):
    open_path = tmp_path / "open.json"
    shadow.record_ticket(_ticket(), open_path)
    request = shadow.build_mark_request(
        datetime(2026, 7, 23, 13, 35, tzinfo=timezone.utc), open_path)
    assert request["status"] == "NO_OPEN_POSITIONS"
    assert "instrument IDs" in request["skipped"][0]["reason"]


def test_trade_ledger_normalizes_pre_p6_settled_rows(tmp_path):
    pnl_path = tmp_path / "pnl.jsonl"
    pnl_path.write_text(json.dumps({
        "status": "settled", "credit_usd": 150.0, "terminal_value_usd": -50.0,
    }) + "\n", encoding="utf-8")
    row = shadow.trade_ledger(pnl_path=pnl_path, open_path=tmp_path / "open.json")["settled"][0]
    assert row["entry_cash_usd"] == 150.0
    assert row["exit_debit_usd"] == 50.0 and row["exit_credit_usd"] == 0.0
    assert row["exit_reason"] == "expiration"
