"""Track A pipeline: warehouse -> samples -> bins -> feature selection -> champion scorecard.

Reproduces notebooks 03, 04 and 05 without the notebooks.

Usage
-----
    python -m pdengine.train                     # reuse data/processed/model_samples.parquet
    python -m pdengine.train --rebuild-samples   # rebuild the samples from the warehouse first

Writes to data/processed/: model_samples.parquet (if rebuilt), binning_process.pkl,
scorecard_shortlist.json, feature_selection.csv, scorecard.json and train_metrics.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cvxpy  # noqa: F401  load before pandas/pyarrow on Windows (D-026)
import duckdb
import pandas as pd

from pdengine import samples as samples_mod
from pdengine import settings as S
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

    pd_hat = card.predict_pd(woe)
    metrics = {}
    for name in ["train", "test", "oot"]:
        m = data.sample.eq(name)
        metrics[name] = {
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
    (out_dir / "train_metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return {"shortlist": selection.shortlist, "scorecard": card, "metrics": metrics}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fit the Track A champion scorecard.")
    p.add_argument("--db", type=Path, default=S.DB_PATH)
    p.add_argument("--out-dir", type=Path, default=S.PROCESSED)
    p.add_argument("--rebuild-samples", action="store_true")
    args = p.parse_args(argv)
    result = run(args.db, args.out_dir, args.rebuild_samples)
    card = result["scorecard"]
    print("Shortlist:", result["shortlist"])
    print("Removed by the sign check:", card.removed)
    print("Champion:", card.features)
    print(pd.DataFrame(result["metrics"]).T.to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
