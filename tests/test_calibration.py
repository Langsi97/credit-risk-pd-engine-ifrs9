import numpy as np
import pandas as pd
import pytest

from pdengine.calibration import (
    CountryRecalibration,
    calibration_line,
    expit,
    intercept_shift,
    jeffreys_p,
    logit,
)

WINDOW = ("2020-04-01", "2021-04-01")


@pytest.fixture
def book():
    """Two countries whose true risk is the model PD moved by a known logit shift."""
    rng = np.random.default_rng(0)
    n = 40_000
    country = pd.Series(rng.choice(["EE", "FI"], n))
    pd_model = pd.Series(expit(rng.normal(-1.0, 1.0, n)))
    true_shift = country.map({"EE": -0.8, "FI": -1.9})
    y = pd.Series(rng.binomial(1, expit(logit(pd_model) + true_shift)))
    date = pd.Series(pd.to_datetime("2020-04-01") + pd.to_timedelta(rng.integers(0, 365, n), "D"))
    return y, pd_model, country, date


def test_shift_recovers_the_true_offset(book):
    y, p, c, d = book
    rec = CountryRecalibration(window=WINDOW).fit(y, p, c, d)
    assert rec.shifts["EE"] == pytest.approx(-0.8, abs=0.05)
    assert rec.shifts["FI"] == pytest.approx(-1.9, abs=0.08)


def test_recalibrated_mean_matches_default_rate(book):
    y, p, c, d = book
    rec = CountryRecalibration(window=WINDOW).fit(y, p, c, d)
    new = rec.transform(p, c)
    for k in ["EE", "FI"]:
        assert new[c.eq(k)].mean() == pytest.approx(y[c.eq(k)].mean(), abs=0.002)


def test_ranking_within_country_is_unchanged(book):
    y, p, c, d = book
    new = CountryRecalibration(window=WINDOW).fit(y, p, c, d).transform(p, c)
    for k in ["EE", "FI"]:
        m = c.eq(k)
        assert (p[m].rank() == new[m].rank()).all()


def test_country_without_data_keeps_its_pd(book):
    y, p, c, d = book
    rec = CountryRecalibration(window=WINDOW).fit(y, p, c, d)
    es = pd.Series(["ES"] * 3)
    assert np.allclose(rec.transform(p[:3], es).to_numpy(), p[:3].to_numpy())


def test_small_country_is_flagged_not_fitted(book):
    y, p, c, d = book
    c = c.copy()
    c.iloc[:100] = "ES"
    rec = CountryRecalibration(window=WINDOW).fit(y, p, c, d)
    assert "ES" in rec.not_recalibrated and "ES" not in rec.shifts


def test_intercept_shift_is_zero_for_a_calibrated_model(book):
    _, p, _, _ = book
    y = pd.Series(np.random.default_rng(1).binomial(1, p))
    s, _ = intercept_shift(y, p)
    a, b = calibration_line(y, p)
    assert abs(s) < 0.05 and abs(a) < 0.1 and b == pytest.approx(1, abs=0.05)


def test_jeffreys_flags_underestimation_only():
    assert jeffreys_p(150, 1000, 0.10) < 0.001  # 15% observed vs 10% PD: underestimated
    assert jeffreys_p(50, 1000, 0.10) > 0.999  # 5% observed vs 10% PD: conservative
    assert 0.3 < jeffreys_p(100, 1000, 0.10) < 0.7


def test_json_round_trip(book, tmp_path):
    y, p, c, d = book
    rec = CountryRecalibration(window=WINDOW).fit(y, p, c, d)
    rec.to_json(tmp_path / "cal.json")
    back = CountryRecalibration.from_json(tmp_path / "cal.json")
    assert back.shifts == rec.shifts and back.window == rec.window
