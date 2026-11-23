"""History features: what Bondora knew about a borrower from their earlier loans (D-020).

A lender knows its own customers. When a repeat customer applies, it can see when they first
borrowed and when they last borrowed. The Kaggle file links a borrower's loans through
`UserName`, so these facts can be rebuilt for every loan, **as of its application date**:
only loans issued strictly before that date count. A loan never sees a later loan, so the
features contain nothing a lender could not have known on the day it decided.

`UserName` is a personal column (registry class `personal`). It is used here only to group a
borrower's loans and never appears in the output.

Usage
-----
    from pdengine.history import history_features

    hist = history_features(kaggle[["LoanId", "UserName", "LoanDate"]])   # indexed by loan id
"""

from __future__ import annotations

import pandas as pd

FEATURES = ("days_since_first_loan", "days_since_last_loan")


def history_features(
    loans: pd.DataFrame, loan_id: str = "LoanId", key: str = "UserName", date: str = "LoanDate"
) -> pd.DataFrame:
    """Customer tenure and recency for every loan, from the same borrower's earlier loans.

    Pass ALL loans of the source (not one sample), so a borrower's full history is visible.

    * days_since_first_loan: days from the borrower's first earlier loan to this loan.
    * days_since_last_loan: days from the borrower's most recent earlier loan to this loan.

    Both are empty (NaN) for a borrower's first loan. Loans issued on the same day as this
    one do not count as earlier.
    """
    d = loans[[loan_id, key, date]].copy()
    d[date] = pd.to_datetime(d[date]).dt.normalize()

    # One row per borrower and issue day, so same-day loans share their history.
    days = d[[key, date]].drop_duplicates().sort_values([key, date])
    days["first"] = days.groupby(key)[date].transform("min")
    days["previous"] = days.groupby(key)[date].shift()  # the last earlier day, if any

    out = d.merge(days, on=[key, date], how="left").set_index(loan_id)
    earlier = out["previous"].notna()
    result = pd.DataFrame(index=out.index)
    result["days_since_first_loan"] = (out[date] - out["first"]).dt.days.where(earlier)
    result["days_since_last_loan"] = (out[date] - out["previous"]).dt.days.where(earlier)
    return result.astype(float)  # the key is not returned
