"""Unit tests for the pure logic: Swap decoding, band test, price math, hour bucketing.
No network. Run with: pytest -q  (from repo root) or python -m pytest tests/."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config
import ethlib


def _word(x):
    """256-bit two's-complement hex word (handles negatives)."""
    return f"{x & (2**256 - 1):064x}"


def make_log(a0, a1, sqrt_p, liq=12345, tick=-7, block=0x10):
    data = "0x" + _word(a0) + _word(a1) + _word(sqrt_p) + _word(liq) + _word(tick)
    return {"data": data, "blockNumber": hex(block)}


def test_decode_swap_roundtrip():
    sp = 79228162514264337593543950336  # 1.0 * 2**96
    a0, a1, got_sp = ethlib.decode_swap(make_log(1_000_000, -1_000_500, sp))
    assert a0 == 1_000_000
    assert a1 == -1_000_500          # negative amount decoded via two's complement
    assert got_sp == sp


def test_executed_price_and_volume():
    # 1 USDC in, 1.0005 USDT out -> executed price 1.0005, volume 1 USDC
    a0, a1 = 1_000_000, -1_000_500
    price = abs(a1 / a0) * 10 ** (config.DEC0 - config.DEC1)
    vol = abs(a0) / 10 ** config.DEC0
    assert abs(price - 1.0005) < 1e-12
    assert abs(vol - 1.0) < 1e-12


def test_band_edges_are_in_band():
    # exactly +/-0.1% is ON the band, not outside (guards the float-rounding trap)
    assert config.is_outside(0.999) is False
    assert config.is_outside(1.001) is False
    assert config.is_outside(1.0) is False


def test_band_outside():
    assert config.is_outside(0.9989) is True
    assert config.is_outside(1.0011) is True
    assert config.is_outside(0.99) is True
    assert config.is_outside(1.02) is True


def test_hour_iso_floors_to_utc_hour():
    base = 1751328000  # 2025-07-01T00:00:00Z
    assert config.hour_iso(base) == "2025-07-01T00:00:00Z"
    assert config.hour_iso(base + 3600 + 1800) == "2025-07-01T01:00:00Z"   # mid-hour floors down
    assert config.hour_iso(base + 3599) == "2025-07-01T00:00:00Z"


if __name__ == "__main__":
    import subprocess
    raise SystemExit(subprocess.call(["python", "-m", "pytest", "-q", __file__]))
