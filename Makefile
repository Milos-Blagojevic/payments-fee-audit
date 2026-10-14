# Every target runs from the repository root. Uses .venv/ when it exists.
BIN := $(if $(wildcard .venv/bin/python),.venv/bin/,)
PYTHON := $(BIN)python
DBT := $(BIN)dbt --no-use-colors
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.PHONY: install contracts data build verify eval extraction-score report test all clean

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

# Python reference engine (schema `reference`), then the differential check against int_expected_charges.
verify:
	$(PYTHON) -m feeaudit.reference
	$(PYTHON) -m feeaudit.verify

# Compare the findings with schema `truth`, write schema `evaluation`, fail below the thresholds.
eval:
	$(PYTHON) -m feeaudit.evaluation

# Finance outputs to reports/, the committed sample in reports/examples/, the README blocks and docs/img chart.
report:
	$(PYTHON) -m feeaudit.reports

test:
	$(PYTHON) -m pytest

# Score the committed LLM extractions (contracts/extracted/) against contracts/providers/; offline, never calls
# the API. Writes evaluation.extraction_scores. The paid extraction itself is `python -m feeaudit.extraction extract`.
extraction-score:
	$(PYTHON) -m feeaudit.extraction score

all: clean contracts data build verify eval extraction-score report

clean:
	rm -rf data
	rm -f warehouse/fees.duckdb warehouse/fees.duckdb.wal
