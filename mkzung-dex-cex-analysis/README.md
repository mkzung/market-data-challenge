# DEX vs CEX: USDC Peg Deviation Analysis

> 👋 **Hi, I'm Max Gorbuk**, applying for the **Inca Digital Investigations Analyst** role (Europe). This repo is a worked example of what the role does day-to-day: take raw market data from a decentralised and a centralised venue, measure how a stablecoin holds its peg hour by hour, and separate real market stress from AMM price impact and MEV. It is my submission to **DN Institute [Market Data Challenge, Issue #493](https://github.com/1712n/dn-institute/issues/493)** (upstream: **[PR 1712n/market-data-challenge#27](https://github.com/1712n/market-data-challenge/pull/27)**); this standalone repo is the canonical, browseable mirror.
>
> **Where to look first (≈ 5 min):**
> 1. 🚀 **[Live dashboard](https://mkzung.github.io/dex-cex-market-analysis/)**, open in your browser, no clone needed (GitHub Pages).
> 2. **[results/dex_cex_peg_deviation.csv](./results/dex_cex_peg_deviation.csv)**, the deliverable: one row per UTC hour.
> 3. **[notebook/dex_cex_analysis.ipynb](./notebook/dex_cex_analysis.ipynb)**, calculations, data sources, the on-chain sandwich exhibit.
> 4. **[memo/task1_hedged_lp.md](./memo/task1_hedged_lp.md)**, Task 1, the LP hedging memo.
>
> **Reach me:** [gorbuk.maxim@gmail.com](mailto:gorbuk.maxim@gmail.com) · +1 (208) 553-3054 · [linkedin.com/in/gorbuk](https://linkedin.com/in/gorbuk) · [github.com/mkzung](https://github.com/mkzung)
>
> 151,246 Uniswap swaps and 5.29M Bybit trades, 2025-07-01 to 2025-09-30 UTC.

![Python](https://img.shields.io/badge/python-3.10+-3776ab?logo=python&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-5%2F5_pass-3fb950)
![reproducible](https://img.shields.io/badge/reproducibility-deterministic_pull-3fb950)
![data](https://img.shields.io/badge/data-free_%2F_key--less-3fb950)
[![tests](https://github.com/mkzung/dex-cex-market-analysis/actions/workflows/test.yml/badge.svg)](https://github.com/mkzung/dex-cex-market-analysis/actions/workflows/test.yml)

---

## TL;DR

| venue | outside-band hours | outside-band USDC | reading |
|---|---|---|---|
| **Bybit (CEX)** | 6 | ~$7.6M | genuine USDC discount, down to 0.99 on 2025-07-02 |
| **Uniswap v3 1bp (DEX)** | 64 | ~$309M | about 99% within 1% of peg: large-swap AMM impact, not a peg move |

The DEX's tail beyond 1% is **sandwich MEV, verified on-chain**: in block 22963581 one address (`0xba6d84cc`) sells $6.7M USDC to push the pool to ~0.80, a victim sells $142k through the Uniswap router and is filled at 0.7995, then the same address buys $6.5M back to ~1.00, across three consecutive transactions ([frontrun](https://etherscan.io/tx/0xb09011d5ee2712caed69d63e067baf37b3c17bebc115c315ce9f7d45471e71d2), [victim](https://etherscan.io/tx/0x3a06e9c03d132c7706f8dd285af0e7d9a684769e87c5ed98b996510a9fa6e418), [backrun](https://etherscan.io/tx/0x49bb5a1b0750121bdae9ac5970d0aa7bc29292d912a22afaac61c96e967cba84)). Both venues deviated in the same hour only **3 times**.

**Takeaway for an investigator:** raw "executed price outside the band" overstates DEX peg stress until you strip out AMM impact and MEV. The CEX trade tape is the cleaner peg gauge; the DEX needs trade size and within-block context applied first.

---

## Task 1. Hedging a Uniswap LP with a CEX perpetual

Full write-up in [`memo/task1_hedged_lp.md`](memo/task1_hedged_lp.md). Short version: a 50/50 Uniswap V2
ETH/USDT LP has, at entry, an ETH delta equal to the ETH it holds, `n = (V/2)/P`, so you make it locally
delta-neutral by shorting `n` ETH on a CEX perpetual. The hedge is only a tangent (the LP is short gamma /
impermanent loss while the short is linear), so you re-hedge as price moves. Beyond delta you carry LP fees,
IL, perp funding, rebalancing cost, gas, CEX margin, and basis risk. In a Uniswap V3 `+/-10%` range the entry
logic is the same, but concentration amplifies both fees and gamma, the hedge sweeps from the whole position
at the low edge to zero at the high edge, and the position goes 100% one-asset once price leaves the range.

## Task 2. USDC peg deviation, DEX vs CEX, hourly

For every UTC hour over **2025-07-01 to 2025-09-30**, the USDC volume traded **outside the +/-0.1% band**
around 1.0000 USDT on each venue, plus the executed-price extremes in those hours.

- **DEX:** Uniswap v3 USDC/USDT 0.01% pool `0x3416cf6c708da44db2624d63ea0aaef7113527c6` (Ethereum mainnet).
- **CEX:** Bybit USDC/USDT spot.

Deliverable: [`results/dex_cex_peg_deviation.csv`](results/dex_cex_peg_deviation.csv), one row per hour,
columns `time, uniswap_volume, bybit_volume, uniswap_min_price, uniswap_max_price, bybit_min_price,
bybit_max_price`. Working in [`notebook/dex_cex_analysis.ipynb`](notebook/dex_cex_analysis.ipynb), visual
dashboard in [`index.html`](index.html) (live on GitHub Pages, link above).

## Data sources

Both free, no API key, no paid provider.

- Uniswap `Swap` logs via public Ethereum JSON-RPC (`ethereum.publicnode.com`, `eth.drpc.org`), pulled with
  `eth_getLogs` and decoded by hand (`src/ethlib.py`).
- Bybit public spot trade dumps: `https://public.bybit.com/spot/USDCUSDT/USDCUSDT_<YYYY-MM-DD>.csv.gz`.

## Conventions

- **Executed price** per swap or trade. Uniswap: `|amount1|/|amount0|` (both tokens 6 decimals, so the ratio
  is USDT per USDC). Bybit: the trade price.
- **USDC volume.** Uniswap: `|amount0|/1e6`. Bybit: the `volume` (base) column.
- **Outside the band:** `abs(price - 1) > 0.001`, with a `1e-9` tolerance so a trade exactly on the edge
  (0.9990 / 1.0010) is treated as in-band rather than leaking out through float rounding.
- **Dust floor:** a trade must be >= 1 USDC to count. Sub-dollar Uniswap swaps give meaningless price ratios
  from integer rounding; the floor removes that on both venues and moves total volume by under a cent.

## Layout

```
memo/task1_hedged_lp.md          Task 1 write-up
src/config.py                    pool, tokens, window, band (single source of truth), dust floor
src/ethlib.py                    JSON-RPC, adaptive eth_getLogs, Swap decode (no web3)
src/fetch_uniswap.py             pull every swap -> data/raw/ (resumable)
src/aggregate_uniswap.py         outside-band + hourly from the cached raw
src/fetch_bybit.py               Bybit spot dumps -> hourly
src/build_table.py               merge -> results/dex_cex_peg_deviation.csv
notebook/dex_cex_analysis.ipynb  calculations, plots, MEV spot-check, findings
dashboard/build_dashboard.py     regenerate index.html / dashboard.html from the CSVs
tests/test_logic.py              decode / band / price / hour-bucket unit tests
results/dex_cex_peg_deviation.csv  the deliverable
index.html, dashboard.html       self-contained dashboard (embedded data + figures, GitHub Pages)
.github/workflows/test.yml       CI: runs the unit tests on every push
LICENSE                          MIT
```

## Run

```bash
pip install -r requirements.txt
python src/fetch_bybit.py        # ~1 min
python src/fetch_uniswap.py      # ~15 min, resumable; writes the raw audit trail then aggregates
python src/build_table.py
pytest -q                        # 5 logic tests
```

The block window is pinned in `src/config.py` and re-verified at runtime, so the pull is deterministic.
`fetch_uniswap.py` resumes from the last cached block if interrupted.
