import numpy as np
import pandas as pd
import pytest

from pdengine.history import FEATURES, history_features
from pdengine.registry import RegistryError, check_model_columns, load_registry


def _loans():
    return pd.DataFrame(
        {
            "LoanId": ["a1", "a2", "a3", "a4", "b1"],
            "UserName": ["ann", "ann", "ann", "ann", "bob"],
            "LoanDate": ["2018-01-01", "2018-03-02", "2018-03-02", "2019-01-01", "2018-05-05"],
        }
    )


def test_values():
    h = history_features(_loans())
    assert np.isnan(h.loc["a1", "days_since_first_loan"])  # first loan: no history
    assert h.loc["a2", "days_since_first_loan"] == 60
    assert h.loc["a2", "days_since_last_loan"] == 60
    assert h.loc["a4", "days_since_first_loan"] == 365
    assert h.loc["a4", "days_since_last_loan"] == 305
    assert h.loc["b1"].isna().all()


def test_same_day_loans_are_not_earlier():
    h = history_features(_loans())
    assert h.loc["a2"].equals(h.loc["a3"])


def test_a_loan_never_sees_later_loans():
    # Adding a later loan must not change the history of any earlier loan.
    before = history_features(_loans())
    later = pd.DataFrame({"LoanId": ["a5"], "UserName": ["ann"], "LoanDate": ["2020-06-01"]})
    after = history_features(pd.concat([_loans(), later], ignore_index=True))
    pd.testing.assert_frame_equal(after.loc[before.index], before)


def test_borrower_key_is_not_returned():
    h = history_features(_loans())
    assert list(h.columns) == list(FEATURES)
    assert "UserName" not in h.columns


def test_history_features_are_registered_and_allowed():
    reg = load_registry()
    assert set(reg.history) == set(FEATURES)
    check_model_columns(list(FEATURES), reg)


def test_history_key_cannot_be_an_application_column(tmp_path):
    p = tmp_path / "reg.yaml"
    p.write_text(
        "columns:\n"
        "  Amount: {class: application, candidate: true}\n"
        "  LoanDate: {class: application, candidate: false}\n"
        "history:\n"
        "  tenure: {key: Amount, date: LoanDate}\n",
        encoding="utf-8",
    )
    with pytest.raises(RegistryError):
        load_registry(p)
