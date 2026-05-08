"""Data loaders for the ETH/BTC challenge dataset.

Schema (observed in 1712n/market-data-challenge):

    eth-btc-trades.csv:
        timestamp (ISO8601 with tz)  price  size  side ('BUY'|'SELL')

    eth-btc-orderbooks.csv:
        timestamp (ISO8601 with tz)
        asks  -> Python-literal: list of {'price': float, 'size': float}, length up to 50
        bids  -> same shape

The orderbooks file does NOT have flat `bid_price`/`ask_price` columns — it stores
full book depth as a stringified Python list-of-dicts. We parse it with
`ast.literal_eval` (safer than eval) and emit two views:

    top_of_book : flat DataFrame with bid_price/ask_price/bid_size/ask_size
    depth       : long-form DataFrame with one row per (snapshot, side, level)

Canonical schema produced by load_trades / load_orderbooks:
    trades:      timestamp (UTC tz-aware), price, size, side ('buy'|'sell')
    orderbooks: 'top_of_book' DataFrame + 'depth' DataFrame attached as attrs
"""
from __future__ import annotations

import ast
from pathlib import Path
import pandas as pd
import numpy as np


def _coerce_timestamp(s: pd.Series) -> pd.Series:
    """Handle ISO strings and unix variants. Returns tz-aware UTC.

    Normalizes to nanosecond precision so merge_asof across trades/orderbooks
    works on pandas 2.2+ (which can otherwise produce mixed [us] vs [ns]
    precision depending on input format).
    """
    if pd.api.types.is_numeric_dtype(s):
        magnitude = s.dropna().abs().median()
        unit = "us" if magnitude > 1e15 else "ms" if magnitude > 1e12 else "s"
        out = pd.to_datetime(s, unit=unit, utc=True)
    else:
        out = pd.to_datetime(s, utc=True, errors="coerce")
    # Force ns precision for cross-DataFrame merge compatibility
    return out.astype("datetime64[ns, UTC]")


def load_trades(path: str | Path) -> pd.DataFrame:
    raw = pd.read_csv(path)
    needed = {"timestamp", "price", "size", "side"}
    if not needed.issubset(raw.columns):
        raise ValueError(
            f"Trades CSV missing columns. Need {needed}; got {list(raw.columns)}"
        )
    df = pd.DataFrame({
        "timestamp": _coerce_timestamp(raw["timestamp"]),
        "price":     pd.to_numeric(raw["price"], errors="coerce"),
        "size":      pd.to_numeric(raw["size"], errors="coerce"),
        "side":      raw["side"].astype(str).str.strip().str.lower(),
    })
    df = df.dropna(subset=["timestamp", "price", "size", "side"])
    df = df[(df["size"] > 0) & (df["price"] > 0)]
    df = df[df["side"].isin(["buy", "sell"])]
    return df.sort_values("timestamp").reset_index(drop=True)


def _parse_levels(cell: str) -> list[dict]:
    """Parse a stringified list-of-dicts: '[{'price': 0.04, 'size': 0.001}, ...]'.
    Tolerates Python-literal syntax (single quotes) which JSON would reject.
    """
    if pd.isna(cell):
        return []
    if isinstance(cell, list):
        return cell
    try:
        parsed = ast.literal_eval(cell)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, SyntaxError):
        return []


def load_orderbooks(path: str | Path) -> pd.DataFrame:
    """Load orderbooks. Returns top-of-book DataFrame; full depth is stashed in attrs.

    Returned columns:
        timestamp     (UTC tz-aware)
        bid_price     (best bid)
        ask_price     (best ask)
        bid_size      (size at best bid)
        ask_size      (size at best ask)
        mid           ((bid+ask)/2)
        spread_bps    ((ask-bid)/mid * 1e4)
        bid_depth_5   (sum of size across top 5 bid levels)
        ask_depth_5   (sum of size across top 5 ask levels)
        n_levels_bid  (book depth count)
        n_levels_ask  (book depth count)

    `df.attrs['depth']` -> long-form DataFrame: timestamp, side, level, price, size.
    """
    raw = pd.read_csv(path)
    needed = {"timestamp", "asks", "bids"}
    if not needed.issubset(raw.columns):
        raise ValueError(
            f"Orderbooks CSV missing columns. Need {needed}; got {list(raw.columns)}"
        )

    asks = raw["asks"].apply(_parse_levels)
    bids = raw["bids"].apply(_parse_levels)

    # Top-of-book: best ask = lowest ask price; best bid = highest bid price.
    # The data appears already sorted (asks ascending, bids descending), but we
    # don't trust the source — sort explicitly.
    def _best_ask(levels):
        if not levels:
            return (np.nan, np.nan)
        s = sorted(levels, key=lambda d: d["price"])
        return (s[0]["price"], s[0]["size"])

    def _best_bid(levels):
        if not levels:
            return (np.nan, np.nan)
        s = sorted(levels, key=lambda d: -d["price"])
        return (s[0]["price"], s[0]["size"])

    def _depth_top_n(levels, n=5, side="ask"):
        if not levels:
            return np.nan
        s = sorted(levels, key=lambda d: d["price"] if side == "ask" else -d["price"])
        return float(np.sum([d["size"] for d in s[:n]]))

    ask_tup = asks.apply(_best_ask)
    bid_tup = bids.apply(_best_bid)

    out = pd.DataFrame({
        "timestamp":    _coerce_timestamp(raw["timestamp"]),
        "ask_price":    ask_tup.map(lambda t: t[0]),
        "ask_size":     ask_tup.map(lambda t: t[1]),
        "bid_price":    bid_tup.map(lambda t: t[0]),
        "bid_size":     bid_tup.map(lambda t: t[1]),
        "ask_depth_5":  asks.apply(lambda L: _depth_top_n(L, 5, "ask")),
        "bid_depth_5":  bids.apply(lambda L: _depth_top_n(L, 5, "bid")),
        "n_levels_ask": asks.apply(len),
        "n_levels_bid": bids.apply(len),
    })
    out = out.dropna(subset=["timestamp", "bid_price", "ask_price"])
    out = out[(out["bid_price"] > 0) & (out["ask_price"] > 0)]
    # Drop crossed/locked books — they're data artifacts.
    out = out[out["ask_price"] >= out["bid_price"]]
    out["mid"] = (out["bid_price"] + out["ask_price"]) / 2
    out["spread_bps"] = (out["ask_price"] - out["bid_price"]) / out["mid"] * 1e4
    out = out.sort_values("timestamp").reset_index(drop=True)

    # Long-form depth view (one row per level), retained on attrs.
    rows = []
    for ts, ask_levels, bid_levels in zip(raw["timestamp"], asks, bids):
        ts_parsed = pd.to_datetime(ts, utc=True, errors="coerce")
        for lv, d in enumerate(sorted(ask_levels, key=lambda x: x["price"])):
            rows.append((ts_parsed, "ask", lv, d["price"], d["size"]))
        for lv, d in enumerate(sorted(bid_levels, key=lambda x: -x["price"])):
            rows.append((ts_parsed, "bid", lv, d["price"], d["size"]))
    depth = pd.DataFrame(rows, columns=["timestamp", "side", "level", "price", "size"])
    out.attrs["depth"] = depth
    return out


def summarize(trades: pd.DataFrame, orderbooks: pd.DataFrame) -> dict:
    """Return a dict of dataset-level facts for the report header."""
    span = trades["timestamp"].max() - trades["timestamp"].min()
    return {
        "n_trades": int(len(trades)),
        "n_orderbooks": int(len(orderbooks)),
        "trades_start": trades["timestamp"].min().isoformat(),
        "trades_end":   trades["timestamp"].max().isoformat(),
        "ob_start":     orderbooks["timestamp"].min().isoformat(),
        "ob_end":       orderbooks["timestamp"].max().isoformat(),
        "span_hours":   round(span.total_seconds() / 3600, 2),
        "buy_pct":      round((trades["side"] == "buy").mean() * 100, 2),
        "median_size":  float(trades["size"].median()),
        "median_price": float(trades["price"].median()),
        "n_unique_sizes": int(trades["size"].round(8).nunique()),
        "median_spread_bps": round(float(orderbooks["spread_bps"].median()), 2),
        "p95_spread_bps":    round(float(orderbooks["spread_bps"].quantile(0.95)), 2),
        "max_spread_bps":    round(float(orderbooks["spread_bps"].max()), 2),
    }
