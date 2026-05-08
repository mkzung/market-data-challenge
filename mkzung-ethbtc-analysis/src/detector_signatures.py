"""D2 — Recurring Trade-Size Signatures (per side).

Hypothesis: bot/wash activity produces identical-size trades repeated many
times. Under a continuous-distribution null, a discrete tick-rounded value
appearing K times is rare for K above some threshold determined by the
sample distribution and size of K.

CRITICAL FIX vs. brief:
The brief proposed shuffling the array and computing max value_counts.
That null is degenerate — shuffling a multiset preserves frequencies, so
every "permutation" yields the same max count. The intended null is
"sizes drawn IID from a continuous distribution, then rounded to tick" —
under that null, exact repeats are rare. We implement that with a
Gaussian KDE on log(size), draw n samples per replicate, round to tick,
count max frequency.

Per-side execution:
The dataset has side-conditional bimodality (BUY sizes ~10^2, SELL
~10^-3). Pooling them dilutes both signals, so we run D2 separately on
each side.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde


def _kde_null_max_counts(
    sizes: np.ndarray,
    n_replicates: int,
    tick_decimals: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw `len(sizes)` samples per replicate from a smooth fit to log(size),
    round to tick, return the max value-count per replicate.
    """
    log_sizes = np.log(sizes)
    kde = gaussian_kde(log_sizes)
    n = len(sizes)
    out = np.empty(n_replicates, dtype=np.int64)
    for i in range(n_replicates):
        draws = np.exp(kde.resample(n, seed=rng).flatten())
        draws_rounded = np.round(draws, tick_decimals)
        # value_counts via numpy
        _, counts = np.unique(draws_rounded, return_counts=True)
        out[i] = int(counts.max())
    return out


def detect_size_signatures(
    trades: pd.DataFrame,
    n_replicates: int = 1000,
    percentile: float = 99.0,
    tick_decimals: int = 8,
    seed: int = 42,
    by_side: bool = True,
) -> dict:
    """Detect anomalously frequent trade sizes.

    Parameters
    ----------
    n_replicates : int (default 1000)   Monte-Carlo replicates of the KDE null
    percentile : float (default 99.0)   percentile of max-count for threshold
    tick_decimals : int (default 8)     decimal places for tick rounding
    seed : int (default 42)             RNG seed (ensures reproducibility)
    by_side : bool (default True)       split BUY/SELL — required when side
                                        size distributions differ structurally

    Returns
    -------
    dict with keys per-side ("buy", "sell", and "all" if by_side=False) →
        each is a dict {threshold, flagged_sizes (DataFrame), null_max_dist (np.ndarray)}.
    """
    rng = np.random.default_rng(seed)
    out: dict = {}

    groups = (
        [(s, trades[trades["side"] == s]) for s in ("buy", "sell")]
        if by_side else
        [("all", trades)]
    )
    for label, sub in groups:
        if len(sub) < 5:
            out[label] = {
                "n": len(sub),
                "threshold": float("nan"),
                "flagged": pd.DataFrame(columns=["size", "count", "share_pct"]),
                "null_max_dist": np.array([]),
            }
            continue
        sizes = sub["size"].round(tick_decimals).values
        observed_counts = pd.Series(sizes).value_counts()
        null_max = _kde_null_max_counts(sizes, n_replicates, tick_decimals, rng)
        threshold = float(np.percentile(null_max, percentile))
        flagged_idx = observed_counts[observed_counts > threshold].index
        flagged = pd.DataFrame({
            "size": flagged_idx,
            "count": observed_counts.loc[flagged_idx].values,
            "share_pct": observed_counts.loc[flagged_idx].values / len(sub) * 100,
        }).sort_values("count", ascending=False).reset_index(drop=True)
        out[label] = {
            "n": int(len(sub)),
            "threshold": threshold,
            "null_max_mean": float(null_max.mean()),
            "null_max_p99": float(np.percentile(null_max, 99)),
            "flagged": flagged,
            "null_max_dist": null_max,
        }
    return out


def summarize_d2(d2: dict) -> dict:
    summary = {}
    for side, payload in d2.items():
        flagged = payload["flagged"]
        summary[side] = {
            "n_trades": payload.get("n", 0),
            "null_threshold": payload.get("threshold"),
            "n_flagged_sizes": int(len(flagged)),
            "max_count": int(flagged["count"].max()) if not flagged.empty else 0,
            "top_size": float(flagged.iloc[0]["size"]) if not flagged.empty else None,
            "top_count": int(flagged.iloc[0]["count"]) if not flagged.empty else 0,
            "top_share_pct": float(flagged.iloc[0]["share_pct"]) if not flagged.empty else 0.0,
        }
    return summary
