.PHONY: demo test inspect clean

PYTHON ?= python
DEMO_OUTPUT ?= .demo-output

demo:
	$(PYTHON) demo/run_demo.py --output-dir "$(DEMO_OUTPUT)"

test:
	$(PYTHON) -m pytest -q \
	  --ignore=tests/unit/test_replication_gcs.py \
	  -m "not gcs"

inspect:
	$(PYTHON) scripts/inspect_demo.py --output-dir "$(DEMO_OUTPUT)"

clean:
	$(PYTHON) scripts/clean_demo.py --output-dir "$(DEMO_OUTPUT)"
