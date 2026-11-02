# Credit Risk PD Engine IFRS 9

[![Python CI](https://github.com/Langsi97/credit-risk-pd-engine-ifrs9/actions/workflows/python-ci.yml/badge.svg)](https://github.com/Langsi97/credit-risk-pd-engine-ifrs9/actions/workflows/python-ci.yml)

> **Important.** This is a portfolio benchmark model built on public data. It is not a bank-approved score and must not be used for real lending decisions. Loss given default (LGD) and exposure at default (EAD) in the ECL step are stated assumptions, not estimates from recovery data.

## Business problem

This project develops a credit risk scorecard and probability of default (PD) engine for European consumer loans, with an explicit focus on IFRS 9 expected credit loss (ECL) estimation. The analysis targets retail lending portfolios from Bondora across Estonia, Finland and Spain, with a primary objective of translating borrower risk into transparent, explainable score grades and portfolio-level ECL metrics.

The work is structured around three linked objectives:

1. Estimate a 12-month PD for individual borrowers using a transparent, auditable risk model.
2. Convert model output into a scorecard framework with clear grade segmentation and calibration by risk band.
3. Translate PD and exposure estimates into IFRS 9 ECL under baseline, adverse, and severe macroeconomic scenarios, with Spain explicitly stress-tested against the EBA 2025 regulatory baseline and adverse conditions.

## Scope

- Portfolio: European consumer loans from Bondora
- Geography: Estonia, Finland and Spain. Slovakia (296 loans) is too small to model or report on its own; see [decision D-008](docs/decision_log.md)
- Horizon: 12-month PD estimation
- Regulatory lens: IFRS 9 and EBA macro scenario overlays
- Deliverable: risk scorecard, calibrated PD by grade, and ECL outputs for scenario analysis

## Success criteria

The project is considered successful when the following outcomes are met:

- Out-of-time (OOT) Gini coefficient of at least 0.35 on the holdout portfolio
- PD is calibrated and monotonic across borrower risk grades
- Score grades provide stable, interpretable rating bands for decision support and monitoring
- ECL estimates are produced for baseline, adverse, and severe scenarios
- Spain stress scenarios are explicitly modeled under the official EBA 2025 baseline and adverse assumptions
- Documentation and reports clearly show assumptions, calibration logic, and scenario outputs

## Project status

| Stage | Status |
|---|---|
| Data download with manifests (`make data`) | Done |
| Preliminary EDA ([notebook 01](notebooks/01_preliminary_eda.ipynb)) | Done |
| DuckDB warehouse (`make warehouse`) | Done |
| Data audit, target and out-of-time split | Next |
| WoE scorecard and LightGBM challenger (`make train`) | Planned |
| SHAP reason codes, risk bands, cut-off table | Planned |
| IFRS 9 ECL under macro scenarios (`make ecl`) | Planned |
| Model documentation report (`make report`) and FastAPI service (`make serve`) | Planned |

## Getting started

Requires Python 3.12. On Windows, run these in PowerShell or the VS Code terminal.

```bash
git clone https://github.com/Langsi97/credit-risk-pd-engine-ifrs9.git
cd credit-risk-pd-engine-ifrs9
python -m venv .venv
.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -e . --no-deps
```

Then run the pipeline step by step:

```bash
python -m pdengine.download_data                    # official Bondora feed
python -m pdengine.download_data --source kaggle    # Kaggle snapshot (needs a Kaggle API token)
python -m pdengine.warehouse                        # Parquet + DuckDB warehouse
pytest --cov=pdengine                               # tests with coverage
```

If `make` is installed (on Windows: `winget install ezwinports.make`), the same steps are `make install`, `make data`, `make warehouse` and `make test`. Run `make help` for every target.

## Data source

The model is built on Bondora's public loan-level dataset: every loan issued on the Bondora platform since February 2009, with borrower demographics, loan terms, credit ratings and repayment status. Bondora's investor product has since been rebranded Go & Grow, and the public statistics page moved with it.

| Source | Link | Coverage | Access |
|---|---|---|---|
| Official (default) | [Go & Grow public statistics](https://goandgrow.eu/en/public-statistics/), file `loan_dataset_investor.xlsx` | 2009 to last month, refreshed by Bondora | Direct download |
| Kaggle snapshot | [sid321axn/bondora-peer-to-peer-lending-loan-data](https://www.kaggle.com/datasets/sid321axn/bondora-peer-to-peer-lending-loan-data) | 2009 to mid-2021 | Kaggle account and API token |
| IEEE DataPort snapshot | [Bondora Peer-to-Peer Lending Data](https://ieee-dataport.org/open-access/bondora-peer-peer-lending-data), DOI [10.21227/33kz-0s65](https://doi.org/10.21227/33kz-0s65) | 2009-03-01 to 2020-01-27 | Free IEEE account login |

The project combines two of them: the Kaggle snapshot provides borrower features at application, and the official feed provides up-to-date loan outcomes. The two are joined on the loan ID in the warehouse ([decision D-001](docs/decision_log.md)).

```bash
python -m pdengine.download_data                      # official source
python -m pdengine.download_data --source kaggle      # needs a Kaggle API token
python -m pdengine.download_data --source ieee --file path/to/Bondora_dataset.zip
```

Files land in `data/raw/<source>/` with a `manifest.json` recording the URL, retrieval time, size and SHA-256 of each file, so every model run can be traced to the exact snapshot used. The warehouse copies these hashes into its `_load_log` table.

**Licence and terms.** None of the three sources publishes the data under a named open licence. The official file is provided by Bondora / Go & Grow under its general [Terms of Use](https://goandgrow.eu/en/terms/); the Kaggle and IEEE DataPort copies are third-party redistributions of the same Bondora data and state no licence of their own. This repository therefore never redistributes the data: `data/*` is git-ignored, and anyone reproducing the work downloads it from the source. The MIT licence of this repository covers the code only, not the data.

## Data warehouse

`python -m pdengine.warehouse` converts the raw files to Parquet (`data/processed/`) and builds `data/bondora.duckdb`:

| Object | Contents |
|---|---|
| `kaggle_loans` | Kaggle snapshot, one row per loan, original column names |
| `official_loans` | Official feed, one row per loan, original column names |
| `loans` (view) | Kaggle loans joined to their official outcomes; official columns prefixed `off_` |
| `_load_log` | Which raw file and SHA-256 each table was built from |
| `_checks` | Result of every integrity check in the build |

The build stops on duplicate loan IDs or unmatched loans and keeps the previous warehouse. Query it from Python with `duckdb.connect("data/bondora.duckdb", read_only=True)`.

## Repository structure

```
├── .github/workflows/   CI: ruff lint and format check, pytest with coverage (Python 3.12)
├── data/                raw downloads, Parquet and the DuckDB warehouse (git-ignored)
├── docs/
│   └── decision_log.md  modelling and engineering decisions, with reasons
├── notebooks/           numbered analysis notebooks (01_preliminary_eda, ...)
├── reports/             generated model reports and scenario tables (git-ignored)
├── src/pdengine/        the installable package: one module per pipeline step
├── tests/               pytest suite (runs offline in CI on tiny fake data)
├── Makefile             pipeline entry points
├── pyproject.toml       package, ruff, pytest and coverage settings
├── requirements.txt     runtime dependencies (pinned)
└── requirements-dev.txt development tools: pytest, ruff, ipykernel, Kaggle CLI
```

## Documentation

- [Decision log](docs/decision_log.md): every key choice, why it was made and what was rejected
- [01 Preliminary EDA](notebooks/01_preliminary_eda.ipynb): what is in the two sources and how they join

## License

This project is licensed under the MIT License. See `LICENSE` for details. The licence covers the code only, not the Bondora data.
