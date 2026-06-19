"""Tests for D6 microstructure cross-checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.detector_microstructure import (
    detect_frozen_orderbook,
    detect_benford,
    detect_interval_regularity,
    summarize_d6,
)


# ---------------------------------------------------------------------------
# D6a, frozen orderbook
# ---------------------------------------------------------------------------

def _ob_row(ts, bids, asks):
    return {"timestamp": ts, "bids": bids, "asks": asks}


def test_frozen_empty_input_returns_zeros():
    df = pd.DataFrame(columns=["timestamp", "bids", "asks"])
    out = detect_frozen_orderbook(df)
    assert out["n_pairs"] == 0
    assert out["frozen_bid"] == 0
    assert out["frozen_ask"] == 0


def test_frozen_single_row_returns_zeros():
    df = pd.DataFrame([_ob_row("2025-09-01T00:00:00Z", "[a]", "[b]")])
    out = detect_frozen_orderbook(df)
    assert out["n_snapshots"] == 1
    assert out["n_pairs"] == 0


def test_frozen_all_identical_runs():
    rows = [
        _ob_row(f"2025-09-01T00:00:0{i}Z", "[same_bid]", "[same_ask]")
        for i in range(5)
    ]
    out = detect_frozen_orderbook(pd.DataFrame(rows))
    assert out["n_pairs"] == 4
    assert out["frozen_bid"] == 4
    assert out["frozen_ask"] == 4
    assert out["longest_bid_run"] == 4
    assert out["longest_ask_run"] == 4


def test_frozen_asymmetry_bid_only():
    rows = [
        _ob_row("2025-09-01T00:00:00Z", "[X]", "[A1]"),
        _ob_row("2025-09-01T00:00:01Z", "[X]", "[A2]"),
        _ob_row("2025-09-01T00:00:02Z", "[X]", "[A3]"),
    ]
    out = detect_frozen_orderbook(pd.DataFrame(rows))
    assert out["frozen_bid"] == 2
    assert out["frozen_ask"] == 0
    assert out["asymmetry_ratio"] == 2.0
    assert out["longest_bid_run"] == 2
    assert out["longest_ask_run"] == 0


def test_frozen_longest_run_correct_endpoints():
    """Run of length 3 (4 identical snapshots), then a change, then a 2-pair run."""
    rows = [
        _ob_row("2025-09-01T00:00:00Z", "[X]", "[a]"),
        _ob_row("2025-09-01T00:00:01Z", "[X]", "[a]"),
        _ob_row("2025-09-01T00:00:02Z", "[X]", "[a]"),
        _ob_row("2025-09-01T00:00:03Z", "[X]", "[a]"),  # 4 identical → run len = 3
        _ob_row("2025-09-01T00:00:04Z", "[Y]", "[a]"),  # break
        _ob_row("2025-09-01T00:00:05Z", "[Y]", "[a]"),
        _ob_row("2025-09-01T00:00:06Z", "[Y]", "[a]"),  # run len 2
    ]
    out = detect_frozen_orderbook(pd.DataFrame(rows))
    # Total pairs equal: 3 (first run) + 2 (second run) = 5
    assert out["frozen_bid"] == 5
    assert out["longest_bid_run"] == 3
    assert out["longest_bid_run_start"].startswith("2025-09-01T00:00:00")
    assert out["longest_bid_run_end"].startswith("2025-09-01T00:00:03")


# ---------------------------------------------------------------------------
# D6b, Benford
# ---------------------------------------------------------------------------

def test_benford_uniform_digits_rejects_null():
    """Uniform digit distribution is far from Benford → reject."""
    rng = np.random.default_rng(42)
    sizes = []
    for d in range(1, 10):
        sizes.extend(rng.uniform(d, d + 0.99, size=200))
    trades = pd.DataFrame({"size": sizes})
    out = detect_benford(trades)
    assert out["reject_null"] is True
    assert out["ks_stat"] > out["ks_critical_05"]


def test_benford_lognormal_does_not_reject():
    """Log-normal sizes spanning many decades should hug Benford."""
    rng = np.random.default_rng(7)
    sizes = np.exp(rng.normal(loc=0, scale=3.0, size=5000))
    trades = pd.DataFrame({"size": sizes})
    out = detect_benford(trades)
    assert out["reject_null"] is False
    assert out["n"] == 5000


def test_benford_empty_input():
    trades = pd.DataFrame({"size": []})
    out = detect_benford(trades)
    assert out["n"] == 0
    assert out["reject_null"] is False


# ---------------------------------------------------------------------------
# D6c, interval regularity
# ---------------------------------------------------------------------------

def test_interval_constant_spacing_zero_cv():
    """Five buys at exactly 60s spacing → median 60, CV ~0."""
    ts = pd.date_range("2025-09-03 14:00", periods=5, freq="60s", tz="UTC")
    trades = pd.DataFrame({
        "timestamp": ts,
        "side": ["buy"] * 5,
        "price": [1.0] * 5,
        "size": [1.0] * 5,
    })
    out = detect_interval_regularity(trades, side="buy")
    assert out["median_seconds"] == 60.0
    assert out["iqr_low_seconds"] == 60.0
    assert out["iqr_high_seconds"] == 60.0


def test_interval_window_filtering_excludes_pre_window():
    """Trades before window_start are dropped."""
    ts = list(pd.date_range("2025-09-03 13:00", periods=3, freq="120s", tz="UTC")) + \
         list(pd.date_range("2025-09-03 14:00", periods=4, freq="60s",  tz="UTC"))
    trades = pd.DataFrame({
        "timestamp": ts,
        "side": ["buy"] * 7,
        "price": [1.0] * 7,
        "size": [1.0] * 7,
    })
    out = detect_interval_regularity(
        trades, side="buy", window_start="2025-09-03 14:00:00+00:00"
    )
    assert out["n_trades"] == 4
    assert out["median_seconds"] == 60.0


def test_interval_side_filter():
    """Only the requested side contributes."""
    ts = pd.date_range("2025-09-03 14:00", periods=4, freq="60s", tz="UTC")
    trades = pd.DataFrame({
        "timestamp": ts,
        "side": ["buy", "sell", "buy", "sell"],
        "price": [1.0] * 4,
        "size": [1.0] * 4,
    })
    out = detect_interval_regularity(trades, side="buy")
    assert out["n_trades"] == 2
    # 2 buys 120s apart → 1 gap of 120s
    assert out["median_seconds"] == 120.0


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

def test_summarize_d6_runs_and_has_keys():
    rows = [
        _ob_row(f"2025-09-01T00:00:0{i}Z", "[X]", "[A]") for i in range(3)
    ]
    ob_raw = pd.DataFrame(rows)
    ts = pd.date_range("2025-09-03 14:00", periods=3, freq="60s", tz="UTC")
    trades = pd.DataFrame({
        "timestamp": ts,
        "side": ["buy"] * 3,
        "price": [1.0] * 3,
        "size":  [1.0, 2.0, 3.0],
    })
    out = summarize_d6(ob_raw, trades)
    assert {"frozen_orderbook", "benford", "interval_buy_sep3_14plus"} == set(out.keys())
