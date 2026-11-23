"""Tests of champion v2, the logical dummy scorecard (D-028), on small synthetic data."""

import numpy as np
import pandas as pd
import pytest

from pdengine.champion import CountryBins, LogicalScorecard, _bin_sort_key, _risk_order

RNG = np.random.default_rng(1)


def _three_bins(n=6000, middle=0.30):
    """One ordered feature with bins a (risky), b, c (safe); b's true rate set by `middle`."""
    lab = pd.Series(RNG.choice(["a", "b", "c"], n), name="f")
    rate = lab.map({"a": 0.40, "b": middle, "c": 0.20})
    y = pd.Series((RNG.random(n) < rate).astype(int))
    return pd.DataFrame({"f": lab}), y


def test_country_bins_follow_each_country_own_pattern():
    n = 8000
    country = pd.Series(RNG.choice(["EE", "FI"], n))
    x = pd.Series(RNG.uniform(0, 100, n))
    # risk rises with x in Estonia and falls with x in Finland
    rate = np.where(country == "EE", 0.1 + 0.005 * x, 0.6 - 0.005 * x)
    y = pd.Series((RNG.random(n) < rate).astype(int))
    X = pd.DataFrame({"x": x})
    cb = CountryBins({"x": "auto_asc_desc"}, ["EE", "FI"]).fit(X, y, country)
    lab = cb.transform(X, country, "x")
    assert lab[country == "EE"].str.startswith("EE:").all()
    assert lab[country == "FI"].str.startswith("FI:").all()
    ee = pd.DataFrame({"l": lab, "y": y, "x": x})[country == "EE"]
    fi = pd.DataFrame({"l": lab, "y": y, "x": x})[country == "FI"]
    ee_rates = ee.groupby("l").agg(x=("x", "mean"), r=("y", "mean")).sort_values("x")["r"]
    fi_rates = fi.groupby("l").agg(x=("x", "mean"), r=("y", "mean")).sort_values("x")["r"]
    assert ee_rates.is_monotonic_increasing and fi_rates.is_monotonic_decreasing


def test_unknown_country_gets_its_own_label():
    X = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0] * 50})
    country = pd.Series(["EE"] * 200)
    y = pd.Series([0, 1] * 100)
    cb = CountryBins({"x": "auto_asc_desc"}, ["EE"]).fit(X, y, country)
    assert cb.transform(X.head(2), pd.Series(["SK", "SK"]), "x").tolist() == ["SK:all"] * 2


def test_logical_fit_never_lets_points_rise_against_the_risk_order():
    labels, y = _three_bins(middle=0.30)
    order = _risk_order(labels["f"], y)
    assert order == ["a", "b", "c"]
    # a noisy middle bin: make b look riskier than a in the data, but require the order a > b > c
    labels2, y2 = _three_bins(middle=0.45)
    card = LogicalScorecard(l2=0.0).fit(labels2, y2, [["f=a", "f=b", "f=c"]])
    b = dict(zip(card.columns, card.coefficients, strict=True))
    assert b["f=a"] >= b["f=b"] - 1e-9 >= b["f=c"] - 1e-9
    assert card.order_violations() == []
    free = LogicalScorecard(l2=0.0).fit(labels2, y2, [])
    fb = dict(zip(free.columns, free.coefficients, strict=True))
    assert fb["f=b"] > fb["f=a"]  # without the constraint the fit would reverse the order


def test_logical_fit_matches_plain_logistic_when_the_order_already_holds():
    labels, y = _three_bins(middle=0.30)
    con = LogicalScorecard(l2=0.0).fit(labels, y, [["f=a", "f=b", "f=c"]])
    free = LogicalScorecard(l2=0.0).fit(labels, y, [])
    np.testing.assert_allclose(con.predict_pd(labels), free.predict_pd(labels), atol=1e-4)
    for v in "abc":  # fitted PD equals the observed rate of each bin
        assert con.predict_pd(labels)[labels["f"] == v].iloc[0] == pytest.approx(
            y[labels["f"] == v].mean(), abs=1e-3
        )


def test_points_add_up_to_the_score_and_unknown_labels_score_nothing():
    labels, y = _three_bins()
    labels["g"] = RNG.choice(["u", "v"], len(labels))
    card = LogicalScorecard().fit(labels, y, [["f=a", "f=b", "f=c"]])
    pts = card.points_table().set_index(["feature", "bin"])["points"]
    row = labels.iloc[0]
    total = pts[("f", row["f"])] + pts[("g", row["g"])]
    assert abs(total - card.score(labels.head(1)).iloc[0]) <= 1  # per-cell rounding
    unseen = pd.DataFrame({"f": ["zzz"], "g": ["u"]})
    assert card.logit(unseen).iloc[0] == pytest.approx(
        card.intercept + dict(zip(card.columns, card.coefficients, strict=True))["g=u"]
    )


def test_logical_scorecard_json_round_trip(tmp_path):
    labels, y = _three_bins()
    card = LogicalScorecard().fit(labels, y, [["f=a", "f=b", "f=c"]])
    card.to_json(tmp_path / "c.json", model="test")
    again = LogicalScorecard.from_json(tmp_path / "c.json")
    np.testing.assert_allclose(again.predict_pd(labels), card.predict_pd(labels))


def test_bins_sort_by_country_and_left_edge():
    labels = ["FI:[5.00, inf)", "EE:Missing", "EE:[2.50, 5.00)", "EE:(-inf, 2.50)"]
    assert sorted(labels, key=_bin_sort_key) == [
        "EE:(-inf, 2.50)",
        "EE:[2.50, 5.00)",
        "EE:Missing",
        "FI:[5.00, inf)",
    ]
