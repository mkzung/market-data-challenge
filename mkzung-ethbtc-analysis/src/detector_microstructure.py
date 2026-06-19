"""Detector 6, microstructure cross-checks (peer-corroborated).

After completing the D1-D5 framework, peer review of prior submissions to
1712n/market-data-challenge surfaced three additional forensic angles that
we had not explicitly tested. We re-derive each on the same dataset and
integrate them as D6 sub-detectors.

D6a, Frozen orderbook
    Count byte-identical consecutive snapshots per side. An asymmetry
    between bid-side and ask-side freeze rates is consistent with stale
    quotes / spoofing on one side, not active two-sided market making.

D6b, Benford's Law conformity
    K-S test of the first-digit distribution of trade sizes against
    Benford's expected log10(1 + 1/d) distribution. Synthetic-data
    forensics indicator: organic size distributions tend to conform
    loosely; programmatically generated sizes often do not.

D6c, Inter-trade interval regularity (windowed)
    Median / IQR / coefficient-of-variation of inter-trade gaps for a
    given side over a chosen time window. Tight IQR around a fixed period
    is consistent with cron-style algorithmic scheduling.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# D6a, frozen orderbook
# ---------------------------------------------------------------------------

def detect_frozen_orderbook(orderbooks_raw: pd.DataFrame) -> dict:
    """Count byte-identical consecutive orderbook snapshots, by side.

    Parameters
    ----------
    orderbooks_raw : DataFrame
        The RAW orderbooks CSV (string columns 'bids', 'asks'), NOT the
        parsed top-of-book DataFrame. Byte-equality is the relevant signal -
        we explicitly want to detect that the venue re-emitted the same
        serialized snapshot, not just that top-of-book happened to round
        to the same number.

    Returns
    -------
    dict with:
        n_snapshots
        n_pairs (= n_snapshots - 1)
        frozen_bid       : pairs where bids string == previous bids string
        frozen_ask       : same, ask side
        frozen_both      : pairs where BOTH sides identical
        frozen_bid_pct, frozen_ask_pct
        asymmetry_ratio  : frozen_bid / max(frozen_ask, 1)
        longest_bid_run  : max length of consecutive identical bids
        longest_bid_run_start, longest_bid_run_end (timestamps, ISO)
        longest_ask_run, longest_ask_run_start, longest_ask_run_end
    """
    needed = {"timestamp", "bids", "asks"}
    if not needed.issubset(orderbooks_raw.columns):
        raise ValueError(
            f"Need columns {needed}; got {list(orderbooks_raw.columns)}"
        )

    df = orderbooks_raw.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
    n = len(df)

    if n < 2:
        return {
            "n_snapshots": n,
            "n_pairs": 0,
            "frozen_bid": 0,
            "frozen_ask": 0,
            "frozen_both": 0,
            "frozen_bid_pct": 0.0,
            "frozen_ask_pct": 0.0,
            "asymmetry_ratio": float("nan"),
            "longest_bid_run": 0,
            "longest_ask_run": 0,
            "longest_bid_run_start": None,
            "longest_bid_run_end": None,
            "longest_ask_run_start": None,
            "longest_ask_run_end": None,
        }

    bid_eq = df["bids"].astype(str).values[1:] == df["bids"].astype(str).values[:-1]
    ask_eq = df["asks"].astype(str).values[1:] == df["asks"].astype(str).values[:-1]

    frozen_bid = int(bid_eq.sum())
    frozen_ask = int(ask_eq.sum())
    frozen_both = int((bid_eq & ask_eq).sum())
    n_pairs = n - 1

    def _longest_run(eq_array: np.ndarray, ts: pd.Series) -> tuple[int, Optional[str], Optional[str]]:
        """Length of longest True run in eq_array; ts indexed [0..n-1].
        A run of length k corresponds to k+1 consecutive identical snapshots.
        """
        if len(eq_array) == 0 or not eq_array.any():
            return 0, None, None
        best_len = 0
        best_start_i = 0
        best_end_i = 0
        cur_len = 0
        cur_start = 0
        for i, v in enumerate(eq_array):
            if v:
                if cur_len == 0:
                    cur_start = i  # first eq pair (i, i+1)
                cur_len += 1
                if cur_len > best_len:
                    best_len = cur_len
                    best_start_i = cur_start
                    best_end_i = i + 1  # inclusive end snapshot index
            else:
                cur_len = 0
        return best_len, ts.iloc[best_start_i].isoformat(), ts.iloc[best_end_i].isoformat()

    bid_run_len, bid_run_start, bid_run_end = _longest_run(bid_eq, df["timestamp"])
    ask_run_len, ask_run_start, ask_run_end = _longest_run(ask_eq, df["timestamp"])

    asymmetry = frozen_bid / max(frozen_ask, 1)

    return {
        "n_snapshots": int(n),
        "n_pairs": int(n_pairs),
        "frozen_bid": frozen_bid,
        "frozen_ask": frozen_ask,
        "frozen_both": frozen_both,
        "frozen_bid_pct": round(frozen_bid / n_pairs * 100, 2),
        "frozen_ask_pct": round(frozen_ask / n_pairs * 100, 2),
        "asymmetry_ratio": round(asymmetry, 2),
        "longest_bid_run": int(bid_run_len),
        "longest_ask_run": int(ask_run_len),
        "longest_bid_run_start": bid_run_start,
        "longest_bid_run_end": bid_run_end,
        "longest_ask_run_start": ask_run_start,
        "longest_ask_run_end": ask_run_end,
    }


# ---------------------------------------------------------------------------
# D6b, Benford's Law (first-digit K-S test)
# ---------------------------------------------------------------------------

def _first_digit(x: float) -> Optional[int]:
    """Return the first significant digit (1..9) of a positive number, else None."""
    if not np.isfinite(x) or x <= 0:
        return None
    # Robust to scientific notation / leading zeros: shift exponent until in [1,10).
    while x < 1:
        x *= 10
    while x >= 10:
        x /= 10
    d = int(x)
    return d if 1 <= d <= 9 else None


def detect_benford(trades: pd.DataFrame, col: str = "size") -> dict:
    """K-S test of first-digit distribution of `trades[col]` against Benford.

    Returns a dict with empirical and expected digit shares, the K-S statistic,
    the critical value at α=0.05 (1.36 / sqrt(n)), and a reject-null flag.
    """
    sizes = trades[col].dropna().astype(float).values
    digits = [d for d in (_first_digit(x) for x in sizes) if d is not None]
    n = len(digits)

    expected = np.array([math.log10(1 + 1 / d) for d in range(1, 10)])

    if n == 0:
        return {
            "n": 0,
            "empirical": [0.0] * 9,
            "expected": expected.tolist(),
            "ks_stat": float("nan"),
            "ks_critical_05": float("nan"),
            "reject_null": False,
        }

    counts = np.array([digits.count(d) for d in range(1, 10)])
    empirical = counts / n

    # Two-sample-style K-S statistic against an exact distribution: max |F_emp - F_exp|.
    cum_emp = np.cumsum(empirical)
    cum_exp = np.cumsum(expected)
    ks = float(np.max(np.abs(cum_emp - cum_exp)))
    crit = 1.36 / math.sqrt(n)

    return {
        "n": int(n),
        "empirical": [round(float(x), 4) for x in empirical],
        "expected":  [round(float(x), 4) for x in expected],
        "ks_stat": round(ks, 4),
        "ks_critical_05": round(crit, 4),
        "reject_null": bool(ks > crit),
    }


# ---------------------------------------------------------------------------
# D6c, inter-trade interval regularity (windowed, side-filtered)
# ---------------------------------------------------------------------------

def detect_interval_regularity(
    trades: pd.DataFrame,
    side: str = "buy",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
) -> dict:
    """Compute summary statistics of inter-trade gaps (seconds) for one side.

    Parameters
    ----------
    trades : DataFrame
        Canonical trades (lowercase 'side' values).
    side : 'buy' | 'sell'
    window_start, window_end : ISO timestamp strings, optional
        Restrict to trades within [start, end). Either bound may be None.
    """
    df = trades[trades["side"] == side].sort_values("timestamp").copy()
    if window_start is not None:
        df = df[df["timestamp"] >= pd.Timestamp(window_start)]
    if window_end is not None:
        df = df[df["timestamp"] < pd.Timestamp(window_end)]
    n = len(df)

    if n < 2:
        return {
            "side": side,
            "n_trades": int(n),
            "window_start": window_start,
            "window_end":   window_end,
            "median_seconds": float("nan"),
            "iqr_low_seconds":  float("nan"),
            "iqr_high_seconds": float("nan"),
            "mean_seconds": float("nan"),
            "std_seconds":  float("nan"),
            "cv": float("nan"),
        }

    gaps = df["timestamp"].diff().dropna().dt.total_seconds().values
    median = float(np.median(gaps))
    q1, q3 = (float(x) for x in np.quantile(gaps, [0.25, 0.75]))
    mean = float(np.mean(gaps))
    std  = float(np.std(gaps, ddof=1)) if len(gaps) > 1 else float("nan")
    cv   = std / mean if mean and not math.isnan(std) else float("nan")

    return {
        "side": side,
        "n_trades": int(n),
        "window_start": window_start,
        "window_end":   window_end,
        "median_seconds": round(median, 2),
        "iqr_low_seconds":  round(q1, 2),
        "iqr_high_seconds": round(q3, 2),
        "mean_seconds": round(mean, 2),
        "std_seconds":  round(std, 2) if not math.isnan(std) else float("nan"),
        "cv": round(cv, 4) if not math.isnan(cv) else float("nan"),
    }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def summarize_d6(orderbooks_raw: pd.DataFrame, trades: pd.DataFrame) -> dict:
    """Run all three D6 sub-detectors and return a single summary dict."""
    return {
        "frozen_orderbook":  detect_frozen_orderbook(orderbooks_raw),
        "benford":           detect_benford(trades, col="size"),
        # Default window: from 2025-09-03 14:00 UTC onward, buy side.
        # This window was identified during D5 burst analysis as the most
        # algorithmically regular phase of the dataset.
        "interval_buy_sep3_14plus": detect_interval_regularity(
            trades,
            side="buy",
            window_start="2025-09-03 14:00:00+00:00",
        ),
    }
