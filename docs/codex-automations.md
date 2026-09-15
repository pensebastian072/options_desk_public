# Codex automations to register (options_desk)

Register these two in the Codex app **Scheduled** tab, same way as `Options Desk Morning`
(local project `C:\Users\<you>\options_desk`, execution_environment = local). They are
read-only and SHADOW. Do not create duplicates.

## 1. Options Desk Re-check — weekdays 10:00 ET

`RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=10;BYMINUTE=0`

Prompt:

> Use the `options-desk-morning` skill's `references/recheck.md` workflow exactly in
> C:\Users\<you>\options_desk. Advisory, SHADOW, read-only. Mark the morning's open
> candidates: run `.venv\Scripts\python.exe -m desk.shadow --mark-request`; if READY,
> quote only the stored instrument IDs with `get_option_quotes` in batches of at most 20,
> write the payload, and run `--finalize-marks`. Marks are observations only and never
> close a trade. Then run `.venv\Scripts\python.exe -m desk.shadow --progress --telegram`
> and require `telegram: sent`. Create no new candidates. Never use account, position,
> order, cancellation, order-guard, or watchlist tools. On any failure, fail neutral,
> preserve all open candidates, and report.

## 2. Options Desk Review — weekdays 16:15 ET

`RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR;BYHOUR=16;BYMINUTE=15`

Prompt:

> Use the `options-desk-morning` skill's `references/after-close-review.md` workflow
> exactly in C:\Users\<you>\options_desk. Advisory, SHADOW, read-only. First take final
> marks (mark-request -> get_option_quotes -> finalize-marks; marks never close a trade).
> Then `.venv\Scripts\python.exe -m desk.review --request`, read the symbol list, and use
> only `get_equity_historicals` (interval=day) and `get_equity_technical_indicators` to
> write a secret-free review payload, then `.venv\Scripts\python.exe -m desk.review
> --finalize <payload> --telegram` and require `telegram: sent`. If Robinhood is
> unavailable, run `.venv\Scripts\python.exe -m desk.review --local --telegram` so the
> review still ships. Never place/cancel orders or read account/positions/portfolio.

Both require the machine awake and Codex signed in at the scheduled time (autostart is
installed; Windows cannot wake a sleeping PC).
