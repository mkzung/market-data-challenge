"""Build a self-contained dashboard (index.html + dashboard.html) for Challenge #493.

Reads the committed CSVs, renders the figures to base64 (so the page is a single file with
no external assets), and writes the dark-theme report to the repo root for GitHub Pages.
"""
import os, sys, io, base64
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = lambda *p: os.path.join(ROOT, *p)

table = pd.read_csv(D("results", "dex_cex_peg_deviation.csv"), parse_dates=["time"])
ubh = pd.read_csv(D("data", "uniswap_hourly.csv"), parse_dates=["time"])
bbh = pd.read_csv(D("data", "bybit_hourly.csv"), parse_dates=["time"])
uob = pd.read_csv(D("data", "uniswap_outside_band_swaps.csv"))
mev = pd.read_csv(D("data", "uniswap_mev_example.csv"))

uni_vol = table.uniswap_volume.sum()
byb_vol = table.bybit_volume.sum()
uni_hours = int((table.uniswap_volume > 0).sum())
byb_hours = int((table.bybit_volume > 0).sum())
both = table[(table.uniswap_volume > 0) & (table.bybit_volume > 0)].copy()
deepest_cex = float(bbh.bybit_min_price.min())
uob["dev"] = (uob.exec_price - 1).abs()
dex_gt1_share = uob[uob.dev > 0.01].usdc_vol.sum() / uob.usdc_vol.sum() * 100


def usd(x):
    if x >= 1e6: return f"${x/1e6:.1f}M"
    if x >= 1e3: return f"${x/1e3:.0f}k"
    return f"${x:,.0f}"


def b64(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


# fig 1: hourly outside-band volume per venue
u = table[table.uniswap_volume > 0]
b = table[table.bybit_volume > 0]
f1, ax = plt.subplots(figsize=(11, 4.0))
ax.scatter(u.time, u.uniswap_volume, s=20, alpha=0.7, color="#2b6cb0", label="Uniswap (DEX)")
ax.scatter(b.time, b.bybit_volume, s=70, alpha=0.9, color="#dd6b20", marker="D", label="Bybit (CEX)")
ax.set_yscale("log"); ax.set_ylabel("outside-band USDC volume (log)")
ax.set_title("Hourly USDC volume traded outside the +/-0.1% band")
ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d")); ax.grid(True, alpha=0.3); ax.legend()
fig1 = b64(f1)

# fig 2: bybit depth below peg
f2, ax = plt.subplots(figsize=(8.5, 3.6))
ax.bar(bbh.time.dt.strftime("%m-%d %Hh"), (1 - bbh.bybit_min_price) * 100, color="#dd6b20")
ax.axhline(0.1, ls="--", color="grey", lw=1, label="0.1% band edge")
ax.set_ylabel("depth below peg (%)"); ax.set_title("Bybit USDC/USDT: how far below 1.0 the outside-band hours reached")
ax.legend(); plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
fig2 = b64(f2)

# fig 3: DEX outside-band volume by deviation bucket
buckets = [(0.001, 0.002, "0.1-0.2%"), (0.002, 0.005, "0.2-0.5%"), (0.005, 0.01, "0.5-1%"), (0.01, 1, ">1% (MEV)")]
vals = [uob[(uob.dev >= lo) & (uob.dev < hi)].usdc_vol.sum() for lo, hi, _ in buckets]
f3, ax = plt.subplots(figsize=(8.5, 3.6))
colors = ["#2b6cb0", "#3182ce", "#63b3ed", "#e53e3e"]
ax.bar([l for _, _, l in buckets], vals, color=colors)
ax.set_yscale("log"); ax.set_ylabel("USDC volume (log)")
ax.set_title("Uniswap outside-band volume by deviation magnitude")
for i, v in enumerate(vals):
    ax.text(i, v, usd(v), ha="center", va="bottom", fontsize=9)
fig3 = b64(f3)

# fig 4: MEV block reconstruction (pool marginal price across the swaps in the sandwich block)
_tb = int(uob.sort_values("exec_price").iloc[0]["block"])
focus = mev[mev.block == _tb].sort_values("tx_index").reset_index(drop=True)
f4, ax = plt.subplots(figsize=(8.5, 3.6))
steps = list(range(len(focus) + 1))
prices = [1.0] + focus.marginal_after.tolist()
ax.step(steps, prices, where="post", color="#2b6cb0", lw=2)
ax.scatter(range(1, len(focus) + 1), focus.marginal_after, s=(focus.usdc_vol / focus.usdc_vol.max() * 350 + 40),
           color="#e53e3e", zorder=5)
for i, r in focus.iterrows():
    ax.annotate(f"{usd(r.usdc_vol)} swap", (i + 1, r.marginal_after),
                textcoords="offset points", xytext=(6, 8), fontsize=8)
ax.axhspan(0.999, 1.001, color="green", alpha=0.08)
ax.set_ylabel("pool marginal price (USDT/USDC)")
ax.set_xlabel("swap sequence within block 22963581")
ax.set_title("Within-block liquidity-void MEV: pool gaps to 0.80 and back in one block")
fig4 = b64(f4)


def table_html(df, cols, headers, fmts):
    h = "".join(f"<th>{x}</th>" for x in headers)
    rows = ""
    for _, r in df.iterrows():
        tds = "".join(f'<td class="num">{fmts[c](r[c])}</td>' for c in cols)
        rows += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{h}</tr></thead><tbody>{rows}</tbody></table>"


def t(x): return pd.to_datetime(x).strftime("%Y-%m-%d %H:00")
def p(x): return "" if pd.isna(x) else f"{x:.4f}"
def v(x): return usd(x)

both_tbl = table_html(both, ["time", "uniswap_volume", "bybit_volume", "uniswap_min_price", "bybit_min_price"],
                      ["hour (UTC)", "Uniswap vol", "Bybit vol", "Uni min px", "Bybit min px"],
                      {"time": t, "uniswap_volume": v, "bybit_volume": v, "uniswap_min_price": p, "bybit_min_price": p})
byb_tbl = table_html(bbh, ["time", "bybit_volume", "bybit_min_price", "bybit_max_price"],
                     ["hour (UTC)", "outside-band vol", "min px", "max px"],
                     {"time": t, "bybit_volume": v, "bybit_min_price": p, "bybit_max_price": p})
mev_tbl = table_html(focus,
                     ["tx_index", "side", "sender", "usdc_vol", "exec_price", "marginal_after"],
                     ["tx #", "side", "sender", "size", "executed px", "pool px after"],
                     {"tx_index": lambda x: str(int(x)), "side": str, "sender": str,
                      "usdc_vol": v, "exec_price": p, "marginal_after": p})

CSS = """
:root{--bg:#0e1116;--panel:#161b22;--panel-2:#1c232c;--border:#2d333b;--text:#e6edf3;--muted:#8b949e;
--accent:#58a6ff;--accent-2:#f0883e;--good:#3fb950;--bad:#f85149;--warn:#d29922;
--mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif;}
*,*::before,*::after{box-sizing:border-box;}
body{background:var(--bg);color:var(--text);font-family:var(--sans);margin:0;padding:0;line-height:1.55;}
a{color:var(--accent);text-decoration:none;} a:hover{text-decoration:underline;}
code,.mono{font-family:var(--mono);font-size:0.92em;}
header{border-bottom:1px solid var(--border);padding:34px 48px;background:linear-gradient(180deg,#161b22 0%,#0e1116 100%);}
header h1{margin:0 0 8px 0;font-size:25px;font-weight:600;}
header .meta{color:var(--muted);font-size:14px;}
main{padding:30px 48px;max-width:1200px;margin:0 auto;}
.lead{font-size:16px;margin:0 0 26px 0;} .lead strong{color:var(--accent-2);}
.grid{display:grid;gap:16px;} .grid.cols-3{grid-template-columns:repeat(3,1fr);} .grid.cols-2{grid-template-columns:1fr 1fr;}
@media(max-width:900px){.grid.cols-3,.grid.cols-2{grid-template-columns:1fr;}main,header{padding:20px 16px;}}
.stat{background:var(--panel);border:1px solid var(--border);padding:18px 20px;border-radius:10px;}
.stat .label{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:0.4px;}
.stat .value{font-size:26px;font-weight:700;margin-top:4px;font-family:var(--mono);}
.stat .sub{color:var(--muted);font-size:12px;margin-top:4px;}
.stat.alert .value{color:var(--bad);} .stat.warn .value{color:var(--warn);} .stat.good .value{color:var(--good);} .stat.accent .value{color:var(--accent-2);}
section{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:22px 26px;margin:18px 0;}
section h2{margin:0 0 6px 0;font-size:18px;font-weight:600;}
section .sub{color:var(--muted);font-size:14px;margin-bottom:14px;}
table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13.5px;}
th,td{border-bottom:1px solid var(--border);text-align:left;padding:8px 12px;}
th{color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase;letter-spacing:0.4px;}
td.num{font-family:var(--mono);text-align:right;}
tr:hover td{background:var(--panel-2);}
.figure{background:white;border:1px solid var(--border);border-radius:8px;padding:8px;margin:12px 0;text-align:center;}
.figure img{max-width:100%;height:auto;display:block;margin:0 auto;}
.interp{background:var(--panel-2);border-left:3px solid var(--accent);padding:14px 18px;border-radius:4px;margin:14px 0;}
.keyfindings{background:linear-gradient(135deg,#1c232c 0%,#161b22 100%);border-left:3px solid var(--accent-2);}
.keyfindings h2{color:var(--accent-2);}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-family:var(--mono);}
.pill.bad{background:rgba(248,81,73,0.15);color:var(--bad);} .pill.good{background:rgba(63,185,80,0.15);color:var(--good);}
footer{color:var(--muted);font-size:13px;padding:24px 48px;border-top:1px solid var(--border);margin-top:30px;}
"""

HTML = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>DEX vs CEX: USDC Peg Deviation · Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>{CSS}</style></head><body>
<header>
  <h1>DEX vs CEX: USDC Peg Deviation</h1>
  <div class="meta">Submission · DN Institute Market Data Challenge #493 ·
    <a href="https://github.com/mkzung">github.com/mkzung</a> · Max Gorbuk<br>
    Dataset: 151,246 Uniswap swaps · 5.29M Bybit trades · 2025-07-01 to 2025-09-30 UTC</div>
</header>
<main>
<p class="lead">How far did <strong>USDC</strong> trade from its 1.0000 USDT peg, hour by hour, on a decentralised
(Uniswap v3 1bp pool) versus a centralised (Bybit spot) venue. Two very different pictures: the CEX order book
left the band in a few genuine discount episodes, while the DEX pool holds the peg tightly and its rare wild
prints are <strong>within-block MEV</strong>, not market peg moves.</p>

<div class="grid cols-3">
  <div class="stat accent"><div class="label">Uniswap outside-band volume</div><div class="value">{usd(uni_vol)}</div><div class="sub">{uni_hours} hours, mostly large swaps at 0.998-0.999</div></div>
  <div class="stat alert"><div class="label">Bybit outside-band volume</div><div class="value">{usd(byb_vol)}</div><div class="sub">{byb_hours} hours, genuine USDC discount</div></div>
  <div class="stat warn"><div class="label">Both venues, same hour</div><div class="value">{len(both)}</div><div class="sub">clearest joint stress 2025-09-23 02:00 UTC</div></div>
  <div class="stat alert"><div class="label">Deepest CEX deviation</div><div class="value">{deepest_cex:.4f}</div><div class="sub">{(1-deepest_cex)*100:.1f}% below peg, 2025-07-02</div></div>
  <div class="stat"><div class="label">DEX volume with dev &gt; 1%</div><div class="value">{dex_gt1_share:.1f}%</div><div class="sub">the MEV tail, not a peg move</div></div>
  <div class="stat good"><div class="label">Grid coverage</div><div class="value">2208 h</div><div class="sub">every UTC hour Jul 1 to Sep 30</div></div>
</div>

<section class="keyfindings"><h2>What the data says</h2>
<ol>
<li><b>The CEX had real, modest peg stress.</b> Bybit USDC/USDT left the band in {byb_hours} hours, always on the discount side, down to {deepest_cex:.4f} on 2025-07-02, for {usd(byb_vol)} of outside-band volume.</li>
<li><b>The DEX 1bp pool holds the peg far tighter.</b> About 99% of its {usd(uni_vol)} of outside-band volume is within 1% of peg (83% within 0.2%, prices 0.998 to 0.999), ordinary AMM impact one tick past the edge, not a peg move.</li>
<li><b>The DEX's wild prices are sandwich MEV, verified on-chain.</b> Only {dex_gt1_share:.1f}% of DEX outside-band volume deviates more than 1%, and it is sandwich attacks. In block 22963581 one address (0xba6d84cc) sells $6.7M USDC to push the pool to ~0.80, a victim sells $142k through the Uniswap router and is filled at 0.7995, then the same address buys $6.5M back to ~1.00, across three consecutive transactions. Same shape in block 22984299 (~1.10).</li>
<li><b>Genuine joint stress is rare:</b> both venues printed outside-band volume in only {len(both)} hours.</li>
</ol></section>

<section><h2>Hourly outside-band volume, both venues</h2>
<div class="sub">Log scale. Uniswap clips the band often on large swaps; Bybit only in a handful of genuine discount hours.</div>
<div class="figure"><img src="data:image/png;base64,{fig1}" alt="hourly outside-band volume"></div></section>

<section><h2>CEX peg-discount episodes</h2>
<div class="sub">Every Bybit hour that left the band, and how deep below 1.0 it went. All on the discount side.</div>
<div class="figure"><img src="data:image/png;base64,{fig2}" alt="bybit depth below peg"></div>
{byb_tbl}</section>

<section><h2>DEX: where the outside-band volume lives</h2>
<div class="sub">Almost all of it sits in the 0.1-0.2% zone (large swaps, normal impact). The &gt;1% bucket is the MEV tail.</div>
<div class="figure"><img src="data:image/png;base64,{fig3}" alt="dex deviation buckets"></div></section>

<section><h2>MEV exhibit: block 22963581</h2>
<div class="sub">A verified sandwich, one block. Address 0xba6d84cc sells $6.7M USDC (tx 0) to push the pool marginal
price to ~0.80, a victim sells $142k through the Uniswap router (tx 1) and is filled at 0.7995, then the same
0xba6d84cc buys $6.5M back (tx 2) to restore ~1.00. The big swaps' executed averages stay near 1.0 because the
liquidity is at 1.0; the marginal price and the victim's fill are what reveal the dislocation.</div>
<div class="figure"><img src="data:image/png;base64,{fig4}" alt="mev block reconstruction"></div>
{mev_tbl}</section>

<section><h2>Both venues outside-band, same hour</h2>
<div class="sub">The {len(both)} hours where the DEX and the CEX simultaneously traded outside the band.</div>
{both_tbl}</section>

<section class="interp"><b>Method.</b> Executed price per swap (Uniswap: |amount1|/|amount0|, both tokens 6 decimals)
or per trade (Bybit). Outside the band means |price - 1| &gt; 0.001 with a 1e-9 epsilon so the exact edge stays
in-band. Trades below 1 USDC are dropped as dust (sub-dollar Uniswap swaps give meaningless price ratios from
integer rounding). Data is free and key-less: Uniswap Swap logs via public Ethereum RPC (eth_getLogs), Bybit
public spot trade dumps. Full working in the Jupyter notebook; logic covered by unit tests.</section>

<footer>Max Gorbuk · <a href="https://github.com/mkzung">github.com/mkzung</a> ·
data from Ethereum mainnet and Bybit public spot dumps · reproducible from the repo (see README).</footer>
</main></body></html>
"""

for name in ("index.html", "dashboard.html"):
    with open(D(name), "w") as f:
        f.write(HTML)
print(f"wrote index.html + dashboard.html ({len(HTML):,} bytes, 4 embedded figures)")
