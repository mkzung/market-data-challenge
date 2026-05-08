"""D4 — Bid-Ask Spread + Depth-Imbalance + Trade-vs-Spread.

Hypothesis: healthy ETH/BTC venues quote tight spreads (5-15 bps) with
roughly symmetric depth. Wide spreads, single-sided depth, or trades
executing outside the contemporaneous bid-ask all signal liquidity
problems consistent with stale quotes, fake liquidity, or aggressive
sweeping.

Adjustments vs. brief:
1. Threshold uses the dataset's own distribution (median + 1.5×IQR), not
   a hard-coded 50 bps. This venue's *median* is 90 bps — the brief's
   threshold would flag virtually everything.
2. Adds depth-imbalance metric: (ask_depth_5 - bid_depth_5) / (ask_depth_5 + bid_depth_5).
3. Adds trade-vs-spread cross-check via merge_asof to flag executions
   outside the contemporaneous best bid-ask.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_liquidity_quality(
    trades: pd.DataFrame,
    orderbooks: pd.DataFrame,
    spread_threshold_bps: float | None = None,
    # Default tolerance set to 30min after audit: median OB inter-snapshot
    # interval is 18.3min and mean is 22min in this dataset, so a 5min
    # tolerance only matched 22.5% of trades and missed 75% of outside-spread
    # prints. 30min covers 87.8% of trades and gives a stable ~17% outside-
    # spread rate that is consistent across tolerance choices ≥15min.
    asof_tolerance: pd.Timedelta = pd.Timedelta("30min"),
) -> dict:
    """Return spread-distribution stats, flagged snapshots, and trade-vs-spread issues.

    Returns
    -------
    dict:
        ob:               input orderbooks DataFrame with extra computed columns
                          (incl. `spread_bps`, `depth_imbalance`)
        summary:          spread distribution stats + outside-spread counts
        flagged_wide:     subset of ob where spread > threshold
        trades_outside:   DataFrame of trades whose price was outside contemporaneous bid-ask
        threshold_bps:    actual threshold used (median + 1.5×IQR by default)
    """
    ob = orderbooks.copy()
    if "spread_bps" not in ob.columns:
        ob["mid"] = (ob["bid_price"] + ob["ask_price"]) / 2
        ob["spread_bps"] = (ob["ask_price"] - ob["bid_price"]) / ob["mid"] * 1e4

    # Threshold: caller-supplied or dataset-relative.
    if spread_threshold_bps is None:
        q1, q3 = ob["spread_bps"].quantile([0.25, 0.75])
        iqr = q3 - q1
        spread_threshold_bps = float(ob["spread_bps"].median() + 1.5 * iqr)

    flagged_wide = ob[ob["spread_bps"] > spread_threshold_bps].copy()

    # Depth imbalance (only if depth columns exist).
    if {"bid_depth_5", "ask_depth_5"}.issubset(ob.columns):
        denom = ob["ask_depth_5"] + ob["bid_depth_5"]
        ob["depth_imbalance"] = np.where(denom > 0, (ob["ask_depth_5"] - ob["bid_depth_5"]) / denom, 0.0)
    else:
        ob["depth_imbalance"] = np.nan

    # Trade-vs-spread cross-check.
    trades_outside = pd.DataFrame()
    if not trades.empty:
        t = trades[["timestamp", "price", "size", "side"]].copy().sort_values("timestamp")
        ob_for_join = ob[["timestamp", "bid_price", "ask_price", "spread_bps"]].sort_values("timestamp")
        merged = pd.merge_asof(
            t, ob_for_join,
            on="timestamp", direction="backward",
            tolerance=asof_tolerance,
        )
        merged = merged.dropna(subset=["bid_price", "ask_price"])
        # A trade is "outside" if its price is below contemporaneous best bid
        # OR above contemporaneous best ask. Allow tiny tolerance for floating
        # point.
        tol = 1e-9
        outside_mask = (merged["price"] < merged["bid_price"] - tol) | \
                       (merged["price"] > merged["ask_price"] + tol)
        trades_outside = merged[outside_mask].copy()

    summary = {
        "n_snapshots": int(len(ob)),
        "median_spread_bps": float(ob["spread_bps"].median()),
        "p25_spread_bps":    float(ob["spread_bps"].quantile(0.25)),
        "p75_spread_bps":    float(ob["spread_bps"].quantile(0.75)),
        "p95_spread_bps":    float(ob["spread_bps"].quantile(0.95)),
        "max_spread_bps":    float(ob["spread_bps"].max()),
        "min_spread_bps":    float(ob["spread_bps"].min()),
        "threshold_bps":     spread_threshold_bps,
        "n_flagged_wide":    int(len(flagged_wide)),
        "pct_flagged_wide":  float(len(flagged_wide) / max(len(ob), 1) * 100),
        "median_depth_imbalance": (
            float(ob["depth_imbalance"].median())
            if ob["depth_imbalance"].notna().any() else None
        ),
        "p95_depth_imbalance": (
            float(ob["depth_imbalance"].quantile(0.95))
            if ob["depth_imbalance"].notna().any() else None
        ),
        "n_trades_outside_spread": int(len(trades_outside)),
        "pct_trades_outside_spread": float(len(trades_outside) / max(len(trades), 1) * 100),
    }

    return {
        "ob": ob,
        "summary": summary,
        "flagged_wide": flagged_wide,
        "trades_outside": trades_outside,
        "threshold_bps": spread_threshold_bps,
    }
