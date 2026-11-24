"""Track A pipeline: warehouse -> samples -> bins -> the v1 WoE scorecard and champion v2.

Reproduces notebooks 03, 04, 05 (v1 WoE scorecard) and 07 (champion v2, the logical dummy
scorecard, D-028) without the notebooks.

Usage
-----
    python -m pdengine.train                     # reuse data/processed/model_samples.parquet
    python -m pdengine.train --rebuild-samples   # rebuild the samples from the warehouse first

Writes to data/processed/: model_samples.parquet (if rebuilt), binning_process.pkl,
scorecard_shortlist.json, feature_selection.csv, scorecard.json (v1), champion_v2.pkl,
champion_v2.json, champion_v2_points.csv, recalibration.json (D-030) and train_metrics.json.
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path

import cvxpy  # noqa: F401  load before pandas/pyarrow on Windows (D-026)
import duckdb
import pandas as pd

from pdengine import samples as samples_mod
from pdengine import settings as S
from pdengine.calibration import CountryRecalibration, calibration_table
from pdengine.champion import fit_champion
from pdengine.dataset import load_model_data
from pdengine.registry import load_registry
from pdengine.scorecard import brier, check_logical_points, fit_scorecard, gini, ks
from pdengine.selection import fit_bins, select_features, transform


def run(db: Path = S.DB_PATH, out_dir: Path = S.PROCESSED, rebuild_samples: bool = False) -> dict:
    samples_path = out_dir / "model_samples.parquet"
    if rebuild_samples or not samples_path.exists():
        samples, _ = samples_mod.build(db, samples_path)
    else:
        samples = pd.read_parquet(samples_path)

    reg = load_registry()
    con = duckdb.connect(str(db), read_only=True)
    try:
        data = load_model_data(con, samples, reg)
    finally:
        con.close()
    tr = data.sample.eq("train")

    bp = fit_bins(data.X[tr], data.y[tr])  # train only
    selection = select_features(bp, data.X, data.y, data.sample, data.country, reg)
    woe = transform(bp, data.X, "woe")
    card = fit_scorecard(woe[tr], data.y[tr], selection.shortlist)
    card.build_points(bp)
    check_logical_points(bp, card)  # D-023

    v2 = fit_champion(data.X, data.y, data.sample, data.country, reg)  # D-028
    if v2.card.order_violations():
        raise ValueError(f"champion v2 points break the risk order: {v2.card.order_violations()}")

    predictions = {
        "v1_woe_scorecard": card.predict_pd(woe),
        "champion_v2": v2.predict_pd(data.X, data.country),
    }
    # D-030: one logit shift per country, fitted on every post-break out-of-time loan.
    # Fit on the whole OOT sample so a country with no loans in the window (Spain) is flagged.
    oot = data.sample.eq("oot")
    post = oot & data.issue_date.ge(S.RECAL_START)
    recal = CountryRecalibration().fit(
        data.y[oot], predictions["champion_v2"][oot], data.country[oot], data.issue_date[oot]
    )
    recal_check = calibration_table(
        data.y[post],
        recal.transform(predictions["champion_v2"][post], data.country[post]),
        data.country[post],
    )

    metrics = {}
    for model, pd_hat in predictions.items():
        metrics[model] = {}
        for name in ["train", "test", "oot"]:
            m = data.sample.eq(name)
            metrics[model][name] = {
                "loans": int(m.sum()),
                "gini": round(gini(data.y[m], pd_hat[m]), 4),
                "ks": round(ks(data.y[m], pd_hat[m]), 4),
                "brier": round(brier(data.y[m], pd_hat[m]), 4),
                "gini_bondora_pd": round(gini(data.y[m], data.bondora_pd[m]), 4),
                "mean_pd": round(float(pd_hat[m].mean()), 4),
                "default_rate": round(float(data.y[m].mean()), 4),
            }

    out_dir.mkdir(parents=True, exist_ok=True)
    bp.save(str(out_dir / "binning_process.pkl"))
    (out_dir / "scorecard_shortlist.json").write_text(
        json.dumps({"features": selection.shortlist}, indent=2), encoding="utf-8"
    )
    selection.table.to_csv(out_dir / "feature_selection.csv")
    card.to_json(out_dir / "scorecard.json", model="WoE logistic scorecard (champion), D-021")
    with open(out_dir / "champion_v2.pkl", "wb") as fh:
        pickle.dump(v2, fh)
    v2.card.to_json(
        out_dir / "champion_v2.json",
        model="Logical dummy scorecard (champion v2), D-028",
        features=v2.features,
        flat_dropped=v2.flat,
    )
    v2.card.points_table().to_csv(out_dir / "champion_v2_points.csv", index=False)
    recal.to_json(
        out_dir / "recalibration.json",
        model="Champion v2 intercept shift per country, D-030",
        check=recal_check[["loans", "default_rate", "mean_pd", "jeffreys_p"]]
        .astype(float)
        .round(4)
        .to_dict(orient="index"),
    )
    (out_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {
        "shortlist": selection.shortlist,
        "scorecard": card,
        "champion_v2": v2,
        "recalibration": recal,
        "metrics": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fit the v1 WoE scorecard and champion v2.")
    p.add_argument("--db", type=Path, default=S.DB_PATH)
    p.add_argument("--out-dir", type=Path, default=S.PROCESSED)
    p.add_argument("--rebuild-samples", action="store_true")
    args = p.parse_args(argv)
    result = run(args.db, args.out_dir, args.rebuild_samples)
    card = result["scorecard"]
    print("Shortlist:", result["shortlist"])
    print("Removed by the sign check:", card.removed)
    print("v1 WoE scorecard:", card.features)
    print("Champion v2 features:", result["champion_v2"].features)
    rec = result["recalibration"]
    print("Recalibration shifts (logit):", {k: round(v, 3) for k, v in rec.shifts.items()})
    print("Not recalibrated (too few post-break loans):", rec.not_recalibrated)
    for model, m in result["metrics"].items():
        print(f"\n{model}\n" + pd.DataFrame(m).T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
