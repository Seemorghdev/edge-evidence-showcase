SHOWCASE_PYTHON ?= $(if $(wildcard .venv/showcase/bin/python),.venv/showcase/bin/python,python3)
PROCESSOR_PYTHON ?= $(if $(wildcard .venv/processor/bin/python),.venv/processor/bin/python,python3)
REPLICATION_PYTHON ?= $(if $(wildcard .venv/replication/bin/python),.venv/replication/bin/python,python3)
OUTPUT_ROOT ?= .demo-output

.PHONY: setup demo test inspect fingerprint artifact clean

setup:
	bash scripts/setup.sh

demo:
	$(SHOWCASE_PYTHON) demo/run_showcase.py \
	  --output-root "$(OUTPUT_ROOT)" \
	  --processor-python "$(PROCESSOR_PYTHON)" \
	  --replication-python "$(REPLICATION_PYTHON)" \
	  demo

test:
	$(SHOWCASE_PYTHON) -m pytest -q
	$(MAKE) -C components/processor-worker \
	  PYTHON="$(abspath $(PROCESSOR_PYTHON))" test
	$(MAKE) -C components/replication-worker \
	  PYTHON="$(abspath $(REPLICATION_PYTHON))" test

inspect:
	$(SHOWCASE_PYTHON) demo/run_showcase.py \
	  --output-root "$(OUTPUT_ROOT)" \
	  --processor-python "$(PROCESSOR_PYTHON)" \
	  --replication-python "$(REPLICATION_PYTHON)" \
	  inspect

fingerprint:
	$(SHOWCASE_PYTHON) demo/run_showcase.py \
	  --output-root "$(OUTPUT_ROOT)" fingerprint

artifact:
	$(SHOWCASE_PYTHON) scripts/package_ci_artifact.py \
	  --output-root "$(OUTPUT_ROOT)"

clean:
	$(SHOWCASE_PYTHON) demo/run_showcase.py \
	  --output-root "$(OUTPUT_ROOT)" clean
