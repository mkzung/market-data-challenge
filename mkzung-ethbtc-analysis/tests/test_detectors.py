"""Unit tests for the five detectors using fixtures with known properties."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.detector_imbalance  import detect_buysell_imbalance, summarize_d1
from src.detector_signatures import detect_size_signatures
from src.detector_pumpdump   import detect_pumpdump
from src.detector_liquidity  import detect_liquidity_quality
from src.detector_bursts     import detect_bursts, detect_time_of_day, detect_anchor_prices


def _balanced_trades(n=200, seed=0):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    timestamps = start + pd.to_timedelta(np.sort(rng.uniform(0, 72*3600, size=n)), unit="s")
    return pd.DataFrame({
        "timestamp": timestamps,
        "price":     0.04 + rng.normal(0, 0.0001, size=n),
        "size":      rng.lognormal(0, 1, size=n),
        "side":      rng.choice(["buy", "sell"], size=n, p=[0.5, 0.5]),
    })


def _fake_orderbooks(n=20, seed=0):
    rng = np.random.default_rng(seed)
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    timestamps = start + pd.to_timedelta(np.sort(rng.uniform(0, 72*3600, size=n)), unit="s")
    return pd.DataFrame({
        "timestamp":   timestamps,
        "ask_price":   0.0405 + rng.normal(0, 1e-5, size=n),
        "bid_price":   0.0395 + rng.normal(0, 1e-5, size=n),
        "ask_size":    rng.lognormal(-2, 1, size=n),
        "bid_size":    rng.lognormal(-2, 1, size=n),
        "ask_depth_5": rng.lognormal(-1, 0.5, size=n),
        "bid_depth_5": rng.lognormal(-1, 0.5, size=n),
        "n_levels_ask": np.full(n, 50),
        "n_levels_bid": np.full(n, 50),
    }).assign(
        mid=lambda d: (d["bid_price"] + d["ask_price"]) / 2,
        spread_bps=lambda d: (d["ask_price"] - d["bid_price"]) / d["mid"] * 1e4,
    )


# ---------------------------------------------------------------------------
# D1 imbalance
# ---------------------------------------------------------------------------
def test_d1_empty():
    out = detect_buysell_imbalance(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert out.empty


def test_d1_balanced_market_no_flags():
    t = _balanced_trades(n=200, seed=1)
    out = detect_buysell_imbalance(t)
    summary = summarize_d1(out)
    # Balanced market: no event clusters, count share near 50%, all buckets stable
    assert summary["n_event_clusters"] == 0
    assert 0.4 < summary["global_buy_count_share"] < 0.6


def test_d1_extreme_imbalance_global_share_close_to_one():
    rng = np.random.default_rng(5)
    n = 100
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    t = pd.DataFrame({
        "timestamp": start + pd.to_timedelta(np.sort(rng.uniform(0, 72*3600, size=n)), unit="s"),
        "price":     0.04 * np.ones(n),
        "size":      np.full(n, 100.0),
        "side":      np.full(n, "buy"),  # all buys
    })
    out = detect_buysell_imbalance(t)
    summary = summarize_d1(out)
    assert summary["global_buy_count_share"] == 1.0


# ---------------------------------------------------------------------------
# D2 signatures
# ---------------------------------------------------------------------------
def test_d2_empty():
    out = detect_size_signatures(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert "buy" in out and "sell" in out
    assert out["buy"]["flagged"].empty


def test_d2_clean_data_no_flags():
    t = _balanced_trades(n=300, seed=2)
    out = detect_size_signatures(t, n_replicates=200)
    # All sizes drawn from continuous lognormal; no recurring exact values
    assert out["buy"]["flagged"].empty
    assert out["sell"]["flagged"].empty


def test_d2_repeated_size_flagged():
    rng = np.random.default_rng(3)
    n = 200
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    sizes = rng.lognormal(0, 1, size=n)
    sizes[:10] = 0.123456  # 10 trades at exactly the same size
    t = pd.DataFrame({
        "timestamp": start + pd.to_timedelta(np.sort(rng.uniform(0, 72*3600, size=n)), unit="s"),
        "price":     0.04 * np.ones(n),
        "size":      sizes,
        "side":      rng.choice(["buy", "sell"], size=n, p=[0.5, 0.5]),
    })
    out = detect_size_signatures(t, n_replicates=200)
    # The 0.123456 repetition should be detected on at least one side
    flagged_total = out["buy"]["flagged"]["size"].tolist() + out["sell"]["flagged"]["size"].tolist()
    assert any(abs(s - 0.123456) < 1e-7 for s in flagged_total)


# ---------------------------------------------------------------------------
# D3 pump-and-dump
# ---------------------------------------------------------------------------
def test_d3_empty():
    out = detect_pumpdump(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert out.empty


def test_d3_no_pump_flat_market():
    t = _balanced_trades(n=200, seed=4)
    out = detect_pumpdump(t)
    assert out.empty   # flat/balanced market has no spike+reversal


def test_d3_detects_constructed_pump():
    """Positive test: build a volume-spike + price-pump-and-reversal and
    verify D3 fires on it. Uses 48h baseline + 1h pump so the trailing window
    has enough baseline points for the spike's z-score to exceed threshold
    (at small N the rolling window mean+std both grow with the spike so z is
    bounded, we use trailing='24h' = 24 buckets to dilute the spike's effect
    on its own baseline).
    """
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    rng = np.random.default_rng(11)
    rows = []
    # 48 hours of low-volume baseline (3 buys/hour at ~0.01)
    for h in range(48):
        for _ in range(3):
            t = start + pd.Timedelta(hours=h, minutes=int(rng.uniform(0, 60)))
            rows.append({"timestamp": t, "price": 0.04, "size": 0.01, "side": "buy"})

    # Hour 48: explicit pump, many large trades pushing price up 3%
    pump_t0 = start + pd.Timedelta(hours=48)
    for k in range(15):
        rows.append({
            "timestamp": pump_t0 + pd.Timedelta(minutes=k * 2),
            "price":     0.04 * (1 + 0.002 * k),   # rises 0.2% per step
            "size":      5.0,                       # 500x baseline volume
            "side":      "buy",
        })
    # Reversal in the second half of the same hour
    for k in range(15):
        rows.append({
            "timestamp": pump_t0 + pd.Timedelta(minutes=30 + k * 2),
            "price":     0.04 * 1.03 * (1 - 0.003 * k),
            "size":      5.0,
            "side":      "sell",
        })

    trades = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    out = detect_pumpdump(
        trades, vol_z=2.0, min_move=0.005, reversal_frac=0.5,
        trailing="24h", min_periods=4,
    )
    assert not out.empty, "D3 should flag a constructed pump-and-dump pattern"
    assert (out["direction"] == "pump").any()


# ---------------------------------------------------------------------------
# D4 liquidity
# ---------------------------------------------------------------------------
def test_d4_empty_trades():
    ob = _fake_orderbooks(n=10)
    out = detect_liquidity_quality(pd.DataFrame(columns=["timestamp","price","size","side"]), ob)
    assert out["summary"]["n_trades_outside_spread"] == 0


def test_d4_normal_spread_distribution():
    ob = _fake_orderbooks(n=20, seed=5)
    t = _balanced_trades(n=100, seed=5)
    out = detect_liquidity_quality(t, ob)
    s = out["summary"]
    assert s["median_spread_bps"] > 0
    # Fixture: ask=0.0405, bid=0.0395 → spread ≈ 0.001/0.04 ≈ 250 bps
    assert 200 < s["median_spread_bps"] < 300


# ---------------------------------------------------------------------------
# D5 bursts / TOD / anchors
# ---------------------------------------------------------------------------
def test_d5_bursts_empty():
    out = detect_bursts(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert out.empty


def test_d5_burst_detection():
    # 7 trades in same second
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    t = pd.DataFrame({
        "timestamp": [start + pd.Timedelta(seconds=10)] * 7
                   + [start + pd.Timedelta(seconds=100)],
        "price":     [0.04] * 8,
        "size":      [1.0]  * 8,
        "side":      ["buy"] * 8,
    })
    out = detect_bursts(t, min_trades_per_second=5)
    assert len(out) == 1
    assert out.iloc[0]["n_trades"] == 7


def test_d5_tod_empty():
    out = detect_time_of_day(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert out.empty


def test_d5_tod_24_hours_when_data_spans_full_day():
    start = pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
    n = 100
    rng = np.random.default_rng(0)
    t = pd.DataFrame({
        "timestamp": start + pd.to_timedelta(rng.uniform(0, 24*3600, size=n), unit="s"),
        "price":     [0.04]*n,
        "size":      [1.0]*n,
        "side":      rng.choice(["buy","sell"], size=n).tolist(),
    })
    out = detect_time_of_day(t)
    # Expect approximately 24 hour buckets (some hours may have 0 trades)
    assert out["hour_utc"].between(0, 23).all()


def test_d5_anchors_empty():
    out = detect_anchor_prices(pd.DataFrame(columns=["timestamp","price","size","side"]))
    assert out.empty


def test_d5_anchors_finds_top_recurring():
    n = 100
    rng = np.random.default_rng(7)
    prices = list(rng.uniform(0.04, 0.041, size=n-10)) + [0.040000]*10
    t = pd.DataFrame({
        "timestamp": pd.Timestamp("2025-09-01 00:00:00", tz="UTC")
                     + pd.to_timedelta(range(n), unit="s"),
        "price":     prices,
        "size":      [1.0]*n,
        "side":      ["buy"]*n,
    })
    out = detect_anchor_prices(t, top_n=5)
    assert out.iloc[0]["price"] == 0.040000
    assert out.iloc[0]["count"] == 10
