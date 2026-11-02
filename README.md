# Credit Risk PD Engine IFRS 9

## Business problem

This project develops a credit risk scorecard and probability of default (PD) engine for European consumer loans, with an explicit focus on IFRS 9 expected credit loss (ECL) estimation. The analysis targets retail lending portfolios from Bondora across Estonia, Finland, Spain, and Slovakia, with a primary objective of translating borrower risk into transparent, explainable score grades and portfolio-level ECL metrics.

The work is structured around three linked objectives:

1. Estimate a 12-month PD for individual borrowers using a transparent, auditable risk model.
2. Convert model output into a scorecard framework with clear grade segmentation and calibration by risk band.
3. Translate PD and exposure estimates into IFRS 9 ECL under baseline, adverse, and severe macroeconomic scenarios, with Spain explicitly stress-tested against the EBA 2025 regulatory baseline and adverse conditions.

## Scope

- Portfolio: European consumer loans from Bondora
- Geography: Estonia, Finland, Spain, Slovakia
- Horizon: 12-month PD estimation
- Regulatory lens: IFRS 9 and EBA macro scenario overlays
- Deliverable: risk scorecard, calibrated PD by grade, and ECL outputs for scenario analysis

## Data and modeling approach

The repository is designed to support a reproducible workflow for:

- data ingestion and validation
- feature engineering and preprocessing
- segmentation and binning for scorecard development
- model training and performance benchmarking
- calibration and PD grading
- IFRS 9 ECL scenario analysis
- report generation for internal and regulatory use

## Success criteria

The project is considered successful when the following outcomes are met:

- Out-of-time (OOT) Gini coefficient of at least 0.35 on the holdout portfolio
- PD is calibrated and monotonic across borrower risk grades
- Score grades provide stable, interpretable rating bands for decision support and monitoring
- ECL estimates are produced for baseline, adverse, and severe scenarios
- Spain stress scenarios are explicitly modeled under the official EBA 2025 baseline and adverse assumptions
- Documentation and reports clearly show assumptions, calibration logic, and scenario outputs

## Expected deliverables

- model training notebook(s) and validation workflow
- reusable Python source package for data processing and scoring
- test suite covering validation and core logic
- scenario-based ECL outputs in the `reports/` directory

## Data source

The model is built on Bondora's public loan-level dataset: every loan issued on the Bondora platform since February 2009, with borrower demographics, loan terms, credit ratings and repayment status. Bondora's investor product has since been rebranded Go & Grow, and the public statistics page moved with it.

| Source | Link | Coverage | Access |
|---|---|---|---|
| Official (default) | [Go & Grow public statistics](https://goandgrow.eu/en/public-statistics/), file `loan_dataset_investor.xlsx` | 2009 to last month, refreshed by Bondora | Direct download |
| Kaggle snapshot | [sid321axn/bondora-peer-to-peer-lending-loan-data](https://www.kaggle.com/datasets/sid321axn/bondora-peer-to-peer-lending-loan-data) | 2009 to mid-2021 | Kaggle account and API token |
| IEEE DataPort snapshot | [Bondora Peer-to-Peer Lending Data](https://ieee-dataport.org/open-access/bondora-peer-peer-lending-data), DOI [10.21227/33kz-0s65](https://doi.org/10.21227/33kz-0s65) | 2009-03-01 to 2020-01-27 | Free IEEE account login |

Download with:

```bash
python src/download_data.py                      # official source
python src/download_data.py --source kaggle      # needs: pip install kaggle + ~/.kaggle/kaggle.json
python src/download_data.py --source ieee --file path/to/Bondora_dataset.zip
```

Files land in `data/raw/<source>/` with a `manifest.json` recording the URL, retrieval time, size and SHA-256 of each file, so every model run can be traced to the exact snapshot used. For a reproducible out-of-time split, record the manifest hash in the model report rather than relying on "latest".

**Licence and terms.** None of the three sources publishes the data under a named open licence. The official file is provided by Bondora / Go & Grow under its general [Terms of Use](https://goandgrow.eu/en/terms/); the Kaggle and IEEE DataPort copies are third-party redistributions of the same Bondora data and state no licence of their own. This repository therefore never redistributes the data: `data/*` is git-ignored, and anyone reproducing the work downloads it from the source. The MIT licence of this repository covers the code only, not the data.

## Repository structure

- `data/` — local datasets and raw inputs (ignored by Git)
- `notebooks/` — exploratory analysis, model development, and validation notebooks
- `src/` — source code for modeling, feature engineering, and scoring logic
- `tests/` — unit and integration tests
- `reports/` — generated outputs such as model summaries, validation reports, and dashboards
- `.github/workflows/` — CI/CD automation

## Getting started

1. Create and activate a virtual environment.
2. Install project dependencies from `requirements.txt`.
3. Add raw or processed datasets under `data/`.
4. Develop exploratory notebooks in `notebooks/`.
5. Implement reusable logic under `src/`.
6. Validate behavior with tests in `tests/`.
7. Save model outputs to `reports/`.

## License

This project is licensed under the MIT License. See `LICENSE` for details.
