"""ETH/BTC suspicious-pattern analysis — DN Institute Challenge #492.

Single-command runner for the five-detector framework (D1 imbalance,
D2 size signatures, D3 pump-and-dump, D4 liquidity, D5 bursts/TOD/anchors).
Loads CSVs, runs each detector, writes figures, prints a summary, and dumps
machine-readable findings.json.

Usage
-----
    python analyze.py \
        --trades data/eth-btc-trades.csv \
        --orderbooks data/eth-btc-orderbooks.csv \
        --out figures

When run inside a fork of the upstream challenge repo, the CSVs live at
the fork root (one level up) — pass --trades ../eth-btc-trades.csv etc.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.data import load_trades, load_orderbooks, summarize
from src.detector_imbalance  import detect_buysell_imbalance, summarize_d1
from src.detector_signatures import detect_size_signatures, summarize_d2
from src.detector_pumpdump   import detect_pumpdump, summarize_d3
from src.detector_liquidity  import detect_liquidity_quality
from src.detector_bursts     import (
    detect_bursts, detect_time_of_day, detect_anchor_prices, summarize_d5,
)
from src.detector_microstructure import summarize_d6
from src.plotting import (
    plot_imbalance, plot_signatures, plot_pumpdump, plot_liquidity,
    plot_cooccurrence_v2, plot_bursts_and_tod,
)


def _to_jsonable(o):
    """JSON serializer that handles numpy scalars, Timestamps, NaN, NaT, DataFrames."""
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.isoformat()
    if isinstance(o, pd.Timedelta):
        return o.total_seconds()
    if isinstance(o, pd.DataFrame):
        return o.to_dict(orient="records")
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Unserializable type: {type(o)}")



def _smart_default(name: str) -> Path:
    """Resolve dataset path: prefer data/<name>, fall back to ../<name>.

    Lets `python analyze.py` work both inside the source-of-truth checkout
    (CSVs in data/) and inside a fork of the upstream challenge repo
    (CSVs at fork root, one level up).
    """
    here = Path("data") / name
    if here.exists():
        return here
    return Path("..") / name


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--trades", type=Path,
                   default=_smart_default("eth-btc-trades.csv"),
                   help="Path to trades CSV (default: data/.. or ../..)")
    p.add_argument("--orderbooks", type=Path,
                   default=_smart_default("eth-btc-orderbooks.csv"),
                   help="Path to orderbooks CSV (default: data/.. or ../..)")
    p.add_argument("--out", default=Path("figures"), type=Path,
                   help="Output directory for PNG figures (default: figures/)")
    p.add_argument("--findings", default=Path("findings.json"), type=Path,
                   help="Output path for machine-readable findings (default: findings.json)")
    args = p.parse_args()

    # Friendly path validation before pandas raises an unhelpful traceback.
    for label, path in [("trades", args.trades), ("orderbooks", args.orderbooks)]:
        if not path.exists():
            sys.exit(f"[error] {label} CSV not found: {path}")

    args.out.mkdir(exist_ok=True, parents=True)

    print(f"[load] trades:     {args.trades}")
    print(f"[load] orderbooks: {args.orderbooks}")
    trades = load_trades(args.trades)
    ob     = load_orderbooks(args.orderbooks)
    if trades.empty:
        sys.exit("[error] trades CSV produced no usable rows after schema validation.")
    if ob.empty:
        sys.exit("[error] orderbooks CSV produced no usable rows after schema validation.")
    meta = summarize(trades, ob)
    print(f"[load] {meta['n_trades']} trades, {meta['n_orderbooks']} orderbook snapshots")
    print(f"[load] span {meta['span_hours']}h ({meta['trades_start']} → {meta['trades_end']})")
    print(f"[load] buy share by count: {meta['buy_pct']}%")
    print(f"[load] median spread: {meta['median_spread_bps']} bps  (max {meta['max_spread_bps']} bps)")

    # --- Detector 1 -------------------------------------------------------
    print("\n[D1] buy/sell imbalance — 30min buckets, 8h rolling z, |z|>3 …")
    d1 = detect_buysell_imbalance(trades)
    d1_sum = summarize_d1(d1)
    print(f"     buckets={d1_sum['n_buckets']}  flagged_any={d1_sum['n_flagged_any']}  "
          f"event_clusters={d1_sum['n_event_clusters']}  "
          f"max|z| count={d1_sum['max_z_count']:.2f}  size={d1_sum['max_z_size']:.2f}")
    print(f"     global buy share — count {d1_sum['global_buy_count_share']*100:.1f}%, "
          f"size {d1_sum['global_buy_size_share']*100:.4f}%")
    plot_imbalance(d1, args.out / "d1_imbalance.png")

    # --- Detector 2 -------------------------------------------------------
    print("\n[D2] recurring trade-size signatures — KDE-on-log(size) null, 1000 reps, p99 …")
    d2 = detect_size_signatures(trades, n_replicates=1000, percentile=99.0)
    d2_sum = summarize_d2(d2)
    for side, s in d2_sum.items():
        thr = s.get("null_threshold")
        thr_is_nan = isinstance(thr, float) and np.isnan(thr)
        thr_str = f"{thr:.2f}" if thr is not None and not thr_is_nan else "n/a"
        top_size = s.get("top_size")
        top_size_str = f"{top_size}" if top_size is not None else "—"
        print(f"     [{side:>4}] n={s['n_trades']}  null_thresh={thr_str}  "
              f"flagged_sizes={s['n_flagged_sizes']}  "
              f"top_size={top_size_str} ×{s['top_count']} "
              f"({s['top_share_pct']:.1f}% of side)")
    plot_signatures(trades, d2, args.out / "d2_signatures.png")

    # --- Detector 3 -------------------------------------------------------
    print("\n[D3] pump/dump — 1h vol z>2σ + ≥0.5% move + ≥50% reversal in 1h, bidirectional …")
    d3 = detect_pumpdump(trades)
    d3_sum = summarize_d3(d3)
    print(f"     candidates={d3_sum['n_candidates']}  "
          f"pump={d3_sum.get('n_pump', 0)}  dump={d3_sum.get('n_dump', 0)}")
    if d3_sum["n_candidates"]:
        print(f"     top: {d3_sum['top_t0']}  move={d3_sum['top_move_pct']*100:+.2f}%  "
              f"reversal={d3_sum['top_reversal_pct']*100:.0f}%  vol_z={d3_sum['top_vol_z']:.2f}")
    plot_pumpdump(trades, d3, args.out / "d3_pumpdump.png")

    # --- Detector 4 -------------------------------------------------------
    print("\n[D4] spread + depth + trade-vs-spread — dataset-relative threshold …")
    d4 = detect_liquidity_quality(trades, ob)
    s4 = d4["summary"]
    print(f"     spread (bps): median {s4['median_spread_bps']:.2f}  "
          f"p95 {s4['p95_spread_bps']:.2f}  max {s4['max_spread_bps']:.2f}")
    print(f"     threshold {s4['threshold_bps']:.2f} bps → {s4['n_flagged_wide']} snapshots flagged "
          f"({s4['pct_flagged_wide']:.1f}%)")
    print(f"     trades outside contemporaneous spread: {s4['n_trades_outside_spread']} "
          f"({s4['pct_trades_outside_spread']:.2f}%)")
    if s4.get("median_depth_imbalance") is not None:
        print(f"     depth imbalance — median {s4['median_depth_imbalance']:+.3f}, "
              f"p95 {s4['p95_depth_imbalance']:+.3f}")
    plot_liquidity(d4, args.out / "d4_liquidity.png")

    # --- Detector 5 -------------------------------------------------------
    print("\n[D5] burst-execution / time-of-day / anchor-prices …")
    bursts  = detect_bursts(trades, min_trades_per_second=5)
    tod     = detect_time_of_day(trades)
    anchors = detect_anchor_prices(trades, top_n=15)
    d5_sum  = summarize_d5(bursts, tod, anchors)
    bb = d5_sum['bursts']
    print(f"     bursts (≥5/sec): {bb['n_bursts']}  "
          f"max_in_one_sec={bb.get('max_n_in_one_second', 0)}  "
          f"({bb.get('max_burst_side', 'n/a')}-dominant @ {bb.get('max_burst_second')})")
    tt = d5_sum['tod']
    print(f"     hours with sells: {tt['hours_with_any_sells']}/24  "
          f"(zero sells in {tt['hours_with_zero_sells']} hours)  "
          f"min_buy_share={tt['min_buy_share_pct']:.1f}% at hour {tt['min_buy_share_hour']}")
    print(f"     top anchor price: {d5_sum['top_anchor_price']} × {d5_sum['top_anchor_count']} "
          f"({d5_sum['top_anchor_share_pct']:.1f}%)")
    plot_bursts_and_tod(bursts, tod, anchors, trades, args.out / "d5_bursts_tod_anchors.png")

    # --- Detector 6 (peer-corroborated cross-checks) ---------------------
    print("\n[D6] microstructure cross-checks (frozen OB · Benford · interval CV) …")
    ob_raw_for_d6 = pd.read_csv(args.orderbooks)
    d6_sum = summarize_d6(ob_raw_for_d6, trades)
    fo = d6_sum["frozen_orderbook"]
    bf = d6_sum["benford"]
    iv = d6_sum["interval_buy_sep3_14plus"]
    print(f"     frozen bid {fo['frozen_bid']}/{fo['n_pairs']} ({fo['frozen_bid_pct']:.1f}%) "
          f"vs ask {fo['frozen_ask']}/{fo['n_pairs']} ({fo['frozen_ask_pct']:.1f}%)  "
          f"asymmetry {fo['asymmetry_ratio']}x  "
          f"longest_bid_run={fo['longest_bid_run']} "
          f"({fo['longest_bid_run_start']} → {fo['longest_bid_run_end']})")
    print(f"     Benford K-S {bf['ks_stat']} vs crit {bf['ks_critical_05']} "
          f"(n={bf['n']}) → {'REJECT' if bf['reject_null'] else 'do not reject'}")
    print(f"     buy intervals (Sep-3 14:00+ UTC): n={iv['n_trades']}  "
          f"median={iv['median_seconds']}s  IQR={iv['iqr_low_seconds']}–{iv['iqr_high_seconds']}s  "
          f"CV={iv['cv']}")

    # --- Co-occurrence ----------------------------------------------------
    print("\n[XR] cross-detector co-occurrence timeline …")
    plot_cooccurrence_v2(d1, d2, d3, d4, trades, args.out / "co_occurrence_timeline.png")

    # --- Persist findings -------------------------------------------------
    findings = {
        "dataset": meta,
        "d1": d1_sum,
        "d2": d2_sum,
        "d3": d3_sum,
        "d4": s4,
        "d5": d5_sum,
        "d5_bursts": bursts.to_dict(orient="records") if not bursts.empty else [],
        "d5_anchors": anchors.to_dict(orient="records") if not anchors.empty else [],
        "d6": d6_sum,
    }
    with open(args.findings, "w") as f:
        json.dump(findings, f, indent=2, default=_to_jsonable)
    print(f"\n[done] figures → {args.out}/  ·  findings → {args.findings}")


if __name__ == "__main__":
    main()
