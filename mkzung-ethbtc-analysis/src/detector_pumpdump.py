"""D3 — Pump-and-Dump Signature (volume spike → price reversal, bidirectional).

Hypothesis: P&D events have a distinctive shape — anomalous volume spike
coincident with a sharp price move, followed by a >50% reversal within
a short forward window. Most P&Ds are upward (pumps), but mirrored
patterns (dumps with sharp recoveries) are also flagged by this detector.

Adjustments vs. brief:
1. Bidirectional: track both max and min within the spike window. Use whichever
   extremum is *furthest* from spike-start price. Brief used only `.max()`,
   missing dumps entirely.
2. 4h trailing window for volume baseline (sample is 72h).
3. Volume is summed over BUY and SELL separately, since the dataset has
   side-conditional unit bimodality. We z-score each, flag spikes on either.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def detect_pumpdump(
    trades: pd.DataFrame,
    vol_bucket: str = "1h",
    trailing: str = "4h",
    vol_z: float = 2.0,
    min_move: float = 0.005,
    reversal_frac: float = 0.5,
    forward: str = "1h",
    min_periods: int = 4,
) -> pd.DataFrame:
    """Return a DataFrame of P&D candidate events.

    Parameters
    ----------
    vol_bucket : str (default "1h")        volume aggregation bucket
    trailing : str (default "4h")          baseline window for vol z-score
    vol_z : float (default 2.0)            volume-spike z-score threshold
    min_move : float (default 0.005)       min |price move| in fwd window (0.5%)
    reversal_frac : float (default 0.5)    min reversal fraction (50%)
    forward : str (default "1h")           forward window after spike start
    min_periods : int (default 4)          min buckets for rolling stats

    Each returned row:
        t0           : spike-window start
        side_dom     : 'buy' | 'sell' | 'mixed' (volume dominance)
        vol_z_buy    : z-score of buy-side volume in this bucket
        vol_z_sell   : z-score of sell-side volume
        p_start      : price at spike-window start
        p_extreme    : peak or trough in forward window (whichever further)
        p_end        : price at end of forward window
        move_pct     : (p_extreme − p_start) / p_start (signed)
        reversal_pct : (p_extreme − p_end) / (p_extreme − p_start)
        direction    : 'pump' if move > 0 else 'dump'
        score        : (|z_buy| + |z_sell|) × |move_pct| × reversal_pct
    """
    if trades.empty:
        return pd.DataFrame()
    df = trades.copy().set_index("timestamp").sort_index()

    buy_vol  = df.loc[df["side"] == "buy",  "size"].resample(vol_bucket).sum()
    sell_vol = df.loc[df["side"] == "sell", "size"].resample(vol_bucket).sum()
    # Reindex to the union grid so trailing stats line up
    grid = buy_vol.index.union(sell_vol.index)
    buy_vol  = buy_vol.reindex(grid).fillna(0)
    sell_vol = sell_vol.reindex(grid).fillna(0)

    def zroll(s):
        mu = s.rolling(trailing, min_periods=min_periods).mean()
        sd = s.rolling(trailing, min_periods=min_periods).std().replace(0, np.nan)
        return (s - mu) / sd

    z_buy  = zroll(buy_vol)
    z_sell = zroll(sell_vol)
    spikes = pd.DataFrame({"vol_z_buy": z_buy, "vol_z_sell": z_sell})
    spikes["spike"] = (spikes["vol_z_buy"].fillna(-np.inf) > vol_z) | \
                      (spikes["vol_z_sell"].fillna(-np.inf) > vol_z)

    forward_td = pd.Timedelta(forward)

    out_rows = []
    for t0 in spikes.index[spikes["spike"]]:
        window = df.loc[t0 : t0 + forward_td]
        if window.empty:
            continue
        p_start = float(window.iloc[0]["price"])
        p_max   = float(window["price"].max())
        p_min   = float(window["price"].min())
        # Pick the extremum further from start
        if abs(p_max - p_start) >= abs(p_min - p_start):
            p_extreme = p_max
        else:
            p_extreme = p_min
        p_end = float(window.iloc[-1]["price"])
        move_pct = (p_extreme - p_start) / p_start if p_start else 0.0
        if abs(move_pct) < min_move:
            continue
        denom = (p_extreme - p_start)
        reversal_pct = (p_extreme - p_end) / denom if denom != 0 else 0.0
        if reversal_pct < reversal_frac:
            continue

        z_b = float(spikes.loc[t0, "vol_z_buy"]) if pd.notna(spikes.loc[t0, "vol_z_buy"]) else 0.0
        z_s = float(spikes.loc[t0, "vol_z_sell"]) if pd.notna(spikes.loc[t0, "vol_z_sell"]) else 0.0
        side_dom = "buy" if z_b > z_s + 1 else "sell" if z_s > z_b + 1 else "mixed"
        score = (abs(z_b) + abs(z_s)) * abs(move_pct) * reversal_pct

        out_rows.append({
            "t0": t0,
            "side_dom": side_dom,
            "vol_z_buy":  z_b,
            "vol_z_sell": z_s,
            "p_start":    p_start,
            "p_extreme":  p_extreme,
            "p_end":      p_end,
            "move_pct":   move_pct,
            "reversal_pct": reversal_pct,
            "direction":  "pump" if move_pct > 0 else "dump",
            "score":      score,
        })

    if not out_rows:
        return pd.DataFrame(columns=[
            "t0", "side_dom", "vol_z_buy", "vol_z_sell", "p_start", "p_extreme",
            "p_end", "move_pct", "reversal_pct", "direction", "score",
        ])
    return pd.DataFrame(out_rows).sort_values("score", ascending=False).reset_index(drop=True)


def summarize_d3(d3: pd.DataFrame) -> dict:
    if d3.empty:
        return {"n_candidates": 0}
    return {
        "n_candidates": int(len(d3)),
        "n_pump":  int((d3["direction"] == "pump").sum()),
        "n_dump":  int((d3["direction"] == "dump").sum()),
        "top_t0":  d3.iloc[0]["t0"].isoformat(),
        "top_move_pct": float(d3.iloc[0]["move_pct"]),
        "top_reversal_pct": float(d3.iloc[0]["reversal_pct"]),
        "top_vol_z": float(max(d3.iloc[0]["vol_z_buy"], d3.iloc[0]["vol_z_sell"])),
    }
