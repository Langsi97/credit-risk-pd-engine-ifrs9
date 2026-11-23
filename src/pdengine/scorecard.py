"""The champion scorecard: logistic regression on WoE, turned into points (notebook 05, D-021).

Positive WoE means safer than average, so every coefficient must be negative. Features that
fail (wrong sign, or p-value of MAX_P_VALUE or more) are removed one at a time, the wrong-sign
feature with the weakest evidence first, refitting after each removal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from optbinning import BinningProcess
from sklearn.metrics import roc_auc_score, roc_curve

from pdengine import settings as S


def coef_table(model) -> pd.DataFrame:
    t = pd.DataFrame({"coef": model.params, "p_value": model.pvalues}).drop(index="const")
    t["passes"] = (t["coef"] < 0) & (t["p_value"] < S.MAX_P_VALUE)
    return t


def fit_logit(woe: pd.DataFrame, y: pd.Series, features: list[str]):
    return sm.Logit(y, sm.add_constant(woe[features])).fit(disp=0)


def fit_with_sign_checks(woe: pd.DataFrame, y: pd.Series, features: list[str]):
    """Refit until every coefficient passes. Returns (model, features kept, features removed)."""
    features, removed = list(features), []
    model = fit_logit(woe, y, features)
    while True:
        t = coef_table(model)
        failing = t[~t["passes"]]
        if failing.empty:
            return model, features, removed
        worst = (
            failing.assign(wrong=failing["coef"] >= 0).sort_values(["wrong", "p_value"]).index[-1]
        )
        removed.append(worst)
        features.remove(worst)
        model = fit_logit(woe, y, features)


@dataclass
class Scorecard:
    features: list[str]
    intercept: float
    coefficients: dict[str, float]
    removed: list[str] = field(default_factory=list)
    scaling: dict[str, float] = field(default_factory=dict)
    points: list[dict] = field(default_factory=list)

    def __post_init__(self):
        if not self.scaling:
            factor = S.PDO / np.log(2)
            offset = S.BASE_SCORE - factor * np.log(S.BASE_ODDS)
            self.scaling = {
                "base_score": S.BASE_SCORE,
                "base_odds": S.BASE_ODDS,
                "pdo": S.PDO,
                "factor": float(factor),
                "offset": float(offset),
            }

    def logit(self, woe: pd.DataFrame) -> pd.Series:
        return self.intercept + sum(woe[f] * c for f, c in self.coefficients.items())

    def predict_pd(self, woe: pd.DataFrame) -> pd.Series:
        """Probability of default within 12 months."""
        return 1 / (1 + np.exp(-self.logit(woe)))

    def score(self, woe: pd.DataFrame) -> pd.Series:
        """Points (higher = safer), before rounding the per-bin points."""
        return self.scaling["offset"] - self.scaling["factor"] * self.logit(woe)

    def build_points(self, bp: BinningProcess) -> pd.DataFrame:
        """Points of every bin: offset/n - factor x (coef x WoE + intercept/n)."""
        n, f, o = len(self.features), self.scaling["factor"], self.scaling["offset"]
        rows = []
        for feat in self.features:
            t = bp.get_binned_variable(feat).binning_table.build().drop(index="Totals")
            for _, r in t[t["Count"] > 0].iterrows():
                pts = o / n - f * (self.coefficients[feat] * r["WoE"] + self.intercept / n)
                rows.append({"feature": feat, "bin": str(r["Bin"]), "points": int(round(pts))})
        self.points = rows
        return pd.DataFrame(rows)

    def to_json(self, path: Path, **extra) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**asdict(self), **extra}, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> Scorecard:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = ("features", "intercept", "coefficients", "removed", "scaling", "points")
        return cls(**{k: d[k] for k in keys if k in d})


class IllogicalPointsError(ValueError):
    """An ordered feature gives fewer points to a higher (safer) category."""


def check_logical_points(bp: BinningProcess, card: Scorecard) -> None:
    """Raise unless every LOGICAL_ORDER feature's points never fall as the category rises."""
    for feature, order in S.LOGICAL_ORDER.items():
        if feature not in card.features:
            continue
        woe = bp.get_binned_variable(feature).transform(np.array(order), metric="woe")
        points = -card.coefficients[feature] * np.asarray(woe)  # points rise with this term
        if (np.diff(points) < -1e-9).any():
            pts = dict(zip(order, np.round(points, 3), strict=True))
            raise IllogicalPointsError(f"{feature}: points fall along {order}: {pts}")


def brier(y, pd_hat) -> float:
    """Mean squared error of the predicted PD: lower is better, rewards correct levels."""
    return float(np.mean((np.asarray(pd_hat) - np.asarray(y)) ** 2))


def fit_scorecard(woe: pd.DataFrame, y: pd.Series, features: list[str]) -> Scorecard:
    """Fit on the train sample (pass train rows only)."""
    model, kept, removed = fit_with_sign_checks(woe, y, features)
    return Scorecard(
        features=kept,
        intercept=float(model.params["const"]),
        coefficients={f: float(model.params[f]) for f in kept},
        removed=removed,
    )


def gini(y, score) -> float:
    return float(2 * roc_auc_score(y, score) - 1)


def ks(y, score) -> float:
    fpr, tpr, _ = roc_curve(y, score)
    return float((tpr - fpr).max())
