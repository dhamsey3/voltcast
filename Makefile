PYTHON ?= .venv/bin/python
TF     := terraform -chdir=infrastructure
SHA    := $(shell git rev-parse --short HEAD)

.PHONY: setup test lint build plan deploy run-local backfill report

setup:            ## create the virtualenv with dev tools
	python3.13 -m venv .venv
	$(PYTHON) -m pip install -r requirements-dev.txt -e .

test:             ## unit tests
	$(PYTHON) -m pytest -q

lint:             ## style + terraform formatting
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests
	terraform fmt -check -recursive infrastructure

build:            ## Lambda bundle: our package + tzdata, nothing else
	rm -rf build/lambda && mkdir -p build/lambda
	cp -R src/dayahead build/lambda/
	$(PYTHON) -m pip install --quiet --target build/lambda -r requirements-lambda.txt
	find build/lambda -name __pycache__ -prune -exec rm -rf {} +

plan: build       ## terraform plan (needs infrastructure/backend.hcl)
	$(TF) init -backend-config=backend.hcl
	$(TF) plan -var code_version=$(SHA) -out=tfplan

deploy:           ## apply the plan from `make plan`
	$(TF) apply tfplan

run-local:        ## today's real pipeline against ./data
	$(PYTHON) -m dayahead ingest
	$(PYTHON) -m dayahead forecast
	$(PYTHON) -m dayahead score

backfill:         ## replay everything since the 15-minute auction started into ./data
	$(PYTHON) -m dayahead backfill --start 2025-10-01 --end $$($(PYTHON) -c "import datetime; print(datetime.date.today())")

report:           ## champion vs challenger, last 30 days
	$(PYTHON) -m dayahead report --days 30
