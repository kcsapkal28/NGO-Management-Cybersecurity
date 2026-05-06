.PHONY: help install smoke full chaos load dash-check pipeline bootstrap teardown clean

# Prefer the project's venv if it exists, otherwise fall back to whatever
# python3 is on PATH. PEP 668 (Homebrew, Debian) refuses system-wide installs,
# so the venv is the supported path. Override with `make install PYTHON=...`.
REPO_ROOT := $(abspath $(CURDIR)/../..)
VENV_PY   := $(REPO_ROOT)/venv/bin/python
ifeq ($(wildcard $(VENV_PY)),)
PYTHON ?= python3
else
PYTHON ?= $(VENV_PY)
endif
PYTEST ?= $(PYTHON) -m pytest

help:
	@echo "make install        Install pytest deps into the active venv"
	@echo "make smoke          Run fast post-deploy checks (~30s)"
	@echo "make full           Run full validation suite"
	@echo "make chaos          Restart workloads and re-smoke"
	@echo "make load           Drive load and append latencies to results/load.csv"
	@echo "make dash-check     Validate every dashboard panel query"
	@echo "make pipeline       In-cluster connectivity check"
	@echo "make bootstrap      Apply k8s manifests, wait, smoke"
	@echo "make teardown       Reap old ES indices and stale CSVs"

install:
	@if [ "$(PYTHON)" = "python3" ]; then \
	  echo "ERROR: no venv at $(REPO_ROOT)/venv — create one first:"; \
	  echo "  python3 -m venv $(REPO_ROOT)/venv"; \
	  echo "  $(REPO_ROOT)/venv/bin/pip install -r $(REPO_ROOT)/requirements.txt"; \
	  echo "Or override: make install PYTHON=/path/to/python"; \
	  exit 1; \
	fi
	@echo "Installing into $(PYTHON)"
	$(PYTHON) -m pip install -r requirements.txt

smoke:
	@bash bash/smoke.sh
	$(PYTEST) -m smoke

full:
	$(PYTEST) -m "smoke or full or correlation"

chaos:
	@bash bash/chaos.sh

load:
	@bash bash/load.sh

dash-check:
	$(PYTEST) test_dashboards.py -m full

pipeline:
	@bash bash/pipeline-check.sh

bootstrap:
	@bash bash/bootstrap.sh

teardown:
	@bash bash/teardown.sh

clean:
	rm -rf .pytest_cache __pycache__
