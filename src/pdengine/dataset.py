"""The model matrix: candidate, derived and history features for the sample loans.

One function builds the raw feature table the same way for binning, training, the challenger
and (later) scoring: registry candidates from the warehouse, derived features
(pdengine.features), history features (pdengine.history), column types, then the leakage guard.
"""

from __future__ import annotations

from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from pdengine import settings as S
from pdengine.features import add_derived
from pdengine.history import history_features
from pdengine.registry import Registry, candidate_features, check_model_columns, load_registry


@dataclass
class ModelData:
    X: pd.DataFrame  # raw features, indexed by loan_key
    y: pd.Series  # 12-month default flag
    sample: pd.Series  # train / test / oot
    country: pd.Series  # ISO country code, for per-country reporting
    issue_date: pd.Series
    bondora_pd: pd.Series  # benchmark: compared with, never a model input


def prepare_types(X: pd.DataFrame) -> pd.DataFrame:
    """Set the column types the bins were fitted on: coded categories as text, empties kept."""
    X = X.copy()
    if "NewCreditCustomer" in X:
        X["NewCreditCustomer"] = X["NewCreditCustomer"].astype(int)  # True/False -> 1/0
    if "CreditScoreEeMini" in X:
        X["CreditScoreEeMini"] = X["CreditScoreEeMini"].astype(float)  # nullable int -> float
    for c in S.CATEGORICAL:
        if c in X:
            X[c] = X[c].astype("string").astype(object).where(X[c].notna(), np.nan)
    return X


def load_model_data(
    con: duckdb.DuckDBPyConnection, samples: pd.DataFrame, reg: Registry | None = None
) -> ModelData:
    """Raw features for every loan in `samples` (columns loan_key, sample, y, issue_date)."""
    reg = reg or load_registry()
    samples = samples.set_index("loan_key")
    con.register("sample_keys", samples.reset_index()[["loan_key"]])
    cols = ", ".join(f'"{c}"' for c in candidate_features(reg))
    raw = (
        con.execute(
            f'SELECT loan_key, {cols}, "ProbabilityOfDefault" AS bondora_pd '
            "FROM loans JOIN sample_keys USING (loan_key)"
        )
        .df()
        .set_index("loan_key")
        .loc[samples.index]
    )
    con.unregister("sample_keys")
    bondora_pd = raw.pop("bondora_pd")
    raw = add_derived(raw)
    # History is computed over ALL Kaggle loans, so earlier loans outside the samples count.
    all_loans = con.execute(
        'SELECT upper(trim("LoanId")) AS "LoanId", "UserName", "LoanDate" FROM kaggle_loans'
    ).df()
    raw = raw.join(history_features(all_loans))
    check_model_columns(raw.columns, reg)  # the leakage guard
    return ModelData(
        X=prepare_types(raw),
        y=samples["y"].astype(int),
        sample=samples["sample"],
        country=raw["Country"],
        issue_date=pd.to_datetime(samples["issue_date"]),
        bondora_pd=bondora_pd,
    )
