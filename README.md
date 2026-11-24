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
- Geography: Estonia, Finland and Spain. Slovakia (296 loans) is too small to model or report on its own, and none of its loans falls in the 2016 to 2021 modelling windows; see decisions [D-008 and D-013](docs/decision_log.md)
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
| DuckDB warehouse (`make warehouse`) | Done |
| Preliminary EDA and data audit ([01](notebooks/01_preliminary_eda.ipynb), [02](notebooks/02_data_audit.ipynb), [data card](docs/data_card.md)) | Done |
| Leakage registry, target and out-of-time samples ([03](notebooks/03_target_and_samples.ipynb)) | Done |
| Binning, WoE, IV and feature selection ([04](notebooks/04_binning_woe_iv.ipynb)) | Done |
| First scorecard: WoE logistic regression, v1 ([05](notebooks/05_scorecard.ipynb)) | Done |
| Challengers: LightGBM, CatBoost, Explainable Boosting Machine ([06](notebooks/06_challenger.ipynb)) | Done |
| **Champion v2: logical dummy scorecard with country-specific bins** ([07](notebooks/07_champion_v2.ipynb), `make train`) | Done |
| PD recalibration per country to the post-2020 level ([08](notebooks/08_recalibration.ipynb), `make train`) | Done |
| Risk grades, reason codes, cut-off and profit analysis, fairness check | Next |
| IFRS 9 ECL under macro scenarios (`make ecl`) | Planned |
| Model documentation report (`make report`) and FastAPI service (`make serve`) | Planned |

## Results so far

**Champion v2** ([notebook 07](notebooks/07_champion_v2.ipynb), [D-028](docs/decision_log.md)): a logistic regression with one coefficient per bin, scaled to points (600 points at good:bad odds of 30:1, 20 points to double the odds). Ten characteristics:
* country with its credit-bureau grade;
* customer tenure, time since the last loan and amount applied for, each binned **inside each country**;
* number and amount of previous loans;
* home ownership, education and income relative to the country median;
* the hour the application was signed.

The fit is constrained so that a safer bin never gets fewer points (logical by construction). Every decline gets reason codes.

| Gini | Test, 2016 to 2019 (32,273 loans) | Out-of-time, 2020 to Jul 2021 (48,150 loans) |
|---|---|---|
| Baseline: country alone | 0.377 | 0.220 |
| Baseline: country and its bureau grade | 0.409 | 0.293 |
| First scorecard, v1 (WoE, 6 features) | 0.459 | 0.368 |
| **Champion v2** | **0.480** | **0.401** |
| Challenger: Explainable Boosting Machine (glass box) | 0.513 | 0.426 |
| Benchmark: LightGBM, 24 candidates (tuned) | 0.515 | 0.439 |
| Benchmark: CatBoost, 24 candidates | 0.516 | 0.449 |
| Bondora's own PD | 0.414 | 0.405 |

* **Champion v2 vs v1:** v2 beats v1 by +0.021 test and +0.033 out of time (paired bootstrap intervals well above zero). The gain is largest in Finland: out-of-time Gini rises from 0.15 to 0.29.
* **Champion v2 vs Bondora:** out of time, v2 matches Bondora's own model (difference −0.004, interval −0.021 to +0.014). v2 uses no interest rate and no repayment history ([D-012](docs/decision_log.md)).
* **Why v1 lost:** notebook 06 shows the challengers' lead came mostly from finer, jointly fitted feature shapes and from features v1's selection rules had removed. Interactions mattered less. Champion v2 fixes those causes inside a scorecard ([D-029](docs/decision_log.md) corrects the first version of that analysis).
* **Challengers vs Bondora:** all three challengers beat Bondora's model out of time. The glass-box EBM is level with the black boxes on test.
* **Seed stability:** repeating the v1 pipeline with eight random seeds selects the same core features every time ([D-022, D-023](docs/decision_log.md)).
* **Calibration:** out of time, every model predicted about 26% default against 14% observed. Notebook 08 traces this to Bondora's 2020 lending stop in Finland and Spain and moves champion v2's PDs to the post-2020 level with one shift per country (D-030): on April to July 2021 loans, Estonia 10.8% predicted vs 11.4% observed, Finland 8.9% vs 7.8%. Finland's 2019–2020 break coincides with its national consumer-credit interest cap.

## What this project does not do, and why

The work follows Siddiqi (*Intelligent Credit Scoring*), Baesens et al. (*Credit Risk Analytics*) and Provost and Fawcett (*Data Science for Business*). Some of their recommendations are scheduled for later phases: calibration tests by grade, reason codes, cut-off and profit analysis, the PD philosophy choice, and vintage evidence for the 12-month definition. Others are not possible with public Bondora data:

* **No reject inference.** The data hold only funded loans, so the scorecard ranks the population Bondora accepted, not every applicant.
* **No credit bureau detail.** Inquiries, other lenders' trades and their payment history are not published. There is only one bureau grade per country, and the Spanish ones are unusable after 2019.
* **Little customer behaviour.** The data describe loans, not accounts. Customer tenure and time since the last loan are what the loan history allows.
* **No separate country scorecards.** Spain has only one quarter of out-of-time lending, and a separate Finland scorecard did not help; country-specific bins inside one scorecard work better (D-028).
* **No validation on recent applicants.** Application fields stop in July 2021.

Each item, its source and its reason are listed in [decision D-024](docs/decision_log.md).

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
python -m pdengine.train --rebuild-samples          # samples, bins, feature selection, scorecard
pytest --cov=pdengine                               # tests with coverage
```

If `make` is installed (on Windows: `winget install ezwinports.make`), the same steps are `make install`, `make data`, `make warehouse`, `make train` and `make test`. Run `make help` for every target.

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
├── config/
│   └── feature_registry.yaml  class of every Kaggle column; what a model may use
├── data/                raw downloads, Parquet and the DuckDB warehouse (git-ignored)
├── docs/
│   ├── data_card.md     sources, fingerprints, samples, known issues, limitations
│   └── decision_log.md  modelling and engineering decisions, with reasons
├── notebooks/           numbered notebooks that explain each step (01 to 05)
├── reports/             generated model reports and scenario tables (git-ignored)
├── src/pdengine/        the installable package: download, warehouse, registry, features,
│                        history, samples, dataset, selection, scorecard, train
├── tests/               pytest suite (runs offline in CI on tiny fake data)
├── Makefile             pipeline entry points
├── pyproject.toml       package, ruff, pytest and coverage settings
├── requirements.txt     runtime dependencies (pinned)
└── requirements-dev.txt development tools: pytest, ruff, ipykernel, Kaggle CLI
```

## Documentation

- [Data card](docs/data_card.md): sources, fingerprints, target, exclusions, samples, known issues and limitations
- [Decision log](docs/decision_log.md): every key choice, why it was made and what was rejected
- [01 Preliminary EDA](notebooks/01_preliminary_eda.ipynb): what is in the two sources and how they join
- [02 Data audit](notebooks/02_data_audit.ipynb): provenance, quality rules, leakage screen, target reconciliation
- [03 Target and samples](notebooks/03_target_and_samples.ipynb): exclusions waterfall, development and out-of-time samples
- [04 Binning, WoE and IV](notebooks/04_binning_woe_iv.ipynb): bins, within-country checks, stability, feature shortlist
- [05 Champion scorecard](notebooks/05_scorecard.ipynb): fit, points, Gini against Bondora, calibration, robustness to the random split
- [06 Challengers](notebooks/06_challenger.ipynb): LightGBM, CatBoost and an EBM, with the corrected gap decomposition
- [07 Champion v2](notebooks/07_champion_v2.ipynb): the logical dummy scorecard with country-specific bins
- [08 Recalibration](notebooks/08_recalibration.ipynb): the 2020 regime break, one PD shift per country, Jeffreys tests by country and score band

## License

This project is licensed under the MIT License. See `LICENSE` for details. The licence covers the code only, not the Bondora data.
