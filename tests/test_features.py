import numpy as np
import pandas as pd

from pdengine.features import (
    DERIVED,
    TRAIN_MEDIAN_INCOME,
    add_derived,
    country_bureau_grade,
    income_vs_country_median,
)
from pdengine.registry import load_registry


def _loans():
    return pd.DataFrame(
        {
            "Country": ["EE", "EE", "FI", "FI", "ES", "SK"],
            "CreditScoreEeMini": [1000.0, np.nan, np.nan, np.nan, np.nan, np.nan],
            "CreditScoreFiAsiakasTietoRiskGrade": [None, None, "3", "RL2", None, None],
            "IncomeTotal": [1000.0, 500.0, 2036.0, 4072.0, 675.0, 900.0],
        },
        index=["a", "b", "c", "d", "e", "f"],
    )


def test_country_bureau_grade_values():
    got = country_bureau_grade(_loans()).tolist()
    assert got == ["EE_1000", "EE_missing", "FI_3", "FI_RL2", "ES", "SK"]


def test_country_bureau_grade_keeps_the_index():
    loans = _loans()
    assert country_bureau_grade(loans).index.equals(loans.index)


def test_income_vs_country_median():
    got = income_vs_country_median(_loans())
    assert got.iloc[:5].tolist() == [1.0, 0.5, 1.0, 2.0, 0.5]
    assert np.isnan(got.iloc[5])  # Slovakia: no train median


def test_train_medians_cover_the_model_countries():
    assert set(TRAIN_MEDIAN_INCOME) == {"EE", "ES", "FI"}


def test_add_derived_adds_columns_without_changing_input():
    loans = _loans()
    out = add_derived(loans)
    assert set(DERIVED) <= set(out.columns)
    assert not set(DERIVED) & set(loans.columns)


def test_every_derived_feature_is_registered():
    # A function here without a registry entry would fail check_model_columns, and the
    # registry entry is what proves its inputs are candidates.
    assert set(DERIVED) == set(load_registry().derived)
