# Pipeline entry points. Each step is a module in src/pdengine/ run with `python -m`.
# On Windows, install make once (e.g. `winget install ezwinports.make`) and run
# these from the VS Code terminal with the venv activated.

PYTHON ?= python

.PHONY: help install data warehouse train ecl report serve lint format test all

help:
	@echo "install    install the package and dev tools into the active venv"
	@echo "data       download Bondora data (official feed + Kaggle snapshot) to data/raw/"
	@echo "warehouse  convert raw files to Parquet and build the DuckDB warehouse"
	@echo "train      fit the WoE logistic scorecard and the LightGBM challenger"
	@echo "ecl        compute 12-month PD x LGD x EAD under baseline, adverse, severe"
	@echo "report     build the model documentation and scenario tables in reports/"
	@echo "serve      start the FastAPI /score endpoint locally"
	@echo "lint       ruff lint and format check (same as CI)"
	@echo "format     auto-fix lint issues and format the code"
	@echo "test       pytest with coverage (same as CI)"
	@echo "all        data -> warehouse -> train -> ecl -> report"

install:
	$(PYTHON) -m pip install -r requirements-dev.txt
	$(PYTHON) -m pip install -e . --no-deps

data:
	$(PYTHON) -m pdengine.download_data --source official
	$(PYTHON) -m pdengine.download_data --source kaggle

# The targets below call modules that are built in later stages of the project.
warehouse:
	$(PYTHON) -m pdengine.warehouse

train:
	$(PYTHON) -m pdengine.train

ecl:
	$(PYTHON) -m pdengine.ecl

report:
	$(PYTHON) -m pdengine.report

serve:
	$(PYTHON) -m uvicorn pdengine.api:app --reload

lint:
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format:
	$(PYTHON) -m ruff check . --fix
	$(PYTHON) -m ruff format .

test:
	$(PYTHON) -m pytest --cov=pdengine --cov-report=term-missing

all: data warehouse train ecl report