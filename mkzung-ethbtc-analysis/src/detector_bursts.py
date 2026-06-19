"""D5, Burst-execution detector + time-of-day + anchor-price.

Three closely-related microstructure signatures that all pointed at the same
operator behavior:

1. **Burst seconds**: same-second clusters of ≥N trades. Inter-arrival time
   for natural retail/MM flow is exponentially distributed with rate
   λ = 1/mean_dt. Under that null, P(≥k trades in 1s) is tiny for k>4. We
   flag any second with ≥5 trades and report the cluster's properties.

2. **Time-of-day asymmetry**: per-UTC-hour buy share. Healthy markets have
   ~uniform buy/sell mix across hours. If sells appear only in specific
   sessions (e.g. US hours) it implies the seller(s) are a small set of
   actors with a daily schedule.

3. **Anchor prices**: prices that recur far more than expected under a
   continuous price formation process. Concentration at specific tick-rounded
   prices is consistent with limit-order anchoring.
"""
from __future__ import annotations

import pandas as pd


def detect_bursts(trades: pd.DataFrame, min_trades_per_second: int = 5) -> pd.DataFrame:
    """Find seconds with anomalously many trades.

    Returns one row per burst with: timestamp (floor to second), n,
    sides (dict), n_unique_sizes, total_size, dominant_side.
    """
    if trades.empty:
        return pd.DataFrame()
    df = trades.copy()
    df["sec"] = df["timestamp"].dt.floor("s")
    grouped = df.groupby("sec")
    sizes_by_sec = grouped.size()
    flagged_secs = sizes_by_sec[sizes_by_sec >= min_trades_per_second].index

    rows = []
    for sec in flagged_secs:
        sub = df[df["sec"] == sec]
        side_counts = sub["side"].value_counts().to_dict()
        rows.append({
            "second": sec,
            "n_trades": int(len(sub)),
            "n_buy":  int(side_counts.get("buy", 0)),
            "n_sell": int(side_counts.get("sell", 0)),
            "n_unique_sizes": int(sub["size"].round(8).nunique()),
            "total_size": float(sub["size"].sum()),
            "min_price": float(sub["price"].min()),
            "max_price": float(sub["price"].max()),
            "dominant_side": "buy" if side_counts.get("buy", 0) > side_counts.get("sell", 0) else "sell",
        })
    out = pd.DataFrame(rows)
    if not out.empty:
        # Secondary key = timestamp: ties on n_trades otherwise inherit
        # groupby/value_counts insertion order, which varies across pandas
        # versions and breaks cross-platform byte-identical findings.json.
        out = (out.sort_values(["n_trades", "second"], ascending=[False, True])
                  .reset_index(drop=True))
    return out


def detect_time_of_day(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-UTC-hour aggregation: trade count, buy share, total buy/sell size."""
    if trades.empty:
        return pd.DataFrame(columns=[
            "hour_utc", "n_trades", "n_buy", "n_sell",
            "buy_share_pct", "buy_size", "sell_size",
        ])
    df = trades.copy()
    df["hour_utc"] = df["timestamp"].dt.hour
    out = df.groupby("hour_utc")[["side", "size"]].apply(
        lambda g: pd.Series({
            "n_trades": int(len(g)),
            "n_buy":   int((g["side"] == "buy").sum()),
            "n_sell":  int((g["side"] == "sell").sum()),
            "buy_share_pct": float((g["side"] == "buy").mean() * 100),
            "buy_size":  float(g.loc[g["side"] == "buy",  "size"].sum()),
            "sell_size": float(g.loc[g["side"] == "sell", "size"].sum()),
        })
    ).reset_index()
    return out


def detect_anchor_prices(trades: pd.DataFrame, top_n: int = 10) -> pd.DataFrame:
    """Top N most-traded exact prices."""
    if trades.empty:
        return pd.DataFrame(columns=["price", "count", "share_pct"])
    # Explicit (count DESC, price ASC) total order BEFORE the head() cut:
    # with bare value_counts().head(n), both the ordering AND the membership
    # of tied counts at the boundary depend on the pandas version -
    # non-deterministic across environments.
    counts = trades["price"].value_counts().reset_index()
    counts.columns = ["price", "count"]
    counts = (counts.sort_values(["count", "price"], ascending=[False, True])
                    .head(top_n).reset_index(drop=True))
    counts["share_pct"] = counts["count"] / len(trades) * 100
    return counts


def summarize_d5(bursts: pd.DataFrame, tod: pd.DataFrame, anchors: pd.DataFrame) -> dict:
    if bursts.empty:
        b_summary = {"n_bursts": 0}
    else:
        max_burst = bursts.iloc[0]
        b_summary = {
            "n_bursts": int(len(bursts)),
            "n_buy_dominant":  int((bursts["dominant_side"] == "buy").sum()),
            "n_sell_dominant": int((bursts["dominant_side"] == "sell").sum()),
            "max_n_in_one_second": int(max_burst["n_trades"]),
            "max_burst_second": max_burst["second"].isoformat() if pd.notna(max_burst["second"]) else None,
            "max_burst_side": str(max_burst["dominant_side"]),
        }

    sells_by_hour = tod[tod["n_sell"] > 0]
    tod_summary = {
        "hours_with_any_sells":   int(len(sells_by_hour)),
        "hours_with_zero_sells":  int(len(tod) - len(sells_by_hour)),
        "min_buy_share_pct":      float(tod["buy_share_pct"].min()),
        "min_buy_share_hour":     int(tod.loc[tod["buy_share_pct"].idxmin(), "hour_utc"]),
        "max_buy_share_pct":      float(tod["buy_share_pct"].max()),
    }

    return {
        "bursts": b_summary,
        "tod": tod_summary,
        "top_anchor_price": float(anchors.iloc[0]["price"]) if not anchors.empty else None,
        "top_anchor_count": int(anchors.iloc[0]["count"])   if not anchors.empty else 0,
        "top_anchor_share_pct": float(anchors.iloc[0]["share_pct"]) if not anchors.empty else 0.0,
    }
