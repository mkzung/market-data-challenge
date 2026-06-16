"""Shared constants for the DEX-CEX peg-deviation analysis (Task 2).

Window: 2025-07-01 00:00:00 UTC .. 2025-09-30 23:59:59 UTC (inclusive).
Venues:
  DEX = Uniswap v3 USDC/USDT 0.01% pool on Ethereum mainnet.
  CEX = Bybit USDC/USDT spot.
Fair price = 1.0000 USDT per USDC. Band = +/- 0.1%.
"""

# --- Uniswap v3 pool ---
POOL = "0x3416cf6c708da44db2624d63ea0aaef7113527c6"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"   # token0, 6 decimals
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"   # token1, 6 decimals
DEC0 = 6   # USDC
DEC1 = 6   # USDT
# keccak256("Swap(address,address,int256,int256,uint160,uint128,int24)")
SWAP_TOPIC = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

# Public, key-less Ethereum JSON-RPC endpoints (verified reachable 2026-06-16).
RPCS = [
    "https://ethereum.publicnode.com",
    "https://eth.drpc.org",
]

# --- time window ---
START_TS = 1751328000   # 2025-07-01T00:00:00Z
END_TS   = 1759276800   # 2025-10-01T00:00:00Z (exclusive upper bound)

# Block bounds derived once via binary search on block timestamps (see src/ethlib.block_for_ts).
# Re-verified at runtime; hard-coded here so the pull is deterministic and fast.
BLOCK_START = 22820674  # first block with ts >= START_TS
BLOCK_END   = 23479244  # first block with ts >= END_TS  -> we pull up to BLOCK_END-1

# --- analysis params ---
FAIR = 1.0
BAND = 0.001            # +/- 0.1% -> in-band = [0.999, 1.001]
EPS  = 1e-9             # tolerance: a trade exactly on the band edge stays in-band, not outside
DUST_USDC = 1.0         # min trade size in USDC; below this, |amount1/amount0| is rounding noise

# --- Bybit spot historical trade dumps (key-less) ---
BYBIT_SYMBOL = "USDCUSDT"
BYBIT_URL = "https://public.bybit.com/spot/{sym}/{sym}_{date}.csv.gz"  # date = YYYY-MM-DD


def hour_iso(ts: int) -> str:
    """UTC hour bucket label for a unix-seconds timestamp -> 'YYYY-MM-DDTHH:00:00Z'."""
    import datetime as _dt
    h = ts - (ts % 3600)
    return _dt.datetime.utcfromtimestamp(h).strftime("%Y-%m-%dT%H:00:00Z")


def is_outside(price: float) -> bool:
    """True if an executed price is strictly outside the band around 1.0 (scalar).

    The EPS tolerance keeps exact band-edge ticks (0.9990 / 1.0010, deviation == 0.1%) in band;
    without it IEEE-754 rounding makes 1.0 - 0.999 == 0.0010000000000000009 > 0.001.
    """
    return abs(price - FAIR) - BAND > EPS


def outside_mask(prices):
    """Vectorised is_outside for a pandas Series / numpy array (single source of truth)."""
    return (abs(prices - FAIR) - BAND) > EPS
