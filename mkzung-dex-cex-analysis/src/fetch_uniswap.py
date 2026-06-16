"""Pull every Swap from the Uniswap v3 USDC/USDT 0.01% pool over the window and
cache one row per swap. Aggregation to outside-band / hourly lives in aggregate_uniswap.py.

Executed price (USDT per USDC) = |amount1| / |amount0|  (both tokens have 6 decimals).
USDC volume of a swap = |amount0| / 1e6.

Resumable: if data/raw/uniswap_swaps.csv already exists, drops the (possibly partial)
last block and continues from there, so an interrupted pull can be finished cheaply.

Output:
  data/raw/uniswap_swaps.csv   block, exec_price, usdc_vol   (full audit trail, gitignored)
then calls aggregate_uniswap.aggregate() to produce:
  data/uniswap_outside_band_swaps.csv
  data/uniswap_hourly.csv
"""
import os, sys, csv, time
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
from config import (POOL, SWAP_TOPIC, DEC0, DEC1, BLOCK_START, BLOCK_END,
                    START_TS, END_TS, is_outside)
import ethlib
from aggregate_uniswap import aggregate

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
RAW = os.path.join(DATA, "raw")
os.makedirs(RAW, exist_ok=True)
RAW_PATH = os.path.join(RAW, "uniswap_swaps.csv")


def _resume_point():
    """Return (start_block, write_mode). Drops the last (maybe-partial) block on resume."""
    if os.path.exists(RAW_PATH) and os.path.getsize(RAW_PATH) > 0:
        df = pd.read_csv(RAW_PATH)
        if len(df):
            maxb = int(df["block"].max())
            df[df["block"] < maxb].to_csv(RAW_PATH, index=False)   # truncate partial tail block
            print(f"resuming: raw covers up to block {maxb}; re-pulling from {maxb}", flush=True)
            return maxb, "a"
    return BLOCK_START, "w"


def main():
    assert ethlib.block_ts(BLOCK_START) >= START_TS > ethlib.block_ts(BLOCK_START - 1), "start block drift"
    assert ethlib.block_ts(BLOCK_END) >= END_TS > ethlib.block_ts(BLOCK_END - 1), "end block drift"
    to_block = BLOCK_END - 1

    start_block, mode = _resume_point()
    if start_block > to_block:
        print("raw already covers full range; skipping pull", flush=True)
    else:
        print(f"pulling swaps blocks {start_block}..{to_block} ({to_block-start_block+1} blocks)", flush=True)
        n_swaps = 0
        n_outside = 0
        t0 = time.time()
        last_log = [t0]
        with open(RAW_PATH, mode, newline="") as rawf:
            rw = csv.writer(rawf)
            if mode == "w":
                rw.writerow(["block", "exec_price", "usdc_vol"])

            def progress(s, e, n):
                now = time.time()
                if now - last_log[0] > 15:
                    pct = 100 * (e - start_block) / max(1, to_block - start_block)
                    print(f"  block {e} ({pct:4.1f}%)  swaps={n_swaps}  outside={n_outside}  {now-t0:5.0f}s", flush=True)
                    last_log[0] = now

            for lg in ethlib.get_logs_adaptive(POOL, SWAP_TOPIC, start_block, to_block, on_chunk=progress):
                a0, a1, _ = ethlib.decode_swap(lg)
                if a0 == 0:
                    continue
                usdc_vol = abs(a0) / 10**DEC0
                exec_price = abs(a1 / a0) * 10**(DEC0 - DEC1)
                n_swaps += 1
                if is_outside(exec_price):
                    n_outside += 1
                rw.writerow([int(lg["blockNumber"], 16), f"{exec_price:.8f}", f"{usdc_vol:.6f}"])
                rawf.flush()
        print(f"done pull: +{n_swaps:,} swaps this run, {n_outside} outside-band, {time.time()-t0:.0f}s", flush=True)

    aggregate()
    print("UNISWAP FETCH DONE", flush=True)


if __name__ == "__main__":
    main()
