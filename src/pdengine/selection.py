"""Binning and feature selection (notebook 04, D-018).

Bins are fitted on the train sample only. A feature reaches the shortlist only if it passes,
in order: IV, out-of-time population stability (PSI, feature values only: the out-of-time
outcomes are never used), the within-country check, "a derived feature replaces its inputs",
correlation with stronger features, and VIF.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from optbinning import BinningProcess
from statsmodels.stats.outliers_influence import variance_inflation_factor

from pdengine import settings as S
from pdengine.registry import Registry


def fit_bins(X: pd.DataFrame, y: pd.Series) -> BinningProcess:
    """Fit the bins of every column of X (pass the train sample only)."""
    features = list(X.columns)
    categorical = [c for c in S.CATEGORICAL if c in features]
    params = {
        c: {"monotonic_trend": "auto" if c in S.NON_MONOTONIC else "auto_asc_desc"}
        for c in features
        if c not in categorical
    }
    bp = BinningProcess(
        features,
        categorical_variables=categorical,
        min_bin_size=S.MIN_BIN_SIZE,
        binning_fit_params=params,
    )
    return bp.fit(X, y)


def transform(bp: BinningProcess, X: pd.DataFrame, metric: str) -> pd.DataFrame:
    """Bin labels ("bins") or WoE values ("woe") of every binned feature, indexed like X."""
    return bp.transform(X[bp.variable_names], metric=metric).set_index(X.index)


def information_value(labels: pd.Series, y: pd.Series) -> float:
    """IV of a feature on any sample, from its bin labels (0.5 added to every count)."""
    t = pd.DataFrame({"bin": np.asarray(labels), "y": np.asarray(y)}).groupby("bin")["y"]
    t = t.agg(["sum", "count"])
    bad, good = t["sum"] + 0.5, t["count"] - t["sum"] + 0.5
    pb, pg = bad / bad.sum(), good / good.sum()
    return float(((pg - pb) * np.log(pg / pb)).sum())


def psi(expected: pd.Series, actual: pd.Series) -> float:
    """Population stability index between two sets of bin labels."""
    e = expected.value_counts(normalize=True)
    a = actual.value_counts(normalize=True)
    idx = e.index.union(a.index)
    e, a = e.reindex(idx, fill_value=0) + 1e-6, a.reindex(idx, fill_value=0) + 1e-6
    return float(((a - e) * np.log(a / e)).sum())


def within_country(woe: pd.Series, country: pd.Series, y: pd.Series) -> pd.Series:
    """Spearman correlation between bin WoE and the bin's default rate, inside each country.

    Close to -1: the pooled pattern holds in that country. Near 0 or positive: it is a country
    effect (Simpson's paradox). Bins with fewer than MIN_LOANS_PER_COUNTRY_BIN loans are ignored.
    """
    t = pd.DataFrame({"woe": woe, "country": country, "y": y})
    out = {}
    for c, g in t.groupby("country"):
        rates = g.groupby("woe")["y"].agg(["mean", "size"])
        rates = rates[rates["size"] >= S.MIN_LOANS_PER_COUNTRY_BIN]
        out[c] = (
            rates.index.to_series().corr(rates["mean"], method="spearman")
            if len(rates) >= 2
            else np.nan
        )
    return pd.Series(out)


@dataclass
class Selection:
    shortlist: list[str]
    table: pd.DataFrame  # one row per feature: iv, iv_test, psi_oot, rho_median, vif, reason


def select_features(
    bp: BinningProcess,
    X: pd.DataFrame,
    y: pd.Series,
    sample: pd.Series,
    country: pd.Series,
    reg: Registry,
) -> Selection:
    """Apply the D-018 rules and return the shortlist with a reason for every dropped feature."""
    tr, te, oot = sample.eq("train"), sample.eq("test"), sample.eq("oot")
    bins = {k: transform(bp, X[m], "bins") for k, m in [("tr", tr), ("te", te), ("oot", oot)]}
    woe_tr = transform(bp, X[tr], "woe")

    table = bp.summary().set_index("name")[["iv"]].astype(float).sort_values("iv", ascending=False)
    table["iv_test"] = [information_value(bins["te"][c], y[te]) for c in table.index]
    table["psi_oot"] = [psi(bins["tr"][c], bins["oot"][c]) for c in table.index]
    table["rho_median"] = np.nan
    for c in table.index:
        if table.loc[c, "iv"] >= S.MIN_IV and c not in S.COUNTRY_FEATURES:
            table.loc[c, "rho_median"] = within_country(woe_tr[c], country[tr], y[tr]).median()

    reason: dict[str, str] = {}
    for c in table.index:
        if table.loc[c, "iv"] < S.MIN_IV:
            reason[c] = f"IV {table.loc[c, 'iv']:.3f} below {S.MIN_IV}"
        elif table.loc[c, "psi_oot"] > S.MAX_PSI:
            reason[c] = f"population shift, PSI {table.loc[c, 'psi_oot']:.2f}"
        elif table.loc[c, "rho_median"] > S.MAX_WITHIN_COUNTRY_RHO:
            reason[c] = (
                f"country effect (within-country correlation {table.loc[c, 'rho_median']:+.2f})"
            )
    for name, inputs in reg.derived.items():  # a derived feature replaces its raw inputs
        if name in table.index:
            for raw in inputs:
                reason.setdefault(raw, f"input of {name}")

    corr = woe_tr.corr()
    kept: list[str] = []
    for c in table.index:  # highest IV first
        if c in reason:
            continue
        clash = [k for k in kept if abs(corr.loc[c, k]) > S.MAX_CORRELATION]
        if clash:
            reason[c] = f"duplicates {clash[0]} (correlation {corr.loc[c, clash[0]]:.2f})"
        else:
            kept.append(c)

    W = np.column_stack([np.ones(int(tr.sum())), woe_tr[kept].to_numpy()])
    table["vif"] = np.nan
    for i, c in enumerate(kept):
        table.loc[c, "vif"] = variance_inflation_factor(W, i + 1)
    too_high = [c for c in kept if table.loc[c, "vif"] >= S.MAX_VIF]
    if too_high:
        raise ValueError(f"VIF of {too_high} is {S.MAX_VIF} or more: review the selection")

    table["reason"] = pd.Series(reason)
    table["reason"] = table["reason"].fillna("kept")
    return Selection(shortlist=kept, table=table)
