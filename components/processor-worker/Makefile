VENV_PYTHON := .venv/bin/python
PYTHON ?= $(if $(wildcard $(VENV_PYTHON)),$(VENV_PYTHON),python3)
OUTPUT_ROOT ?= .demo-output

.PHONY: setup demo test inspect clean

setup:
	PYTHON="$(PYTHON)" bash scripts/setup.sh

demo:
	$(PYTHON) demo/run_demo.py --output-root "$(OUTPUT_ROOT)" demo

test:
	$(PYTHON) -m pytest -q

inspect:
	$(PYTHON) demo/run_demo.py --output-root "$(OUTPUT_ROOT)" inspect

clean:
	$(PYTHON) demo/run_demo.py --output-root "$(OUTPUT_ROOT)" clean
