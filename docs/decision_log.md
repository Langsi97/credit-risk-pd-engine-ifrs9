# Decision log

A running record of the modelling and engineering choices in this project, why they were made, and what was rejected. New decisions go at the bottom. A decision is never edited after the fact: if it changes, add a new entry that supersedes it.

| ID | Date | Status |
|---|---|---|
| D-001 | 2026-11-02 | Accepted |
| D-002 | 2026-11-02 | Accepted |
| D-003 | 2026-11-02 | Accepted |
| D-004 | 2026-11-02 | Proposed |
| D-005 | 2026-11-02 | Accepted |
| D-006 | 2026-11-02 | Accepted |
| D-007 | 2026-11-02 | Accepted |
| D-008 | 2026-11-02 | Accepted |
| D-009 | 2026-11-04 | Accepted |
| D-010 | 2026-11-04 | Accepted |
| D-011 | 2026-11-04 | Accepted |
| D-012 | 2026-11-04 | Accepted |

---

## D-001 Use Bondora loan data instead of Home Credit

**Context.** The original plan named Home Credit Default Risk (Kaggle) as the primary dataset and Lending Club as the alternative. The project goals call for a 12-month PD, an out-of-time test and an IFRS 9 stress test for Spain under the EBA 2025 scenarios.

**Decision.** Use Bondora consumer loans (Estonia, Finland, Spain, Slovakia), combining the Kaggle snapshot (borrower features) with the official Bondora / Go & Grow public feed (repayment outcomes and the current book).

**Why.** Bondora has real issue dates, so an out-of-time split is possible. It covers Spain, so country-level loans can be linked to Spanish macro series for the EBA stress test. Home Credit has no usable dates and no geography. Lending Club is US only.

**Rejected.** Home Credit (no time dimension, no country). Lending Club (wrong geography for an EU IFRS 9 / EBA story).

## D-002 Never commit raw data; download with a script and record a manifest

**Decision.** `data/*` is git-ignored. `pdengine.download_data` fetches each source into `data/raw/<source>/` and writes `manifest.json` with the URL, retrieval time, size and SHA-256 of every file.

**Why.** None of the sources publishes the data under an open licence, so the repository must not redistribute it. The official feed is refreshed monthly, so the SHA-256 fingerprint is the only way to tie a model result to the exact snapshot it was trained on.

## D-003 Split runtime and development dependencies; pin exact versions

**Decision.** `requirements.txt` holds what the pipeline and API need to run. `requirements-dev.txt` adds pytest, pytest-cov, ruff and the Kaggle CLI. All versions are pinned. `pyproject.toml` reads its dependencies from `requirements.txt`, so the pins live in one place.

**Why.** The scoring service should not ship test and lint tools. Pinned versions keep CI and the local venv identical. Kaggle CLI 1.8.4 is pinned because older versions do not support the new KGAT access tokens.

## D-004 Store data as Parquet, query with DuckDB

**Decision (proposed).** Convert raw files once to Parquet in `data/processed/`, then build a local DuckDB file (`data/bondora.duckdb`) for SQL feature aggregation. PostgreSQL stays an option if a shared server is needed later.

**Why.** The official file is a 175 MB Excel workbook that takes minutes to read. Parquet loads in seconds, and DuckDB runs SQL on it with no server and no cost.

**Open.** Confirm once the `warehouse` step is built.

## D-005 Package layout, tooling and CI

**Decision.** Code lives in an installable package `pdengine` under `src/`. Python 3.12. Ruff for linting and formatting (line length 100). Pytest with coverage. CI runs lint and tests on every push to every branch and on every pull request. A Makefile exposes the pipeline: `data`, `warehouse`, `train`, `ecl`, `report`, `serve`.

**Why.** A package makes modules importable from notebooks, tests and the API without path hacks. Running CI on every branch catches problems before a pull request is opened.

## D-006 Branch workflow

**Decision.** Work happens on feature branches (starting with `data-setup`) and reaches `main` only through a pull request with green CI.

**Why.** Keeps `main` always working, and the pull request history documents how the project was built.

## D-007 Joined loans that disagree on country are flagged, not dropped

**Context.** Building the warehouse on the real data found one loan (`F9E26B81-AEE4-442B-B4FC-A87400B4F8E1`) with the same ID, issue date and amount in both sources but a different country: Estonia in the Kaggle snapshot, Finland in the official feed. The preliminary EDA showed this as "100.00% agree" because the share was rounded.

**Decision.** The warehouse build fails only on broken keys (duplicate loan IDs, or Kaggle loans missing from the official feed). Country disagreements are kept, flagged in `loans.country_mismatch`, and counted in the `_checks` table. `country_name` uses the Kaggle country, mapped from its ISO code.

**Why.** One loan out of 179,235 does not justify stopping the pipeline, and dropping it silently would hide a data-quality issue. The Kaggle record describes the borrower at application time, which is the moment the scorecard predicts from.

**Rejected.** Failing the build (too strict for a single corrected record). Using the official country (it may reflect changes after the application).

## D-008 Slovakia is kept in the data but not modelled or reported on its own

**Context.** The README scope listed four countries: Estonia, Finland, Spain and Slovakia. The warehouse shows only 296 Slovak loans in the joined population (0.2% of 179,235), with a 12-month default rate of 70.6%, against 110,714 Estonian, 41,955 Finnish and 26,270 Spanish loans.

**Decision.** Slovak loans stay in the warehouse and in the pooled training data, with country as a candidate feature. Slovakia gets no country-level performance reporting, calibration or stress scenario. The project scope is Estonia, Finland and Spain.

**Why.** 296 loans give an out-of-time sample of a few dozen defaults at best: far too few for a stable Gini, calibration or ECL estimate. Removing them would throw away valid observations for no gain; reporting on them would present noise as a result.

**Rejected.** Dropping Slovak loans entirely (loses data, no benefit). Modelling and reporting Slovakia separately (statistically meaningless at this size).

**Revisit if.** The official feed adds enough Slovak loans with borrower features to support a separate analysis.

## D-009 Only features collected in both the development and out-of-time windows enter the scorecard

**Context.** The data audit (02, section 5) found that Bondora stopped collecting six application fields on 1 June 2017: `EmploymentStatus`, `MaritalStatus`, `UseOfLoan`, `OccupationArea`, `WorkExperience` and `NrOfDependants`. From that date they are `-1` or empty for every loan. `PreviousRepaymentsBeforeLoan` and `PreviousEarlyRepaymentsBefoleLoan` are also empty for half to all loans from 2018. The out-of-time window (2020 to 2021) contains none of the dropped form fields.

**Decision.** A feature is a scorecard candidate only if it is populated for most loans in both the development window and the out-of-time window. The eight fields above are excluded from the candidate list in `config/feature_registry.yaml`. The previous-loan counts (`NoOfPreviousLoansBeforeLoan`, `PreviousEarlyRepaymentsCountBeforeLoan`) and `AmountOfPreviousLoansBeforeLoan` stay in, since they remain populated. Country-specific bureau scores (`CreditScore*`) are judged within their own country, not on the pooled missing rate.

**Why.** A model that relies on a field missing from every recent loan cannot be scored on the out-of-time sample or on new applications, and a "missing" bin that stands for "issued after June 2017" would teach the model the issue period instead of borrower risk.

**Rejected.** Imputing the dropped fields for post-2017 loans (no information to impute from). Restricting development to pre-June 2017 loans to keep the fields (the model could not score any current application).

**Revisit if.** A newer Bondora feature extract brings these fields back.

## D-010 Returned and InPostFundingReview loans are excluded from every modelling sample

**Context.** In the official feed, the 4,241 `Returned` loans and 11 `InPostFundingReview` loans all carry `has_default_within_12_months = 0` and `is_default = NULL` (02, section 8). These loans were cancelled or never funded normally, so the 0 records that nothing was observed, not that the borrower repaid.

**Decision.** Exclude both statuses as the first step of the exclusions waterfall, before the maturity and missing-target filters. Report their count in the waterfall table.

**Why.** Counting them as non-defaults would add goods that never were loans at risk and understate the default rate. Notebook 01's "no missing target among mature loans" counted these loans as non-missing, so the filter has to be explicit.

**Rejected.** Treating the flag value as the outcome (wrong meaning). Excluding on `is_default IS NULL` instead of status (would also drop 3,461 repaid loans with a valid flag).

## D-011 Default month = issue month + months_on_book for defaulted loans

**Context.** `mart_vintage_curves` needs the month in which each loan defaulted. Three official-feed candidates were tested against the Kaggle `DefaultDate` on 23,725 loans defaulted in both sources (02, section 10):

| Candidate | Same month | Within 1 month |
|---|---|---|
| `debt_occured_date_local` | 13.6% | 19.0% |
| feed date − `months_in_default` | 28.7% | 99.9% |
| issue date + `months_on_book` | 64.4% | 99.7% |

**Decision.** For loans with `loan_status = 'Defaulted'`, default month = `date_trunc('month', loan_issued_at) + months_on_book months`.

**Why.** For defaulted loans `months_on_book` stops counting at default, so this candidate is the most often exactly right and does not depend on a reference date. `months_in_default` is as close to within one month, but it counts to an unstated extraction date (around 22 October 2026), so its exact month shifts with whatever date is assumed. `debt_occured_date_local` marks the start of arrears, a median of 78 days before default; the data dictionary calls it dynamic, and 15,379 loans carry a `1970-01-01` placeholder.

**Rejected.** `debt_occured_date_local` (wrong event, dynamic, placeholders). `months_in_default` (depends on an undocumented reference date).

**Revisit if.** Bondora publishes an explicit default date in the official feed.

## D-012 Interest and MonthlyPayment are excluded from the champion scorecard and tested in a sensitivity run

**Context.** The leakage check (02, section 4.1) flagged `Interest` as the only application column with a single-column AUC above 0.70 (0.711). It is known at application, so it is not a leak. But Bondora sets the rate from its own risk rating, so `Interest` carries Bondora's view of the borrower. The project benchmarks its scorecard against Bondora's own `ProbabilityOfDefault`.

**Decision.** The champion scorecard is built without `Interest` and without `MonthlyPayment`, which is derived from the rate, amount and term. `Amount` and `LoanDuration` stay candidates, so loan size and term are still covered. A sensitivity version adds `Interest` and `MonthlyPayment` back, and both versions are reported against the Bondora benchmark.

**Why.** With `Interest` in, the "our scorecard vs Bondora" comparison is partly circular: part of our model's ranking power would be Bondora's model. `MonthlyPayment` carries the same pricing signal through the rate. Leaving both out keeps the champion a pure applicant-risk model, and the sensitivity run shows how much the price adds.

**Rejected.** Keeping `Interest` in the champion without comment (benchmark not independent). Dropping it with no sensitivity run (hides how much predictive power it holds). Keeping `MonthlyPayment` (it would bring the rate back in indirectly).

---

## Template

```
## D-0XX Title

**Context.** What problem or question prompted this.
**Decision.** What was chosen.
**Why.** The evidence or reasoning.
**Rejected.** Alternatives considered and why they lost.
```
