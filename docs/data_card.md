# Data card: Bondora consumer loans (Track A modelling data)

A short, factual description of the data behind the scorecard: where it comes from, which exact version, what was removed and why, and the known issues. Numbers refer to the snapshot fingerprinted below. Rebuild everything with `make data warehouse train`.

## 1. Sources

| | Kaggle snapshot | Official Bondora / Go & Grow feed |
|---|---|---|
| Role | Borrower features at application | Loan outcomes (target) and current status |
| Origin | [sid321axn/bondora-peer-to-peer-lending-loan-data](https://www.kaggle.com/datasets/sid321axn/bondora-peer-to-peer-lending-loan-data) | [goandgrow.eu public statistics](https://goandgrow.eu/en/public-statistics/), `loan_dataset_investor.xlsx` |
| Retrieved (UTC) | 2026-11-02 15:48 | 2026-11-02 14:15 |
| File | `LoanData_Bondora.csv`, 149,586,306 bytes | `loan_dataset_investor.xlsx`, 175,053,538 bytes |
| SHA-256 | `465abbef…c5c31fa460` | `633e3fa4…b5b92b99` |
| Rows | 179,235 loans | 843,755 loans |
| Period | Loans issued 28 Feb 2009 to 19 Jul 2021; snapshot as of 20 Jul 2021 | Loans issued 28 Feb 2009 to 30 Sep 2026; extracted about 22 Oct 2026 |

Full hashes are in `data/raw/<source>/manifest.json`; the warehouse records them in `_load_log`, and notebook 02 (step 1) checks they match.

**Licence.** Neither source publishes the data under a named open licence. The official file falls under Go & Grow's [Terms of Use](https://goandgrow.eu/en/terms/), and the Kaggle copy is a third-party redistribution. The data are therefore never committed (`data/*` is git-ignored); anyone reproducing the work downloads them with `make data`.

## 2. Join

The two sources are joined on the loan GUID (`LoanId` = `loan_id`, compared in upper case). Every one of the 179,235 Kaggle loans is found in the official feed, and neither source has duplicate IDs (warehouse `_checks`). One loan has a different country in the two sources; it is kept and flagged (D-007).

| Country | Joined loans | 12-month default rate |
|---|---|---|
| Estonia | 110,714 | 15.8% |
| Finland | 41,955 | 33.8% |
| Spain | 26,270 | 55.6% |
| Slovakia | 296 | 70.6% |

## 3. Target

`has_default_within_12_months` from the official feed: 1 if the loan defaulted (about 60 days past due, Bondora's definition) within 12 months of issue (roadmap D2, notebooks 02 and 03).

* **Cross-check.** On 148,783 loans old enough for the Kaggle file to know their 12-month outcome, the official flag and a flag rebuilt from the Kaggle `DefaultDate` agree on **99.69%**. All disagreements are defaults recorded only by the official feed (notebook 02, step 9).
* **Cured defaults** (defaulted in the first year, later repaid) count as bads, because the default happened.
* **`Returned` and `InPostFundingReview` loans** carry a 0 that means "not observed"; they are excluded (D-010). None of them is in the Kaggle join.

## 4. Exclusions and samples

| Step | Removed | Loans left | Default rate | Decision |
|---|---|---|---|---|
| All joined loans | | 179,235 | 25.91% | |
| Returned or InPostFundingReview | 0 | 179,235 | 25.91% | D-010 |
| Repaid early within 14 days (withdrawal) | 2,894 | 176,341 | 26.34% | roadmap |
| Slovakia (flagged, kept) | 0 | 176,341 | 26.34% | D-008 |
| Issued before 2016 (removes all Slovak loans) | 20,616 | 155,725 | 26.12% | roadmap D3, D-013 |
| Missing target | 0 | 155,725 | 26.12% | guard |

| Sample | Issue dates | Loans | Default rate | Estonia / Finland / Spain |
|---|---|---|---|---|
| Train | 2016 to 2019, random 70% | 75,302 | 31.37% | 43,348 / 18,643 / 13,311 |
| Test | 2016 to 2019, random 30% | 32,273 | 31.37% | 18,343 / 8,219 / 5,711 |
| Out-of-time | Jan 2020 to 19 Jul 2021 | 48,150 | 14.38% | 34,888 / 10,266 / 2,996 |

The train/test split is stratified by issue year and target, with seed 42, after sorting the loans by key so the split is reproducible (D-022). Spanish lending stops in March 2020, so Spain's out-of-time sample covers Q1 2020 only.

## 5. Features

The Kaggle file has 112 columns. `config/feature_registry.yaml` gives each one exactly one class, and `pdengine.registry.check_model_columns` refuses anything but candidate, derived or history features in a model matrix.

| Class | Columns | Use |
|---|---|---|
| application | 44 | Known on the application day; 20 remain candidates after D-009, D-012, D-014, D-015 and D-016 |
| leak | 38 | Servicing state on 20 July 2021: never a model input |
| benchmark | 11 | Bondora's own PD, ratings and expected loss: comparison only |
| outcome | 7 | Default and recovery facts: target checks and LGD only |
| protected | 6 | Age, gender, family situation, language (D-016): fairness analysis only |
| personal | 4 | Identify a person: `UserName` is only a join key for history features (D-020) |
| key | 2 | Loan identifiers |

Engineered features: `country_bureau_grade` and `income_vs_country_median` (D-017, `pdengine.features`); `days_since_first_loan` and `days_since_last_loan`, built only from the borrower's earlier loans (D-020, `pdengine.history`).

## 6. Known issues

| Issue | Size | Handling | Reference |
|---|---|---|---|
| Six application fields not collected from 1 June 2017 (`-1` or empty) | 100% of loans from 2018 | Not candidates | D-009 |
| Ten income and affordability fields always `0` from June 2017 | 100% of loans from 2018 | Not candidates | D-015 |
| `ExistingLiabilities` and `LiabilitiesTotal`: never 0 before June 2017, 0 for about 25% after | Definition likely changed | Kept; checked before and after the change | D-015, notebook 04 |
| Spanish bureau scores empty or uninformative out of time | All Spanish out-of-time loans | Not candidates | D-014 |
| Placeholder date 1 January 1970 in four official date columns | 15,379 to 25,216 loans per column | Treat as missing | notebook 02, step 3 |
| `Age` of 0 to 2 | 53 loans | Set to missing (Age is not a model input) | notebook 02, step 2 |
| Total income of 0 | 64 loans | Kept | notebook 02, step 2 |
| Code `0` outside the valid codes | 8 to 32 loans in five fields | Own group in binning | notebook 02, step 6 |
| Joined loan with different country in the two sources | 1 loan | Flagged, Kaggle country used | D-007 |
| Kaggle `Status` describes July 2021, not the outcome | 10,870 "Current" loans later defaulted | Never used as a target | notebook 02, step 7 |
| DuckDB returns rows in no fixed order | Every query | Sort before any seeded operation | D-022 |
| Default rates fell sharply from 2020 (31% in development, 14% out of time) | Whole portfolio | Recalibration before any use of PDs | roadmap D10 |

## 7. Limitations

* **Accepted loans only.** The data contain no rejected applications, so reject inference (Siddiqi, chapter 10) is not possible. The scorecard ranks the population Bondora chose to fund; how it would rank the rejected applicants is unknown.
* **Policy effects.** Bondora rarely lends again to a borrower who defaulted, and the few it did were selected by hand: they default less than average. Such features describe Bondora's policy, not borrower risk, and are not used (D-020).
* **One lender, three countries, a public snapshot.** The data are fit for a portfolio benchmark model, not for real lending decisions.
