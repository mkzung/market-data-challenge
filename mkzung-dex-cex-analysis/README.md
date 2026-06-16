# DEX-CEX Market Analysis

My submission for DN Institute / Inca Challenge **#493** ([issue](https://github.com/1712n/dn-institute/issues/493)).
Two parts: a hedging memo, and an hourly USDC peg-deviation study across a DEX and a CEX.

## Task 1. Hedging a Uniswap LP with a CEX perpetual

Full write-up in [`memo/task1_hedged_lp.md`](memo/task1_hedged_lp.md). Short version:

A 50/50 Uniswap V2 ETH/USDT LP has, at entry, an ETH delta equal to the ETH it holds, `n = (V/2)/P`.
So you make it locally delta-neutral by shorting `n` ETH on a CEX perpetual. The hedge is only a tangent:
the LP is short gamma (impermanent loss) while the short is linear, so you re-hedge as price moves. Beyond
delta you also carry LP fees earned, IL, perp funding, rebalancing cost, gas, CEX fees/margin, and basis
risk. In Uniswap V3 with a +/-10% range the entry logic is the same (short the ETH the position holds), but
concentration amplifies both fees and gamma, the correct hedge sweeps from the whole position at the low
edge to zero at the high edge, and the position stops earning and goes 100% one-asset once price leaves the
range, which the hedge has to handle explicitly. (Full derivation in the memo.)

## Task 2. USDC peg deviation, DEX vs CEX, hourly

For every UTC hour over **2025-07-01 to 2025-09-30**, how much USDC traded **outside the +/-0.1% band**
around 1.0000 USDT, on each venue, and the executed-price extremes in those hours.

- **DEX:** Uniswap v3 USDC/USDT 0.01% pool `0x3416cf6c708da44db2624d63ea0aaef7113527c6` (Ethereum mainnet).
- **CEX:** Bybit USDC/USDT spot.

Deliverable: [`results/dex_cex_peg_deviation.csv`](results/dex_cex_peg_deviation.csv), one row per hour,
columns `time, uniswap_volume, bybit_volume, uniswap_min_price, uniswap_max_price, bybit_min_price,
bybit_max_price`. Full working in [`notebook/dex_cex_analysis.ipynb`](notebook/dex_cex_analysis.ipynb).
A self-contained visual dashboard is in [`index.html`](index.html); open it locally, or via GitHub Pages
once enabled at `https://mkzung.github.io/dex-cex-market-analysis/`.

### Key findings

- The Bybit order book left the band in **6 hours**, always on the discount side (USDC down to ~0.99 on
  2025-07-02), about **$7.6M** of outside-band volume. Real, modest, market-wide peg stress.
- The Uniswap 1bp pool holds the peg much tighter. About 99% of its ~**$309M** of outside-band volume is
  within 1% of peg (83% within 0.2%, prices 0.998 to 0.999), ordinary AMM impact one tick past the edge,
  not a peg move.
- Only ~1.3% of the DEX outside-band volume deviates more than 1%, and it is sandwich MEV, verified
  on-chain. In block 22963581 one address (`0xba6d84cc`) sells $6.7M USDC to push the pool to ~0.80, a
  victim sells $142k through the Uniswap router and is filled at 0.7995, then the same address buys $6.5M
  back to ~1.00, across three consecutive transactions. Not USDC peg moves.
- Both venues printed outside-band volume in only **3 hours**, all USDC discount; the clearest is
  **2025-09-23 02:00 UTC**.

The point for an investigator: "executed price outside the band" overstates DEX peg stress until you strip
out AMM impact and MEV. The CEX tape is the cleaner peg gauge; the DEX needs size and within-block context
applied first.

## Data sources

Both free, no API key, no paid provider.

- Uniswap `Swap` logs via public Ethereum JSON-RPC (`ethereum.publicnode.com`, `eth.drpc.org`), pulled with
  `eth_getLogs` and decoded by hand (`src/ethlib.py`).
- Bybit public spot trade dumps: `https://public.bybit.com/spot/USDCUSDT/USDCUSDT_<YYYY-MM-DD>.csv.gz`.

## Conventions

- **Executed price** per swap/trade. Uniswap: `|amount1|/|amount0|` (both tokens 6 decimals, so the ratio
  is USDT per USDC). Bybit: the trade price.
- **USDC volume.** Uniswap: `|amount0|/1e6`. Bybit: the `volume` (base) column.
- **Outside the band:** `abs(price - 1) > 0.001`, with a `1e-9` tolerance so a trade exactly on the edge
  (0.9990 / 1.0010) is treated as in-band rather than leaking out through float rounding.
- **Dust floor:** a trade must be >= 1 USDC to count. Sub-dollar Uniswap swaps give meaningless price ratios
  from integer rounding; the floor removes that on both venues and moves total volume by under a cent.

## Layout

```
memo/task1_hedged_lp.md          Task 1 write-up
src/config.py                    pool, tokens, window, band, dust floor
src/ethlib.py                    JSON-RPC, adaptive eth_getLogs, Swap decode (no web3)
src/fetch_uniswap.py             pull every swap -> data/raw/ (resumable)
src/aggregate_uniswap.py         outside-band + hourly from the cached raw
src/fetch_bybit.py               Bybit spot dumps -> hourly
src/build_table.py               merge -> results/dex_cex_peg_deviation.csv
notebook/dex_cex_analysis.ipynb  calculations, plots, MEV spot-check, findings
tests/test_logic.py              decode / band / price / hour-bucket unit tests
results/dex_cex_peg_deviation.csv  the deliverable
index.html, dashboard.html       self-contained dashboard (embedded data + figures, GitHub Pages)
dashboard/build_dashboard.py     regenerate the dashboard from the CSVs
```

## Run

```bash
pip install -r requirements.txt
python src/fetch_bybit.py        # ~1 min
python src/fetch_uniswap.py      # ~15 min, resumable; writes the raw audit trail then aggregates
python src/build_table.py
pytest -q
```

The block window is pinned in `src/config.py` and re-verified at runtime, so the pull is deterministic.
`fetch_uniswap.py` resumes from the last cached block if interrupted.
