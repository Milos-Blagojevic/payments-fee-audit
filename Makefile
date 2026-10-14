# Every target runs from the repository root. Uses .venv/ when it exists.
BIN := $(if $(wildcard .venv/bin/python),.venv/bin/,)
PYTHON := $(BIN)python
DBT := $(BIN)dbt --no-use-colors
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.PHONY: install contracts data build test all clean

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

# Validate every contract YAML and load schema `contracts`.
contracts:
	$(PYTHON) -m feeaudit.contracts

# Generate data/raw and data/truth from config/generator.yml, load schemas `raw` and `truth`, print the calibration.
data:
	$(PYTHON) -m generator

build:
	$(DBT) build $(DBT_ARGS)

test:
	$(PYTHON) -m pytest

all: clean contracts data build

clean:
	rm -rf data
	rm -f warehouse/fees.duckdb warehouse/fees.duckdb.wal
