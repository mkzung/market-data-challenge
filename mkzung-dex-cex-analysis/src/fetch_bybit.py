"""Download Bybit USDC/USDT spot per-trade dumps for each day in the window,
aggregate the OUTSIDE-BAND trades to the hour.

Dump columns: id, timestamp(ms), price(USDT per USDC), volume(USDC base), side, rpi.
USDC volume of a trade = volume. Executed price = price.

Outputs (data/):
  bybit_outside_band_trades.csv   time, ts_ms, price, volume
  bybit_hourly.csv                time, bybit_volume, bybit_min_price, bybit_max_price
  bybit_daily_summary.csv         date, n_trades, total_usdc, n_outside   (sanity)
"""
import os, sys, io, gzip, time, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))

import requests
import pandas as pd
from config import BYBIT_SYMBOL, BYBIT_URL, START_TS, END_TS, DUST_USDC, hour_iso, outside_mask

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA, exist_ok=True)
session = requests.Session()


def days():
    d = dt.datetime.utcfromtimestamp(START_TS).date()
    end = dt.datetime.utcfromtimestamp(END_TS).date()   # exclusive (Oct 1)
    while d < end:
        yield d
        d += dt.timedelta(days=1)


def main():
    outside_rows = []
    daily = []
    grand_trades = 0
    grand_usdc = 0.0
    t0 = time.time()

    for d in days():
        ds = d.strftime("%Y-%m-%d")
        url = BYBIT_URL.format(sym=BYBIT_SYMBOL, date=ds)
        for attempt in range(4):
            try:
                r = session.get(url, timeout=60)
                break
            except Exception:
                time.sleep(1.5 * (attempt + 1))
        else:
            print(f"  {ds}: download failed after retries", flush=True)
            daily.append({"date": ds, "n_trades": 0, "total_usdc": 0.0, "n_outside": 0, "status": "FAIL"})
            continue
        if r.status_code != 200:
            print(f"  {ds}: HTTP {r.status_code}", flush=True)
            daily.append({"date": ds, "n_trades": 0, "total_usdc": 0.0, "n_outside": 0, "status": r.status_code})
            continue

        df = pd.read_csv(io.BytesIO(gzip.decompress(r.content)))
        df["price"] = df["price"].astype(float)
        df["volume"] = df["volume"].astype(float)
        n = len(df)
        tot = float(df["volume"].sum())
        # outside band AND above the dust floor (same convention as the DEX side)
        mask = outside_mask(df["price"]) & (df["volume"] >= DUST_USDC)
        ob = df[mask].copy()
        grand_trades += n
        grand_usdc += tot
        daily.append({"date": ds, "n_trades": n, "total_usdc": tot, "n_outside": int(mask.sum()), "status": 200})

        if len(ob):
            ob["time"] = (ob["timestamp"] // 1000).astype("int64").map(hour_iso)
            for _, t in ob.iterrows():
                outside_rows.append({"time": t["time"], "ts_ms": int(t["timestamp"]),
                                     "price": float(t["price"]), "volume": float(t["volume"])})
        print(f"  {ds}: {n:7d} trades, {tot:14,.0f} USDC, outside={int(mask.sum())}", flush=True)

    pd.DataFrame(daily).to_csv(os.path.join(DATA, "bybit_daily_summary.csv"), index=False)
    ob = pd.DataFrame(outside_rows)
    # keep only trades inside the exact window (dumps are whole-day UTC, already aligned)
    ob.to_csv(os.path.join(DATA, "bybit_outside_band_trades.csv"), index=False)

    if len(ob):
        g = ob.groupby("time")
        vol = g["volume"].sum().rename("bybit_volume")
        mn = g["price"].min().rename("bybit_min_price")
        mx = g["price"].max().rename("bybit_max_price")
        hourly = pd.concat([vol, mn, mx], axis=1).reset_index()
    else:
        hourly = pd.DataFrame(columns=["time", "bybit_volume", "bybit_min_price", "bybit_max_price"])
    hourly.to_csv(os.path.join(DATA, "bybit_hourly.csv"), index=False)

    print(f"done: {grand_trades:,} trades, total USDC vol {grand_usdc:,.0f}, "
          f"{len(ob)} outside-band trades, {len(hourly)} hours with outside-band vol "
          f"in {time.time()-t0:.0f}s", flush=True)
    print("BYBIT FETCH DONE", flush=True)


if __name__ == "__main__":
    main()
