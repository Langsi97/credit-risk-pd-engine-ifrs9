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
| D-019 | 2026-11-09 | Superseded by D-021 |
| D-020 | 2026-11-23 | Accepted |
| D-021 | 2026-11-23 | Accepted |
| D-022 | 2026-11-23 | Accepted |
| D-023 | 2026-11-23 | Accepted |
| D-024 | 2026-11-23 | Accepted |
| D-025 | 2026-11-23 | Accepted |
| D-026 | 2026-11-23 | Accepted |

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


## D-020 History features: customer tenure and recency, rebuilt as of the application date

**Context.** A review of phases 1 to 3 against Siddiqi (Appendix A, "time as customer"; chapter 6 on tenure-based segments) and Baesens et al. (chapter 5, behavioural variables) asked what a lender knows about its own repeat customers. The Kaggle file links a borrower's loans through `UserName` (registry class `personal`). Counting a borrower's earlier loans this way reproduces Bondora's `NoOfPreviousLoansBeforeLoan` for 99.9% of loans, so the link is reliable. This review came after notebook 05 had shown the first out-of-time result (D-019). The new features were chosen on the train and test samples only.

**Decision.**
* Add `src/pdengine/history.py`, which computes for every loan, from the same borrower's loans issued **strictly before** its date:
  * `days_since_first_loan` (tenure) and
  * `days_since_last_loan` (recency).

  Both are empty for a first loan. The history is computed over all 179,235 Kaggle loans.
* Add a `history:` section to `config/feature_registry.yaml`. `pdengine.registry` accepts a history feature only if its key is a `key` or `personal` column and its date is an `application` column, and `check_model_columns` allows it. The key itself never enters a model and is not returned by the function.
* Unit tests check the values, that same-day loans do not count as earlier, that adding a later loan never changes an earlier loan's history, and that the key is not in the output.

**Evidence.** Tenure has IV 0.27 (test 0.25) and recency 0.19. Both are monotone inside every country (median within-country correlation -0.83 and -0.88) and stable out of time (PSI 0.01 and 0.03).

**Rejected (tested on the train and test samples).**
* Prior defaults with Bondora: only 560 of 75,302 train loans have one, and they default *less* than average, because Bondora rarely re-lends after a default and hand-picks the exceptions (Siddiqi's cherry-picking example, chapter 10).
* Affordability ratios (liabilities, amount or monthly principal over income): IV 0.005 to 0.04.
* Active previous loans: wrong sign once tenure is in.
* Loan step-up (amount vs the average previous loan): repeats the previous-loan count (correlation 0.83).
* A separate scorecard for new and repeat customers: +0.0025 Gini on test, not worth a second model (Siddiqi chapter 6).

## D-021 Champion scorecard, version 2 (supersedes D-019)

**Context.** Notebooks 04 and 05 were re-run with the D-020 history features, under the unchanged D-018 rules. Tenure replaces `NoOfPreviousLoansBeforeLoan` (correlation 0.73, higher IV), and the shortlist has nine features.

**Decision.**
* The sign-and-significance check is now a loop. Remove the wrong-sign feature with the highest p-value first, then any non-significant one, refitting each time. It removed `ExistingLiabilities` (+0.07, p 0.06), then `AmountOfPreviousLoansBeforeLoan` (+0.24).
* The champion has seven features: `country_bureau_grade`, `days_since_first_loan`, `days_since_last_loan`, `HomeOwnershipType`, `AppliedAmount`, `Education`, `income_vs_country_median`. All coefficients are negative with p ≤ 0.0001, and a refit on the test sample gives the same signs.
* Scaling is unchanged: 600 points at 30:1, PDO 20. Train scores run from 483 to 588. 38 bins.

**Results.**

| Sample | Gini v2 (95% bootstrap) | Gini v1 (D-019) | Bondora PD | Paired difference v2 vs Bondora |
|---|---|---|---|---|
| Test | 0.454 (0.442 to 0.466) | 0.440 | 0.418 | +0.036 (0.025 to 0.047) |
| Out-of-time | 0.356 (0.342 to 0.371) | 0.349 | 0.405 | -0.049 (-0.068 to -0.032) |

Calibration: exact in-time; out of time the PD averages 26.8% against 14.4% observed (ratio 1.86).

**Why.** The history features carry what a lender knows about a repeat customer and hold in every country. Version 1 stays in the log so the change after the first out-of-time read is visible.

**Open.** Recalibration per country before any use (roadmap D10, Phase 4). The out-of-time gap to Bondora remains; Bondora has repayment behaviour and bureau data that this project cannot use.


## D-022 Reproducible sample split, Track A pipeline in src/pdengine, and results over seeds

**Context.** Moving notebooks 03 to 05 into the package (`python -m pdengine.train`) showed that the pipeline gave different samples from notebook 03, although the code was the same. The cause: DuckDB returns rows in a different order on every run (it reads in parallel), and a seeded random split is only reproducible if its input order is fixed. Of 155,725 loans, about 150,000 changed position between two identical queries. The saved samples were consistent across notebooks 04 and 05, but re-running notebook 03 would have produced a different split.

**Decision.**
* Sort the loans by `loan_key` before the train/test split (`pdengine.samples.assign_samples` and notebook 03). A test checks that shuffling the input never changes the split.
* The Track A pipeline lives in `src/pdengine`:
  * `settings` (every rule and threshold, with its decision),
  * `samples` (waterfall and split),
  * `dataset` (model matrix and column types),
  * `selection` (bins and D-018 rules),
  * `scorecard` (fit with the sign loop, points, JSON),
  * `train` (end to end).

  `make samples` and `make train` run it. The notebooks keep the explanations, and each checks that the pipeline reproduces its result (notebook 03: same samples; notebook 05: same scorecard).
* The samples were rebuilt with the fixed order and notebooks 03 to 05 re-run. The frozen Finnish median income for `income_vs_country_median` (D-017) changes from 2,036 to 2,068 euros, the median of the new train sample; notebook 04's guard caught the difference.
* Report the out-of-time Gini as a range over seeds next to the seed-42 value.
* Pin `scipy==1.15.3`: statsmodels 0.14.4 fails to import with scipy 1.16 or later.

**Results (seed 42, reproducible).** The same seven champion features as D-021.

| Sample | Gini (95% bootstrap) | Bondora PD | Paired difference |
|---|---|---|---|
| Test | 0.461 (0.449 to 0.472) | 0.414 | +0.046 (0.035 to 0.056) |
| Out-of-time | 0.367 (0.353 to 0.381) | 0.405 | -0.038 (-0.056 to -0.020) |

Across eight seeds (42, 1 to 7), the whole pipeline chose the same seven features every time. Test Gini ranged from 0.447 to 0.463, out-of-time Gini from 0.357 to 0.367 (mean 0.363), and the scorecard beat Bondora's PD on test with every seed. The earlier 0.356 (D-021) was one draw within that range. Out-of-time calibration ratio: 1.88.

**Why.** A model result that cannot be reproduced cannot be validated. One number from one random draw can mislead; the range shows how much is the draw.

**Rejected.** Keeping the old saved samples as the "official" ones (they cannot be rebuilt). Hash-based splitting on the loan key (also reproducible, but changes the sampling method rather than fixing the order).


## D-023 Logical points for Education, a baseline comparison, and a test of indeterminate loans

**Context.** A second review against the textbooks (Siddiqi, *Intelligent Credit Scoring*; Baesens et al., *Credit Risk Analytics*; Provost and Fawcett, *Data Science for Business*) found three things the scorecard did not yet do.

**Decision.**
1. **Logical points (Siddiqi, ch. 10, "Points allocation").** The automatic bins ranked secondary education (code 4) above higher education (5), giving a degree fewer points (76 against 74). Education is now grouped by hand, in a logical order: secondary or higher (4, 5), basic or vocational (2, 3), primary or unknown (1, -1, 0), in `pdengine.settings.MANUAL_GROUPS`. `pdengine.scorecard.check_logical_points` makes the pipeline fail if an ordered feature (`settings.LOGICAL_ORDER`) ever gives fewer points to a higher category. With the logical grouping, Education's IV is 0.019, below the 0.02 minimum, so it leaves the shortlist. The champion has six features: `country_bureau_grade`, `days_since_first_loan`, `days_since_last_loan`, `HomeOwnershipType`, `AppliedAmount`, `income_vs_country_median`.
2. **Baseline (Provost and Fawcett, ch. 7).** Notebook 05 now compares the scorecard with simple baselines on the same loans:

   | Model | Test Gini | Out-of-time Gini |
   |---|---|---|
   | Country alone | 0.377 | 0.220 |
   | Country and bureau grade | 0.409 | 0.293 |
   | Champion scorecard | 0.459 | 0.368 |
   | Bondora PD | 0.414 | 0.405 |

3. **Indeterminates (Siddiqi, ch. 6).** Loans fully repaid within their first 12 months (8,099 train loans, 11%, default rate about 0.1%) are counted as goods. Refitting without them changes the Gini by less than 0.002 on test and out of time, so the target stays as it is. They stay in for calibration, because they are real non-defaults.

The pipeline metrics now include the Brier score: 0.185 on test (Bondora 0.193), 0.137 out of time (Bondora 0.116, because its PD level is closer).

**Results (seed 42).**
* Test Gini 0.459 (0.448 to 0.471), paired difference with Bondora +0.045.
* Out-of-time Gini 0.368 (0.353 to 0.382), paired difference -0.037.

Over eight seeds, the six core features are chosen every time. Education also enters with two seeds, because its IV is 0.018 to 0.020, right on the cut-off. Out-of-time Gini ranges from 0.358 to 0.368.

**Why.** Illogical points would fail a model review. Without a baseline, a Gini says nothing about what the model adds beyond the country. The indeterminate test shows the target choice does not drive the result.

**Rejected.**
* Keeping Education with its reversal (unexplainable points).
* Forcing Education in despite its IV below 0.02 (the rule applies to every feature).
* Excluding the indeterminates from the target (no effect on ranking, and it would bias calibration).

## D-024 Textbook practices not applied yet, or not possible with this data

**Context.** The same review listed every practice the three books recommend for a scorecard and PD model. This entry records the ones the project has not applied, and why, so a reviewer can see they were considered rather than missed.

**Deferred to a later phase (possible with this data).**

| Practice | Source | Phase | Why later |
|---|---|---|---|
| Calibration tests: Hosmer-Lemeshow, binomial test per grade, traffic-light summary | Baesens ch. 13 | 4 | They test PD levels by grade; the grades only exist after recalibration. The out-of-time PDs are currently 1.9 times too high, so testing them now would only confirm that. |
| Point-in-time vs through-the-cycle PD philosophy | Baesens | 4 | Decided at recalibration. IFRS 9 needs point-in-time, forward-looking PDs. |
| Reason codes from the neutral score | Siddiqi ch. 10 | 4 | Delivered with the risk grades and the API, alongside SHAP for the challenger. |
| Cut-off table and profit curve (approval rate, bad rate, expected profit) | Siddiqi ch. 11; Provost and Fawcett ch. 7-8 | 4 | Needs calibrated PDs and a stated LGD. |
| Several candidate scorecards compared, including the D-012 sensitivity run with `Interest` | Siddiqi ch. 10 | 3 (challenger notebook) | Compared together with the LightGBM challenger on the same samples. |
| Learning curve and fitting graph | Provost and Fawcett ch. 5 | 3 (challenger notebook) | Most informative for the challenger, whose complexity can vary. |
| Justify the 12-month default definition with vintage or roll-rate evidence | Siddiqi ch. 6 | 5 | Uses the vintage curves built for the lifetime PD (D-011). |
| Staging layer that turns 1970 placeholder dates into missing values | Notebook 02, step 3 | 5 | Those dates are first used in the vintage and LGD work; no Track A feature uses them. |
| Scorecard characteristic analysis (score shift caused by each feature's population shift) | Siddiqi ch. 14 | 6 | A monitoring report; the PSI of every feature is already reported (notebook 04). |

**Not possible with this data.**

| Practice | Source | Why not |
|---|---|---|
| Reject inference | Siddiqi ch. 10 | The data contain only funded loans, no rejected applications. The scorecard ranks the population Bondora accepted. |
| Credit bureau variables (inquiries, trades, delinquency at other lenders) | Siddiqi App. A | Not in the public data; only a single bureau grade per country is available, and the Spanish ones are unusable out of time (D-014). |
| Internal behaviour beyond the loan history (balances, payments, other products) | Siddiqi App. A; Baesens ch. 5 | Bondora's public data describe loans, not customers' accounts. Tenure and recency are what the data allow (D-020). |
| Override and policy-rule analysis | Siddiqi ch. 10-11 | No record of manual decisions or policy rules. |
| Separate scorecards by country | Siddiqi ch. 6 | Spain has only one quarter of out-of-time lending (2,996 loans). A new-versus-repeat customer segmentation was tested instead and added 0.0025 Gini (D-020). |
| Pre-implementation validation on recent applicants with the full feature set | Siddiqi ch. 11 | Kaggle features stop in July 2021. Later loans exist only in the official feed, without application fields; the roadmap's core score is the partial answer. |
| Previous-default features | Siddiqi App. A | Possible to build, but biased: Bondora rarely re-lends after a default, and the few exceptions default less than average (D-020). |

**Why.** Recording what was not done, and why, is part of model documentation: it separates a considered limitation from an oversight.


## D-025 Pin cvxpy 1.6.7 and osqp 0.6.7 so the tests run on Windows

**Context.** On Windows, `pytest` crashed with an access violation while importing `optbinning`. The chain is `optbinning` -> `ropwr` -> `cvxpy` -> `osqp`. `osqp` 1.x, which `cvxpy` 1.7 and later require, probes an optional Intel MKL backend (`osqp.ext_mkl`) when it is imported, and that probe crashed the process. A plain `python -c "import optbinning"` worked, so the crash depends on what is already loaded in the process. CI on Linux was not affected.

**Decision.** Pin `cvxpy==1.6.7` and `osqp==0.6.7.post3` in `requirements.txt`. `osqp` 0.6.7 is a single compiled module with no backend probe, and `cvxpy` 1.6.7 is the last series that accepts it. The project uses neither library directly; `optbinning` bins with OR-Tools.

**Evidence.** A clean environment with every pinned requirement passes `pip check`, imports all libraries with the crash handler on, and passes the full test suite (89 tests).

**Rejected.** Changing the import order (fragile, and the cause is inside `osqp`). Removing `osqp` (`cvxpy` declares it as a dependency).


## D-026 Load the solver libraries before pandas so tests and training run on Windows

**Context.** With the D-025 pins installed, `pytest` still crashed on Windows, now when `osqp` loaded its compiled module. The real cause is the Microsoft C++ runtime. Several packages ship their own `msvcp140.dll`: pyarrow's is version 14.28, while numpy, scikit-learn and highspy ship 14.40. pandas imports pyarrow on import, and whichever copy loads first is used by every later compiled library in the process. When pandas loaded first, `cvxpy`'s compiled core and `osqp` crashed with an access violation. A plain `import cvxpy, optbinning` worked because it loaded the solvers before pandas.

**Decision.**
* `tests/conftest.py` imports `cvxpy` and `optbinning` before any test module.
* `pdengine/train.py` imports `cvxpy` before `duckdb` and pandas.
* The D-025 pins stay: `osqp` 0.6.7 also avoids its MKL probe.

**Evidence.** On Windows, the full suite passes after the change (89 tests).

**Rejected.** Deleting or replacing bundled DLLs (breaks the packages and comes back with every install). Upgrading pyarrow (not pinned directly; its runtime version is outside the project's control).

**Watch.** Notebooks 04 and 05 import pandas before `optbinning` and run without problems in VS Code, so the crash depends on what else the process has loaded. If a new script or notebook crashes the same way on Windows, import `cvxpy` first.

---

## Template

```
## D-0XX Title

**Context.** What problem or question prompted this.
**Decision.** What was chosen.
**Why.** The evidence or reasoning.
**Rejected.** Alternatives considered and why they lost.
```
