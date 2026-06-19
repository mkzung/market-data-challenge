"""End-to-end reproducibility test, analyze.py must produce identical findings."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

def _find_csv(name: str) -> Path:
    """Locate a challenge CSV in data/ (source-of-truth) or repo parent (fork)."""
    for candidate in (REPO / "data" / name, REPO.parent / name):
        if candidate.exists():
            return candidate
    return REPO / "data" / name  # default for skipif

TRADES_CSV     = _find_csv("eth-btc-trades.csv")
ORDERBOOKS_CSV = _find_csv("eth-btc-orderbooks.csv")
DATA = TRADES_CSV.parent  # back-compat alias for legacy test code


@pytest.mark.skipif(not TRADES_CSV.exists(),
                    reason="challenge data not present")
def test_analyze_produces_consistent_findings(tmp_path):
    """Run analyze.py twice, findings.json must be byte-identical."""
    f1 = tmp_path / "findings1.json"
    f2 = tmp_path / "findings2.json"
    figs = tmp_path / "figures"

    cmd = [
        sys.executable, str(REPO / "analyze.py"),
        "--trades",      str(TRADES_CSV),
        "--orderbooks",  str(ORDERBOOKS_CSV),
        "--out",         str(figs),
    ]
    subprocess.run(cmd + ["--findings", str(f1)], check=True, cwd=str(REPO),
                   capture_output=True, text=True)
    subprocess.run(cmd + ["--findings", str(f2)], check=True, cwd=str(REPO),
                   capture_output=True, text=True)

    assert f1.read_bytes() == f2.read_bytes(), \
        "findings.json must be byte-identical on rerun (seeded RNGs)"


@pytest.mark.skipif(not TRADES_CSV.exists(),
                    reason="challenge data not present")
def test_analyze_findings_have_expected_top_level_keys(tmp_path):
    """analyze.py must populate dataset / d1..d5 keys."""
    f = tmp_path / "findings.json"
    figs = tmp_path / "figures"
    subprocess.run([
        sys.executable, str(REPO / "analyze.py"),
        "--trades",      str(TRADES_CSV),
        "--orderbooks",  str(ORDERBOOKS_CSV),
        "--out",         str(figs),
        "--findings",    str(f),
    ], check=True, cwd=str(REPO), capture_output=True)

    data = json.loads(f.read_text())
    assert {"dataset", "d1", "d2", "d3", "d4", "d5"} <= data.keys()
    assert data["dataset"]["n_trades"] > 0
    assert data["dataset"]["n_orderbooks"] > 0
