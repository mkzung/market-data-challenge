# EDA — eth-btc-trades.csv + eth-btc-orderbooks.csv

## Schema

**trades** (845 rows): `timestamp, price, size, side`. ISO8601 timestamps with UTC tz.
**orderbooks** (188 rows): `timestamp, asks, bids` where each cell is a Python-literal
list-of-dicts holding up to 50 price levels per side. Parsed via `ast.literal_eval`.

## Time range

Trades: **2025-09-01 00:02:57 UTC → 2025-09-03 23:51:34 UTC** (71.81 hours).
Orderbooks: 2025-09-01 00:13 → 2025-09-03 20:50 UTC (slightly shorter window).

Implication for detectors: **24h rolling baselines are too long** for a 72h sample.
Switching D1 to an 8h rolling window.

## Side composition — major anomaly

| side | count | pct  | size median  | size max     |
|------|-------|------|--------------|--------------|
| buy  | 720   | 85.2 | **188.14**   | 687.33       |
| sell | 125   | 14.8 | **0.0014**   | 0.191        |

**Five orders of magnitude separating BUY-side and SELL-size distributions.**
Either:
1. Inconsistent unit reporting (BUY in ETH, SELL in some other unit), or
2. Genuinely asymmetric flow (institutional buys vs. retail sells)

Either reading is a strong forensic signal. PR #19 reported "5.76:1 buy/sell ratio"
(count) but did not catch the size bimodality.

## Recurring sizes (PR #19's finding, confirmed + extended)

`size = 0.000261` appears **13 times**. All on SELL side (size class 1e-3).
Other top-frequency sizes: 70.47 (×5), 137.808 (×5), 399.33 (×5), 187.92 (×4).
The high-frequency BUY sizes look like quote-currency-rounded fills.

D2 must be applied **per-side**, not pooled — the two distributions are
unrelated and pooling collapses both signals.

## Price

Price range **0.038800 → 0.041031** = 5.7% over 72h. Stable trading band.
Despite 720 buys vs. 125 sells, price did not gap. This is itself anomalous:
either (a) the venue has deep liquidity that absorbs the imbalance (D4 says no
— median spread is 90 bps, far from "deep"), or (b) the buys aren't real demand
(wash/self-trades), or (c) the side labels are misaligned.

## Spread quality

| stat   | value (bps) |
|--------|-------------|
| min    | 1.83        |
| 25%    | 54.50       |
| median | **89.71**   |
| 75%    | 131.67      |
| 95%    | 141.17      |
| max    | 145.58      |

Brief's 50bps "anomaly" threshold is the median minus a bit — wrong cutoff.
Healthy ETH/BTC venues (Binance, Coinbase, Kraken) typically quote 5–15 bps.
**This venue is 6–10× wider than baseline as the baseline**, suggesting either
a small/illiquid venue or systemic stale quoting. Switching D4 threshold to
dataset-relative (median + 1.5×IQR).

## Depth

Both sides ship 50 levels per snapshot. `bid_depth_5` median ≈ 0.016 ETH,
`ask_depth_5` median ≈ 0.14 ETH (rough first-snapshot read — to be confirmed
across the full sample). Asks are ~9× deeper than bids in the top 5 levels —
another asymmetry consistent with the buy-pressure narrative.

## Detector design implications

| brief assumption                        | reality                                             | action                                           |
|----------------------------------------|-----------------------------------------------------|--------------------------------------------------|
| 24h rolling window for D1 z-score      | sample is 72h                                       | use 4h rolling                                   |
| pool sizes for D2 frequency null       | side-bimodal distributions                          | run D2 per-side                                  |
| permutation test by shuffling array     | shuffles preserve frequency → degenerate null       | use parametric KDE-on-log(size) null             |
| 50 bps spread threshold                | median is 90 bps                                    | dataset-relative threshold (median + 1.5×IQR)    |
| price reversal signature for P&D       | price barely moves (5.7% range)                     | report empty / weak D3, document why             |
| top-of-book only                       | 50 levels available                                 | add depth-imbalance metric to D4                 |
