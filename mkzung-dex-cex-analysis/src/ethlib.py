"""Minimal Ethereum JSON-RPC helpers: no web3 dependency, just requests.

We talk to public key-less RPC endpoints, decode Uniswap v3 Swap events by hand,
and resolve block timestamps with a small cache. Everything here is read-only.
"""
import time
import requests

from config import RPCS, SWAP_TOPIC

_session = requests.Session()
_ts_cache = {}   # block_number -> unix ts


def rpc(method, params, timeout=25, tries=4):
    """Call an RPC method, rotating endpoints and retrying with backoff."""
    last = None
    for attempt in range(tries):
        url = RPCS[attempt % len(RPCS)]
        try:
            r = _session.post(url, json={"jsonrpc": "2.0", "method": method,
                                         "params": params, "id": 1}, timeout=timeout)
            j = r.json()
            if "result" in j:
                return j["result"]
            last = j.get("error")
        except Exception as e:
            last = str(e)
        time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(f"rpc {method} failed: {last}")


def block_number():
    return int(rpc("eth_blockNumber", []), 16)


def block_ts(n):
    """Timestamp (unix seconds) of block n, cached."""
    if n not in _ts_cache:
        b = rpc("eth_getBlockByNumber", [hex(n), False])
        _ts_cache[n] = int(b["timestamp"], 16)
    return _ts_cache[n]


def block_for_ts(target, lo, hi):
    """First block whose timestamp is >= target (binary search over [lo, hi])."""
    while lo < hi:
        mid = (lo + hi) // 2
        if block_ts(mid) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo


def _to_int256(word):
    """Decode a 64-hex-char two's-complement word to a signed int."""
    v = int(word, 16)
    return v - (1 << 256) if v >= (1 << 255) else v


def decode_swap(log):
    """Decode a Uniswap v3 Swap log -> (amount0_raw, amount1_raw, sqrtPriceX96).

    Non-indexed data layout: int256 amount0, int256 amount1, uint160 sqrtPriceX96,
    uint128 liquidity, int24 tick  (5 x 32-byte words).
    """
    d = log["data"][2:]
    a0 = _to_int256(d[0:64])
    a1 = _to_int256(d[64:128])
    sqrt_p = int(d[128:192], 16)
    return a0, a1, sqrt_p


def get_logs_adaptive(addr, topic, from_block, to_block, chunk=5000, floor=200, on_chunk=None):
    """Pull logs over [from_block, to_block] in adaptive chunks.

    Halves the span on 'too many results' / errors down to `floor`. Calls
    on_chunk(start, end) for progress. Yields raw log dicts.
    """
    start = from_block
    size = chunk
    while start <= to_block:
        end = min(start + size - 1, to_block)
        try:
            logs = rpc("eth_getLogs", [{
                "fromBlock": hex(start), "toBlock": hex(end),
                "address": addr, "topics": [topic],
            }])
        except RuntimeError:
            if size > floor:
                size = max(floor, size // 2)
                continue
            raise
        if on_chunk:
            on_chunk(start, end, len(logs))
        for lg in logs:
            yield lg
        start = end + 1
        # gently grow the window back up after a successful large-ish pull
        if size < chunk and len(logs) < 3000:
            size = min(chunk, size * 2)
