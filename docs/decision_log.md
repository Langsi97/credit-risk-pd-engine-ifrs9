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

---

## Template

```
## D-0XX Title

**Context.** What problem or question prompted this.
**Decision.** What was chosen.
**Why.** The evidence or reasoning.
**Rejected.** Alternatives considered and why they lost.
```
