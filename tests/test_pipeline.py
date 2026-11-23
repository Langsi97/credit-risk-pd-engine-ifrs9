"""Tests of the Track A pipeline modules on small synthetic data (no warehouse needed)."""

import numpy as np
import pandas as pd
import pytest

from pdengine import settings as S
from pdengine.dataset import prepare_types
from pdengine.samples import assign_samples, exclusions_waterfall
from pdengine.scorecard import (
    IllogicalPointsError,
    Scorecard,
    brier,
    check_logical_points,
    fit_with_sign_checks,
    gini,
)
from pdengine.selection import fit_bins, information_value, psi, within_country

RNG = np.random.default_rng(0)


def _base(n=4000):
    issue = pd.to_datetime("2015-06-01") + pd.to_timedelta(RNG.integers(0, 2200, n), unit="D")
    return pd.DataFrame(
        {
            "loan_key": [f"K{i:05d}" for i in range(n)],
            "issue_date": issue,
            "country_name": RNG.choice(["Estonia", "Finland", "Spain", "Slovakia"], n),
            "loan_status": RNG.choice(["Repaid", "Defaulted", "Active", "Returned"], n),
            "early_repaid_14d": RNG.choice([1.0, 0.0, np.nan], n, p=[0.02, 0.3, 0.68]),
            "y": RNG.choice([0.0, 1.0], n, p=[0.7, 0.3]),
        }
    )


# ------------------------------------------------------------------------- samples


def test_waterfall_removes_in_order_and_flags_slovakia():
    base = _base()
    pop, wf = exclusions_waterfall(base)
    assert wf["loans_left"].iloc[-1] == len(pop)
    assert (wf["removed"] >= 0).all()
    assert wf.set_index("step").loc["Slovakia (flagged, kept in pool)", "removed"] == 0
    assert not pop["loan_status"].isin(["Returned", "InPostFundingReview"]).any()
    assert (pop["issue_date"] >= pd.Timestamp(S.DEV_START)).all()


def test_split_is_reproducible_whatever_the_input_order():
    pop, _ = exclusions_waterfall(_base())
    pop = pop[pop["issue_date"] < pd.Timestamp(S.OOT_END)]
    a = assign_samples(pop).set_index("loan_key")["sample"]
    shuffled = pop.sample(frac=1, random_state=7)
    b = assign_samples(shuffled).set_index("loan_key")["sample"]
    pd.testing.assert_series_equal(a.sort_index(), b.sort_index())


def test_split_windows_and_no_overlap():
    pop, _ = exclusions_waterfall(_base())
    pop = pop[pop["issue_date"] < pd.Timestamp(S.OOT_END)]
    s = assign_samples(pop)
    assert s["loan_key"].is_unique
    dev = s[s["sample"].isin(["train", "test"])]
    assert (dev["issue_date"] < pd.Timestamp(S.OOT_START)).all()
    assert (s.loc[s["sample"] == "oot", "issue_date"] >= pd.Timestamp(S.OOT_START)).all()
    assert abs((dev["sample"] == "test").mean() - S.TEST_SHARE) < 0.01


def test_loan_outside_the_windows_is_refused():
    pop, _ = exclusions_waterfall(_base())
    late = pop.iloc[:1].assign(issue_date=pd.Timestamp("2022-01-01"), loan_key="LATE")
    with pytest.raises(ValueError):
        assign_samples(pd.concat([pop, late]))


# ------------------------------------------------------------------------- dataset


def test_prepare_types_keeps_missing_and_makes_codes_text():
    X = pd.DataFrame(
        {"Education": [4, None, 1], "NewCreditCustomer": [True, False, True]}, dtype=object
    )
    out = prepare_types(X)
    assert out["Education"].tolist()[0] == "4" and pd.isna(out["Education"].iloc[1])
    assert out["NewCreditCustomer"].tolist() == [1, 0, 1]


# ------------------------------------------------------------------------- selection


def test_psi_is_zero_for_identical_and_positive_for_shifted():
    a = pd.Series(["x"] * 50 + ["y"] * 50)
    assert psi(a, a) == pytest.approx(0, abs=1e-6)
    assert psi(a, pd.Series(["x"] * 90 + ["y"] * 10)) > 0.25


def test_information_value_is_zero_without_signal():
    labels = pd.Series(["a", "b"] * 500)
    y = pd.Series([0, 0, 1, 1] * 250)
    assert information_value(labels, y) == pytest.approx(0, abs=1e-3)


def test_within_country_detects_simpsons_paradox():
    # Pooled, high WoE looks safe only because it is common in the safe country A;
    # inside each country the WoE has no link with default.
    n = 4000
    country = np.where(np.arange(n) < n / 2, "A", "B")
    woe = np.where(
        country == "A",
        RNG.choice([1.0, 0.5], n, p=[0.8, 0.2]),
        RNG.choice([1.0, 0.5], n, p=[0.2, 0.8]),
    )
    y = np.where(country == "A", RNG.random(n) < 0.1, RNG.random(n) < 0.5).astype(int)
    rho = within_country(pd.Series(woe), pd.Series(country), pd.Series(y))
    assert rho.median() > S.MAX_WITHIN_COUNTRY_RHO  # would fail the D-018 check


# ------------------------------------------------------------------------- scorecard


def _woe_data(n=6000):
    good = RNG.normal(size=n)
    noise = RNG.normal(size=n)
    logit = -1 - 1.0 * good
    y = (RNG.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    # 'copy' repeats 'good' with a little noise, so inside the model it gets the wrong sign.
    woe = pd.DataFrame({"good": good, "copy": good + 0.05 * noise, "noise": noise})
    return woe, pd.Series(y)


def test_sign_check_keeps_only_negative_significant_features():
    woe, y = _woe_data()
    model, kept, removed = fit_with_sign_checks(woe, y, ["good", "copy", "noise"])
    assert "good" in kept or "copy" in kept
    assert all(model.params[f] < 0 for f in kept)
    assert "noise" in removed


def test_points_add_up_to_the_score():
    card = Scorecard(features=["a", "b"], intercept=-0.8, coefficients={"a": -0.9, "b": -0.4})
    woe = pd.DataFrame({"a": [0.5, -1.0], "b": [0.2, 0.3]})
    n, f, o = 2, card.scaling["factor"], card.scaling["offset"]
    by_hand = sum(o / n - f * (card.coefficients[c] * woe[c] + card.intercept / n) for c in "ab")
    np.testing.assert_allclose(card.score(woe), by_hand)
    # 600 points at odds 30:1, 20 more points double the odds
    assert card.scaling["offset"] + card.scaling["factor"] * np.log(30) == pytest.approx(600)


def test_scorecard_json_round_trip(tmp_path):
    card = Scorecard(features=["a"], intercept=-0.5, coefficients={"a": -0.7}, removed=["b"])
    card.to_json(tmp_path / "s.json", model="test")
    again = Scorecard.from_json(tmp_path / "s.json")
    assert again == card


def test_manual_education_groups_are_kept():
    n = 3000
    edu = pd.Series(RNG.choice(["1", "2", "3", "4", "5"], n))
    y = pd.Series((RNG.random(n) < np.where(edu == "5", 0.45, 0.25)).astype(int))
    bp = fit_bins(pd.DataFrame({"Education": edu}), y)
    bins = bp.get_binned_variable("Education").transform(np.array(["4", "5", "2"]), "bins")
    assert str(bins[0]) == str(bins[1])  # 4 and 5 share a bin whatever the data say
    assert str(bins[0]) != str(bins[2])


def test_illogical_education_points_are_refused():
    class FakeBins:  # WoE per code: secondary (4) looks safer than higher (5)
        woe = {"1": -0.2, "2": -0.1, "3": -0.1, "4": 0.2, "5": 0.1}

        def get_binned_variable(self, name):
            return self

        def transform(self, x, metric):
            return np.array([self.woe[v] for v in x])

    card = Scorecard(features=["Education"], intercept=-0.5, coefficients={"Education": -0.3})
    with pytest.raises(IllogicalPointsError):
        check_logical_points(FakeBins(), card)
    FakeBins.woe["5"] = 0.2  # tie is fine: points never fall
    check_logical_points(FakeBins(), card)


def test_brier_of_perfect_predictions_is_zero():
    assert brier([0, 1, 1], [0.0, 1.0, 1.0]) == 0
    assert brier([0, 1], [0.5, 0.5]) == pytest.approx(0.25)


def test_gini_of_a_perfect_score_is_one():
    assert gini([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == pytest.approx(1)


# ------------------------------------------------------------------------- end to end


@pytest.mark.skipif(not S.DB_PATH.exists(), reason="warehouse not built (data are not in the repo)")
def test_pipeline_end_to_end(tmp_path):
    from pdengine.train import run

    result = run(S.DB_PATH, tmp_path, rebuild_samples=True)
    card = result["scorecard"]
    assert all(c < 0 for c in card.coefficients.values())  # every weight has the expected sign
    v1, v2 = result["metrics"]["v1_woe_scorecard"], result["metrics"]["champion_v2"]
    assert v1["test"]["gini"] > 0.40
    assert v1["oot"]["gini"] > 0.35  # roadmap target
    assert v2["test"]["gini"] > v1["test"]["gini"]  # D-028: v2 must beat v1 on test
    assert result["champion_v2"].card.order_violations() == []
    for f in ["model_samples.parquet", "binning_process.pkl", "scorecard.json", "champion_v2.pkl"]:
        assert (tmp_path / f).exists()


def test_screens_keep_weak_features_and_drop_derived_inputs():
    from types import SimpleNamespace

    from pdengine.selection import screen_features

    n = 6000
    country = pd.Series(RNG.choice(["EE", "FI"], n))
    signal = pd.Series(RNG.normal(size=n))
    y = pd.Series((RNG.random(n) < 1 / (1 + np.exp(-(signal - 0.8)))).astype(int))
    X = pd.DataFrame(
        {
            "signal": signal,
            "weak": RNG.normal(size=n) + 0.05 * signal,  # tiny IV: v1 would drop it, v2 keeps it
            "raw": signal + RNG.normal(scale=0.1, size=n),
            "derived": signal,
        }
    )
    sample = pd.Series(np.where(RNG.random(n) < 0.7, "train", "oot"))
    bp = fit_bins(X[sample.eq("train")], y[sample.eq("train")])
    reg = SimpleNamespace(derived={"derived": ["raw"]})  # only .derived is used
    sel = screen_features(bp, X, y, sample, country, reg)
    assert "weak" in sel.shortlist and "signal" in sel.shortlist
    assert "raw" not in sel.shortlist
    assert sel.table.loc["raw", "reason"] == "input of derived"
