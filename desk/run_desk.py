"""options_desk daily runner — read signal -> select strategies -> publish + alert.

    python -m desk.run_desk --once [--telegram]   # build, publish, (optionally) alert
    python -m desk.run_desk --dry-run             # build + print, NO writes / no notify
    python -m desk.run_desk --summary [--telegram]# re-summarize the last published flag

Advisory only: prints/pushes a paper alert. Never places an order.
"""
from __future__ import annotations

import argparse
import json

from . import config, enrich, etf_options, shadow, signal_read, strategies, telegram_notify, ticket


def _print(t: dict) -> None:
    sig = t.get("signal") or {}
    print(f"[{t['date']}] {t['action']} - {t.get('reason')}")
    if sig:
        print(f"  spot={sig.get('spot')} vix={sig.get('vix')} vrp_pct={sig.get('vrp_pct')} "
              f"mag_pct={sig.get('magnitude_pct')} term={sig.get('term_ratio')}")
    for i, c in enumerate(t.get("candidates") or [], 1):
        econ = (f"credit ${c['credit_usd']}" if c.get("credit_usd")
                else f"debit ${c.get('debit_usd')}")
        print(f"  {i}. {c['strategy']} {c.get('legs_short','')} {econ} "
              f"risk ${c.get('max_risk_usd')} pop={c.get('pop')}")
    if t.get("pairs_tilt"):
        print(f"  pairs: {t['pairs_tilt']['rationale']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="build + publish the ticket")
    ap.add_argument("--telegram", action="store_true", help="also push the alert (fail-safe)")
    ap.add_argument("--dry-run", action="store_true", help="build + print only; no writes/notify")
    ap.add_argument("--summary", action="store_true", help="re-summarize the last published flag")
    ap.add_argument("--status-only", action="store_true",
                    help="publish + send a terse status line without estimate-priced "
                         "candidate details (used by the unattended 09:05 task)")
    args = ap.parse_args()

    if args.summary:
        t = ticket.load_flag()
        if not t:
            print("no published flag")
            return
        t["shadow_performance"] = shadow.summary()
        _print(t)
        if args.telegram:
            ok, err = telegram_notify.send_message(telegram_notify.format_alert(t))
            print(f"telegram: {'sent' if ok else 'skipped — ' + str(err)}")
        return

    sig = signal_read.read_signal()
    # v3 live policy: magnitude advisory (not a hard block), $1000 per-trade cap.
    t = strategies.select(sig, magnitude_blocks=False, risk_cap=config.MAX_TRADE_RISK_USD)
    t["shadow_performance"] = shadow.summary()

    if args.dry_run:
        _print(t)
        etf_request = etf_options.build_request()
        print(f"ETF P5: {etf_request['status']} - {etf_request['reason']}")
        print(json.dumps({"dry_run": True}, indent=0))
        return

    settled = shadow.settle_expired()
    if settled:
        t["shadow_performance"] = shadow.summary()
    path = ticket.publish(t)
    request_path = enrich.write_lookup_request(t)
    etf_request = etf_options.build_request()
    etf_request_path = etf_options.write_request(etf_request)
    # Track the Qlib-filtered ETF (v2) strategy every day with BS estimates, so its
    # SHADOW record accumulates without a live Codex session. The live 09:35 run
    # upgrades these to real mids and supersedes the estimates when it completes.
    etf_estimate = etf_options.finalize_estimate(etf_request)
    etf_options.publish_estimate(etf_estimate)
    _print(t)
    print(f"flag -> {path}")
    print(f"robinhood read request -> {request_path}")
    print(f"ETF P5 request -> {etf_request_path} ({etf_request['status']})")
    print(f"ETF estimate track -> {etf_estimate['action']} ({len(etf_estimate['candidates'])} tracked)")
    print(f"shadow settled -> {settled}")

    if args.telegram:
        # Unattended runs cannot reach session-scoped Robinhood MCP, so they must not
        # present Black-Scholes estimates as actionable prices.
        body = (telegram_notify.format_status(t) if args.status_only
                else telegram_notify.format_alert(t))
        ok, err = telegram_notify.send_message(body)
        print(f"telegram: {'sent' if ok else 'skipped - ' + str(err)}")


if __name__ == "__main__":
    main()
