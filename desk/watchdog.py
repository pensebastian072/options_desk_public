"""P9 — detect a missed live morning run and say so. Never invents trade ideas.

On 2026-07-23 the 09:35 Codex live-validation step did not produce its finalization
artifact and nothing noticed until the user asked. This module closes that gap.

It distinguishes the two legitimate outcomes from a real miss:

  * request status NO_TRADE -> a deterministic local veto completed the lane; a
    published NO_TRADE flag for today is SUCCESS, not a miss.
  * request status READY    -> a live Codex/Robinhood session was required; the lane
    is only complete when today's flag carries today's matching request_id.

Per the miss policy: a miss sends an explanatory Telegram alert with ZERO candidates.
Estimate-priced ideas are never presented as a substitute for live validation.
Fail-safe and idempotent: it alerts at most once per day and never raises.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config

NY = ZoneInfo("America/New_York")
STAMP = config.FLAGS_DIR / "watchdog_stamp.json"

OK, MISS, PENDING, SKIP = "OK", "MISS", "PENDING", "SKIP"
LOCAL_DEADLINE = time(9, 15)
LIVE_DEADLINE = time(10, 15)


def _read(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _ny_date(raw) -> date | None:
    try:
        stamp = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(NY).date()
    except Exception:  # noqa: BLE001
        return None


def check(now: datetime | None = None) -> dict:
    """Classify today's ETF lane as OK / MISS / PENDING / SKIP. Never raises."""
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(NY)
    today = local_now.date()
    result = {"checked_at": now.isoformat(), "date": today.isoformat()}

    if today.weekday() >= 5:
        return {**result, "status": SKIP, "reason": "weekend - no market open"}

    request = _read(config.ETF_OPTIONS_REQUEST)
    flag = _read(config.ETF_OPTIONS_FLAG)
    flag_date = _ny_date((flag or {}).get("ts"))

    if request is None:
        if local_now.time() < LOCAL_DEADLINE:
            return {**result, "status": PENDING,
                    "reason": "waiting for the local 09:05 task",
                    "stage": "local_request"}
        return {**result, "status": MISS,
                "reason": "no ETF request file exists - the local 09:05 task did not run",
                "stage": "local_request"}

    request_date = _ny_date(request.get("generated_at"))
    if request_date != today:
        if local_now.time() < LOCAL_DEADLINE:
            return {**result, "status": PENDING,
                    "reason": "waiting for today's local 09:05 request",
                    "stage": "local_request"}
        return {**result, "status": MISS,
                "reason": (f"ETF request is from {request_date}, not today - the local "
                           "09:05 task did not run"),
                "stage": "local_request"}

    status = request.get("status")
    if status != "READY":
        if flag_date == today:
            return {**result, "status": OK,
                    "reason": f"deterministic veto completed: {request.get('reason')}",
                    "stage": "local_veto"}
        if local_now.time() < LOCAL_DEADLINE:
            return {**result, "status": PENDING,
                    "reason": "today's deterministic veto is still publishing",
                    "stage": "local_publish"}
        return {**result, "status": MISS,
                "reason": "today's veto request never produced a published result flag",
                "stage": "local_publish"}

    if flag_date != today:
        if local_now.time() < LIVE_DEADLINE:
            return {**result, "status": PENDING,
                    "reason": "today's 09:35 live validation is pending",
                    "stage": "live_validation",
                    "eligible": [row.get("symbol") for row in request.get("eligible") or []]}
        return {**result, "status": MISS,
                "reason": ("today's request was READY but no result was published - the "
                           "09:35 live Codex/Robinhood validation did not complete"),
                "stage": "live_validation",
                "eligible": [row.get("symbol") for row in request.get("eligible") or []]}

    if flag.get("request_id") != request.get("request_id"):
        if local_now.time() < LIVE_DEADLINE:
            return {**result, "status": PENDING,
                    "reason": "today's 09:35 live validation is pending",
                    "stage": "live_validation",
                    "eligible": [row.get("symbol") for row in request.get("eligible") or []]}
        return {**result, "status": MISS,
                "reason": ("published result does not match today's request_id - the live "
                           "run finalized a stale request"),
                "stage": "live_validation",
                "eligible": [row.get("symbol") for row in request.get("eligible") or []]}

    return {**result, "status": OK,
            "reason": f"live validation complete: {flag.get('action')} - {flag.get('reason')}",
            "stage": "live_validation"}


def format_miss(result: dict) -> str:
    """Miss alert: explains what did not run. Contains NO trade ideas by policy."""
    lines = [f"OPTIONS DESK WATCHDOG - MISSED RUN ({result.get('date')})",
             f"stage: {result.get('stage')}",
             f"what happened: {result.get('reason')}"]
    eligible = result.get("eligible")
    if eligible:
        lines.append(f"symbols that were awaiting live validation: {', '.join(eligible)}")
    lines.append("No trade ideas are included: live quotes were never confirmed, and "
                 "estimate-priced candidates are not a substitute.")
    lines.append("To finish manually: run the read-only Codex enrich flow, then "
                 "`-m desk.etf_options --finalize <payload> --telegram`.")
    return "\n".join(lines)


def _already_alerted(today: date) -> bool:
    stamp = _read(STAMP) or {}
    return stamp.get("last_miss_alert") == today.isoformat()


def _record_alert(today: date) -> None:
    try:
        config.FLAGS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = STAMP.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"last_miss_alert": today.isoformat()}, indent=2),
                       encoding="utf-8")
        tmp.replace(STAMP)
    except Exception:  # noqa: BLE001
        pass


def run(now: datetime | None = None, telegram: bool = False) -> dict:
    result = check(now)
    if result["status"] != MISS or not telegram:
        return result
    today = date.fromisoformat(result["date"])
    if _already_alerted(today):
        result["notified"] = "suppressed - already alerted today"
        return result
    from . import telegram_notify
    ok, err = telegram_notify.send_message(format_miss(result))
    result["notified"] = "sent" if ok else f"failed: {err}"
    if ok:
        _record_alert(today)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect a missed options-desk live run")
    parser.add_argument("--telegram", action="store_true",
                        help="send the miss alert (fail-safe, once per day)")
    args = parser.parse_args()
    result = run(telegram=args.telegram)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
