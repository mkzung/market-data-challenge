# ETH/BTC Suspicious Pattern Analysis

> 👋 **Hi — I'm Max Gorbuk**, applying for the **Inca Digital R&D Data Engineering Intern** role (Summer 2026). This repo is my submission to **DN Institute [Market Data Challenge — Issue #492](https://github.com/1712n/dn-institute/issues/492)**. The submission also lives upstream as **[PR 1712n/market-data-challenge#24](https://github.com/1712n/market-data-challenge/pull/24)**; this standalone repo is the canonical, browseable mirror.
>
> **Where to look first (≈ 5 min):**
> 1. 🚀 **[Live dashboard](https://mkzung.github.io/ethbtc-suspicious-patterns/dashboard.html)** — click to open in your browser (GitHub Pages, no clone needed).
> 2. The TL;DR table below — five primary signals + three peer-corroborated cross-checks.
> 3. **[REPORT.md](./REPORT.md)** — full methodology, evidence, limitations (~8 min read).
> 4. **`make all`** from a fresh clone — pytest 46/46 + analyze + audit + dashboard.
>
> **Reach me:** [gorbuk@stanford.edu](mailto:gorbuk@stanford.edu) · +1 (208) 553-3054 · [linkedin.com/in/gorbuk](https://linkedin.com/in/gorbuk) · [github.com/mkzung](https://github.com/mkzung)
>
> Six-detector forensic framework over the ETH/BTC dataset (845 trades, 188 orderbook snapshots, 2025-09-01 → 2025-09-03 UTC).

![Python](https://img.shields.io/badge/python-3.10+-3776ab?logo=python&logoColor=white)
![pytest](https://img.shields.io/badge/pytest-46%2F46_pass-3fb950)
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
| 6a | Frozen-orderbook asymmetry | bid frozen **63.6%** vs ask **7.0%** of consecutive snapshots (**9.15× asymmetry**); longest run 18 snapshots ≈ 6h |
| 6b | Benford rejection on trade sizes | K-S **0.0626** > critical 0.0468 (n=845, α=0.05) → reject Benford-conformity |
| 6c | Cron-style buy interval (Sep-3 14:00+) | n=95 buys, median **318 s**, IQR 295.25–341 s (CV = 0.69) |

Signals 1–5 are the primary forensic case. Signals 6a–6c are independent
cross-checks added after peer review of prior submissions; all three reproduce
on this dataset and corroborate the wash-trading interpretation.

**Forensic interpretation:** two automated operators on the venue — a 24/7 buyer running wash flow against pre-arranged liquidity, and a US-trading-hours seller running real algorithmic execution. Full methodology, evidence, and limitations: **[REPORT.md](./REPORT.md)** (≈8 min read) or **[dashboard.html](./dashboard.html)** (visual, open in browser).

---

## Quick start

```bash
make all          # install + pytest + analyze + audit + open dashboard
```

Or step-by-step:

```bash
pip install -r requirements.txt
python -m pytest tests/ -v       # 46 unit tests
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
├── src/                       ← 5 primary + 1 cross-check detector module + loader + plotting
├── tests/                     ← 46-test pytest suite
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
| Unit tests | `make pytest` | 46-test pytest suite: loaders, all 6 detectors, edge cases, end-to-end repro |
| Calibration study | `make calibrate` | detectors on synthetic clean ETH/BTC data → zero false positives |
| Continuous integration | `.github/workflows/test.yml` | full pipeline on Python 3.10 / 3.11 / 3.12 on every push |

---

## Author

**Max Gorbuk** · [gorbuk@stanford.edu](mailto:gorbuk@stanford.edu) · [github.com/mkzung](https://github.com/mkzung)

Researcher at the Stanford GSB Venture Capital Initiative under Prof. Ilya Strebulaev. Incoming MSc, INTENT — Bocconi University, Milan.
