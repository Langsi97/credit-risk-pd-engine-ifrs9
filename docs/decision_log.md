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
| D-013 | 2026-11-04 | Accepted |
| D-014 | 2026-11-04 | Accepted |
| D-015 | 2026-11-09 | Accepted |
| D-016 | 2026-11-09 | Accepted |
| D-017 | 2026-11-09 | Accepted |
| D-018 | 2026-11-09 | Accepted |
| D-019 | 2026-11-09 | Accepted |

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


## D-013 The pre-2016 cut removes every Slovak loan from the Track A samples

**Context.** D-008 keeps Slovak loans in the pooled training data and leaves them out of country-level reporting. The exclusions waterfall in notebook 03 (step 2) shows that all 296 Slovak loans were issued between 13 March 2014 and 5 January 2015, before the development window starts (1 January 2016, roadmap D3).

**Decision.** No change to D-008. The waterfall keeps a Slovakia step that flags the loans and removes none, so the D-008 rule stays visible; the pre-2016 step then removes all 296. The Track A train, test and out-of-time samples contain Estonia, Finland and Spain only, and `Country` has three values in practice.

**Why.** Recording this avoids a reader assuming Slovak loans are in the model because D-008 says "kept in the pool".

**Rejected.** Moving the Slovakia step after the pre-2016 step (it would show 0 Slovak loans and hide where they went). Editing D-008 (decisions are never edited; this note adds the fact).

## D-014 The two Spanish bureau scores are removed from the scorecard candidates

**Context.** D-009 says a feature is a candidate only if it is populated for most loans in both the development and out-of-time windows, and that bureau scores are judged within their own country. Notebook 03 (step 4) checked this on the final samples:

| Score | Spain, development | Spain, out-of-time |
|---|---|---|
| `CreditScoreEsEquifaxRisk` | missing for 57% | missing for 100% |
| `CreditScoreEsMicroL` | real grade (`M1` to `M10`) for 45%, plain `M` for 55% | plain `M` for 100% |

Every Estonian and Finnish loan also carries the plain code `M` in `CreditScoreEsMicroL`. The Estonian (`CreditScoreEeMini`) and Finnish (`CreditScoreFiAsiakasTietoRiskGrade`) scores are filled in for practically every loan of their own country in both windows.

**Decision.** Set `candidate: false` for `CreditScoreEsEquifaxRisk` and `CreditScoreEsMicroL` in `config/feature_registry.yaml`, with the note "D-014: no information for Spanish out-of-time loans". Keep the Estonian and Finnish scores as candidates.

**Why.** Neither Spanish score carries any information for the out-of-time sample, so the model could not use them where it is tested, and their "missing" or `M` group would partly stand for "issued before 2020". Spain stays represented through `Country` and the ordinary application fields.

**Rejected.** Keeping them with a "missing" bin (teaches the issue period, the problem D-009 exists to prevent). Imputing a Spanish score for 2020 loans (nothing to impute from).

**Revisit if.** A newer feature extract has Spanish bureau scores for 2020 loans.


## D-015 Ten income and affordability fields coded 0 after June 2017 are removed from the candidates

**Context.** D-009 removed features that are empty or `-1` in the out-of-time window. Before binning (Phase 3), the candidates were checked for a third way of saying "not collected": the value `0`. From June 2017, when Bondora changed its application form (D-009), ten fields are `0` for every loan, and in the out-of-time sample each has a single value:

| Field | Zero before June 2017 | Zero June 2017 to 2019 | Zero out-of-time |
|---|---|---|---|
| `IncomeFromPrincipalEmployer` | 6.7% | 100% | 100% |
| `IncomeFromPension` | 87.3% | 100% | 100% |
| `IncomeFromFamilyAllowance` | 82.0% | 100% | 100% |
| `IncomeFromSocialWelfare` | 93.5% | 100% | 100% |
| `IncomeFromLeavePay` | 97.7% | 100% | 100% |
| `IncomeFromChildSupport` | 95.4% | 100% | 100% |
| `IncomeOther` | 85.9% | 100% | 100% |
| `DebtToIncome` | 0.0% | 100% | 100% |
| `FreeCash` | 0.0% | 100% | 100% |
| `RefinanceLiabilities` | 78.6% | 100% | 100% |

`IncomeTotal` stays filled in for every loan in every period, so Bondora kept the total and stopped storing the breakdown and the affordability ratios.

**Decision.** Set `candidate: false` for the ten fields, with the note "D-015: always 0 from June 2017". `IncomeTotal`, `ExistingLiabilities` and `LiabilitiesTotal` stay candidates. An affordability ratio can be rebuilt later as a derived feature from candidate inputs (for example instalment or liabilities relative to `IncomeTotal`).

**Why.** Same reasoning as D-009: a field with one value in the out-of-time sample cannot help the model there, and in development its `0` group would mostly mean "issued after June 2017", teaching the model the calendar instead of borrower risk. The audit's missing-value check counted only empty and `-1`, so these zeros passed it.

**Rejected.** Treating `0` as missing and keeping the fields (they would still be missing for every recent loan). Rebuilding `DebtToIncome` from the dropped parts (the parts are gone too).

**Watch.** `ExistingLiabilities` and `LiabilitiesTotal` are never 0 before June 2017 but 0 for about 25% of loans afterwards, so their definition may have changed with the form. They stay in, and notebook 04 checks whether their bins behave the same before and after June 2017.


## D-016 LanguageCode is a protected attribute, not a scorecard candidate

**Context.** `LanguageCode` was an application candidate. In the train sample it almost duplicates `Country` (WoE correlation 0.98): code 1 (Estonian) and 3 (Russian) are used in Estonia, 4 (Finnish) in Finland, 6 (Spanish) in Spain. The only thing it adds beyond country is inside Estonia, where Russian-speaking borrowers default more often than Estonian speakers (23.4% against 17.7%; notebook 04, step 6a).

**Decision.** Reclassify `LanguageCode` as `protected` (`candidate: false`). Use it, like `Age` and `Gender`, only in the Phase 4 fairness analysis.

**Why.** In Estonia, the language a borrower speaks is closely tied to ethnic origin. A scorecard that gives Russian speakers fewer points would price borrowers by ethnicity, which EU non-discrimination law forbids and the EU AI Act treats as a key risk for credit scoring (a high-risk use). Everything legitimate it carries (the country) is already in `country_bureau_grade`.

**Rejected.** Keeping it because it is "known at application" (being known is necessary, not sufficient). Dropping it from the data entirely (it is needed to test whether the final scores still differ by language).

## D-017 Two derived features: country_bureau_grade and income_vs_country_median

**Context.** Two pooled raw features mislead (notebook 04, steps 1 and 5). Each credit-bureau score exists only for its own country, so pooled most of its bins only say "not this country". Raw `IncomeTotal` ranks risk the wrong way (more income, more default: 22% to 37%) because Finnish incomes are about twice Estonian ones and Finland defaults more; inside Estonia and Spain more income means slightly less default (Simpson's paradox).

**Decision.** Add two derived features in `src/pdengine/features.py`, registered under `derived:` in `config/feature_registry.yaml`:

* `country_bureau_grade` (inputs `Country`, `CreditScoreEeMini`, `CreditScoreFiAsiakasTietoRiskGrade`): `EE_<Estonian grade>`, `FI_<Finnish grade>`, or the country code where no bureau score is usable (`ES`, D-014). Train IV 0.57, the strongest feature.
* `income_vs_country_median` (inputs `IncomeTotal`, `Country`): income divided by the train median of the country (Estonia 1,000, Spain 1,350, Finland 2,036). The medians are frozen in the code and checked against the train sample in notebook 04. Train IV 0.022; more income means less default inside every country.

When a derived feature is shortlisted, its raw inputs are not (D-018).

**Why.** One feature then carries the country risk and the bureau grade within each country, without three near-duplicate features in the model (correlations 0.85 to 0.95). Income relative to the country is the version whose direction a credit officer can defend.

**Rejected.** Pooled bureau scores next to `Country` (collinear, and most bins only repeat the country). Raw `IncomeTotal` (wrong direction). Separate scorecards per country (Spain and Finland are too small in the out-of-time sample, and Spain has no out-of-time period after March 2020).

## D-018 Feature selection rules and the scorecard shortlist

**Context.** Notebook 04 bins all 22 features on the train sample (optbinning, at least 5% of loans per bin, monotonic trends for numeric features except application hour and payment day). The out-of-time sample stays blind: only its feature distributions (PSI) are used, never its default outcomes.

**Decision.** A feature enters the shortlist only if it passes, in this order:

1. Train IV at least 0.02 (IV above 0.5 is checked for leakage first).
2. PSI from train to out-of-time at most 0.25.
3. Its pattern holds inside each country: median within-country Spearman correlation between bin WoE and bin default rate of -0.5 or lower (country features exempt).
4. A shortlisted derived feature replaces its raw inputs.
5. From the highest IV down, WoE correlation at most 0.7 with every feature already kept.
6. VIF below 5.

**Result.** Seven features: `country_bureau_grade`, `NoOfPreviousLoansBeforeLoan`, `HomeOwnershipType`, `ExistingLiabilities`, `AppliedAmount`, `Education`, `income_vs_country_median` (VIF 1.03 to 1.87). Dropped: `IncomeTotal` and `MonthlyPaymentDay` (country effect), `VerificationType` (PSI 0.71) and `LoanDuration` (PSI 0.28), four features below IV 0.02, the three inputs of `country_bureau_grade`, and four duplicates (`Amount`, `AmountOfPreviousLoansBeforeLoan`, `NewCreditCustomer`, `LiabilitiesTotal`).

**Why.** Each rule removes a known failure: noise (1), features whose population has moved (2), country effects that look like borrower risk (3), and unstable or unexplainable coefficients from near-duplicates (4 to 6). Keeping the out-of-time outcomes out of selection keeps the out-of-time test independent.

**Rejected.** Choosing features by out-of-time IV (would tune the model to its own test). Automatic selection without the within-country rule (would have kept raw income with the wrong sign and payment day with no meaning).

**Revisit.** `Education` and `income_vs_country_median` (IV about 0.02) stay only if their coefficients have the expected sign and are significant in notebook 05.


## D-019 Champion scorecard: six features, logistic regression on WoE, 600 points at 30:1 and PDO 20

**Context.** Notebook 05 fits a logistic regression of the 12-month default flag on the WoE values of the seven features shortlisted in D-018 (train sample only). The roadmap requires every coefficient to have the expected sign; with WoE positive for safer bins, that sign is negative.

**Decision.**
* Remove `ExistingLiabilities`: its coefficient is +0.06 with p = 0.15 once `NoOfPreviousLoansBeforeLoan` and `HomeOwnershipType` are in the model (WoE correlation 0.62 with the previous-loan count).
* The champion is the refit on six features: `country_bureau_grade`, `NoOfPreviousLoansBeforeLoan`, `HomeOwnershipType`, `AppliedAmount`, `Education`, `income_vs_country_median`. All coefficients are negative with p < 0.001, and a refit on the test sample gives the same signs.
* Points: 600 points at good:bad odds of 30:1, 20 points to double the odds (Siddiqi, chapter 11). The intercept is spread evenly over the features. Train scores run from 484 to 572.
* Saved to `data/processed/scorecard.json` (coefficients, scaling, points table); the bins stay in `binning_process.pkl`.

**Results (for the record, not used to change the model).**

| Sample | Gini (95% bootstrap) | KS | Bondora PD Gini | Mean PD / observed |
|---|---|---|---|---|
| Train | 0.443 | 0.345 | 0.418 | 31.4% / 31.4% |
| Test | 0.440 (0.428 to 0.452) | 0.340 | 0.418 | 31.4% / 31.4% |
| Out-of-time | 0.349 (0.336 to 0.364) | 0.252 | 0.405 | 27.0% / 14.4% |

Paired difference with Bondora's PD: +0.022 on test (0.012 to 0.033), -0.056 out of time (-0.075 to -0.038). The out-of-time drop is mainly the collapse of the country gap (Finland's default rate fell from 42% to 14%); within Estonia the Gini rose from 0.21 to 0.31.

**Why.** A positive coefficient on a WoE feature contradicts the feature's own bins and makes the points unexplainable; the removed feature adds nothing once the others are in. The scaling is the common industry convention and changes no ranking.

**Rejected.** Keeping `ExistingLiabilities` with a wrong-sign weight. Changing features after seeing the out-of-time results (would end the independence of the out-of-time test).

**Open.** The out-of-time PDs are about 1.9 times the observed rate: recalibrate per country before any decision or ECL use (roadmap D10, Phase 4). `Education` has the least stable weight (-0.34 on train, -0.23 on test).

---

## Template

```
## D-0XX Title

**Context.** What problem or question prompted this.
**Decision.** What was chosen.
**Why.** The evidence or reasoning.
**Rejected.** Alternatives considered and why they lost.
```
