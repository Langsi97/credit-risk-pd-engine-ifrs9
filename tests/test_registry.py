"""Tests for pdengine.registry and config/feature_registry.yaml.

These tests are the safety net against data leakage: they fail if the registry file is changed
in a way that would let a post-origination, protected or personal column into a model.
"""

import duckdb
import pytest

from pdengine import registry as rg

DB = rg.PROJECT_ROOT / "data" / "bondora.duckdb"


@pytest.fixture(scope="module")
def reg():
    return rg.load_registry()


# ------------------------------------------------------------------ the real registry file


def test_registry_has_all_112_columns(reg):
    assert len(reg.columns) == 112


def test_only_application_columns_are_candidates(reg):
    for col in reg.columns.values():
        if col.candidate:
            assert col.cls == "application", col.name


@pytest.mark.parametrize(
    "name",
    ["PrincipalBalance", "DefaultDate", "Status", "ProbabilityOfDefault", "Age", "Gender",
     "UserName", "LoanId", "ReportAsOfEOD"],
)  # fmt: skip
def test_known_non_features_are_not_candidates(reg, name):
    assert not reg.columns[name].candidate


@pytest.mark.parametrize(
    "name",
    ["EmploymentStatus", "UseOfLoan", "OccupationArea", "WorkExperience",
     "PreviousRepaymentsBeforeLoan", "PreviousEarlyRepaymentsBefoleLoan"],
)  # fmt: skip
def test_d009_fields_are_excluded(reg, name):
    assert not reg.columns[name].candidate
    assert "D-009" in reg.columns[name].note


@pytest.mark.parametrize("name", ["Interest", "MonthlyPayment"])
def test_d012_price_fields_are_excluded(reg, name):
    assert not reg.columns[name].candidate
    assert "D-012" in reg.columns[name].note


@pytest.mark.parametrize(
    "name",
    [
        "IncomeFromPrincipalEmployer",
        "IncomeFromPension",
        "IncomeFromFamilyAllowance",
        "IncomeFromSocialWelfare",
        "IncomeFromLeavePay",
        "IncomeFromChildSupport",
        "IncomeOther",
        "DebtToIncome",
        "FreeCash",
        "RefinanceLiabilities",
    ],
)
def test_d015_zero_coded_fields_are_excluded(reg, name):
    assert not reg.columns[name].candidate
    assert "D-015" in reg.columns[name].note


def test_d016_language_is_protected(reg):
    col = reg.columns["LanguageCode"]
    assert col.cls == "protected" and not col.candidate
    assert "D-016" in col.note


def test_core_application_features_are_candidates(reg):
    core = ["Amount", "LoanDuration", "IncomeTotal", "ExistingLiabilities", "Country", "Education"]
    for name in core:
        assert reg.columns[name].candidate, name


@pytest.mark.skipif(not DB.exists(), reason="warehouse not built (data are not in the repo)")
def test_registry_matches_the_real_kaggle_file(reg):
    con = duckdb.connect(str(DB), read_only=True)
    try:
        in_file = {r[0] for r in con.execute("DESCRIBE kaggle_loans").fetchall()}
    finally:
        con.close()
    assert set(reg.columns) == in_file


# ------------------------------------------------------------------ the enforcement function


def test_check_model_columns_accepts_candidates(reg):
    rg.check_model_columns(rg.candidate_features(reg), reg)


@pytest.mark.parametrize("name", ["PrincipalBalance", "Age", "Interest", "made_up_column"])
def test_check_model_columns_rejects_non_features(reg, name):
    with pytest.raises(rg.LeakageError, match=name):
        rg.check_model_columns(["Amount", name], reg)


# ------------------------------------------------------------------ validation of bad files


def write(tmp_path, text):
    p = tmp_path / "registry.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_leak_marked_as_candidate_is_rejected(tmp_path):
    p = write(tmp_path, "columns:\n  PrincipalBalance: {class: leak, candidate: true}\n")
    with pytest.raises(rg.RegistryError, match="never be a candidate"):
        rg.load_registry(p)


def test_unknown_class_is_rejected(tmp_path):
    p = write(tmp_path, "columns:\n  Amount: {class: aplication, candidate: true}\n")
    with pytest.raises(rg.RegistryError, match="unknown class"):
        rg.load_registry(p)


def test_derived_feature_from_a_leak_is_rejected(tmp_path):
    p = write(
        tmp_path,
        "columns:\n"
        "  Amount: {class: application, candidate: true}\n"
        "  PrincipalBalance: {class: leak, candidate: false}\n"
        "derived:\n"
        "  balance_ratio: {inputs: [PrincipalBalance, Amount]}\n",
    )
    with pytest.raises(rg.RegistryError, match="non-candidate inputs"):
        rg.load_registry(p)


def test_valid_derived_feature_is_allowed_in_a_model(tmp_path):
    p = write(
        tmp_path,
        "columns:\n"
        "  Amount: {class: application, candidate: true}\n"
        "  IncomeTotal: {class: application, candidate: true}\n"
        "derived:\n"
        "  amount_to_income: {inputs: [Amount, IncomeTotal]}\n",
    )
    reg = rg.load_registry(p)
    rg.check_model_columns(["Amount", "amount_to_income"], reg)
