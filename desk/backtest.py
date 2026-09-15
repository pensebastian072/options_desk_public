"""P4 offline parametric option backtest through the canonical research gate.

This module has no broker integration and is never imported by the scheduled desk.
It replays point-in-time signals, calls the production selector/builders, settles
each option structure at intrinsic value, and evaluates non-overlapping PnL with
``macro_gpu_lab.validate.evaluate_gate``.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import date, datetime, time, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, gate_status, shadow, strategies

CONTRACT = 100


def unadjusted_close(close: pd.Series, factor: pd.Series) -> pd.Series:
    """Undo Yahoo back-adjustment for historically meaningful option strikes."""
    safe = factor.where(factor > 0)
    return close / safe


def rolling_percentile(series: pd.Series, window: int = 252) -> pd.Series:
    """Trailing inclusive percentile; the result at t never reads after t."""
    def _rank(values) -> float:
        arr = np.asarray(values, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return np.nan
        return float(np.mean(arr <= arr[-1]))

    return series.rolling(window, min_periods=window).apply(_rank, raw=True)


def _read_price_csv(name: str, csv_dir: Path) -> pd.DataFrame:
    path = csv_dir / f"{name}.csv"
    frame = pd.read_csv(path, parse_dates=["date"]).set_index("date").sort_index()
    frame.index = pd.DatetimeIndex(frame.index).tz_localize(None)
    return frame


def load_market_history(csv_dir: Path | None = None) -> pd.DataFrame:
    """Load local qlib CSV inputs. No download and no qlib runtime dependency."""
    root = csv_dir or config.QLIB_CSV_DIR
    spy = _read_price_csv("SPY", root)
    vix = _read_price_csv("VIX", root)
    out = pd.DataFrame(index=spy.index)
    out["spot"] = unadjusted_close(spy["close"], spy["factor"])
    out["vix"] = vix["close"].reindex(out.index)
    for name, col in (("VIX9D", "vix9d"), ("VIX3M", "vix3m")):
        try:
            out[col] = _read_price_csv(name, root)["close"].reindex(out.index)
        except FileNotFoundError:
            out[col] = np.nan
    return out.dropna(subset=["spot", "vix"])


def _load_macro_modules():
    root = str(config.MACRO_GPU_LAB_DIR)
    if root not in sys.path:
        sys.path.insert(0, root)
    from macro_gpu_lab import config as macro_config  # noqa: PLC0415
    from macro_gpu_lab import data as macro_data  # noqa: PLC0415
    from macro_gpu_lab.models.shift_detector import (  # noqa: PLC0415
        _calm_and_base,
        build_market_features,
        shift_label,
    )
    from macro_gpu_lab.validate import evaluate_gate, walk_forward_splits  # noqa: PLC0415
    return (macro_config, macro_data, _calm_and_base, build_market_features,
            shift_label, evaluate_gate, walk_forward_splits)


def replay_shift_signals(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Generate dated OOS surprise probabilities with expanding walk-forward fits.

    Training labels are calm-state outcomes only. Each fold predicts every feature
    row in its test block, matching the live model's ability to score a non-calm
    row while keeping the horizon-length gap that prevents label leakage.
    """
    (macro_config, _, calm_and_base, build_market_features, shift_label,
     _, walk_forward_splits) = _load_macro_modules()
    from sklearn.ensemble import RandomForestClassifier  # noqa: PLC0415

    feat = build_market_features(panel).sort_index()
    result = pd.DataFrame(index=feat.index)
    meta = {"n_feature_rows": int(len(feat)), "horizons": {}}
    X = feat.to_numpy()

    for horizon in macro_config.HORIZONS_DAYS:
        calm, _, _ = calm_and_base(panel, horizon)
        calm = calm.reindex(feat.index)
        spike = shift_label(panel, horizon).reindex(feat.index)
        label = (spike * calm.astype(float)).where(calm)
        y = label.to_numpy(dtype=float)
        probability = np.full(len(feat), np.nan, dtype=float)
        fold_rows = []

        for train_idx, test_idx in walk_forward_splits(
                len(feat), macro_config.N_WALK_FORWARD_FOLDS, horizon):
            valid_train = train_idx[np.isfinite(y[train_idx])]
            if valid_train.size == 0 or np.unique(y[valid_train]).size < 2:
                continue
            model = RandomForestClassifier(**macro_config.RF_KWARGS)
            model.fit(X[valid_train], y[valid_train].astype(int))
            probability[test_idx] = model.predict_proba(X[test_idx])[:, 1]
            fold_rows.append({
                "train_start": str(feat.index[valid_train[0]].date()),
                "train_end": str(feat.index[valid_train[-1]].date()),
                "test_start": str(feat.index[test_idx[0]].date()),
                "test_end": str(feat.index[test_idx[-1]].date()),
                "n_train": int(valid_train.size),
                "n_test": int(test_idx.size),
            })

        tag = f"{horizon}d"
        result[f"calm_{tag}"] = calm.astype("boolean")
        result[f"p_eruption_{tag}"] = probability
        result[f"eruption_predicted_{tag}"] = pd.Series(
            probability > 0.5, index=feat.index, dtype="boolean"
        ).where(np.isfinite(probability))
        meta["horizons"][tag] = {
            "n_predictions": int(np.isfinite(probability).sum()),
            "folds": fold_rows,
        }

    return result, meta


def load_shift_replay() -> tuple[pd.DataFrame, dict, dict]:
    modules = _load_macro_modules()
    macro_data = modules[1]
    panel = macro_data.load_latest_panel()
    if panel is None or panel.empty:
        raise RuntimeError("macro_gpu_lab panel missing; refresh its local panel first")
    replay, meta = replay_shift_signals(panel)
    panel_meta = {
        "rows": int(len(panel)),
        "start": str(pd.Timestamp(panel.index.min()).date()),
        "end": str(pd.Timestamp(panel.index.max()).date()),
    }
    return replay, meta, panel_meta


def build_signal_frame(market: pd.DataFrame, replay: pd.DataFrame) -> pd.DataFrame:
    spy_return = market["spot"].pct_change()
    realized_vol = spy_return.rolling(20, min_periods=20).std() * math.sqrt(252) * 100
    vrp = market["vix"] ** 2 - realized_vol ** 2
    sigma_1d = (market["vix"] / 100.0) / math.sqrt(252)
    out = market.copy()
    out["vrp"] = vrp
    out["vrp_pct"] = rolling_percentile(vrp)
    out["sigma_1d"] = sigma_1d
    out["magnitude_pct"] = rolling_percentile(sigma_1d)
    out["term_ratio"] = out["vix9d"] / out["vix3m"]
    return out.join(replay, how="left")


def signal_from_row(row: pd.Series) -> dict | None:
    required = (
        "spot", "vix", "vrp_pct", "magnitude_pct",
        "calm_5d", "calm_21d", "eruption_predicted_5d",
        "eruption_predicted_21d",
    )
    if any(pd.isna(row.get(name)) for name in required):
        return None
    pred5 = bool(row["eruption_predicted_5d"])
    pred21 = bool(row["eruption_predicted_21d"])
    term = row.get("term_ratio")
    return {
        "ok": True,
        "reason": "historical point-in-time replay",
        "vrp": {
            "spot": float(row["spot"]),
            "vix": float(row["vix"]),
            "vrp": float(row["vrp"]),
            "vrp_pct": float(row["vrp_pct"]),
        },
        "shift": {
            "calm_5d": bool(row["calm_5d"]),
            "calm_21d": bool(row["calm_21d"]),
            "p_eruption_5d": (None if pd.isna(row.get("p_eruption_5d"))
                               else float(row["p_eruption_5d"])),
            "p_eruption_21d": (None if pd.isna(row.get("p_eruption_21d"))
                                else float(row["p_eruption_21d"])),
            "eruption_predicted": pred5 or pred21,
        },
        "magnitude": {
            "magnitude_pct": float(row["magnitude_pct"]),
            "expected_move_usd": round(float(row["spot"] * row["sigma_1d"]), 2),
        },
        "vol_surface": ({"term_ratio": float(term)} if not pd.isna(term) else None),
    }


def terminal_option_value(candidate: dict, terminal_spot: float) -> float:
    """Signed intrinsic value of all legs, in dollars per one structure."""
    return shadow.terminal_option_value(candidate, terminal_spot)


def candidate_pnl(candidate: dict, terminal_spot: float,
                  cost_per_leg: float | None = None) -> dict:
    return shadow.candidate_pnl(candidate, terminal_spot, cost_per_leg)


def _terminal_observation(market: pd.DataFrame, entry: pd.Timestamp,
                          expiry: date) -> tuple[pd.Timestamp, float] | None:
    expiry_ts = pd.Timestamp(expiry)
    if market.index.max() < expiry_ts:
        return None
    eligible = market.loc[(market.index >= entry) & (market.index <= expiry_ts), "spot"].dropna()
    if eligible.empty:
        return None
    return eligible.index[-1], float(eligible.iloc[-1])


def build_trade_ledger(signal_frame: pd.DataFrame, market: pd.DataFrame) -> tuple[list[dict], dict]:
    last_expiry: dict[str, date] = {}
    ledger: list[dict] = []
    diagnostics = {
        "signal_rows": int(len(signal_frame)),
        "eligible_rows": 0,
        "actions": Counter(),
        "vix_iv_tilts": Counter(),
        "dropped_censored": 0,
        "dropped_overlap": Counter(),
    }

    for signal_date, row in signal_frame.iterrows():
        signal = signal_from_row(row)
        if signal is None:
            continue
        next_pos = market.index.searchsorted(signal_date, side="right")
        if next_pos >= len(market.index):
            continue
        entry_date = market.index[next_pos]
        now = datetime.combine(entry_date.date(), time(9, 5), tzinfo=timezone.utc)
        ticket = strategies.select(signal, now=now, apply_gate=False)
        diagnostics["eligible_rows"] += 1
        diagnostics["actions"][ticket["action"]] += 1
        pairs = ticket.get("pairs_tilt") or {}
        if pairs.get("tilt"):
            diagnostics["vix_iv_tilts"][pairs["tilt"]] += 1

        for candidate in ticket.get("candidates") or []:
            name = candidate["strategy"]
            expiry = date.fromisoformat(candidate["expiry"])
            if name in last_expiry and entry_date.date() <= last_expiry[name]:
                diagnostics["dropped_overlap"][name] += 1
                continue
            terminal = _terminal_observation(market, entry_date, expiry)
            if terminal is None:
                diagnostics["dropped_censored"] += 1
                continue
            terminal_date, terminal_spot = terminal
            economics = candidate_pnl(candidate, terminal_spot)
            ledger.append({
                "experiment_id": config.GATE_EXPERIMENT_ID,
                "strategy": name,
                "signal_date": str(signal_date.date()),
                "entry_date": str(entry_date.date()),
                "expiry": str(expiry),
                "terminal_date": str(terminal_date.date()),
                "entry_spot": round(float(signal["vrp"]["spot"]), 4),
                "entry_vix": round(float(signal["vrp"]["vix"]), 4),
                "vrp_pct": round(float(signal["vrp"]["vrp_pct"]), 4),
                "magnitude_pct": round(float(signal["magnitude"]["magnitude_pct"]), 4),
                "terminal_spot": round(terminal_spot, 4),
                "expiry_rule": "prior session if market holiday",
                "legs": candidate.get("legs") or [],
                **economics,
            })
            last_expiry[name] = expiry

    diagnostics["actions"] = dict(diagnostics["actions"])
    diagnostics["vix_iv_tilts"] = dict(diagnostics["vix_iv_tilts"])
    diagnostics["dropped_overlap"] = dict(diagnostics["dropped_overlap"])
    return ledger, diagnostics


def _pnl_stats(values: list[float]) -> dict:
    if not values:
        return {"mean_usd": None, "median_usd": None, "win_rate": None,
                "total_usd": 0.0, "max_drawdown_usd": None}
    arr = np.asarray(values, dtype=float)
    curve = np.cumsum(arr)
    peaks = np.maximum.accumulate(np.concatenate(([0.0], curve)))[1:]
    return {
        "mean_usd": round(float(arr.mean()), 2),
        "median_usd": round(float(np.median(arr)), 2),
        "win_rate": round(float(np.mean(arr > 0)), 4),
        "total_usd": round(float(arr.sum()), 2),
        "max_drawdown_usd": round(float(np.min(curve - peaks)), 2),
        "best_usd": round(float(arr.max()), 2),
        "worst_usd": round(float(arr.min()), 2),
    }


def evaluate_ledger(ledger: list[dict]) -> dict:
    evaluate_gate = _load_macro_modules()[5]
    results = {}
    for name in gate_status.PRICED_STRATEGIES:
        rows = [row for row in ledger if row["strategy"] == name]
        pnls = [float(row["pnl_usd"]) for row in rows]
        results[name] = {
            "n_trades": len(pnls),
            "stats": _pnl_stats(pnls),
            "gate": evaluate_gate(np.asarray(pnls, dtype=float),
                                  n_trials=config.GATE_N_TRIALS),
        }
    return results


def run_backtest() -> tuple[dict, list[dict]]:
    prereg = config.EXPERIMENTS_DIR / f"{config.GATE_EXPERIMENT_ID}.json"
    if not prereg.exists():
        raise RuntimeError(f"pre-registration missing: {prereg}")
    market = load_market_history()
    replay, replay_meta, panel_meta = load_shift_replay()
    signals = build_signal_frame(market, replay)
    ledger, diagnostics = build_trade_ledger(signals, market)
    results = evaluate_ledger(ledger)
    scorecard = {
        "experiment_id": config.GATE_EXPERIMENT_ID,
        "spec_fingerprint": gate_status.spec_fingerprint(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "SHADOW",
        "advisory_only": True,
        "n_trials": config.GATE_N_TRIALS,
        "data": {
            "qlib_csv_dir": str(config.QLIB_CSV_DIR),
            "market_rows": int(len(market)),
            "market_start": str(market.index.min().date()),
            "market_end": str(market.index.max().date()),
            "macro_panel": panel_meta,
        },
        "signal_replay": replay_meta,
        "assumptions": gate_status.current_spec(),
        "diagnostics": diagnostics,
        "strategies": results,
        "cleared_strategies": [name for name, row in results.items()
                               if row["gate"].get("passes") is True],
        "note": ("Canonical PBO/Deflated-Sharpe verdicts. A pass changes only the "
                 "display badge; this desk remains paper/advisory and SHADOW."),
    }
    return scorecard, ledger


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def write_results(scorecard: dict, ledger: list[dict],
                  scorecard_path: Path | None = None,
                  ledger_path: Path | None = None) -> None:
    score_path = scorecard_path or config.GATE_SCORECARD
    trades_path = ledger_path or config.GATE_LEDGER
    _atomic_write(score_path, json.dumps(scorecard, indent=2, default=str) + "\n")
    lines = "".join(json.dumps(row, default=str) + "\n" for row in ledger)
    _atomic_write(trades_path, lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pre-registered P4 options gate")
    parser.add_argument("--scorecard", type=Path, default=config.GATE_SCORECARD)
    parser.add_argument("--ledger", type=Path, default=config.GATE_LEDGER)
    args = parser.parse_args()
    scorecard, ledger = run_backtest()
    write_results(scorecard, ledger, args.scorecard, args.ledger)
    print(f"P4 {scorecard['experiment_id']} -> {args.scorecard}")
    for name, row in scorecard["strategies"].items():
        gate = row["gate"]
        dsr = (gate.get("deflated_sharpe") or {}).get("ratio")
        print(f"  {name:20s} n={row['n_trades']:3d} pass={gate['passes']} "
              f"DSR={dsr} PBO={gate.get('pbo')} PF={gate.get('profit_factor')}")
    print("  desk status: SHADOW / advisory only")


if __name__ == "__main__":
    main()
