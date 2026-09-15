"""P7 — offline ETF-universe replay of the frozen short-put-spread rule.

`options_gate_v1` could only produce 16-24 SPY observations, so canonical PBO was
unavailable and no verdict was possible. This module replays the SAME structure and
the SAME global regime veto across the frozen nine-ETF universe to raise the
observation count enough for the gate to decide.

Read `journal/experiments/options_etf_gate_v1.json` before interpreting anything: the
population is a SUPERSET of live-lane entries (no Qlib discovery filter), entry IV is
PROXIED from SPY's volatility premium, and entry credit is a model credit rather than
the live lane's stricter natural bid/ask. Results are an upper bound on the live edge.

Independence is the trap this module exists to avoid: SPY/QQQ/DIA/IWM move together, so
same-date entries are collapsed into one clustered observation. The cluster-adjusted view
is the ONLY view a promotion decision may use.

No broker integration. Never imported by the scheduled desk.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, time, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import backtest, bs, config, shadow, strategies

CONTRACT = 100
IV_RV_FLOOR = 1.10          # mirrors the live lane's minimum_iv_rv_ratio
MAGNITUDE_MAX = 0.70        # exclusive; mirrors the live global veto
SHORT_PUT_DELTA = -0.30


# options_etf_gate_v1 pre-registered the NINE v1 symbols. This module stays pinned to
# that spec so the published scorecard remains reproducible; it deliberately does NOT
# follow config.ETF_EXPERIMENT_ID when the live lane moves to a wider universe. A wider
# backtest needs its own pre-registration (and, per the v1 finding, would add coverage
# rather than independent evidence under a purely global entry rule).
UNIVERSE_SPEC = "options_etf_universe_v1"


def load_universe(spec_path: Path | None = None) -> dict:
    """Frozen candidate universe pinned to the pre-registered v1 spec."""
    path = spec_path or (config.EXPERIMENTS_DIR / f"{UNIVERSE_SPEC}.json")
    spec = json.loads(path.read_text(encoding="utf-8"))
    return spec["scope"]["candidate_universe"]


def load_prereg(path: Path | None = None) -> dict:
    target = path or (config.EXPERIMENTS_DIR / "options_etf_gate_v1.json")
    if not target.exists():
        raise RuntimeError(f"pre-registration missing: {target}")
    return json.loads(target.read_text(encoding="utf-8"))


def realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualized stdev of trailing log returns; value at t uses only data <= t."""
    logret = np.log(close / close.shift(1))
    return logret.rolling(window, min_periods=window).std() * math.sqrt(252)


def load_symbol_history(symbol_map: dict, csv_dir: Path | None = None) -> dict[str, pd.DataFrame]:
    """Per-symbol unadjusted close + RV20, keyed by trading symbol."""
    root = csv_dir or config.QLIB_CSV_DIR
    out: dict[str, pd.DataFrame] = {}
    for symbol, policy in symbol_map.items():
        asset = policy["qlib_asset"]
        try:
            raw = backtest._read_price_csv(asset, root)
        except FileNotFoundError:
            continue
        spot = backtest.unadjusted_close(raw["close"], raw["factor"]).dropna()
        if spot.empty:
            continue
        frame = pd.DataFrame({"spot": spot})
        frame["rv20"] = realized_vol(spot)
        frame["sma50"] = spot.rolling(50, min_periods=50).mean()    # v4 trend gate (fast)
        frame["sma200"] = spot.rolling(200, min_periods=200).mean()  # v5 trend gate (slow)
        frame["mom126"] = spot / spot.shift(126) - 1.0               # v10 momentum (6-month)
        out[symbol] = frame.dropna(subset=["spot", "rv20"])
    return out


def premium_factor(signals: pd.DataFrame) -> pd.Series:
    """Market-wide IV/RV premium from SPY: (VIX/100) / RV20(SPY).

    NOTE (pre-registered): this is a single scalar per date, so the live lane's
    per-asset IV/RV test degenerates to a market-wide condition here. It cannot
    discriminate between assets — see the spec's declared deviations.
    """
    spy_rv = realized_vol(signals["spot"])
    factor = (signals["vix"] / 100.0) / spy_rv
    return factor.replace([np.inf, -np.inf], np.nan)


def global_regime_ok(row: pd.Series) -> bool:
    """The live lane's global veto, replayed point-in-time."""
    for field in ("calm_5d", "eruption_predicted_5d", "eruption_predicted_21d", "magnitude_pct"):
        if pd.isna(row.get(field)):
            return False
    if not bool(row["calm_5d"]):
        return False
    if bool(row["eruption_predicted_5d"]) or bool(row["eruption_predicted_21d"]):
        return False
    return float(row["magnitude_pct"]) < MAGNITUDE_MAX


def build_spread(spot: float, iv: float, width: float, dte: int, expiry: date,
                 low_delta: bool = False) -> dict | None:
    """Frozen structure: short ~-0.30 delta put (v12: -0.16), long exactly `width` lower."""
    if not (spot > 0 and iv > 0 and width > 0):
        return None
    t = max(dte, 1) / 365.0
    short_k = bs.strike_for_put_delta(spot, iv, t, LOW_DELTA_PUT if low_delta else SHORT_PUT_DELTA)
    long_k = short_k - width
    if long_k <= 0:
        return None
    credit = bs.bs_put(spot, short_k, iv, t) - bs.bs_put(spot, long_k, iv, t)
    if credit <= 0 or credit >= width:
        return None
    return {
        "strategy": "etf_short_put_spread_v1", "dte": dte, "expiry": expiry.isoformat(),
        "legs": [{"side": "sell", "type": "put", "strike": short_k},
                 {"side": "buy", "type": "put", "strike": long_k}],
        "credit_usd": round(credit * CONTRACT, 2),
        "max_risk_usd": round((width - credit) * CONTRACT, 2),
        "width": width,
    }


MIN_POP = 0.51           # tastytrade-style probability-of-profit floor (v3)
MOMENTUM_MAX = 0.10      # v10: do not sell CALL premium on symbols with 6-month momentum above this
STOP_LOSS_MULT = 2.0     # v11: exit when the realized loss reaches 2x the credit (tastytrade standard)
LOW_DELTA_PUT = -0.16    # v12: ~1 SD short strike instead of 0.30
LOW_DELTA_CALL = 0.16
MANAGE_DTE = 21          # v14: close remaining positions at 21 DTE (gamma window, Sosnoff rule)
SHORT_CALL_DELTA = 0.30
PUT_SPREAD = "etf_short_put_spread_v1"
CALL_SPREAD = "etf_short_call_spread_v1"
IRON_CONDOR = "etf_iron_condor_v1"


def _finish(cand: dict, spot: float, iv: float, t: float,
            put_be: float | None, call_be: float | None) -> dict | None:
    """Attach breakeven, POP-at-expiry, entry IV; drop below the POP floor or $1000 cap."""
    cand["entry_iv"] = iv
    cand["pop"] = bs.pop_at_expiry(spot, iv, t, cand["strategy"],
                                   put_breakeven=put_be, call_breakeven=call_be)
    cand["breakevens"] = "; ".join(
        s for s in (f"put {round(put_be, 2)}" if put_be else "",
                    f"call {round(call_be, 2)}" if call_be else "") if s)
    if cand["pop"] < MIN_POP:
        return None
    if cand["max_risk_usd"] > config.MAX_TRADE_RISK_USD:
        return None
    return cand


def build_call_spread(spot: float, iv: float, width: float, dte: int, expiry: date,
                      low_delta: bool = False) -> dict | None:
    if not (spot > 0 and iv > 0 and width > 0):
        return None
    t = max(dte, 1) / 365.0
    short_k = bs.strike_for_call_delta(spot, iv, t, LOW_DELTA_CALL if low_delta else SHORT_CALL_DELTA)
    long_k = short_k + width
    credit = bs.bs_call(spot, short_k, iv, t) - bs.bs_call(spot, long_k, iv, t)
    if credit <= 0 or credit >= width:
        return None
    cand = {"strategy": CALL_SPREAD, "dte": dte, "expiry": expiry.isoformat(),
            "legs": [{"side": "sell", "type": "call", "strike": short_k},
                     {"side": "buy", "type": "call", "strike": long_k}],
            "credit_usd": round(credit * CONTRACT, 2),
            "max_risk_usd": round((width - credit) * CONTRACT, 2), "width": width}
    return _finish(cand, spot, iv, t, None, short_k + credit)


def build_iron_condor(spot: float, iv: float, width: float, dte: int, expiry: date,
                      low_delta: bool = False, no_upside_risk: bool = False) -> dict | None:
    if not (spot > 0 and iv > 0 and width > 0):
        return None
    t = max(dte, 1) / 365.0
    sp = bs.strike_for_put_delta(spot, iv, t, LOW_DELTA_PUT if low_delta else SHORT_PUT_DELTA)
    lp = sp - width
    sc = bs.strike_for_call_delta(spot, iv, t, LOW_DELTA_CALL if low_delta else SHORT_CALL_DELTA)
    # v13 (broken wing): a SYMMETRIC condor can never satisfy credit >= call width -- that
    # would mean non-positive risk on both sides. The jade lizard finances its call wing with
    # a NAKED put, which the $1,000 cap forbids. So we narrow the call wing instead: a
    # half-width call spread CAN be fully financed by the total credit -> no upside risk.
    call_width = width * 0.5 if no_upside_risk else width
    lc = sc + call_width
    if lp <= 0:
        return None
    put_credit = bs.bs_put(spot, sp, iv, t) - bs.bs_put(spot, lp, iv, t)
    call_credit = bs.bs_call(spot, sc, iv, t) - bs.bs_call(spot, lc, iv, t)
    credit = put_credit + call_credit
    if put_credit <= 0 or call_credit <= 0 or credit >= width:   # only one side can lose
        return None
    if no_upside_risk and credit < call_width:
        return None       # call wing not fully financed -> upside risk remains -> skip
    cand = {"strategy": IRON_CONDOR, "dte": dte, "expiry": expiry.isoformat(),
            "legs": [{"side": "sell", "type": "put", "strike": sp},
                     {"side": "buy", "type": "put", "strike": lp},
                     {"side": "sell", "type": "call", "strike": sc},
                     {"side": "buy", "type": "call", "strike": lc}],
            "credit_usd": round(credit * CONTRACT, 2),
            "max_risk_usd": round((width - credit) * CONTRACT, 2), "width": width}
    return _finish(cand, spot, iv, t, sp - credit, sc + credit)


def build_structure(structure: str, spot: float, iv: float, width: float,
                    dte: int, expiry: date, low_delta: bool = False,
                    no_upside_risk: bool = False) -> dict | None:
    if structure == CALL_SPREAD:
        return build_call_spread(spot, iv, width, dte, expiry, low_delta=low_delta)
    if structure == IRON_CONDOR:
        return build_iron_condor(spot, iv, width, dte, expiry, low_delta=low_delta,
                                 no_upside_risk=no_upside_risk)
    cand = build_spread(spot, iv, width, dte, expiry, low_delta=low_delta)   # put spread
    if cand is None:
        return None
    return _finish(cand, spot, iv, t=max(dte, 1) / 365.0,
                   put_be=cand["legs"][0]["strike"] - cand["credit_usd"] / CONTRACT,
                   call_be=None)


def eruption_veto_ok(row: pd.Series) -> bool:
    """v3 veto: ONLY a predicted eruption (or missing signal) blocks. Magnitude/calm advise."""
    for field in ("eruption_predicted_5d", "eruption_predicted_21d"):
        if pd.isna(row.get(field)):
            return False
    return not (bool(row["eruption_predicted_5d"]) or bool(row["eruption_predicted_21d"]))


def _leg_value(leg: dict, spot: float, iv: float, t: float) -> float:
    k = float(leg["strike"])
    return bs.bs_call(spot, k, iv, t) if leg["type"] == "call" else bs.bs_put(spot, k, iv, t)


def simulate_exit(candidate: dict, frame: pd.DataFrame, entry: pd.Timestamp,
                  expiry: date, stop_loss: bool = False,
                  manage_dte: bool = False) -> dict | None:
    """50%-profit-target exit via daily BS repricing (entry IV held constant along path).
    Falls back to expiry intrinsic if the target is never reached. Returns economics."""
    iv = candidate["entry_iv"]
    entry_credit_ps = candidate["credit_usd"] / CONTRACT
    target_value = 0.5 * entry_credit_ps          # close when the spread can be bought back for <= this
    expiry_ts = pd.Timestamp(expiry)
    path = frame.loc[(frame.index > entry) & (frame.index <= expiry_ts), "spot"].dropna()
    cost = config.BACKTEST_COST_PER_LEG_RT * len(candidate["legs"])
    for stamp, spot in path.items():
        t = max((expiry_ts - stamp).days, 0) / 365.0
        spread_val = sum(_leg_value(leg, float(spot), iv, t) * (1.0 if leg["side"] == "sell" else -1.0)
                         for leg in candidate["legs"])
        # v11 stop-loss: cost to close reached (1 + STOP_LOSS_MULT) x credit -> realized
        # loss of STOP_LOSS_MULT x credit. Checked BEFORE the profit target on the same bar.
        if stop_loss and spread_val >= (1.0 + STOP_LOSS_MULT) * entry_credit_ps:
            realized = (entry_credit_ps - spread_val) * CONTRACT
            return {"exit": "stop", "exit_date": str(stamp.date()),
                    "terminal_spot": round(float(spot), 4),
                    "holding_days": (stamp.date() - entry.date()).days,
                    "pnl_usd": round(realized - cost, 2), "cost_usd": round(cost, 2)}
        # v14: manage remaining positions at 21 DTE (gamma window), if not already closed.
        if manage_dte and (expiry_ts - stamp).days <= MANAGE_DTE:
            realized = (entry_credit_ps - spread_val) * CONTRACT
            return {"exit": "dte21", "exit_date": str(stamp.date()),
                    "terminal_spot": round(float(spot), 4),
                    "holding_days": (stamp.date() - entry.date()).days,
                    "pnl_usd": round(realized - cost, 2), "cost_usd": round(cost, 2)}
        if spread_val <= target_value:
            realized = (entry_credit_ps - spread_val) * CONTRACT
            return {"exit": "target", "exit_date": str(stamp.date()),
                    "terminal_spot": round(float(spot), 4),
                    "holding_days": (stamp.date() - entry.date()).days,
                    "pnl_usd": round(realized - cost, 2), "cost_usd": round(cost, 2)}
    # target never hit in the available path
    if path.empty or frame.index.max() < expiry_ts:
        return None                               # censored: cannot settle, drop the observation
    terminal_spot = float(path.iloc[-1])          # hold to expiry intrinsic
    econ = shadow.candidate_pnl(candidate, terminal_spot)
    return {"exit": "expiry", "exit_date": str(path.index[-1].date()),
            "terminal_spot": round(terminal_spot, 4),
            "holding_days": (path.index[-1].date() - entry.date()).days, **econ}


def _terminal(frame: pd.DataFrame, entry: pd.Timestamp, expiry: date):
    expiry_ts = pd.Timestamp(expiry)
    if frame.index.max() < expiry_ts:
        return None            # censored: not yet settled, must be dropped
    window = frame.loc[(frame.index >= entry) & (frame.index <= expiry_ts), "spot"].dropna()
    if window.empty:
        return None
    return window.index[-1], float(window.iloc[-1])


def build_ledger(signals: pd.DataFrame, histories: dict[str, pd.DataFrame],
                 universe: dict,
                 eligible: dict[str, set] | None = None) -> tuple[list[dict], dict]:
    """Replay entries. `eligible` (symbol -> allowed dates) applies the point-in-time
    Qlib per-asset filter; None reproduces the v1 global-only population."""
    factor = premium_factor(signals)
    last_expiry: dict[str, date] = {}
    ledger: list[dict] = []
    diag = {"signal_rows": int(len(signals)), "regime_ok_rows": 0,
            "entries": Counter(), "dropped_censored": 0, "dropped_overlap": Counter(),
            "dropped_no_structure": Counter(), "dropped_iv_rv": 0,
            "dropped_qlib_filter": 0}

    for stamp, row in signals.iterrows():
        if not global_regime_ok(row):
            continue
        diag["regime_ok_rows"] += 1
        pf = factor.get(stamp, np.nan)
        if not np.isfinite(pf) or pf < IV_RV_FLOOR:
            diag["dropped_iv_rv"] += 1      # degenerate market-wide test (see spec)
            continue
        now = datetime.combine(stamp.date(), time(9, 5), tzinfo=timezone.utc)
        expiry, dte = strategies.target_expiry(now)

        for symbol, policy in universe.items():
            frame = histories.get(symbol)
            if frame is None or stamp not in frame.index:
                continue
            if symbol in last_expiry and stamp.date() <= last_expiry[symbol]:
                diag["dropped_overlap"][symbol] += 1
                continue
            if eligible is not None and stamp.date() not in eligible.get(symbol, set()):
                diag["dropped_qlib_filter"] += 1
                continue
            asset = frame.loc[stamp]
            spot, rv = float(asset["spot"]), float(asset["rv20"])
            if not (spot > 0 and rv > 0):
                continue
            candidate = build_spread(spot, rv * float(pf), float(policy["spread_width"]),
                                     dte, expiry)
            if candidate is None:
                diag["dropped_no_structure"][symbol] += 1
                continue
            terminal = _terminal(frame, stamp, expiry)
            if terminal is None:
                diag["dropped_censored"] += 1
                continue
            terminal_date, terminal_spot = terminal
            economics = shadow.candidate_pnl(candidate, terminal_spot)
            ledger.append({
                "experiment_id": "options_etf_gate_v1",
                "symbol": symbol, "bucket": policy["bucket"],
                "strategy": candidate["strategy"],
                "entry_date": str(stamp.date()), "expiry": candidate["expiry"],
                "terminal_date": str(terminal_date.date()),
                "entry_spot": round(spot, 4), "rv20": round(rv, 6),
                "premium_factor": round(float(pf), 4),
                "entry_iv_proxy": round(rv * float(pf), 6),
                "magnitude_pct": round(float(row["magnitude_pct"]), 4),
                "terminal_spot": round(terminal_spot, 4),
                "width": candidate["width"],
                "legs": candidate["legs"], **economics,
            })
            diag["entries"][symbol] += 1
            last_expiry[symbol] = candidate_expiry(candidate)

    for key in ("entries", "dropped_overlap", "dropped_no_structure"):
        diag[key] = dict(diag[key])
    return ledger, diag


def candidate_expiry(candidate: dict) -> date:
    return date.fromisoformat(candidate["expiry"])


def cluster_by_date(ledger: list[dict]) -> list[float]:
    """Collapse same-date entries into one observation (mean PnL).

    SPY/QQQ/DIA/IWM are highly correlated; counting concurrent positions as
    independent would inflate n and fabricate a PBO/DSR verdict.
    """
    buckets: dict[str, list[float]] = defaultdict(list)
    for row in ledger:
        buckets[row["entry_date"]].append(float(row["pnl_usd"]))
    return [float(np.mean(v)) for _, v in sorted(buckets.items())]


def evaluate(ledger: list[dict], n_trials: int) -> dict:
    evaluate_gate = backtest._load_macro_modules()[5]
    pooled = [float(row["pnl_usd"]) for row in ledger]
    clustered = cluster_by_date(ledger)
    spy_only = [float(row["pnl_usd"]) for row in ledger if row["symbol"] == "SPY"]

    def _view(values: list[float]) -> dict:
        return {"n_trades": len(values),
                "stats": backtest._pnl_stats(values),
                "gate": evaluate_gate(np.asarray(values, dtype=float), n_trials=n_trials)}

    return {
        "pooled": {**_view(pooled),
                   "warning": "naive; same-date correlated entries counted as independent"},
        "cluster_adjusted": {**_view(clustered),
                             "note": "HEADLINE — one observation per entry date; the only view a promotion decision may use"},
        "spy_only": {**_view(spy_only),
                     "note": "directly comparable to options_gate_v1"},
    }


def route_from_lean(lean, conviction: float, min_directional: float = 0.70,
                    no_call_spreads: bool = False) -> str | None:
    """Combined Qlib lean -> structure. Directional needs the conviction bar; neutral
    (iron condor) does not (it pays via the stricter IV/RV + POP floors instead).

    v8 (no_call_spreads=True): a bearish lean produces NO trade instead of a short call
    spread -- selling upside premium fights the positive equity drift.
    """
    try:
        v = int(lean)
    except (TypeError, ValueError):
        return None
    if v == 1:
        return PUT_SPREAD if conviction >= min_directional else None
    if v == -1:
        if no_call_spreads:
            return None
        return CALL_SPREAD if conviction >= min_directional else None
    if v == 0:
        return IRON_CONDOR
    return None


def v3_eligible(scores: pd.DataFrame, universe: dict,
                no_call_spreads: bool = False) -> dict[str, list[tuple]]:
    """symbol -> [(date, structure), ...] from point-in-time leans (all three structures)."""
    wanted = {policy["qlib_asset"]: symbol for symbol, policy in universe.items()}
    sub = scores[scores["asset"].isin(wanted)]
    out: dict[str, list[tuple]] = {symbol: [] for symbol in universe}
    for _, r in sub.iterrows():
        structure = route_from_lean(r["lean"], float(r.get("conviction") or 0.0),
                                    no_call_spreads=no_call_spreads)
        if structure is None:
            continue
        out[wanted[str(r["asset"])]].append((r["date"].date()
                                             if hasattr(r["date"], "date") else r["date"], structure))
    return out


PUT_SIDE = {PUT_SPREAD, IRON_CONDOR}   # structures carrying short-put exposure (v4 gate)


def market_risk_off_days(signals: pd.DataFrame, window: int = 200) -> set:
    """Dates where SPY (signals['spot']) is BELOW its own N-day SMA = market bearish.
    v6 index-level overlay. Point-in-time (rolling mean uses data <= t)."""
    spy = signals["spot"]
    sma = spy.rolling(window, min_periods=window).mean()
    below = spy < sma
    return {d.date() for d, b in below.items() if bool(b)}


def build_ledger_v3(signals: pd.DataFrame, histories: dict[str, pd.DataFrame],
                    universe: dict, eligible: dict[str, list[tuple]],
                    trend_filter: bool = False,
                    trend_col: str = "sma50",
                    market_risk_off: set | None = None,
                    symmetric_trend: bool = False,
                    momentum_gate: bool = False, low_delta: bool = False,
                    no_upside_risk: bool = False, stop_loss: bool = False,
                    manage_dte: bool = False) -> tuple[list[dict], dict]:
    """v3 replay: eruption-only veto, lean-routed structure, POP>=0.51, $1000 cap,
    50%-target exit. Also stores a hold-to-expiry PnL on the same entries for comparison.

    v4 (trend_filter=True): additionally DROP put-side structures (put spread, iron
    condor) when the symbol is below its 50-day SMA -- never sell puts into a downtrend.
    """
    factor = premium_factor(signals)
    regime_ok = {d.date() for d, row in signals.iterrows() if eruption_veto_ok(row)}
    factor_by_day = {d.date(): factor.get(d) for d in signals.index}
    last_expiry: dict[str, date] = {}
    ledger: list[dict] = []
    diag = {"regime_ok_days": len(regime_ok), "entries": Counter(),
            "by_structure": Counter(), "dropped_pop_or_cap": 0, "dropped_censored": 0,
            "dropped_no_structure": 0, "dropped_trend": 0, "dropped_market": 0,
            "exits": Counter()}

    for symbol, dated in sorted(eligible.items()):
        frame = histories.get(symbol)
        if frame is None:
            continue
        policy_width = float(universe[symbol]["spread_width"])
        for day, structure in sorted(dated):
            if day not in regime_ok:
                continue
            if symbol in last_expiry and day <= last_expiry[symbol]:
                continue
            stamp = pd.Timestamp(day)
            if stamp not in frame.index:
                continue
            pf = factor_by_day.get(day)
            if pf is None or not np.isfinite(pf) or pf < IV_RV_FLOOR:
                continue
            row = frame.loc[stamp]
            spot, rv = float(row["spot"]), float(row["rv20"])
            if not (spot > 0 and rv > 0):
                continue
            # v4/v5 trend gate: never sell put-side premium below the trend average
            # (v4 = 50-day, v5 = 200-day). A missing average also blocks (fail-safe).
            if trend_filter and structure in PUT_SIDE:
                sma = row.get(trend_col)
                if sma is None or pd.isna(sma) or spot < float(sma):
                    diag["dropped_trend"] += 1
                    continue
            # v9 symmetric gate: never sell CALL-side premium into an uptrend.
            if symmetric_trend and structure == CALL_SPREAD:
                sma = row.get(trend_col)
                if sma is None or pd.isna(sma) or spot > float(sma):
                    diag["dropped_trend"] += 1
                    continue
            # v10 momentum gate: do not sell CALL premium on a high-momentum symbol --
            # sustained growth/optimism keeps running through short strikes.
            if momentum_gate and structure == CALL_SPREAD:
                mom = row.get("mom126")
                if mom is None or pd.isna(mom) or float(mom) > MOMENTUM_MAX:
                    diag["dropped_trend"] += 1
                    continue
            # v6 market overlay: no put-side anywhere when SPY is below its 200-day.
            if market_risk_off is not None and structure in PUT_SIDE and day in market_risk_off:
                diag["dropped_market"] += 1
                continue
            now = datetime.combine(day, time(9, 5), tzinfo=timezone.utc)
            expiry, dte = strategies.target_expiry(now)
            cand = build_structure(structure, spot, rv * float(pf), policy_width, dte, expiry,
                                   low_delta=low_delta, no_upside_risk=no_upside_risk)
            if cand is None:
                diag["dropped_pop_or_cap"] += 1
                continue
            econ = simulate_exit(cand, frame, stamp, expiry, stop_loss=stop_loss,
                                 manage_dte=manage_dte)
            if econ is None:
                diag["dropped_censored"] += 1
                continue
            # Hold-to-expiry baseline on the SAME entry: settle at the TRUE expiry spot
            # (not the early target-exit spot) so the two exit policies compare fairly.
            exp_term = _terminal(frame, stamp, expiry)
            hold_pnl = (shadow.candidate_pnl(cand, exp_term[1])["pnl_usd"]
                        if exp_term else None)
            ledger.append({
                "experiment_id": "options_etf_gate_v3", "symbol": symbol,
                "bucket": universe[symbol]["bucket"], "strategy": structure,
                "entry_date": str(day), "expiry": cand["expiry"],
                "pop": cand["pop"], "credit_usd": cand["credit_usd"],
                "max_risk_usd": cand["max_risk_usd"], "entry_iv": round(cand["entry_iv"], 6),
                "legs": cand["legs"], "hold_to_expiry_pnl_usd": hold_pnl, **econ,
            })
            diag["entries"][symbol] += 1
            diag["by_structure"][structure] += 1
            diag["exits"][econ["exit"]] += 1
            last_expiry[symbol] = candidate_expiry(cand)

    for k in ("entries", "by_structure", "exits"):
        diag[k] = dict(diag[k])
    return ledger, diag


def _per_year(ledger: list[dict]) -> dict:
    years: dict[str, list[dict]] = defaultdict(list)
    for r in ledger:
        years[r["entry_date"][:4]].append(r)
    out = {}
    for yr, rows in sorted(years.items()):
        pnls = [float(r["pnl_usd"]) for r in rows]
        targets = sum(1 for r in rows if r.get("exit") == "target")
        wins = sum(1 for p in pnls if p > 0)
        gains = sum(p for p in pnls if p > 0)
        losses = -sum(p for p in pnls if p < 0)
        out[yr] = {"n": len(pnls), "win_rate": round(wins / len(pnls), 4),
                   "total_pnl_usd": round(sum(pnls), 2),
                   "profit_factor": round(gains / losses, 4) if losses else None,
                   "avg_holding_days": round(np.mean([r["holding_days"] for r in rows]), 1),
                   "pct_exited_at_target": round(targets / len(rows), 4)}
    return out


def _equity_curve(ledger: list[dict]) -> list[dict]:
    rows = sorted(ledger, key=lambda r: (r.get("exit_date") or r["entry_date"], r["entry_date"]))
    cum = 0.0
    curve = []
    for r in rows:
        cum += float(r["pnl_usd"])
        curve.append({"date": r.get("exit_date") or r["entry_date"],
                      "symbol": r["symbol"], "pnl_usd": round(float(r["pnl_usd"]), 2),
                      "cumulative_usd": round(cum, 2)})
    return curve


def run_v3() -> tuple[dict, list[dict], list[dict]]:
    return _run_v3_family("options_etf_gate_v3", trend_filter=False)


def run_v4() -> tuple[dict, list[dict], list[dict]]:
    """v3 + a per-symbol trend gate (no put-side premium below the 50-day SMA)."""
    return _run_v3_family("options_etf_gate_v4", trend_filter=True, trend_col="sma50")


def run_v5() -> tuple[dict, list[dict], list[dict]]:
    """v4 with a SLOWER 200-day trend gate (holds defense through a full bear)."""
    return _run_v3_family("options_etf_gate_v5", trend_filter=True, trend_col="sma200")


def run_v6() -> tuple[dict, list[dict], list[dict]]:
    """v5 + an index-level risk-off overlay (no put-side when SPY < its 200-day)."""
    return _run_v3_family("options_etf_gate_v6", trend_filter=True, trend_col="sma200",
                          market_overlay=True)


def tail_hedge_ledger(market: pd.DataFrame) -> list[dict]:
    """v7 overlay: one long SPY put per month (~7% OTM, ~45 DTE), held to expiry, BS-priced
    at the entry VIX. A risk overlay, not a gate trial. Returns per-hedge rows with PnL."""
    spy = market["spot"].dropna()
    vix = market["vix"].reindex(spy.index).ffill()
    months = spy.groupby([spy.index.year, spy.index.month]).apply(lambda s: s.index[0])
    rows: list[dict] = []
    for entry in months:
        spot = float(spy.loc[entry])
        iv = float(vix.loc[entry]) / 100.0
        if not (spot > 0 and iv > 0):
            continue
        now = datetime.combine(entry.date(), time(9, 5), tzinfo=timezone.utc)
        expiry, dte = strategies.target_expiry(now)
        expiry_ts = pd.Timestamp(expiry)
        if spy.index.max() < expiry_ts:
            continue                                   # not yet settled
        strike = round(spot * 0.93)                    # 7% OTM long put
        cost = bs.bs_put(spot, strike, iv, max(dte, 1) / 365.0) * CONTRACT
        s_exp = float(spy.loc[spy.index <= expiry_ts].iloc[-1])
        payoff = max(strike - s_exp, 0.0) * CONTRACT
        fee = config.BACKTEST_COST_PER_LEG_RT
        rows.append({"entry_date": str(entry.date()), "expiry": str(expiry),
                     "strike": strike, "entry_spot": round(spot, 2), "entry_vix": round(iv * 100, 2),
                     "cost_usd": round(cost, 2), "payoff_usd": round(payoff, 2),
                     "pnl_usd": round(payoff - cost - fee, 2)})
    return rows


def _hedge_by_year(hedge: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for yr in sorted({r["entry_date"][:4] for r in hedge}):
        rs = [r for r in hedge if r["entry_date"].startswith(yr)]
        pnls = [r["pnl_usd"] for r in rs]
        out[yr] = {"n": len(rs), "cost_usd": round(sum(r["cost_usd"] for r in rs), 2),
                   "payoff_usd": round(sum(r["payoff_usd"] for r in rs), 2),
                   "pnl_usd": round(sum(pnls), 2),
                   "paid_months": sum(1 for r in rs if r["payoff_usd"] > 0)}
    return out


def run_v7() -> dict:
    """v5 book + rolling long-SPY-put tail hedge, combined at the annual (pooled) level."""
    v5_score, v5_ledger, _ = run_v5()
    market = backtest.load_market_history()
    hedge = tail_hedge_ledger(market)
    # restrict the hedge to the same window the book covers
    yrs = set(v5_score["per_year"].keys())
    hedge = [h for h in hedge if h["entry_date"][:4] in yrs]
    hy = _hedge_by_year(hedge)
    combined = {}
    book_total = hedge_total = net_total = 0.0
    for yr, s in v5_score["per_year"].items():
        book = float(s["total_pnl_usd"])
        h = float(hy.get(yr, {}).get("pnl_usd", 0.0))
        combined[yr] = {"book_pnl_usd": round(book, 2), "hedge_pnl_usd": round(h, 2),
                        "net_pnl_usd": round(book + h, 2),
                        "hedge_paid_months": hy.get(yr, {}).get("paid_months", 0)}
        book_total += book; hedge_total += h; net_total += book + h
    return {
        "experiment_id": "options_etf_gate_v7", "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW", "advisory_only": True,
        "design": "v5 short-premium book + monthly long SPY put (~7% OTM, ~45 DTE) tail hedge",
        "per_year": combined,
        "totals": {"book_pnl_usd": round(book_total, 2), "hedge_pnl_usd": round(hedge_total, 2),
                   "net_pnl_usd": round(net_total, 2)},
        "hedge_detail": hy,
        "note": ("Pooled annual view. The hedge is a portfolio overlay, not a gate trial; "
                 "v5's per-trade gate verdict (DSR<0) is unchanged. Model-priced -> upper bound."),
    }


def run_v8() -> tuple[dict, list[dict], list[dict]]:
    """v5 minus the bearish short-call-spread structure (put spreads + condors only)."""
    return _run_v3_family("options_etf_gate_v8", trend_filter=True, trend_col="sma200",
                          no_call_spreads=True)


def _v10_base(experiment_id: str, **kw):
    return _run_v3_family(experiment_id, trend_filter=True, trend_col="sma200",
                          momentum_gate=True, **kw)


def run_v11():
    """v10 + 2x-credit stop-loss (risk-management lever)."""
    return _v10_base("options_etf_gate_v11", stop_loss=True)


def run_v12():
    """v10 with ~16-delta short strikes (strike-selection lever)."""
    return _v10_base("options_etf_gate_v12", low_delta=True)


def run_v13():
    """v10 with a broken-wing (no-upside-risk) condor (structure lever)."""
    return _v10_base("options_etf_gate_v13", no_upside_risk=True)


def run_v14():
    """v10 + close remaining positions at 21 DTE (Sosnoff time-exit lever)."""
    return _v10_base("options_etf_gate_v14", manage_dte=True)


def run_v10() -> tuple[dict, list[dict], list[dict]]:
    """v5 + momentum gate: no call-side premium sold on high-momentum symbols."""
    return _run_v3_family("options_etf_gate_v10", trend_filter=True, trend_col="sma200",
                          momentum_gate=True)


def run_v9() -> tuple[dict, list[dict], list[dict]]:
    """v5 + symmetric trend gate: no call-side premium sold into an uptrend."""
    return _run_v3_family("options_etf_gate_v9", trend_filter=True, trend_col="sma200",
                          symmetric_trend=True)


def _run_v3_family(experiment_id: str, trend_filter: bool,
                   trend_col: str = "sma50",
                   market_overlay: bool = False,
                   no_call_spreads: bool = False,
                   symmetric_trend: bool = False,
                   momentum_gate: bool = False, low_delta: bool = False,
                   no_upside_risk: bool = False, stop_loss: bool = False,
                   manage_dte: bool = False) -> tuple[dict, list[dict], list[dict]]:
    from . import qlib_evidence
    prereg = load_prereg(config.EXPERIMENTS_DIR / f"{experiment_id}.json")
    universe = qlib_evidence.load_universe("options_etf_universe_v2")
    scores = qlib_evidence.load_scores()
    market = backtest.load_market_history()
    replay, replay_meta, panel_meta = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)
    lo, hi = scores["date"].min(), scores["date"].max()
    signals = signals.loc[(signals.index >= lo) & (signals.index <= hi)]
    histories = load_symbol_history(universe)
    eligible = v3_eligible(scores, universe, no_call_spreads=no_call_spreads)
    risk_off = market_risk_off_days(signals, 200) if market_overlay else None
    ledger, diag = build_ledger_v3(signals, histories, universe, eligible,
                                   trend_filter=trend_filter, trend_col=trend_col,
                                   market_risk_off=risk_off, symmetric_trend=symmetric_trend,
                                   momentum_gate=momentum_gate, low_delta=low_delta,
                                   no_upside_risk=no_upside_risk, stop_loss=stop_loss,
                                   manage_dte=manage_dte)
    for r in ledger:
        r["experiment_id"] = experiment_id

    n_trials = int(prereg["trial_accounting"]["n_trials"])
    views = evaluate(ledger, n_trials)
    hold_ledger = [{**r, "pnl_usd": r["hold_to_expiry_pnl_usd"]} for r in ledger
                   if r["hold_to_expiry_pnl_usd"] is not None]
    hold_cluster = cluster_by_date(hold_ledger)
    headline = views["cluster_adjusted"]
    scorecard = {
        "experiment_id": experiment_id,
        "trend_filter": trend_filter, "trend_col": trend_col if trend_filter else None,
        "market_overlay": market_overlay, "no_call_spreads": no_call_spreads,
        "symmetric_trend": symmetric_trend, "momentum_gate": momentum_gate,
        "low_delta": low_delta, "no_upside_risk": no_upside_risk,
        "stop_loss": stop_loss, "manage_dte": manage_dte,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW", "advisory_only": True, "n_trials": n_trials,
        "exit_policy": "50%_profit_target_then_expiry",
        "data": {"symbols_loaded": sorted(histories),
                 "window": [str(lo.date()), str(hi.date())], "macro_panel": panel_meta},
        "declared_deviations": prereg.get("declared_deviations")
            or prereg.get("guardrails", {}).get("same_deviations"),
        "minimum_pop": MIN_POP, "per_trade_cap_usd": config.MAX_TRADE_RISK_USD,
        "diagnostics": diag,
        "per_year": _per_year(ledger),
        "views": views,
        "hold_to_expiry_comparison": {
            "cluster_adjusted_n": len(hold_cluster),
            "cluster_adjusted_total_usd": round(float(np.sum(hold_cluster)), 2) if hold_cluster else 0.0,
            "note": "same entries, settled at expiry instead of the 50% target",
        },
        "headline_view": "cluster_adjusted",
        "pbo_available": headline["n_trades"] >= 40,
        "cleared": bool(headline["gate"].get("passes") is True),
        "note": ("Proxied IV, constant-IV repricing, model credit -> an UPPER BOUND on the "
                 "live edge. A pass changes only a display badge; the desk stays SHADOW."),
    }
    return scorecard, ledger, _equity_curve(ledger)


def run() -> tuple[dict, list[dict]]:
    prereg = load_prereg()
    universe = load_universe()
    market = backtest.load_market_history()
    replay, replay_meta, panel_meta = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)
    histories = load_symbol_history(universe)
    ledger, diag = build_ledger(signals, histories, universe)
    n_trials = int(prereg["trial_accounting"]["n_trials"])
    views = evaluate(ledger, n_trials)
    headline = views["cluster_adjusted"]
    scorecard = {
        "experiment_id": "options_etf_gate_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW", "advisory_only": True, "n_trials": n_trials,
        "data": {"qlib_csv_dir": str(config.QLIB_CSV_DIR),
                 "symbols_loaded": sorted(histories),
                 "market_start": str(market.index.min().date()),
                 "market_end": str(market.index.max().date()),
                 "macro_panel": panel_meta},
        "signal_replay": replay_meta,
        "declared_deviations": prereg["declared_deviations_from_the_live_lane"],
        "independence": prereg["independence_and_inference"],
        "diagnostics": diag,
        "views": views,
        "headline_view": "cluster_adjusted",
        "pbo_floor_trades": 40,
        "pbo_available": headline["n_trades"] >= 40,
        "cleared": bool(headline["gate"].get("passes") is True),
        "note": ("Superset population (no Qlib filter), proxied IV, model credit — an upper "
                 "bound on the live edge. A pass changes only a display badge; the desk "
                 "stays paper/advisory and SHADOW."),
    }
    return scorecard, ledger


def run_v2() -> tuple[dict, list[dict]]:
    """options_etf_gate_v2 — same structure, plus the point-in-time Qlib per-asset filter.

    v1 showed a purely global rule locks every symbol to identical entry dates. This run
    tests whether Qlib's cross-sectional lean decorrelates entry timing enough for the
    canonical gate to decide. Fewer trades are EXPECTED; independent observations should
    rise. If cluster-adjusted n does not rise well above v1's 41, the filter added no
    evidence and that is the honest result.
    """
    from . import qlib_evidence

    prereg = load_prereg(config.EXPERIMENTS_DIR / "options_etf_gate_v2.json")
    universe = qlib_evidence.load_universe("options_etf_universe_v2")
    scores = qlib_evidence.load_scores()
    eligible = qlib_evidence.eligible_map(scores, universe)

    market = backtest.load_market_history()
    replay, replay_meta, panel_meta = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)

    # Never extrapolate beyond the window the score export actually covers.
    lo, hi = scores["date"].min(), scores["date"].max()
    signals = signals.loc[(signals.index >= lo) & (signals.index <= hi)]

    histories = load_symbol_history(universe)
    ledger, diag = build_ledger(signals, histories, universe, eligible)
    n_trials = int(prereg["trial_accounting"]["n_trials"])
    views = evaluate(ledger, n_trials)
    headline = views["cluster_adjusted"]
    scorecard = {
        "experiment_id": "options_etf_gate_v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW", "advisory_only": True, "n_trials": n_trials,
        "data": {"qlib_csv_dir": str(config.QLIB_CSV_DIR),
                 "symbols_loaded": sorted(histories),
                 "window": [str(lo.date()), str(hi.date())],
                 "macro_panel": panel_meta},
        "signal_replay": replay_meta,
        "qlib_filter": prereg["entry_policy"]["qlib_filter"],
        "carried_over_deviations": prereg["carried_over_deviations"],
        "independence": prereg["independence_and_inference"],
        "diagnostics": diag,
        "views": views,
        "headline_view": "cluster_adjusted",
        "pbo_floor_trades": 40,
        "pbo_available": headline["n_trades"] >= 40,
        "cleared": bool(headline["gate"].get("passes") is True),
        "comparison_to_v1": {
            "v1_cluster_adjusted_n": 41,
            "v2_cluster_adjusted_n": headline["n_trades"],
            "filter_added_independent_observations": headline["n_trades"] > 41,
        },
        "note": ("Qlib-filtered population. Proxied IV and model credit still apply, so "
                 "this remains an upper bound. A pass changes only a display badge."),
    }
    return scorecard, ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pre-registered P7 ETF options gate")
    parser.add_argument("--scorecard", type=Path,
                        default=config.SCORECARDS_DIR / "options_etf_gate_v1.json")
    parser.add_argument("--ledger", type=Path,
                        default=config.SCORECARDS_DIR / "options_etf_gate_v1_trades.jsonl")
    parser.add_argument("--v2", action="store_true",
                        help="run options_etf_gate_v2 (adds the point-in-time Qlib filter)")
    parser.add_argument("--v3", action="store_true",
                        help="run options_etf_gate_v3 (3 structures, POP>=0.51, 50%% target exit)")
    parser.add_argument("--v4", action="store_true",
                        help="run options_etf_gate_v4 (v3 + per-symbol trend gate: no put-side below SMA50)")
    parser.add_argument("--v5", action="store_true",
                        help="run options_etf_gate_v5 (slower 200-day trend gate)")
    for _v in ("v11", "v12", "v13", "v14"):
        parser.add_argument(f"--{_v}", action="store_true", help=f"run options_etf_gate_{_v}")
    parser.add_argument("--v10", action="store_true",
                        help="run options_etf_gate_v10 (v5 + momentum gate on calls)")
    parser.add_argument("--v9", action="store_true",
                        help="run options_etf_gate_v9 (v5 + symmetric trend gate on calls)")
    parser.add_argument("--v8", action="store_true",
                        help="run options_etf_gate_v8 (v5 without bearish call spreads)")
    parser.add_argument("--v6", action="store_true",
                        help="run options_etf_gate_v6 (v5 + SPY-200-day market risk-off overlay)")
    parser.add_argument("--v7", action="store_true",
                        help="run options_etf_gate_v7 (v5 book + monthly long-SPY-put tail hedge)")
    args = parser.parse_args()
    if args.v7:
        result = run_v7()
        out = config.SCORECARDS_DIR / "options_etf_gate_v7.json"
        backtest._atomic_write(out, json.dumps(result, indent=2, default=str) + "\n")
        print(f"options_etf_gate_v7 (v5 book + tail hedge) -> {out}")
        print("  year |   book |  hedge |    net | hedge paid mo")
        for yr, s in result["per_year"].items():
            print(f"  {yr} | {s['book_pnl_usd']:6.0f} | {s['hedge_pnl_usd']:6.0f} | "
                  f"{s['net_pnl_usd']:6.0f} | {s['hedge_paid_months']}")
        t = result["totals"]
        print(f"  TOTAL book ${t['book_pnl_usd']} | hedge ${t['hedge_pnl_usd']} | net ${t['net_pnl_usd']}")
        print("  desk status: SHADOW / advisory only (hedge is a risk overlay, not a gate trial)")
        return
    if args.v3 or args.v4 or args.v5 or args.v6 or args.v8 or args.v9 or args.v10 or args.v11 or args.v12 or args.v13 or args.v14:
        _extra = {"v11": args.v11, "v12": args.v12, "v13": args.v13, "v14": args.v14}
        _hit = next((k for k, v in _extra.items() if v), None)
        tag = (f"options_etf_gate_{_hit}" if _hit else
               "options_etf_gate_v10" if args.v10 else
               "options_etf_gate_v9" if args.v9 else
               "options_etf_gate_v8" if args.v8 else
               "options_etf_gate_v6" if args.v6 else
               "options_etf_gate_v5" if args.v5 else
               "options_etf_gate_v4" if args.v4 else "options_etf_gate_v3")
        _runners = {"v11": run_v11, "v12": run_v12, "v13": run_v13, "v14": run_v14}
        scorecard, ledger, equity = (_runners[_hit]() if _hit else
                                     run_v10() if args.v10 else
                                     run_v9() if args.v9 else
                                     run_v8() if args.v8 else
                                     run_v6() if args.v6 else run_v5() if args.v5 else
                                     run_v4() if args.v4 else run_v3())
        score_path = config.SCORECARDS_DIR / f"{tag}.json"
        ledger_path = config.SCORECARDS_DIR / f"{tag}_trades.jsonl"
        equity_path = config.SCORECARDS_DIR / f"{tag}_equity.csv"
        backtest.write_results(scorecard, ledger, score_path, ledger_path)
        lines = ["date,symbol,pnl_usd,cumulative_usd"] + [
            f"{e['date']},{e['symbol']},{e['pnl_usd']},{e['cumulative_usd']}" for e in equity]
        backtest._atomic_write(equity_path, "\n".join(lines) + "\n")
        print(f"{tag} (trend_filter={scorecard.get('trend_filter', False)}) -> {score_path}")
        for name, view in scorecard["views"].items():
            gate = view["gate"]
            dsr = (gate.get("deflated_sharpe") or {}).get("ratio")
            print(f"  {name:17s} n={view['n_trades']:4d} pass={gate['passes']} "
                  f"DSR={dsr} PBO={gate.get('pbo')} PF={gate.get('profit_factor')} "
                  f"total=${view['stats'].get('total_usd')}")
        print("  per-year (50% target):")
        for yr, s in scorecard["per_year"].items():
            print(f"    {yr}: n={s['n']:4d} win={s['win_rate']:.0%} PnL=${s['total_pnl_usd']:>9.0f} "
                  f"PF={s['profit_factor']} tgt={s['pct_exited_at_target']:.0%} hold={s['avg_holding_days']}d")
        hc = scorecard["hold_to_expiry_comparison"]
        print(f"  hold-to-expiry (same entries): cluster total ${hc['cluster_adjusted_total_usd']}")
        print(f"  structures: {scorecard['diagnostics']['by_structure']} | exits: {scorecard['diagnostics']['exits']}"
              + (f" | dropped_trend: {scorecard['diagnostics'].get('dropped_trend')}"
                 if (args.v4 or args.v5 or args.v6) else "")
              + (f" | dropped_market: {scorecard['diagnostics'].get('dropped_market')}"
                 if args.v6 else ""))
        print(f"  equity curve -> {equity_path}")
        print("  desk status: SHADOW / advisory only")
        return
    if args.v2:
        scorecard, ledger = run_v2()
        score_path = config.SCORECARDS_DIR / "options_etf_gate_v2.json"
        ledger_path = config.SCORECARDS_DIR / "options_etf_gate_v2_trades.jsonl"
        backtest.write_results(scorecard, ledger, score_path, ledger_path)
        print(f"options_etf_gate_v2 -> {score_path}")
        for name, view in scorecard["views"].items():
            gate = view["gate"]
            dsr = (gate.get("deflated_sharpe") or {}).get("ratio")
            print(f"  {name:17s} n={view['n_trades']:4d} pass={gate['passes']} "
                  f"DSR={dsr} PBO={gate.get('pbo')} PF={gate.get('profit_factor')}")
        cmp = scorecard["comparison_to_v1"]
        print(f"  cluster n: v1={cmp['v1_cluster_adjusted_n']} -> v2={cmp['v2_cluster_adjusted_n']} "
              f"(filter added evidence={cmp['filter_added_independent_observations']})")
        print("  desk status: SHADOW / advisory only")
        return
    scorecard, ledger = run()
    backtest.write_results(scorecard, ledger, args.scorecard, args.ledger)
    print(f"P7 options_etf_gate_v1 -> {args.scorecard}")
    for name, view in scorecard["views"].items():
        gate = view["gate"]
        dsr = (gate.get("deflated_sharpe") or {}).get("ratio")
        print(f"  {name:17s} n={view['n_trades']:4d} pass={gate['passes']} "
              f"DSR={dsr} PBO={gate.get('pbo')} PF={gate.get('profit_factor')}")
    print(f"  headline n={scorecard['views']['cluster_adjusted']['n_trades']} "
          f"PBO available={scorecard['pbo_available']} (floor 40)")
    print("  desk status: SHADOW / advisory only")


if __name__ == "__main__":
    main()
