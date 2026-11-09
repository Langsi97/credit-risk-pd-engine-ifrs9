"""Engineered features: computed only from candidate columns in the feature registry.

Every function here builds one feature listed under `derived:` in config/feature_registry.yaml.
The registry checks that its inputs are candidates, so a leak cannot enter through a derived
feature. The same functions are used for training, testing and (later) the scoring API, so a
feature is always computed the same way.

Usage
-----
    from pdengine.features import add_derived

    df = add_derived(df)   # adds every derived feature as a new column
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _code(value) -> str:
    """Bureau code as text: 1000.0 -> '1000', '3' -> '3', empty -> 'missing'."""
    if pd.isna(value):
        return "missing"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def country_bureau_grade(df: pd.DataFrame) -> pd.Series:
    """Country plus the credit-bureau grade of that country (D-017).

    Estonian loans get their CreditScoreEeMini ('EE_1000', 'EE_800', ...), Finnish loans their
    CreditScoreFiAsiakasTietoRiskGrade ('FI_3', 'FI_RL2', ...), and loans from any other
    country just the country code ('ES'), because their bureau scores are not usable (D-014).
    A missing grade becomes '<country>_missing'.
    """
    ee = "EE_" + df["CreditScoreEeMini"].map(_code)
    fi = "FI_" + df["CreditScoreFiAsiakasTietoRiskGrade"].map(_code)
    out = np.select(
        [df["Country"].eq("EE"), df["Country"].eq("FI")], [ee, fi], default=df["Country"]
    )
    return pd.Series(out, index=df.index, name="country_bureau_grade", dtype="object")


# Median IncomeTotal per country in the train sample (notebook 04 checks these still match).
# Frozen here so a new application is scored with the same reference as the training data.
TRAIN_MEDIAN_INCOME = {"EE": 1000.0, "ES": 1350.0, "FI": 2036.0}


def income_vs_country_median(df: pd.DataFrame) -> pd.Series:
    """IncomeTotal divided by the train median income of the borrower's country (D-017).

    Raw income mostly measures the country (Finnish incomes are about twice Estonian ones, and
    Finland defaults more), so pooled it ranks risk the wrong way. Relative to the country
    median, a higher value means a lower default rate in every country. Countries without a
    median (no train loans) get NaN, which binning treats as its own group.
    """
    median = df["Country"].map(TRAIN_MEDIAN_INCOME)
    return (df["IncomeTotal"] / median).rename("income_vs_country_median").astype(float)


DERIVED = {
    "country_bureau_grade": country_bureau_grade,
    "income_vs_country_median": income_vs_country_median,
}


def add_derived(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of df with every derived feature added as a column."""
    out = df.copy()
    for name, func in DERIVED.items():
        out[name] = func(df)
    return out
