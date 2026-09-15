"""P2a -- build the point-in-time feature+label matrix for the v5 meta-model.

Each v5 entry (from options_etf_gate_v5_trades.jsonl) gets features known AT ENTRY (no
lookahead): ledger economics (pop, entry IV, return-on-risk), the regime signal frame
(magnitude/vrp/term/eruption), and per-symbol trend distance (spot vs 50/200-day, RV20).
Label = win (BS-modeled pnl_usd > 0). Leaky post-entry fields are excluded. Exports a
parquet the GPU trainer (alpaca_gpu_lab) reads; no option pricing here.

    .venv\\Scripts\\python.exe -m desk.meta_features
"""
from __future__ import annotations

import json
from datetime import datetime

import numpy as np
import pandas as pd

from . import backtest, config, etf_backtest as eb, qlib_evidence

LEDGER = config.SCORECARDS_DIR / "options_etf_gate_v5_trades.jsonl"
OUT = config.SCORECARDS_DIR / "deep_v5_meta_features.parquet"
STRUCTS = ["etf_short_put_spread_v1", "etf_short_call_spread_v1", "etf_iron_condor_v1"]


def _signal_features(signals: pd.DataFrame) -> pd.DataFrame:
    """Per-date regime features from the v5 signal frame."""
    f = pd.DataFrame(index=signals.index)
    f["magnitude_pct"] = signals.get("magnitude_pct")
    f["vrp_pct"] = signals.get("vrp_pct")     # build_signal_frame already computes this
    f["term_ratio"] = signals.get("term_ratio")
    f["p_eruption_5d"] = signals.get("p_eruption_5d")
    f["p_eruption_21d"] = signals.get("p_eruption_21d")
    f.index = [d.date() for d in f.index]
    return f


def build() -> pd.DataFrame:
    rows = [json.loads(l) for l in LEDGER.read_text(encoding="utf-8").splitlines() if l.strip()]
    universe = qlib_evidence.load_universe("options_etf_universe_v2")
    market = backtest.load_market_history()
    replay, _, _ = backtest.load_shift_replay()
    signals = backtest.build_signal_frame(market, replay)
    sig_feat = _signal_features(signals)
    histories = eb.load_symbol_history(universe)

    recs = []
    for r in rows:
        sym, d = r["symbol"], r["entry_date"]
        day = pd.Timestamp(d).date()
        frame = histories.get(sym)
        if frame is None or pd.Timestamp(d) not in frame.index:
            continue
        h = frame.loc[pd.Timestamp(d)]
        spot = float(h["spot"]); rv = float(h["rv20"])
        sma50, sma200 = h.get("sma50"), h.get("sma200")
        sf = sig_feat.loc[day] if day in sig_feat.index else {}
        credit, risk = float(r["credit_usd"]), float(r["max_risk_usd"])
        entry_iv = float(r["entry_iv"])
        rec = {
            "entry_date": d, "symbol": sym, "bucket": r["bucket"], "strategy": r["strategy"],
            # ledger economics (known at entry)
            "pop": float(r["pop"]), "entry_iv": entry_iv,
            "credit_usd": credit, "max_risk_usd": risk,
            "return_on_risk": credit / risk if risk else 0.0,
            "iv_rv": entry_iv / rv if rv else np.nan,
            # trend distance
            "trend_dist_50": spot / float(sma50) - 1 if sma50 and not pd.isna(sma50) else np.nan,
            "trend_dist_200": spot / float(sma200) - 1 if sma200 and not pd.isna(sma200) else np.nan,
            "rv20": rv,
            # regime
            "magnitude_pct": float(sf.get("magnitude_pct")) if sf is not None and not pd.isna(sf.get("magnitude_pct", np.nan)) else np.nan,
            "vrp_pct": float(sf.get("vrp_pct")) if sf is not None and not pd.isna(sf.get("vrp_pct", np.nan)) else np.nan,
            "term_ratio": float(sf.get("term_ratio")) if sf is not None and not pd.isna(sf.get("term_ratio", np.nan)) else np.nan,
            "p_eruption_5d": float(sf.get("p_eruption_5d")) if sf is not None and not pd.isna(sf.get("p_eruption_5d", np.nan)) else np.nan,
            "p_eruption_21d": float(sf.get("p_eruption_21d")) if sf is not None and not pd.isna(sf.get("p_eruption_21d", np.nan)) else np.nan,
            # calendar
            "entry_month": pd.Timestamp(d).month, "entry_dow": pd.Timestamp(d).weekday(),
            # one-hot structure
            **{f"is_{s.split('_')[1]}_{s.split('_')[2]}": int(r["strategy"] == s) for s in STRUCTS},
            # LABEL (modeled)
            "win": int(float(r["pnl_usd"]) > 0), "pnl_usd": float(r["pnl_usd"]),
        }
        recs.append(rec)
    df = pd.DataFrame(recs)
    return df


def main() -> None:
    df = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"deep_v5_meta_features -> {OUT}")
    print(f"rows={len(df)} | win base rate={df['win'].mean():.1%} | "
          f"date {df['entry_date'].min()}..{df['entry_date'].max()}")
    feat = [c for c in df.columns if c not in ("entry_date", "symbol", "bucket", "strategy",
                                               "win", "pnl_usd")]
    print(f"features ({len(feat)}): {feat}")
    print(f"NaN counts:\n{df[feat].isna().sum()[df[feat].isna().sum() > 0]}")


if __name__ == "__main__":
    main()
