"""Every modelling rule of Track A in one place, with the decision that set it.

The notebooks explain these choices; the pipeline (`python -m pdengine.train`) applies them.
Changing a value here changes the model: record the reason in docs/decision_log.md.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/pdengine/ -> repo root
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "bondora.duckdb"
PROCESSED = DATA_DIR / "processed"

# ---------------------------------------------------------------- samples (notebook 03)
DEV_START = "2016-01-01"  # roadmap D3: earlier vintages are a different product era
OOT_START = "2020-01-01"  # out-of-time window: Jan 2020 to the Kaggle snapshot (Jul 2021)
OOT_END = "2021-07-21"  # exclusive upper bound
TEST_SHARE = 0.30  # development split 70/30, stratified by issue year and target
SEED = 42

# ---------------------------------------------------------------- binning (notebook 04)
MIN_BIN_SIZE = 0.05  # at least 5% of train loans per bin
# Codes stored as numbers that are really categories (a code 4 is not "twice" a code 2).
CATEGORICAL = [
    "VerificationType",
    "Country",
    "Education",
    "EmploymentDurationCurrentEmployer",
    "HomeOwnershipType",
    "ApplicationSignedWeekday",
    "CreditScoreFiAsiakasTietoRiskGrade",
    "country_bureau_grade",
]
# No economic reason for a one-direction trend: allow one peak or valley.
NON_MONOTONIC = ["ApplicationSignedHour", "MonthlyPaymentDay"]
# Manual groupings (Siddiqi, ch. 10: overrides are allowed when documented). D-023:
# the automatic bins put secondary education (code 4) above higher education (5), which gave
# a degree fewer points. Education codes: 1 primary, 2 basic, 3 vocational, 4 secondary,
# 5 higher, -1/0 unknown.
MANUAL_GROUPS = {"Education": [["4", "5"], ["2", "3"], ["1", "-1", "0"]]}
# Ordered features whose points must never fall as the category rises (D-023).
LOGICAL_ORDER = {"Education": ["1", "2", "3", "4", "5"]}

# ---------------------------------------------------------------- selection rules (D-018)
MIN_IV = 0.02
MAX_PSI = 0.25
MAX_WITHIN_COUNTRY_RHO = -0.5  # median Spearman(WoE, within-country default rate)
MIN_LOANS_PER_COUNTRY_BIN = 100
MAX_CORRELATION = 0.7
MAX_VIF = 5.0
# Features that measure country itself are exempt from the within-country check.
COUNTRY_FEATURES = [
    "Country",
    "CreditScoreEeMini",
    "CreditScoreFiAsiakasTietoRiskGrade",
    "country_bureau_grade",
]

# ---------------------------------------------------------------- scorecard (D-021)
MAX_P_VALUE = 0.05
BASE_SCORE, BASE_ODDS, PDO = 600, 30, 20  # 600 points = good:bad odds 30:1, 20 points to double

# ---------------------------------------------------------------- champion v2 (notebook 07, D-028)
# A dummy-coded logistic scorecard: one coefficient per bin, constrained so the points follow
# the risk order of the bins (logical by construction). It uses every feature that passes the
# stability and logic screens (no IV, correlation or VIF rule: those protect a one-coefficient
# WoE model; the joint, penalised and constrained fit handles overlap itself).
V2_MIN_BIN_SIZE = 0.02  # finer bins than v1: at least 2% of train loans per bin
V2_MIN_PREBIN_SIZE = 0.01  # optbinning's default pre-bins (5%, at most 20) cap the resolution
V2_MAX_N_PREBINS = 100
# Interaction characteristics (Siddiqi): these features are binned inside each country,
# because loan size and borrowing history mean different things in Estonia, Finland and Spain.
CROSS_FEATURES = {
    "AppliedAmount": "auto_asc_desc",
    "days_since_last_loan": "descending",
    "days_since_first_loan": "descending",
}
CROSS_COUNTRIES = ["EE", "FI", "ES"]
CROSS_MIN_BIN_SIZE = 0.05  # share of the country's train loans
CROSS_MIN_PREBIN_SIZE = 0.02
CROSS_MAX_N_PREBINS = 50
L2_PENALTY = 1e-4  # ridge penalty on the bin coefficients (per loan, mean log-loss scale)

# ---------------------------------------------------------------- challengers (notebook 06, D-029)
# Monotone constraints kept only where economics fixes the direction AND the train data agree.
# Dropped (D-029): AppliedAmount/Amount (risk is not monotone in loan size and differs by
# country), days_since_last_loan (risk rises again after long gaps), the liabilities fields.
MONOTONE = {
    "days_since_first_loan": -1,
    "NoOfPreviousLoansBeforeLoan": -1,
    "AmountOfPreviousLoansBeforeLoan": -1,
    "NewCreditCustomer": 1,
    "income_vs_country_median": -1,
}

# --------------------------------------------------------- recalibration (notebook 08, D-030)
# Bondora stopped lending in Finland and Spain at the start of the pandemic and restarted in
# Finland at the end of 2020. Default rates fell from about 24% (2020 Q1) to about 10%, so the
# development PDs are far too high out of time. One logit shift per country moves them to the
# post-break level (calibration-in-the-large); ranking, points and reason codes do not change.
RECAL_START = "2020-04-01"  # first full quarter after the break
RECAL_VALIDATE_END = "2021-04-01"  # notebook 08: fit before this date, test on the rest of OOT
RECAL_WINDOW = (RECAL_START, OOT_END)  # final shift: every post-break loan (make train)
RECAL_MIN_LOANS = 500  # fewer post-break loans: no shift, flagged (Spain)
JEFFREYS_ALPHA = 0.05  # ECB (2019) one-sided Jeffreys test of PD underestimation
# D-030a: closed testing (Vergouwe et al., 2017). A per-country slope on the logit is added to the
# shift only when a likelihood-ratio test asks for it at this level.
RECAL_SLOPE_ALPHA = 0.05
