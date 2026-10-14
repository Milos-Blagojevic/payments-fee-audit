# Every target runs from the repository root. Uses .venv/ when it exists.
BIN := $(if $(wildcard .venv/bin/python),.venv/bin/,)
PYTHON := $(BIN)python
DBT := $(BIN)dbt --no-use-colors
DBT_ARGS := --project-dir dbt --profiles-dir dbt

.PHONY: install build test all clean

install:
	$(PYTHON) -m pip install -r requirements.txt -r requirements-dev.txt

build:
	$(DBT) build $(DBT_ARGS)

test:
	$(PYTHON) -m pytest

all: clean build

clean:
	rm -f warehouse/fees.duckdb warehouse/fees.duckdb.wal
