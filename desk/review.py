"""After-close day review (SHADOW, advisory, read-only).

Runs ~16:15 ET as a Codex session. Produces a Telegram day-review: how held names and the
watch set closed, updated shadow stats, and where to look tomorrow (Qlib leans off today's
close). Continuity: today's close feeds tomorrow's open.

Robinhood is read-only and session-only, so this module does NOT call it. It writes a
secret-free read request (`get_equity_historicals` daily bars + `get_equity_technical_
indicators` for held + watch symbols); a Codex session fills it and calls `finalize_review`.
A `local_review` fallback uses only local Qlib CSV closes when no RH data is available.

No broker action, no order, no account/position read. Deterministic summary in Python.
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, shadow

NY = ZoneInfo("America/New_York")
REVIEW_REQUEST = config.FLAGS_DIR / "review_request.json"
REVIEW_FLAG = config.FLAGS_DIR / "review_state.json"
WATCH_MAX = 8


def _read_json(path: Path) -> dict | None:
    try:
        v = json.loads(path.read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def held_symbols() -> list[str]:
    """Underlyings of currently open SHADOW positions."""
    out = {row.get("underlying") for row in shadow._load_open().values() if row.get("underlying")}
    return sorted(s for s in out if s)


def qlib_watch(limit: int = WATCH_MAX) -> list[dict]:
    """Top directional Qlib leans off today's close (tomorrow's candidates)."""
    state = _read_json(config.QLIB_STATE_FLAG) or {}
    assets = state.get("assets") or {}
    rows = []
    for name, a in assets.items():
        lean = a.get("lean")
        if lean in (1, -1):
            rows.append({"symbol": name, "lean": int(lean),
                         "conviction": float(a.get("conviction") or 0.0)})
    rows.sort(key=lambda r: (-abs(r["lean"]), -r["conviction"], r["symbol"]))
    return rows[:limit]


def _last_two_closes(qlib_asset: str) -> tuple[float, float] | None:
    path = config.QLIB_CSV_DIR / f"{qlib_asset}.csv"
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.DictReader(fh)]
        closes = [float(r["close"]) / float(r.get("factor", 1) or 1) for r in rows[-2:]]
        if len(closes) == 2:
            return closes[-2], closes[-1]
    except Exception:  # noqa: BLE001
        return None
    return None


def build_review_request(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    symbols = sorted(set(held_symbols()) | {w["symbol"] for w in qlib_watch()})
    return {
        "generated_at": now.isoformat(), "date": now.astimezone(NY).date().isoformat(),
        "read_only": True, "symbols": symbols,
        "robinhood_steps": [
            "READ-ONLY: get_equity_historicals(interval=day) for each symbol (last ~5 sessions)",
            "get_equity_technical_indicators for each symbol (e.g. RSI, moving averages)",
            "write a secret-free payload: {symbol: {close, prior_close, rsi, sma?}}",
        ],
        "note": "read-only market data only (historicals + technicals); no broker/portfolio tools",
    }


def write_request(request: dict | None = None) -> str:
    _atomic(REVIEW_REQUEST, request or build_review_request())
    return str(REVIEW_REQUEST)


def _close_rows(market: dict) -> list[dict]:
    rows = []
    for symbol, data in (market or {}).items():
        data = data or {}
        close = data.get("close")
        prior = data.get("prior_close")
        chg = None
        if isinstance(close, (int, float)) and isinstance(prior, (int, float)) and prior:
            chg = round((close / prior - 1) * 100, 2)
        rows.append({"symbol": symbol, "close": close, "day_change_pct": chg,
                     "rsi": data.get("rsi")})
    rows.sort(key=lambda r: r["symbol"])
    return rows


def _assemble(now: datetime, closes: list[dict], source: str) -> dict:
    return {
        "date": now.astimezone(NY).date().isoformat(), "ts": now.isoformat(),
        "status": "SHADOW", "source": source, "closes": closes,
        "shadow_performance": shadow.summary(),
        "tomorrow_watch": qlib_watch(),
        "note": "advisory SHADOW review; read-only; today's close feeds tomorrow's open",
    }


def finalize_review(payload: dict, now: datetime | None = None) -> dict:
    """Build the review from a Codex-supplied read-only RH market payload."""
    now = now or datetime.now(timezone.utc)
    return _assemble(now, _close_rows(payload.get("market") or payload), "robinhood_read_only")


def local_review(now: datetime | None = None) -> dict:
    """Fallback review using only local Qlib CSV closes (no RH, no technicals)."""
    now = now or datetime.now(timezone.utc)
    watch_assets = {w["symbol"]: w["symbol"] for w in qlib_watch()}
    closes = []
    for symbol in sorted(set(held_symbols()) | set(watch_assets)):
        two = _last_two_closes(symbol)
        if two:
            prior, close = two
            closes.append({"symbol": symbol, "close": round(close, 2),
                           "day_change_pct": round((close / prior - 1) * 100, 2)
                           if prior else None, "rsi": None})
    return _assemble(now, closes, "local_qlib_close")


def publish(review: dict) -> str:
    _atomic(REVIEW_FLAG, review)
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with (config.JOURNAL_DIR / f"review-{month}.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(review) + "\n")
    return str(REVIEW_FLAG)


def main() -> None:
    from . import telegram_notify
    parser = argparse.ArgumentParser(description="After-close options-desk day review")
    parser.add_argument("--request", action="store_true", help="write the read-only review request")
    parser.add_argument("--finalize", type=Path, help="build the review from a Codex/RH payload")
    parser.add_argument("--local", action="store_true", help="build a review from local closes only")
    parser.add_argument("--telegram", action="store_true", help="send the review to Telegram")
    args = parser.parse_args()

    if args.request:
        print(f"review request -> {write_request()}")
        return
    if args.finalize:
        review = finalize_review(_read_json(args.finalize) or {})
    else:
        review = local_review()
    path = publish(review)
    text = telegram_notify.format_review(review)
    print(text)
    print(f"review flag -> {path}")
    if args.telegram:
        ok, err = telegram_notify.send_message(text)
        print(f"telegram: {'sent' if ok else 'skipped - ' + str(err)}")


if __name__ == "__main__":
    main()
