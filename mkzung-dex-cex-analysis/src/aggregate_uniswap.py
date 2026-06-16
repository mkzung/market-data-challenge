"""Derive outside-band swaps + hourly aggregate from the cached raw swap CSV.

Split out from the pull so changes to the band logic do not require re-fetching
the full window. Timestamps are resolved only for the (few) outside-band swaps.
"""
import os, sys
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from config import START_TS, END_TS, DUST_USDC, hour_iso, outside_mask
import ethlib

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
RAW = os.path.join(DATA, "raw")


def aggregate():
    raw = pd.read_csv(os.path.join(RAW, "uniswap_swaps.csv"))
    # outside the band AND above the dust floor: sub-1-USDC swaps give meaningless |amt1/amt0|
    # ratios (a 0.000003 USDC swap can report a "price" of 0.33 purely from integer rounding).
    beyond = outside_mask(raw["exec_price"])
    ob = raw[beyond & (raw["usdc_vol"] >= DUST_USDC)].copy()
    print(f"raw swaps {len(raw):,}, beyond-band {int(beyond.sum()):,}, "
          f"beyond-band & >={DUST_USDC} USDC {len(ob):,}", flush=True)

    blocks = sorted(int(b) for b in ob["block"].unique())
    print(f"resolving timestamps for {len(blocks)} unique outside-band blocks...", flush=True)
    ts_map = {b: ethlib.block_ts(b) for b in blocks}
    ob["ts"] = ob["block"].astype(int).map(ts_map)
    ob = ob[(ob["ts"] >= START_TS) & (ob["ts"] < END_TS)].copy()
    ob["time"] = ob["ts"].map(hour_iso)

    ob[["time", "block", "exec_price", "usdc_vol"]].sort_values("time").to_csv(
        os.path.join(DATA, "uniswap_outside_band_swaps.csv"), index=False)

    if len(ob):
        g = ob.groupby("time")
        vol = g["usdc_vol"].sum().rename("uniswap_volume")
        mn = g["exec_price"].min().rename("uniswap_min_price")
        mx = g["exec_price"].max().rename("uniswap_max_price")
        hourly = pd.concat([vol, mn, mx], axis=1).reset_index()
    else:
        hourly = pd.DataFrame(columns=["time", "uniswap_volume", "uniswap_min_price", "uniswap_max_price"])
    hourly.to_csv(os.path.join(DATA, "uniswap_hourly.csv"), index=False)
    print(f"uniswap hourly rows (hours with outside-band vol): {len(hourly)}", flush=True)
    return hourly


if __name__ == "__main__":
    aggregate()
