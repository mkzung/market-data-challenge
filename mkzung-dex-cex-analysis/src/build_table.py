"""Merge the per-venue hourly aggregates into the deliverable CSV.

One row per UTC hour across the full window (2025-07-01 .. 2025-09-30).
Columns: time, uniswap_volume, bybit_volume,
         uniswap_min_price, uniswap_max_price, bybit_min_price, bybit_max_price

Convention:
  *_volume     = total USDC volume traded OUTSIDE the +/-0.1% band that hour (0 if none).
  *_min/max_price = min/max executed price among that venue's outside-band trades
                    (>= 1 USDC, to keep dust/rounding out of the extremes); blank if none.
"""
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from config import START_TS, END_TS

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")
os.makedirs(RESULTS, exist_ok=True)


def full_grid():
    rows = []
    t = START_TS
    while t < END_TS:
        rows.append(dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%dT%H:00:00Z"))
        t += 3600
    return pd.DataFrame({"time": rows})


def main():
    grid = full_grid()
    uni = pd.read_csv(os.path.join(DATA, "uniswap_hourly.csv"))
    byb = pd.read_csv(os.path.join(DATA, "bybit_hourly.csv"))

    out = grid.merge(uni, on="time", how="left").merge(byb, on="time", how="left")
    out["uniswap_volume"] = out["uniswap_volume"].fillna(0.0)
    out["bybit_volume"] = out["bybit_volume"].fillna(0.0)

    out = out[["time", "uniswap_volume", "bybit_volume",
               "uniswap_min_price", "uniswap_max_price",
               "bybit_min_price", "bybit_max_price"]]
    # round for a clean, readable CSV
    for c in ["uniswap_volume", "bybit_volume"]:
        out[c] = out[c].round(6)
    for c in ["uniswap_min_price", "uniswap_max_price", "bybit_min_price", "bybit_max_price"]:
        out[c] = out[c].round(6)

    path = os.path.join(RESULTS, "dex_cex_peg_deviation.csv")
    out.to_csv(path, index=False)

    both = ((out["uniswap_volume"] > 0) & (out["bybit_volume"] > 0)).sum()
    print(f"rows (hours): {len(out)}")
    print(f"  uniswap outside-band hours: {(out['uniswap_volume']>0).sum()}")
    print(f"  bybit   outside-band hours: {(out['bybit_volume']>0).sum()}")
    print(f"  BOTH venues outside-band:   {both}")
    print(f"  total uniswap outside USDC: {out['uniswap_volume'].sum():,.0f}")
    print(f"  total bybit   outside USDC: {out['bybit_volume'].sum():,.0f}")
    print(f"wrote {path}")
    print("BUILD TABLE DONE")


if __name__ == "__main__":
    main()
