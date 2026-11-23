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
