.PHONY: help install analyze audit calibrate dashboard all clean test pytest

# ----------------------------------------------------------------------------
# Path resolution — works from BOTH the source-of-truth checkout (with
# data/ subfolder) and the upstream fork checkout (CSVs at fork root, ../).
# Override at the command line if neither location matches your layout:
#     make analyze TRADES=path/to/trades.csv ORDERBOOKS=path/to/orderbooks.csv
# ----------------------------------------------------------------------------
PYTHON     ?= $(shell command -v python3 >/dev/null 2>&1 && echo python3 || echo python)
TRADES     ?= $(shell test -f data/eth-btc-trades.csv     && echo data/eth-btc-trades.csv     || echo ../eth-btc-trades.csv)
ORDERBOOKS ?= $(shell test -f data/eth-btc-orderbooks.csv && echo data/eth-btc-orderbooks.csv || echo ../eth-btc-orderbooks.csv)

help:
	@echo "ETH/BTC Suspicious Pattern Analysis — make targets:"
	@echo ""
	@echo "  make install     install pinned Python dependencies"
	@echo "  make analyze     run analyze.py → 6 PNGs + findings.json"
	@echo "  make audit       run audit.py  → audit.txt with raw evidence"
	@echo "  make calibrate   run calibration.py → detectors on synthetic clean data"
	@echo "  make pytest      run unit tests in tests/"
	@echo "  make dashboard   open dashboard.html in default browser"
	@echo "  make all         install + pytest + analyze + audit + dashboard"
	@echo "  make test        verify reproducibility (rerun, diff findings.json)"
	@echo "  make clean       remove generated outputs"
	@echo ""
	@echo "Resolved data paths (override on the cmd line if different):"
	@echo "  TRADES     = $(TRADES)"
	@echo "  ORDERBOOKS = $(ORDERBOOKS)"

install:
	$(PYTHON) -m pip install -r requirements.txt

analyze:
	$(PYTHON) analyze.py \
	    --trades $(TRADES) \
	    --orderbooks $(ORDERBOOKS) \
	    --out figures \
	    --findings findings.json

audit:
	$(PYTHON) audit.py \
	    --trades $(TRADES) \
	    --orderbooks $(ORDERBOOKS)

calibrate:
	$(PYTHON) calibration.py \
	    --challenge-trades $(TRADES) \
	    --challenge-orderbooks $(ORDERBOOKS)

pytest:
	$(PYTHON) -m pytest tests/ -v

dashboard:
	@echo "Opening dashboard.html …"
	@(command -v open >/dev/null 2>&1 && open dashboard.html) \
	 || (command -v xdg-open >/dev/null 2>&1 && xdg-open dashboard.html) \
	 || (command -v start >/dev/null 2>&1 && start dashboard.html) \
	 || echo "Please open dashboard.html manually in your browser."

all: install pytest analyze audit dashboard

test:
	@cp findings.json findings.json.bak
	@$(PYTHON) analyze.py --trades $(TRADES) \
	                   --orderbooks $(ORDERBOOKS) \
	                   --out figures \
	                   --findings findings.json > /dev/null
	@diff -q findings.json findings.json.bak \
	    && echo "✓ reproducibility OK — findings.json byte-identical" \
	    || echo "✗ reproducibility FAILED — findings.json changed"
	-@rm -f findings.json.bak 2>/dev/null || true

clean:
	rm -rf figures findings.json audit.txt
	rm -rf src/__pycache__ __pycache__
	rm -rf notebooks/.ipynb_checkpoints
