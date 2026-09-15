# Four new levers (v11-v14): exit risk, strike selection, structure, time-exit

Date: 2026-07-24. SHADOW research. Pre-registrations `options_etf_gate_v11..v14.json`
(all written before results). All built on **v10** (v5 + call momentum gate).

Every prior variant tuned ENTRY selection. These four tune levers we had never touched:
**exit risk (stop-loss), strike placement (delta), structure design, and time-in-trade.**
Two of the four come from Tom Sosnoff / tastytrade's published mechanics.

## Results (cluster-adjusted, the honest view)

| variant | lever | n | total | PF | **DSR** | maxDD | win | 2022 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| v5 | (base, 200d gate) | 373 | $5,111 | 1.62 | −37.3 | −$1,011 | 77% | −$2,802 |
| **v10** | + call momentum gate | 385 | **$6,231** | 1.78 | −36.5 | −$709 | 78% | −$2,880 |
| **v11** | + 2x-credit STOP-LOSS | 385 | **$6,262** | 1.80 | −36.8 | **−$698** | 77% | **−$2,312** |
| **v12** | **16-delta strikes** | 300 | $3,175 | **2.03** | **−27.3** | −$831 | **90%** | **−$960** |
| v13 | broken-wing condor | 414 | $3,661 | 1.38 | −42.3 | −$1,325 | 83% | −$1,764 |
| v14 | 21-DTE time exit | 385 | $2,005 | 1.35 | −42.7 | **−$603** | 68% | −$1,434 |

## v11 — stop-loss: a clean risk win (keep)

2x-credit stop, 73 stops triggered. **Same total as v10 ($6,262 vs $6,231) but 2022 improves
$568 (−$2,880 -> −$2,312)** and drawdown is marginally better. Getting bear-tail protection
for free is the best kind of result. Contrary to the common claim that stops hurt premium
selling, here the stop paid for itself — because our losers were running to near-max width.

## v12 — 16-delta: the most important finding

Total falls a lot ($6,231 -> $3,175) BUT:
- **DSR −36.5 -> −27.3 — by far the best of any variant**, i.e. the biggest move toward the
  gate we have ever produced.
- **PF 2.03 (best), win rate 90% (best), 2022 −$960 (best bear year of any variant).**

Selling further OTM collects less premium but takes far fewer losses, so **risk-adjusted
quality improves dramatically while raw dollars fall.** Since the canonical gate scores
per-trade Sharpe (not total dollars), this is the direction that could eventually clear it.
The obvious follow-up (its own pre-registration): 16-delta **with more contracts/size** to
recover the dollar total while keeping the better per-trade distribution.

## v13 — broken-wing condor: FAILED

I caught a design flaw before running: a symmetric condor can never satisfy "credit >= call
width" (that implies non-positive risk on both sides); the real jade lizard finances its call
wing with a NAKED put, which our $1,000 cap forbids. Fix was to narrow the call wing to half
width. Result: **the condor was eliminated entirely** (0 condors in the ledger — none could
finance the wing), so the book degenerated to put+call spreads and lost its main profit
engine (condors were +$9,729 of v5). Worst DSR and worst drawdown. **Rejected.**

## v14 — 21-DTE exit (Sosnoff's signature rule): worse here

Best drawdown of all (−$603) and a better 2022 (−$1,434), but **total collapses to $2,005**
and DSR worsens to −42.7. Cause is visible in the exit mix: **760 positions closed at 21 DTE
vs only 248 reaching the 50% target** — the time exit fires before most winners mature, so
we pay theta to enter and then leave before collecting it.

Important caveat in tastytrade's favour: our constant-IV repricing **understates** gamma/vol
risk near expiry, which is exactly the risk the 21-DTE rule exists to avoid. So this test is
biased against the rule. With real option data (post-OPRA) it could look better. Recorded as
"worse on our modeled data", not "the rule is wrong".

## Verdict

- **v11 (stop-loss) is a free risk improvement — adopt into the candidate stack.**
- **v12 (16-delta) is the most promising direction for ever passing the gate** and deserves a
  sizing follow-up.
- v13 rejected. v14 not supported on modeled data (retest with real options).
- Nothing promoted: all still fail the gate, all prices modeled, **v5 stays live**.

**Multiple-testing disclosure:** these are variants 11-14 on the same dataset. The more
variants tried, the likelier one looks good by luck. v11 and v12 both have mechanical
rationales (cap the left tail; sell further from the money), which is why I weight them —
but real-option confirmation is still required before any promotion.

Sources for the externally-derived rules (v11 stop, v12 delta, v14 21-DTE):
- [tastytrade strategy mechanics review](https://www.sjoptions.com/does-tastytrade-work/)
- [The 21-DTE rule and 50% profit exit](https://traderc.com/21-dte-50-percent-profit-exit-options/)
- [21 DTE rule explained](https://www.daystoexpiry.com/blog/the-21-dte-rule-explained-when-and-why-to-close-options-positions-early)
