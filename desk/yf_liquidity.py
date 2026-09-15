"""Options liquidity gate via yfinance (real current chains: bid/ask + OI + volume + IV).

Alpaca's indicative feed gave junk spreads and no OI. yfinance returns clean current option
chains, so this is the reliable STRUCTURAL liquidity gate for the ETF universe expansion:
can we sell 30-60 DTE options on this name with tight spreads and real open interest?

Current-snapshot only (yfinance has no option history) -> this gates liquidity, it does NOT
price history. The real-option deep test still needs OPRA/Polygon. Read-only data.

    .venv\\Scripts\\python.exe -m desk.yf_liquidity
"""
from __future__ import annotations

import json
import os
import ssl
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import config

OUT = config.SCORECARDS_DIR / "yf_option_liquidity.json"
DTE_LO, DTE_HI = 30, 60
STRIKE_BAND = 0.05           # +/-5% of spot: the region we actually trade (~30-delta at 45 DTE)
MIN_MID = 0.10
MAX_REL_SPREAD = 0.15        # median near-ATM per-leg relative spread
# Depth floor calibrated to the FROZEN 31 (known-tradable): their near-ATM OI 25th
# percentile is ~31k. Require a candidate to reach that bar to count as comparably liquid.
MIN_OI = 31000               # summed near-ATM open interest (both sides)
MIN_VOL = 5000               # summed near-ATM day volume (alternative depth route)

BASE_31 = ["SPY", "QQQ", "IWM", "DIA", "TLT", "IEF", "AGG", "HYG", "LQD", "GLD", "SLV",
           "XLF", "XLE", "XLK", "XLV", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC",
           "SMH", "KRE", "GDX", "XBI", "EEM", "EFA", "FXI", "EWZ", "VNQ"]
DECORRELATORS = ["UNG", "XOP", "IWO", "EMB", "DBC", "INDA", "SHY", "XHB", "VLUE", "GDXJ",
                 "XRT", "IYT", "RSP", "EWY", "ITA", "IWN", "MUB", "BNDX", "IWF", "IWD",
                 "MTUM", "QUAL", "USMV", "SPLV", "MDY", "TIP", "EWJ", "EWG", "EWU", "EWC"]


def _trust_certs() -> None:
    import certifi
    bundle = config.DATA_DIR / "_yf_ca_bundle.pem"
    bundle.parent.mkdir(parents=True, exist_ok=True)
    parts = [Path(certifi.where()).read_text(encoding="utf-8")]
    for store in ("ROOT", "CA"):
        for der, enc, _ in ssl.enum_certificates(store):
            if enc == "x509_asn":
                parts.append(ssl.DER_cert_to_PEM_cert(der))
    bundle.write_text("\n".join(parts), encoding="utf-8")
    for v in ("CURL_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        os.environ[v] = str(bundle)


def _monthly_expiry(exps: list[str], now: date) -> str | None:
    """Pick the expiry nearest 45 DTE inside [30, 60]; prefer 3rd-Friday (monthly, deep OI)."""
    import datetime as dt
    cand = []
    for e in exps:
        try:
            d = dt.date.fromisoformat(e)
        except ValueError:
            continue
        dte = (d - now).days
        if DTE_LO <= dte <= DTE_HI:
            third_friday = d.weekday() == 4 and 15 <= d.day <= 21
            cand.append((0 if third_friday else 1, abs(dte - 45), e))
    if not cand:
        return None
    cand.sort()
    return cand[0][2]


def market_is_open(now: datetime | None = None) -> bool:
    """US RTH check (NY 09:30-16:00 weekdays). Quoted option spreads are only meaningful
    inside RTH; outside it yfinance serves stale/wide quotes."""
    from zoneinfo import ZoneInfo
    ny = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return False
    return (ny.hour, ny.minute) >= (9, 30) and ny.hour < 16


def screen_symbol(yf, symbol: str, now: date, rth: bool = True) -> dict:
    import statistics
    t = yf.Ticker(symbol)
    try:
        exps = list(t.options)
    except Exception as e:  # noqa: BLE001
        return {"symbol": symbol, "ok": False, "reason": f"no options: {str(e)[:60]}"}
    if not exps:
        return {"symbol": symbol, "ok": False, "reason": "no expirations"}
    exp = _monthly_expiry(exps, now)
    if exp is None:
        return {"symbol": symbol, "ok": False, "reason": "no 30-60 DTE expiry"}
    try:
        spot = float(t.fast_info["lastPrice"])
    except Exception:  # noqa: BLE001
        try:
            spot = float(t.history(period="1d")["Close"].iloc[-1])
        except Exception:  # noqa: BLE001
            return {"symbol": symbol, "ok": False, "reason": "no spot"}
    try:
        ch = t.option_chain(exp)
    except Exception as e:  # noqa: BLE001
        return {"symbol": symbol, "ok": False, "reason": f"chain err: {str(e)[:50]}"}
    lo, hi = spot * (1 - STRIKE_BAND), spot * (1 + STRIKE_BAND)
    spreads, oi_sum, vol_sum, n = [], 0.0, 0.0, 0
    for legs in (ch.puts, ch.calls):
        near = legs[(legs["strike"] >= lo) & (legs["strike"] <= hi)]
        for _, r in near.iterrows():
            def _num(v) -> float:
                try:
                    f = float(v)
                except (TypeError, ValueError):
                    return 0.0
                return 0.0 if f != f else f          # NaN-safe (yfinance leaves NaN volume/OI)

            bid, ask = _num(r.get("bid")), _num(r.get("ask"))
            oi_sum += _num(r.get("openInterest"))
            vol_sum += _num(r.get("volume"))
            if bid > 0 and ask > 0 and ask >= bid:
                mid = (bid + ask) / 2
                if mid >= MIN_MID:
                    spreads.append((ask - bid) / mid)
                    n += 1
    # Too few two-sided quotes near ATM = effectively no option market for our structures.
    if n < 3:
        return {"symbol": symbol, "ok": True, "liquid": False, "spot": round(spot, 2),
                "expiry": exp, "n_quoted": n, "median_rel_spread": None,
                "near_atm_open_interest": round(oi_sum), "near_atm_volume": round(vol_sum),
                "reason": f"only {n} near-ATM two-sided quotes"}
    med_spread = round(statistics.median(spreads), 4)
    # OI/volume are end-of-day settled = reliable any time. QUOTED SPREADS ARE ONLY
    # MEANINGFUL DURING RTH -- outside market hours yfinance returns stale/wide quotes
    # (observed: HYG 1.5M OI reading an 80% "spread" on a Saturday). So the spread test is
    # applied only when the market is open; otherwise depth (OI/volume) is the gate and the
    # spread is recorded as advisory for an RTH re-check.
    depth_ok = (oi_sum >= MIN_OI or vol_sum >= MIN_VOL)
    spread_ok = med_spread <= MAX_REL_SPREAD
    liquid = (depth_ok and spread_ok) if rth else depth_ok
    return {"symbol": symbol, "ok": True, "liquid": bool(liquid), "spot": round(spot, 2),
            "expiry": exp, "n_quoted": n, "median_rel_spread": med_spread,
            "spread_reliable": bool(rth),
            "near_atm_open_interest": round(oi_sum), "near_atm_volume": round(vol_sum),
            "reason": "" if liquid else (f"spread {med_spread:.0%} / OI {round(oi_sum)} / vol {round(vol_sum)}"
                                         if rth else f"depth OI {round(oi_sum)} / vol {round(vol_sum)}")}


def run(symbols: list[str] | None = None) -> dict:
    _trust_certs()
    import yfinance as yf
    now = datetime.now(timezone.utc).date()
    rth = market_is_open()
    print(f"market_open={rth} -> spread test {'APPLIED' if rth else 'ADVISORY ONLY (depth gates)'}")
    syms = symbols or (BASE_31 + DECORRELATORS)
    results = []
    for s in syms:
        r = screen_symbol(yf, s, now, rth)
        results.append(r)
        tag = "LIQUID" if r.get("liquid") else "thin" if r.get("ok") else "ERR"
        print(f"  {s:5s} {tag:6s} spread={r.get('median_rel_spread')} "
              f"OI={r.get('near_atm_open_interest')} vol={r.get('near_atm_volume')} {r.get('reason','')}")
    liq = [r["symbol"] for r in results if r.get("liquid")]
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "source": "yfinance current chain",
            "dte_band": [DTE_LO, DTE_HI], "strike_band": STRIKE_BAND,
            "thresholds": {"max_rel_spread": MAX_REL_SPREAD, "min_oi": MIN_OI, "min_vol": MIN_VOL},
            "caveat": "current snapshot only (no option history); this gates LIQUIDITY, not pricing history",
            "results": results, "liquid_symbols": liq,
            "base_31_liquid": [s for s in liq if s in BASE_31],
            "new_liquid_decorrelators": [s for s in liq if s in DECORRELATORS]}


def main() -> None:
    report = run()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"\nyf option liquidity -> {OUT}")
    print(f"base-31 liquid: {len(report['base_31_liquid'])}/31")
    print(f"NEW liquid decorrelators ({len(report['new_liquid_decorrelators'])}): "
          f"{report['new_liquid_decorrelators']}")


if __name__ == "__main__":
    main()
