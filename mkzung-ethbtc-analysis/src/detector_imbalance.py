"""D1 — Buy/Sell Imbalance with Rolling Z-Score (count- AND size-weighted).

Hypothesis: healthy markets have buy/sell ratios oscillating around 1.0.
Sustained deviations beyond 3σ — both in trade *count* and trade *size* —
indicate one-sided pressure consistent with wash trading, momentum ignition,
or a single dominant taker.

Adjustments vs. brief:
1. 8h rolling window (not 24h) — sample spans only 72h.
2. 30-min buckets (mean ~6 trades/bucket); buckets with fewer than
   `min_trades_per_bucket` trades are dropped to keep the rolling baseline
   stable.
3. The size log-ratio uses a `+1` smoothing constant rather than a small
   epsilon: 119 of 143 valid buckets contain zero sells in this dataset, and
   any small-eps formulation is dominated by `log(buy_size / eps)` — pure
   smoothing artifact. The far stronger size-side finding is the GLOBAL
   imbalance (~175,245:1) reported in `summarize_d1`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_buysell_imbalance(
    trades: pd.DataFrame,
    bucket: str = "30min",
    rolling: str = "8h",
    z_thresh: float = 3.0,
    min_periods: int = 6,
    min_trades_per_bucket: int = 2,
) -> pd.DataFrame:
    """Return a per-bucket DataFrame with imbalance signals.

    Parameters
    ----------
    bucket : str (default "30min")    pandas resample frequency for binning
    rolling : str (default "8h")      rolling window length for z-score baseline
    z_thresh : float (default 3.0)    |z| flag threshold
    min_periods : int (default 6)     min buckets required for rolling stats
    min_trades_per_bucket : int (default 2)   drop buckets with fewer trades

    Columns returned:
        buy_count, sell_count, log_count_ratio, z_count, flag_count
        buy_size,  sell_size,  log_size_ratio,  z_size,  flag_size
        flag_any  (either flag fires)
    """
    if trades.empty:
        return pd.DataFrame()

    df = trades.copy()
    df = df.set_index("timestamp")
    df["is_buy"] = (df["side"] == "buy").astype(int)
    df["is_sell"] = (df["side"] == "sell").astype(int)
    df["buy_size"] = df["size"] * df["is_buy"]
    df["sell_size"] = df["size"] * df["is_sell"]

    g = pd.DataFrame({
        "buy_count":  df["is_buy"].resample(bucket).sum(),
        "sell_count": df["is_sell"].resample(bucket).sum(),
        "buy_size":   df["buy_size"].resample(bucket).sum(),
        "sell_size":  df["sell_size"].resample(bucket).sum(),
    })
    # Filter: only bucket with enough trades to give a stable ratio. Empty
    # buckets pulled into the rolling baseline collapse sigma and inflate z.
    g["n_trades"] = g["buy_count"] + g["sell_count"]
    g = g[g["n_trades"] >= min_trades_per_bucket].copy()

    # Count-ratio: smoothed by +1 for log stability.
    g["log_count_ratio"] = np.log((g["buy_count"] + 1) / (g["sell_count"] + 1))
    # Size-ratio: 119/143 buckets have zero sells in this dataset, so any
    # epsilon-based log((buy+eps)/(sell+eps)) is dominated by log(buy/eps) — a
    # pure smoothing artifact, not signal. We use eps=1 (≈ neutral baseline of
    # 1 ETH) which makes the log stable but means the "size z-score" is
    # numerically constrained and rarely fires. The far stronger size-side
    # finding is the GLOBAL imbalance ratio (~175,245:1 in this dataset),
    # reported separately in `summarize_d1` rather than via per-bucket flags.
    g["log_size_ratio"]  = np.log((g["buy_size"] + 1) / (g["sell_size"] + 1))

    for col, ztgt, ftgt in [
        ("log_count_ratio", "z_count", "flag_count"),
        ("log_size_ratio",  "z_size",  "flag_size"),
    ]:
        mu    = g[col].rolling(rolling, min_periods=min_periods).mean()
        sigma = g[col].rolling(rolling, min_periods=min_periods).std()
        # Guard against sigma==0 (degenerate window) -> z=NaN, flag=False
        sigma = sigma.replace(0, np.nan)
        g[ztgt] = (g[col] - mu) / sigma
        g[ftgt] = g[ztgt].abs() > z_thresh

    # The headline D1 flag is count-based; size is reported alongside but the
    # size-window stats are stabilized by eps=1, not eps=0, see comment above.
    g["flag_any"] = g["flag_count"].fillna(False) | g["flag_size"].fillna(False)
    return g


def summarize_d1(d1: pd.DataFrame) -> dict:
    if d1.empty:
        return {"n_buckets": 0}
    flagged_idx = d1.index[d1["flag_any"].fillna(False)]
    cluster_starts = []
    if len(flagged_idx) > 0:
        # Group consecutive flags as one event (gap > 2 buckets => new cluster)
        diffs = flagged_idx.to_series().diff().dt.total_seconds().fillna(0)
        bucket_sec = (d1.index[1] - d1.index[0]).total_seconds() if len(d1) > 1 else 300
        new_cluster = diffs > 2 * bucket_sec
        cluster_starts = flagged_idx[new_cluster | (diffs == 0)]
    return {
        "n_buckets": int(len(d1)),
        "n_flagged_count": int(d1["flag_count"].fillna(False).sum()),
        "n_flagged_size":  int(d1["flag_size"].fillna(False).sum()),
        "n_flagged_any":   int(d1["flag_any"].fillna(False).sum()),
        "n_event_clusters": int(len(cluster_starts)),
        "max_z_count": float(d1["z_count"].abs().max()) if d1["z_count"].notna().any() else float("nan"),
        "max_z_size":  float(d1["z_size"].abs().max())  if d1["z_size"].notna().any()  else float("nan"),
        "global_buy_count_share": float(
            d1["buy_count"].sum() / max(d1["buy_count"].sum() + d1["sell_count"].sum(), 1)
        ),
        "global_buy_size_share": float(
            d1["buy_size"].sum() / max(d1["buy_size"].sum() + d1["sell_size"].sum(), 1)
        ),
    }
