"""Unit tests for src/data.py loaders."""
from __future__ import annotations

import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data import load_trades, load_orderbooks, _coerce_timestamp, _parse_levels


# ---------------------------------------------------------------------------
# load_trades
# ---------------------------------------------------------------------------
def _write_csv(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(content).lstrip())
    return p


def test_load_trades_basic(tmp_path):
    p = _write_csv(tmp_path, "t.csv", """
        timestamp,price,size,side
        2025-09-01 00:00:00+00:00,0.04,1.0,BUY
        2025-09-01 00:00:01+00:00,0.041,2.5,SELL
    """)
    df = load_trades(p)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "price", "size", "side"]
    assert df["side"].tolist() == ["buy", "sell"]
    assert df["timestamp"].dt.tz is not None  # tz-aware


def test_load_trades_drops_nan_and_negative(tmp_path):
    p = _write_csv(tmp_path, "t.csv", """
        timestamp,price,size,side
        2025-09-01 00:00:00+00:00,0.04,1.0,BUY
        2025-09-01 00:00:01+00:00,,1.0,BUY
        2025-09-01 00:00:02+00:00,0.04,,BUY
        2025-09-01 00:00:03+00:00,0.04,-1.0,BUY
        2025-09-01 00:00:04+00:00,-0.04,1.0,BUY
        2025-09-01 00:00:05+00:00,0.04,1.0,bid
    """)
    df = load_trades(p)
    assert len(df) == 1


def test_load_trades_missing_columns_raises(tmp_path):
    p = _write_csv(tmp_path, "t.csv", """
        timestamp,price,quantity,direction
        2025-09-01 00:00:00+00:00,0.04,1.0,BUY
    """)
    with pytest.raises(ValueError, match="missing columns"):
        load_trades(p)


def test_load_trades_empty_csv(tmp_path):
    p = _write_csv(tmp_path, "t.csv", "timestamp,price,size,side\n")
    df = load_trades(p)
    assert df.empty
    assert list(df.columns) == ["timestamp", "price", "size", "side"]


def test_load_trades_normalizes_side_case(tmp_path):
    p = _write_csv(tmp_path, "t.csv", """
        timestamp,price,size,side
        2025-09-01 00:00:00+00:00,0.04,1.0,Buy
        2025-09-01 00:00:01+00:00,0.04,1.0,SELL
        2025-09-01 00:00:02+00:00,0.04,1.0,buy
    """)
    df = load_trades(p)
    assert df["side"].tolist() == ["buy", "sell", "buy"]


def test_load_trades_sorts_by_timestamp(tmp_path):
    p = _write_csv(tmp_path, "t.csv", """
        timestamp,price,size,side
        2025-09-01 00:00:02+00:00,0.04,1.0,BUY
        2025-09-01 00:00:00+00:00,0.04,1.0,BUY
        2025-09-01 00:00:01+00:00,0.04,1.0,BUY
    """)
    df = load_trades(p)
    assert df["timestamp"].is_monotonic_increasing


# ---------------------------------------------------------------------------
# load_orderbooks
# ---------------------------------------------------------------------------
def test_load_orderbooks_basic(tmp_path):
    asks = [{"price": 0.041, "size": 1.0}, {"price": 0.042, "size": 2.0}]
    bids = [{"price": 0.039, "size": 1.5}, {"price": 0.038, "size": 0.5}]
    p = _write_csv(tmp_path, "ob.csv", f"""
        timestamp,asks,bids
        2025-09-01 00:00:00+00:00,"{asks}","{bids}"
    """)
    ob = load_orderbooks(p)
    assert len(ob) == 1
    assert ob.iloc[0]["bid_price"] == 0.039
    assert ob.iloc[0]["ask_price"] == 0.041
    assert ob.iloc[0]["mid"] == pytest.approx(0.040, abs=1e-6)
    assert ob.iloc[0]["spread_bps"] == pytest.approx((0.002 / 0.040) * 1e4, rel=0.01)


def test_load_orderbooks_drops_crossed_books(tmp_path):
    crossed_asks = [{"price": 0.039, "size": 1.0}]   # ask < bid
    crossed_bids = [{"price": 0.041, "size": 1.0}]
    normal_asks = [{"price": 0.041, "size": 1.0}]
    normal_bids = [{"price": 0.039, "size": 1.0}]
    p = _write_csv(tmp_path, "ob.csv", f"""
        timestamp,asks,bids
        2025-09-01 00:00:00+00:00,"{crossed_asks}","{crossed_bids}"
        2025-09-01 00:01:00+00:00,"{normal_asks}","{normal_bids}"
    """)
    ob = load_orderbooks(p)
    assert len(ob) == 1   # crossed dropped
    assert ob.iloc[0]["bid_price"] == 0.039


def test_load_orderbooks_attaches_depth(tmp_path):
    asks = [{"price": 0.041, "size": 1.0}, {"price": 0.042, "size": 2.0}]
    bids = [{"price": 0.039, "size": 1.5}, {"price": 0.038, "size": 0.5}]
    p = _write_csv(tmp_path, "ob.csv", f"""
        timestamp,asks,bids
        2025-09-01 00:00:00+00:00,"{asks}","{bids}"
    """)
    ob = load_orderbooks(p)
    depth = ob.attrs["depth"]
    assert {"timestamp", "side", "level", "price", "size"} <= set(depth.columns)
    assert len(depth) == 4   # 2 asks + 2 bids


def test_load_orderbooks_missing_columns_raises(tmp_path):
    p = _write_csv(tmp_path, "ob.csv", """
        timestamp,bid_levels,ask_levels
        2025-09-01 00:00:00+00:00,[],[]
    """)
    with pytest.raises(ValueError, match="missing columns"):
        load_orderbooks(p)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def test_parse_levels_handles_python_literal():
    result = _parse_levels("[{'price': 0.04, 'size': 1.0}]")
    assert result == [{"price": 0.04, "size": 1.0}]


def test_parse_levels_handles_nan_and_invalid():
    assert _parse_levels(np.nan) == []
    assert _parse_levels("not valid python") == []


def test_coerce_timestamp_iso():
    s = pd.Series(["2025-09-01 00:00:00+00:00"])
    out = _coerce_timestamp(s)
    assert out.iloc[0].tz is not None


def test_coerce_timestamp_unix_seconds():
    s = pd.Series([1_700_000_000])
    out = _coerce_timestamp(s)
    assert 2023 <= out.iloc[0].year <= 2025


def test_coerce_timestamp_unix_ms():
    s = pd.Series([1_700_000_000_000])
    out = _coerce_timestamp(s)
    assert 2023 <= out.iloc[0].year <= 2025
