# ETH/BTC Suspicious Pattern Analysis

> Submission to the [**DN Institute Market Data Challenge**](https://github.com/1712n/market-data-challenge).
> Five-detector forensic framework over the ETH/BTC dataset (845 trades, 188 orderbook snapshots, 2025-09-01 → 2025-09-03 UTC).

![Python](https://img.shields.io/badge/python-3.10+-3776ab?logo=python&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-34%2F34_pass-3fb950)
![calibration](https://img.shields.io/badge/calibration-clean--baseline_passes-3fb950)
![reproducible](https://img.shields.io/badge/reproducibility-byte--identical-3fb950)
![CI](https://img.shields.io/badge/CI-github_actions-2088ff?logo=githubactions&logoColor=white)

---

## TL;DR — five mutually-consistent signals of automated, likely non-organic activity

| # | Signal | Headline number |
|---|---|---|
| 1 | One-sided buy flow with zero price impact | **99.9994%** of size on buy side; buys move price 0 bps median, sells −17.8 bps |
| 2 | Identical-clip burst on both sides of book | size **0.00026058 ETH** × 13 in two ≤2-second bursts 22h apart (P-value ≈ 0) |
| 3 | Sub-second multi-trade clusters | **9 burst-seconds**; max 12 sells in one second on 09-01 16:16:46 |
| 4 | Operator-schedule asymmetry | sells in only **15 of 24 UTC hours** (US-session-bound); buys 24/7 |
| 5 | Liquidity pathology | median spread 89.7 bps; **127 of 845 trades (15%) outside contemporaneous bid-ask** |

**Forensic interpretation:** two automated operators on the venue — a 24/7 buyer running wash flow against pre-arranged liquidity, and a US-trading-hours seller running real algorithmic execution. Full methodology, evidence, and limitations: **[REPORT.md](./REPORT.md)** (≈8 min read) or **[dashboard.html](./dashboard.html)** (visual, open in browser).

---

## Quick start

```bash
make all          # install + pytest + analyze + audit + open dashboard
```

Or step-by-step:

```bash
pip install -r requirements.txt
python -m pytest tests/ -v       # 34 unit tests
python analyze.py --trades ../eth-btc-trades.csv \
                  --orderbooks ../eth-btc-orderbooks.csv
python audit.py                  # raw-evidence dump for every claim
python calibration.py            # detectors on synthetic clean baseline
```

`analyze.py` writes `findings.json` and 6 PNG figures to `figures/`. Total runtime ≈ 30 seconds on a laptop.

---

## Repository layout

```
mkzung-ethbtc-analysis/
├── README.md                  ← you are here (entry point)
├── REPORT.md                  ← main deliverable: methodology, findings, limitations
├── dashboard.html             ← interactive single-file dashboard (open in browser)
├── analyze.py                 ← single-command runner → figures + findings.json
├── audit.py                   ← raw-evidence verification of every claim
├── calibration.py             ← synthetic clean-baseline calibration study
├── Makefile                   ← make all / pytest / analyze / audit / calibrate / test
├── requirements.txt
├── src/                       ← 5 detector modules + loader + plotting
├── tests/                     ← 34-test pytest suite
├── notebooks/                 ← EDA notes + interactive Jupyter alternative
├── .github/workflows/         ← CI: pytest + analyze + audit + calibration on every push
├── data/                      ← challenge CSVs + spec
├── figures/                   ← 6 generated PNGs
├── findings.json              ← machine-readable summary
└── audit.txt                  ← raw evidence dump
```

---

## What this submission does beyond the brief

- **D2 null replaced.** A naïve "shuffle the size array, take max value-count" null is degenerate (shuffling preserves frequencies). Replaced with a parametric KDE-on-log(size) null (1000 replicates), cross-validated against a uniform-on-log-range null. Both give P ≈ 0.
- **D1 epsilon fix.** `log((buy + 1e-9)/(sell + 1e-9))` inflates to ~25 in the 119/143 buckets that contain zero sells — pure smoothing artifact. Switched to `+1`.
- **D3 made bidirectional.** Original used `max(price)` only; missed dump-recovery patterns. Now picks whichever extremum is further from the spike start.
- **D4 tolerance audit.** OB inter-snapshot intervals average 22 minutes; the brief's 5-min `merge_asof` tolerance matched only 22.5% of trades and underreported outside-spread by **4×**. Switched to 30-min tolerance (matches 87.8%).
- **Side semantics verified.** BUY median trade price is +21 bps above contemporaneous mid; SELL is −29 bps below; SELL trades push mid down −18 bps post-trade. Aggressor semantics confirmed.
- **Doubling-ladder Monte Carlo.** 4 explicit 2× pairs in the 18 flagged BUY sizes vs MC null (2000 reps) where mean is 0.09 and max is 2 — P(null ≥ 4) = 0.0000.

Patterns tested and **rejected** as non-findings (the framework doesn't cherry-pick): round-number price clustering, quote stuffing (orderbook churn ≈ 3.6 changes per snapshot, far below stuffing thresholds), hidden-liquidity depth gaps.

## Reproducibility & rigour

| Validation | Command | What it checks |
|---|---|---|
| Byte-identical reproducibility | `make test` | re-running `analyze.py` produces identical `findings.json` (seeded RNGs) |
| Unit tests | `make pytest` | 34-test pytest suite: loaders, all 5 detectors, edge cases, end-to-end repro |
| Calibration study | `make calibrate` | detectors on synthetic clean ETH/BTC data → zero false positives |
| Continuous integration | `.github/workflows/test.yml` | full pipeline on Python 3.10 / 3.11 / 3.12 on every push |

---

## Author

**Maksim Gorbuk** · [gorbuk.maxim@gmail.com](mailto:gorbuk.maxim@gmail.com) · [github.com/mkzung](https://github.com/mkzung)

Researcher at the Stanford GSB Venture Capital Initiative under Prof. Ilya Strebulaev. Incoming MSc, INTENT — Bocconi University, Milan.
