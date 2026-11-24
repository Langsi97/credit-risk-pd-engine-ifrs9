"""Recalibration of champion v2 to the post-2020 default level, by country (notebook 08, D-030).

The scorecard ranks loans well out of time, but its PDs carry the 2016-2019 default level.
Bondora stopped lending in Finland and Spain in spring 2020 and restarted in Finland at the end
of 2020 with a much lower default rate. Recalibration moves each country's PDs to the new level
with an intercept shift on the logit scale per country, plus a slope where a likelihood-ratio
test asks for one (D-030a). Both keep the ranking, the points and the reason codes untouched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.stats import beta, chi2

from pdengine import settings as S

EPS = 1e-6


def logit(p) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return np.log(p / (1 - p))


def expit(z) -> np.ndarray:
    return 1 / (1 + np.exp(-np.asarray(z, dtype=float)))


def intercept_shift(y, pd_hat) -> tuple[float, float]:
    """Calibration-in-the-large: the logit shift s (and its standard error) that makes
    mean(expit(logit(pd) + s)) match the default rate. A logistic fit with the old logit as
    an offset and only an intercept free."""
    y = np.asarray(y, dtype=float)
    fit = sm.GLM(y, np.ones(len(y)), family=sm.families.Binomial(), offset=logit(pd_hat)).fit()
    return float(fit.params[0]), float(fit.bse[0])


def calibration_line(y, pd_hat) -> tuple[float, float]:
    """Weak calibration (Cox, 1958): intercept and slope of logit(P(y=1)) on logit(pd).
    A perfect model has intercept 0 and slope 1; slope < 1 means PDs too extreme, > 1 too flat."""
    X = sm.add_constant(logit(pd_hat))
    fit = sm.GLM(np.asarray(y, dtype=float), X, family=sm.families.Binomial()).fit()
    return float(fit.params[0]), float(fit.params[1])


def slope_test(y, pd_hat) -> tuple[float, float, float]:
    """Shift only vs shift + slope: the calibration line (a, b) and the likelihood-ratio
    p-value (1 degree of freedom) for adding the slope."""
    y, z = np.asarray(y, dtype=float), logit(pd_hat)
    shift = sm.GLM(y, np.ones(len(y)), family=sm.families.Binomial(), offset=z).fit()
    line = sm.GLM(y, sm.add_constant(z), family=sm.families.Binomial()).fit()
    p = float(chi2.sf(2 * (line.llf - shift.llf), 1))
    return float(line.params[0]), float(line.params[1]), p


def jeffreys_p(defaults: int, loans: int, mean_pd: float) -> float:
    """ECB (2019) Jeffreys test, one-sided. H0: the PD is not lower than the true default rate.
    p-value = P(true rate <= mean PD) under the Beta(D + 1/2, N - D + 1/2) posterior.
    A small p-value (< 0.05) means the PD underestimates risk."""
    return float(beta.cdf(mean_pd, defaults + 0.5, loans - defaults + 0.5))


def ece(y, pd_hat, n_bins: int = 10) -> float:
    """Expected calibration error: loan-weighted mean |default rate - mean PD| over PD deciles."""
    d = pd.DataFrame({"y": np.asarray(y, float), "p": np.asarray(pd_hat, float)})
    d["bin"] = pd.qcut(d["p"].rank(method="first"), n_bins, labels=False)
    g = d.groupby("bin").agg(y=("y", "mean"), p=("p", "mean"), n=("y", "size"))
    return float((g["y"].sub(g["p"]).abs() * g["n"]).sum() / g["n"].sum())


def calibration_table(y: pd.Series, pd_hat: pd.Series, by: pd.Series) -> pd.DataFrame:
    """Per group: loans, defaults, default rate, mean PD, Jeffreys p-value, slope, Brier, ECE."""
    rows = {}
    for g, idx in y.groupby(by).groups.items():
        yy, pp = y.loc[idx], pd_hat.loc[idx]
        d, n = int(yy.sum()), len(yy)
        _, slope = calibration_line(yy, pp) if 0 < d < n and n >= 200 else (np.nan, np.nan)
        rows[g] = {
            "loans": n,
            "defaults": d,
            "default_rate": yy.mean(),
            "mean_pd": pp.mean(),
            "jeffreys_p": jeffreys_p(d, n, pp.mean()),
            "slope": slope,
            "brier": float(((pp - yy) ** 2).mean()),
            "ece": ece(yy, pp) if n >= 200 else np.nan,
        }
    return pd.DataFrame(rows).T


@dataclass
class CountryRecalibration:
    """Per country: new logit = shift + slope x old logit. The slope is 1 unless the closed test
    asks for it (D-030a). Countries without post-2020 data (Spain) keep their PDs and are listed
    in `not_recalibrated` so reports can flag them."""

    window: tuple[str, str] = S.RECAL_WINDOW
    min_loans: int = S.RECAL_MIN_LOANS
    slope_alpha: float = S.RECAL_SLOPE_ALPHA  # closed test: add a slope only when p < alpha
    shifts: dict[str, float] = field(default_factory=dict)
    slopes: dict[str, float] = field(default_factory=dict)  # 1.0 = shift only
    slope_p_values: dict[str, float] = field(default_factory=dict)
    std_errors: dict[str, float] = field(default_factory=dict)
    loans: dict[str, int] = field(default_factory=dict)
    not_recalibrated: list[str] = field(default_factory=list)

    def fit(self, y, pd_hat, country, issue_date) -> CountryRecalibration:
        in_window = issue_date.ge(self.window[0]) & issue_date.lt(self.window[1])
        for c in sorted(country.dropna().unique()):
            m = in_window & country.eq(c)
            if m.sum() < self.min_loans:
                self.not_recalibrated.append(c)
                continue
            self.shifts[c], self.std_errors[c] = intercept_shift(y[m], pd_hat[m])
            self.loans[c] = int(m.sum())
            # Closed testing (Vergouwe et al., 2017): keep the slope only if the LR test asks.
            a, b, p = slope_test(y[m], pd_hat[m])
            self.slope_p_values[c] = p
            self.slopes[c] = 1.0
            if p < self.slope_alpha:
                self.shifts[c], self.slopes[c] = a, b
        return self

    def transform(self, pd_hat: pd.Series, country: pd.Series) -> pd.Series:
        s = country.map(self.shifts).fillna(0.0).to_numpy()
        b = country.map(self.slopes).fillna(1.0).to_numpy()
        return pd.Series(expit(s + b * logit(pd_hat)), index=pd_hat.index, name="pd_recalibrated")

    def to_json(self, path: Path, **extra) -> None:
        keys = [
            "window",
            "min_loans",
            "slope_alpha",
            "shifts",
            "slopes",
            "slope_p_values",
            "std_errors",
            "loans",
            "not_recalibrated",
        ]
        out = {k: getattr(self, k) for k in keys} | extra
        Path(path).write_text(json.dumps(out, indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, path: Path) -> CountryRecalibration:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
        keys = [
            "window",
            "min_loans",
            "slope_alpha",
            "shifts",
            "slopes",
            "slope_p_values",
            "std_errors",
            "loans",
            "not_recalibrated",
        ]
        d = {k: d[k] for k in keys}
        d["window"] = tuple(d["window"])
        return cls(**d)
