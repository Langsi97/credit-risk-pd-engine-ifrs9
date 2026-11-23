"""Champion v2: the logical dummy scorecard (notebook 07, D-028).

Three changes from the v1 WoE scorecard (notebook 05), each tested in the 2026-11-23 audit:

1. One coefficient per bin (dummy coding) instead of one per feature. A WoE logit keeps every
   feature's single-variable WoE shape; a joint fit lets each shape adjust for the others.
2. Interaction characteristics: the features in settings.CROSS_FEATURES are binned inside each
   country ("FI:[300, 480)"), because loan size and history mean different things by country.
3. Logical points by construction: inside every ordered feature (and every country of a crossed
   feature) the bin coefficients must follow the bins' train risk order. The fit is a ridge
   logistic regression solved with L-BFGS-B on monotone increments (bounds keep the order).

Usage
-----
    from pdengine.champion import CountryBins, LogicalScorecard, labels_for

    cross = CountryBins().fit(X[train], y[train], country[train])
    labels = labels_for(bp, cross, X, country, features)        # one text label per feature
    card = LogicalScorecard().fit(labels[train], y[train], ordered_groups(...))
    pd_hat = card.predict_pd(labels)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from optbinning import BinningProcess, OptimalBinning
from scipy.optimize import minimize
from scipy.special import expit

from pdengine import settings as S
from pdengine.selection import transform

MISSING_LABELS = ("Missing", "Special")


class CountryBins:
    """Optimal bins of each CROSS_FEATURES feature, fitted separately inside each country."""

    def __init__(self, features: dict[str, str] | None = None, countries: list[str] | None = None):
        self.features = dict(S.CROSS_FEATURES if features is None else features)
        self.countries = list(S.CROSS_COUNTRIES if countries is None else countries)
        self.binners: dict[tuple[str, str], OptimalBinning] = {}

    def fit(self, X: pd.DataFrame, y: pd.Series, country: pd.Series) -> CountryBins:
        """Pass the train sample only."""
        for f, trend in self.features.items():
            for c in self.countries:
                m = country.eq(c).to_numpy()
                ob = OptimalBinning(
                    f,
                    dtype="numerical",
                    monotonic_trend=trend,
                    min_bin_size=S.CROSS_MIN_BIN_SIZE,
                    min_prebin_size=S.CROSS_MIN_PREBIN_SIZE,
                    max_n_prebins=S.CROSS_MAX_N_PREBINS,
                )
                self.binners[(f, c)] = ob.fit(X.loc[m, f].to_numpy(), y[m].to_numpy())
        return self

    def transform(self, X: pd.DataFrame, country: pd.Series, feature: str) -> pd.Series:
        """Labels such as 'EE:[300.00, 480.00)'. Loans of other countries get '<country>:all'."""
        out = country.astype(str) + ":all"
        for c in self.countries:
            m = country.eq(c).to_numpy()
            if m.any():
                lab = self.binners[(feature, c)].transform(X.loc[m, feature].to_numpy(), "bins")
                out[m] = c + ":" + pd.Series(lab, index=X.index[m]).astype(str)
        return out.rename(feature)


def labels_for(
    bp: BinningProcess, cross: CountryBins, X: pd.DataFrame, country: pd.Series, features: list[str]
) -> pd.DataFrame:
    """One text bin label per feature and loan; crossed features use their country bins."""
    lab = transform(bp, X, "bins")[[f for f in features if f not in cross.features]].astype(str)
    for f in features:
        if f in cross.features:
            lab[f] = cross.transform(X, country, f)
    return lab[features]


def _bin_sort_key(label: str):
    """Sort 'EE:[300.00, 480.00)' by country then left edge; Missing and Special last."""
    country, _, interval = label.rpartition(":") if ":" in label else ("", "", label)
    if interval in MISSING_LABELS or interval == "all":
        return (country, 1, float("inf"), interval)
    left = interval.strip("[(").split(",")[0].strip()
    try:
        return (country, 0, float(left), "")
    except ValueError:
        return (country, 0, float("inf"), interval)


def _risk_order(labels: pd.Series, y: pd.Series) -> list[str]:
    """Labels from riskiest to safest by train default rate (0.5 added to every count)."""
    t = pd.DataFrame({"l": labels, "y": y}).groupby("l")["y"].agg(["sum", "count"])
    woe = np.log((t["count"] - t["sum"] + 0.5) / (t["sum"] + 0.5))
    return list(woe.sort_values().index)


def ordered_groups(
    bp: BinningProcess, cross: CountryBins, labels: pd.DataFrame, y: pd.Series
) -> list[list[str]]:
    """The cells whose coefficients must follow the train risk order (pass train rows only).

    Ordered numeric features (monotone binning trend) and every country of a crossed feature
    are constrained, plus the categorical features in settings.LOGICAL_ORDER. Missing and
    Special bins, unordered categories (home ownership, bureau grade) and NON_MONOTONIC
    features are free.
    """
    groups = []
    for f in labels.columns:
        if f in cross.features:
            for c in cross.countries:
                sub = labels[f][labels[f].str.startswith(c + ":")]
                sub = sub[~sub.str.contains("|".join(MISSING_LABELS))]
                if sub.nunique() > 1:
                    groups.append([f"{f}={k}" for k in _risk_order(sub, y[sub.index])])
            continue
        numeric = bp.get_binned_variable(f).dtype == "numerical"
        if (numeric and f not in S.NON_MONOTONIC) or f in S.LOGICAL_ORDER:
            sub = labels[f][~labels[f].isin(MISSING_LABELS)]
            if sub.nunique() > 1:
                groups.append([f"{f}={k}" for k in _risk_order(sub, y[sub.index])])
    return groups


@dataclass
class LogicalScorecard:
    """Ridge logistic regression on bin dummies with order constraints, scaled to points."""

    l2: float = S.L2_PENALTY
    columns: list[str] = field(default_factory=list)
    coefficients: list[float] = field(default_factory=list)
    intercept: float = 0.0
    groups: list[list[str]] = field(default_factory=list)
    converged: bool = False

    # ------------------------------------------------------------------ design
    def design(self, labels: pd.DataFrame) -> np.ndarray:
        """0/1 matrix in self.columns order; a label never seen in train gets no points."""
        Z = np.zeros((len(labels), len(self.columns)))
        index = {c: i for i, c in enumerate(self.columns)}
        for f in labels.columns:
            cells = (f + "=" + labels[f].astype(str)).map(index)
            ok = cells.notna().to_numpy()
            Z[np.flatnonzero(ok), cells[ok].astype(int).to_numpy()] = 1.0
        return Z

    # ------------------------------------------------------------------ fit
    def fit(self, labels: pd.DataFrame, y: pd.Series, groups: list[list[str]]) -> LogicalScorecard:
        """Coefficients b = T d. Inside each group (riskiest to safest) the first cell is free
        and every next cell adds an increment d <= 0, so coefficients never rise with safety."""
        self.columns = [f"{f}={v}" for f in labels.columns for v in sorted(labels[f].unique())]
        self.groups = [[c for c in g if c in self.columns] for g in groups]
        n = len(self.columns)
        idx = {c: i for i, c in enumerate(self.columns)}
        T = np.eye(n)
        bounds: list[tuple[float | None, float | None]] = [(None, None)] * n
        for g in self.groups:
            ids = [idx[c] for c in g]
            for j in range(1, len(ids)):
                T[ids[j], :] = T[ids[j - 1], :]
                T[ids[j], ids[j]] = 1.0
                bounds[ids[j]] = (None, 0.0)
        A = self.design(labels) @ T
        t = y.to_numpy().astype(float)
        m = len(t)

        def loss(w):
            b0, d = w[0], w[1:]
            b = T @ d
            z = b0 + A @ d
            p = expit(z)
            value = np.mean(np.logaddexp(0, z) - t * z) + self.l2 * b @ b
            grad = A.T @ (p - t) / m + 2 * self.l2 * T.T @ b
            return value, np.concatenate([[np.mean(p - t)], grad])

        r = minimize(
            loss,
            np.zeros(n + 1),
            jac=True,
            method="L-BFGS-B",
            bounds=[(None, None), *bounds],
            options={"maxiter": 10000},
        )
        self.intercept = float(r.x[0])
        self.coefficients = [float(v) for v in T @ r.x[1:]]
        self.converged = bool(r.success)
        return self

    # ------------------------------------------------------------------ predict
    def logit(self, labels: pd.DataFrame) -> pd.Series:
        z = self.intercept + self.design(labels) @ np.asarray(self.coefficients)
        return pd.Series(z, index=labels.index)

    def predict_pd(self, labels: pd.DataFrame) -> pd.Series:
        """Probability of default within 12 months."""
        return 1 / (1 + np.exp(-self.logit(labels)))

    # ------------------------------------------------------------------ points
    def points_table(self) -> pd.DataFrame:
        """Points per cell (higher = safer). A loan's score is the sum over its features."""
        factor = S.PDO / np.log(2)
        offset = S.BASE_SCORE - factor * np.log(S.BASE_ODDS)
        feats = sorted({c.split("=", 1)[0] for c in self.columns}, key=self._feature_order)
        n = len(feats)
        rows = []
        for c, b in zip(self.columns, self.coefficients, strict=True):
            f, v = c.split("=", 1)
            pts = offset / n - factor * (b + self.intercept / n)
            rows.append({"feature": f, "bin": v, "coefficient": b, "points": int(round(pts))})
        out = pd.DataFrame(rows)
        out["_k"] = out["bin"].map(_bin_sort_key)
        out["_f"] = out["feature"].map(self._feature_order)
        return out.sort_values(["_f", "_k"]).drop(columns=["_k", "_f"]).reset_index(drop=True)

    def _feature_order(self, f: str) -> int:
        return next(i for i, c in enumerate(self.columns) if c.startswith(f + "="))

    def score(self, labels: pd.DataFrame) -> pd.Series:
        """Points before rounding (offset - factor x logit)."""
        factor = S.PDO / np.log(2)
        offset = S.BASE_SCORE - factor * np.log(S.BASE_ODDS)
        return offset - factor * self.logit(labels)

    def order_violations(self, tol: float = 1e-8) -> list[str]:
        """Groups whose coefficients rise with safety (should be empty)."""
        b = dict(zip(self.columns, self.coefficients, strict=True))
        return [g[0].split("=")[0] for g in self.groups if np.any(np.diff([b[c] for c in g]) > tol)]

    # ------------------------------------------------------------------ save
    def to_json(self, path: Path, **extra) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**asdict(self), **extra}, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> LogicalScorecard:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = ("l2", "columns", "coefficients", "intercept", "groups", "converged")
        return cls(**{k: d[k] for k in keys if k in d})


MIN_POINTS_RANGE = 2  # a characteristic whose points vary by less than this is dropped (D-028)


@dataclass
class ChampionV2:
    bins: BinningProcess
    cross: CountryBins
    card: LogicalScorecard
    features: list[str]
    screened_out: dict[str, str]
    flat: list[str]

    def labels(self, X: pd.DataFrame, country: pd.Series) -> pd.DataFrame:
        return labels_for(self.bins, self.cross, X, country, self.features)

    def predict_pd(self, X: pd.DataFrame, country: pd.Series) -> pd.Series:
        return self.card.predict_pd(self.labels(X, country))


def fit_champion(X, y, sample, country, reg) -> ChampionV2:
    """Bins (train) -> screens -> country bins (train) -> logical fit -> drop flat features."""
    from pdengine.selection import fit_bins, screen_features

    tr = sample.eq("train")
    bp = fit_bins(X[tr], y[tr], S.V2_MIN_BIN_SIZE, S.V2_MIN_PREBIN_SIZE, S.V2_MAX_N_PREBINS)
    sel = screen_features(bp, X, y, sample, country, reg)
    cross = CountryBins().fit(X[tr], y[tr], country[tr])
    features, flat = list(sel.shortlist), []
    while True:
        lab = labels_for(bp, cross, X[tr], country[tr], features)
        card = LogicalScorecard().fit(lab, y[tr], ordered_groups(bp, cross, lab, y[tr]))
        spread = card.points_table().groupby("feature")["points"].agg(lambda s: s.max() - s.min())
        drop = [f for f in features if spread.get(f, 0) < MIN_POINTS_RANGE]
        if not drop:
            break
        flat += drop
        features = [f for f in features if f not in drop]
    screened = sel.table.loc[sel.table["reason"] != "kept", "reason"].to_dict()
    return ChampionV2(bp, cross, card, features, screened, flat)
