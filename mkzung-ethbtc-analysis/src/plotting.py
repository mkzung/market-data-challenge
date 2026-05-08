"""All plotting code for the five detectors + co-occurrence timeline.

Each function takes the detector output and a `Path` to write a PNG.
Plots use matplotlib only (no seaborn dependency at runtime — keeps the
toolkit small).
"""
from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# Consistent visual identity across all figures.
plt.rcParams.update({
    "figure.dpi": 110,
    "savefig.dpi": 140,
    "savefig.bbox": "tight",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linestyle": "--",
    "axes.labelsize": 10,
    "axes.titlesize": 11,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 8,
})

C_BUY  = "#1f77b4"
C_SELL = "#d62728"
C_FLAG = "#ff7f0e"
C_BG   = "#9ecae1"


def _format_time_axis(ax) -> None:
    """Apply rotated, properly-spaced date labels to avoid the overlap bug."""
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=5, maxticks=8))
    for label in ax.get_xticklabels():
        label.set_rotation(30)
        label.set_ha("right")


# --------------------------------------------------------------------- D1 ---
def plot_imbalance(d1: pd.DataFrame, out: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    ax = axes[0]
    ax.plot(d1.index, d1["log_count_ratio"], color=C_BUY, lw=1.0, label="log(buy/sell) — count")
    ax.plot(d1.index, d1["log_size_ratio"],  color=C_SELL, lw=1.0, label="log(buy/sell) — size", alpha=0.7)
    ax.axhline(0, color="black", lw=0.5)
    flagged = d1[d1["flag_any"].fillna(False)]
    if len(flagged):
        ax.scatter(flagged.index, flagged["log_count_ratio"],
                   color=C_FLAG, s=18, zorder=5, label="flagged window")
    ax.set_ylabel("log buy/sell ratio")
    ax.set_title("D1 — Buy/Sell imbalance (30-min buckets, 8h rolling z-score, |z|>3)")
    ax.legend(loc="upper right", framealpha=0.9)

    ax = axes[1]
    ax.plot(d1.index, d1["z_count"], color=C_BUY,  lw=0.8, label="z (count)")
    ax.plot(d1.index, d1["z_size"],  color=C_SELL, lw=0.8, label="z (size)", alpha=0.7)
    ax.axhline( 3, color="gray", lw=0.5, ls="--")
    ax.axhline(-3, color="gray", lw=0.5, ls="--")
    ax.set_ylabel("z-score")
    ax.set_xlabel("time (UTC)")
    ax.legend(loc="upper right", framealpha=0.9)
    _format_time_axis(ax)

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# --------------------------------------------------------------------- D2 ---
def plot_signatures(trades: pd.DataFrame, d2: dict, out: Path) -> None:
    sides = [s for s in ("buy", "sell") if s in d2 and d2[s]["n"] > 0]
    fig, axes = plt.subplots(len(sides), 2, figsize=(12, 4 * len(sides)),
                             squeeze=False)

    for row, side in enumerate(sides):
        payload = d2[side]
        sub = trades[trades["side"] == side]
        # Left: empirical value-count distribution + null threshold
        ax = axes[row, 0]
        counts = sub["size"].round(8).value_counts().values
        ax.hist(counts, bins=range(1, int(counts.max()) + 2),
                color=(C_BUY if side == "buy" else C_SELL), alpha=0.65,
                edgecolor="black", lw=0.4)
        ax.axvline(payload["threshold"], color=C_FLAG, lw=1.5, ls="--",
                   label=f"99th-pctile null threshold = {payload['threshold']:.1f}")
        ax.set_yscale("log")
        ax.set_xlabel("recurrence count for a given size")
        ax.set_ylabel("# of distinct sizes (log)")
        ax.set_title(f"D2 — {side.upper()} side recurrences (n={payload['n']})")
        ax.legend(loc="upper right", framealpha=0.9)

        # Right: timeline of flagged sizes
        ax = axes[row, 1]
        flagged = payload["flagged"]
        if not flagged.empty:
            for _, r in flagged.head(8).iterrows():
                hits = sub[np.isclose(sub["size"], r["size"])]
                ax.scatter(hits["timestamp"], [r["size"]] * len(hits),
                           s=28, alpha=0.8,
                           label=f"size={r['size']:.6g} ×{int(r['count'])}")
            ax.set_yscale("log")
            # Place legend OUTSIDE the plot to avoid overlapping data points
            ax.legend(loc="center left", bbox_to_anchor=(1.02, 0.5),
                      fontsize=7, framealpha=0.95, borderaxespad=0)
        else:
            ax.text(0.5, 0.5, "no flagged sizes", ha="center", va="center",
                    transform=ax.transAxes)
        ax.set_xlabel("time (UTC)")
        ax.set_ylabel("size")
        ax.set_title(f"D2 — {side.upper()} flagged-size occurrence timeline")
        _format_time_axis(ax)

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# --------------------------------------------------------------------- D3 ---
def plot_pumpdump(trades: pd.DataFrame, d3: pd.DataFrame, out: Path) -> None:
    if d3.empty:
        fig, ax = plt.subplots(figsize=(11, 5))
        ax.plot(trades["timestamp"], trades["price"], color=C_BUY, lw=0.6)
        ax.set_title("D3 — no pump/dump candidates met thresholds")
        ax.set_xlabel("time (UTC)")
        ax.set_ylabel("price (ETH/BTC)")
        _format_time_axis(ax)
        fig.tight_layout()
        fig.savefig(out)
        plt.close(fig)
        return

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(trades["timestamp"], trades["price"], color="#444", lw=0.6, label="price")
    for _, r in d3.head(5).iterrows():
        color = C_FLAG if r["direction"] == "pump" else "#7e44a4"
        ax.axvspan(r["t0"], r["t0"] + pd.Timedelta("1h"), color=color, alpha=0.2)
        ax.scatter([r["t0"]], [r["p_start"]], color=color, s=40, zorder=5,
                   label=f"{r['direction']} @ {r['t0'].strftime('%m-%d %H:%M')} "
                         f"({r['move_pct']*100:+.1f}%, rev {r['reversal_pct']*100:.0f}%)")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("price (ETH/BTC)")
    ax.set_title("D3 — Volume spikes (z>2σ) with price reversal ≥50% within 1h")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    _format_time_axis(ax)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# --------------------------------------------------------------------- D4 ---
def plot_liquidity(d4: dict, out: Path) -> None:
    ob = d4["ob"]
    summary = d4["summary"]
    threshold = d4["threshold_bps"]

    fig = plt.figure(figsize=(12, 8))
    gs = fig.add_gridspec(2, 2)

    # Top-left: spread distribution (log y).
    ax = fig.add_subplot(gs[0, 0])
    ax.hist(ob["spread_bps"], bins=30, color=C_BUY, alpha=0.7, edgecolor="black", lw=0.4)
    ax.axvline(threshold, color=C_FLAG, ls="--", lw=1.5,
               label=f"threshold = {threshold:.1f} bps (median + 1.5×IQR)")
    ax.axvline(15, color="green", ls=":", lw=1.2, label="healthy ETH/BTC ≤15 bps")
    ax.set_xlabel("spread (bps)")
    ax.set_ylabel("# of snapshots")
    ax.set_title(f"D4 — spread distribution (median {summary['median_spread_bps']:.0f}bps, "
                 f"max {summary['max_spread_bps']:.0f}bps)")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)

    # Top-right: spread time series.
    ax = fig.add_subplot(gs[0, 1])
    ax.plot(ob["timestamp"], ob["spread_bps"], color=C_BUY, lw=0.7)
    ax.axhline(threshold, color=C_FLAG, ls="--", lw=1.0)
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("spread (bps)")
    ax.set_title("Spread over time")
    _format_time_axis(ax)

    # Bottom-left: depth imbalance over time.
    ax = fig.add_subplot(gs[1, 0])
    if "depth_imbalance" in ob.columns and ob["depth_imbalance"].notna().any():
        ax.plot(ob["timestamp"], ob["depth_imbalance"], color=C_SELL, lw=0.7)
        ax.axhline(0, color="black", lw=0.5)
        ax.set_ylim(-1, 1)
        ax.set_ylabel("depth imbalance (ask−bid)/(ask+bid)")
        ax.set_xlabel("time (UTC)")
        ax.set_title("Top-5 depth imbalance (positive = ask-heavy)")
        _format_time_axis(ax)

    # Bottom-right: trades outside spread.
    ax = fig.add_subplot(gs[1, 1])
    outside = d4["trades_outside"]
    ax.plot(ob["timestamp"], ob["bid_price"], color=C_BUY,  lw=0.6, label="bid")
    ax.plot(ob["timestamp"], ob["ask_price"], color=C_SELL, lw=0.6, label="ask")
    if not outside.empty:
        ax.scatter(outside["timestamp"], outside["price"],
                   color=C_FLAG, s=12, alpha=0.7, label=f"trade outside spread (n={len(outside)})")
    ax.set_xlabel("time (UTC)")
    ax.set_ylabel("price (ETH/BTC)")
    ax.set_title(f"Trade-vs-spread cross-check ({summary['pct_trades_outside_spread']:.1f}% outside)")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    _format_time_axis(ax)

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# --------------------------------------------- co-occurrence timeline ---
def plot_cooccurrence_v2(
    d1: pd.DataFrame,
    d2: dict,
    d3: pd.DataFrame,
    d4: dict,
    trades: pd.DataFrame,
    out: Path,
    bin_freq: str = "1h",
) -> None:
    """Like plot_cooccurrence but builds the D2 row from trade timestamps."""
    start = d1.index.min().floor(bin_freq) if not d1.empty else trades["timestamp"].min().floor(bin_freq)
    end   = d1.index.max().ceil(bin_freq)  if not d1.empty else trades["timestamp"].max().ceil(bin_freq)
    grid  = pd.date_range(start, end, freq=bin_freq)

    def bin_series(timestamps):
        s = pd.Series(False, index=grid)
        for ts in timestamps:
            t = ts.floor(bin_freq)
            if t in s.index:
                s.loc[t] = True
        return s

    flag_d1 = (
        bin_series(d1.index[d1["flag_any"].fillna(False)])
        if not d1.empty else pd.Series(False, index=grid)
    )

    flagged_sizes = []
    for side in ("buy", "sell"):
        if side in d2 and not d2[side]["flagged"].empty:
            flagged_sizes.extend([(side, s) for s in d2[side]["flagged"]["size"].tolist()])
    d2_ts = []
    for side, s in flagged_sizes:
        sub = trades[(trades["side"] == side) & (np.isclose(trades["size"], s))]
        d2_ts.extend(sub["timestamp"].tolist())
    flag_d2 = bin_series(d2_ts)

    flag_d3 = bin_series(d3["t0"].tolist()) if not d3.empty else pd.Series(False, index=grid)
    flag_d4 = (
        bin_series(d4["flagged_wide"]["timestamp"].tolist())
        if not d4["flagged_wide"].empty else pd.Series(False, index=grid)
    )

    matrix = np.vstack([
        flag_d1.values.astype(int),
        flag_d2.values.astype(int),
        flag_d3.values.astype(int),
        flag_d4.values.astype(int),
    ])
    co = matrix.sum(axis=0)

    fig, ax = plt.subplots(figsize=(12, 4.2))
    # origin='lower' so matrix[0] (D1) renders at y=0 = bottom of the axis;
    # then we reverse the labels so D1 appears visually on top.
    ax.imshow(
        matrix[::-1], aspect="auto", cmap="Oranges", interpolation="nearest",
        extent=[mdates.date2num(grid[0]), mdates.date2num(grid[-1]), -0.5, 3.5],
        origin="lower",
    )
    ax.set_yticks([0, 1, 2, 3])
    ax.set_yticklabels(["D4 wide spread", "D3 pump/dump", "D2 size signature", "D1 imbalance"])
    ax.xaxis_date()
    _format_time_axis(ax)
    ax.set_title("Cross-detector flag timeline — red = ≥2 detectors fire")
    for i, c in enumerate(co):
        if c >= 2 and i < len(grid) - 1:
            ax.axvspan(mdates.date2num(grid[i]), mdates.date2num(grid[i+1]),
                       color="red", alpha=0.20, zorder=0)
    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)


# --------------------------------------------- D5: bursts / TOD / anchors ---
def plot_bursts_and_tod(bursts: pd.DataFrame, tod: pd.DataFrame, anchors: pd.DataFrame,
                       trades: pd.DataFrame, out) -> None:
    """Three-panel figure: burst timeline, time-of-day buy-share, anchor prices."""
    fig = plt.figure(figsize=(13, 9))
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 1, 1])

    # Top: trade-count per second (log y), bursts highlighted
    ax = fig.add_subplot(gs[0, 0])
    if not trades.empty:
        per_sec = trades.assign(sec=trades["timestamp"].dt.floor("s")).groupby("sec").size()
        ax.scatter(per_sec.index, per_sec.values, s=4, color="#444", alpha=0.5, label="trades/sec")
    if not bursts.empty:
        for _, b in bursts.iterrows():
            color = C_BUY if b["dominant_side"] == "buy" else C_SELL
            ax.scatter([b["second"]], [b["n_trades"]], color=color, s=60, zorder=5,
                       edgecolor="black", linewidths=0.5)
    ax.axhline(5, color=C_FLAG, ls="--", lw=1, label="burst threshold (≥5/sec)")
    ax.set_ylabel("trades per second")
    ax.set_yscale("symlog", linthresh=1)
    ax.set_title(f"D5a — burst seconds (n={len(bursts)} bursts of ≥5 trades in one second)")
    ax.legend(loc="upper right", framealpha=0.9, fontsize=8)
    _format_time_axis(ax)

    # Middle: time-of-day pattern
    ax = fig.add_subplot(gs[1, 0])
    width = 0.4
    x = tod["hour_utc"].values
    ax.bar(x - width/2, tod["n_buy"],  width, label="buys",  color=C_BUY, alpha=0.85)
    ax.bar(x + width/2, tod["n_sell"], width, label="sells", color=C_SELL, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xlabel("hour (UTC)")
    ax.set_ylabel("# trades")
    ax.set_title("D5b — trade count by UTC hour (sells concentrate in US session, buys 24/7)")
    ax.legend(loc="upper right", framealpha=0.9)
    # Highlight US session hours
    for h in range(13, 21):
        ax.axvspan(h - 0.5, h + 0.5, color="#fff7bc", alpha=0.4, zorder=0)
    ax.text(16.5, ax.get_ylim()[1] * 0.95, "US session (UTC 13-20)",
            ha="center", fontsize=8, color="#666")

    # Bottom: top anchor prices
    ax = fig.add_subplot(gs[2, 0])
    a = anchors.head(15)
    ax.barh([f"{p:.6f}" for p in a["price"]], a["count"], color=C_BUY, alpha=0.85)
    ax.invert_yaxis()
    ax.set_xlabel("# trades at this exact price")
    ax.set_title("D5c — top 15 anchor prices (limit-order resting clusters)")
    for i, (_, r) in enumerate(a.iterrows()):
        ax.text(r["count"] + 0.2, i, f"  {r['count']} ({r['share_pct']:.1f}%)",
                va="center", fontsize=8, color="#444")

    fig.tight_layout()
    fig.savefig(out)
    plt.close(fig)
