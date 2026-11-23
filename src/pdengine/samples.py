"""Exclusions waterfall and modelling samples (notebook 03, D-008, D-010, D-013).

Starting from every joined loan, remove the groups that must not enter a modelling sample, one
rule at a time, and record what is left after each. Then split the population by issue date:
development (2016 to 2019, split at random into train and test) and out-of-time (2020 to July
2021).

Usage
-----
    python -m pdengine.samples          # writes data/processed/model_samples.parquet
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
from sklearn.model_selection import train_test_split

from pdengine import settings as S


@dataclass(frozen=True)
class Rule:
    name: str
    decision: str
    remove: bool  # False = flag only: the step is shown in the waterfall but removes nothing

    def applies(self, d: pd.DataFrame) -> pd.Series:
        return RULE_MASKS[self.name](d)


RULE_MASKS = {
    "Returned or InPostFundingReview": lambda d: d["loan_status"].isin(
        ["Returned", "InPostFundingReview"]
    ),
    "Early repaid within 14 days (withdrawal)": lambda d: d["early_repaid_14d"].eq(1),
    "Slovakia (flagged, kept in pool)": lambda d: d["country_name"].eq("Slovakia"),
    "Issued before 2016": lambda d: d["issue_date"] < pd.Timestamp(S.DEV_START),
    "Missing target": lambda d: d["y"].isna(),
}
RULES = [
    Rule("Returned or InPostFundingReview", "D-010", True),
    Rule("Early repaid within 14 days (withdrawal)", "roadmap Phase 2", True),
    Rule("Slovakia (flagged, kept in pool)", "D-008", False),
    Rule("Issued before 2016", "roadmap D3", True),
    Rule("Missing target", "guard", True),
]

BASE_QUERY = """
SELECT loan_key,
       "LoanDate"::DATE                    AS issue_date,
       country_name,
       off_loan_status                     AS loan_status,
       off_is_early_repaid_within_14_days  AS early_repaid_14d,
       off_has_default_within_12_months    AS y
FROM loans
"""


def load_base(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per joined loan with the columns the exclusions and samples need."""
    base = con.execute(BASE_QUERY).df()
    base["issue_date"] = pd.to_datetime(base["issue_date"])
    return base


def exclusions_waterfall(base: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply RULES in order. Returns (population left, waterfall table)."""

    def snapshot(d, step, removed, decision):
        return {
            "step": step,
            "removed": removed,
            "loans_left": len(d),
            "bads_left": int(d["y"].sum()),
            "default_rate_left": d["y"].mean(),
            "decision": decision,
        }

    left, rows = base.copy(), [snapshot(base, "All joined loans", 0, "")]
    for rule in RULES:
        hit = rule.applies(left)
        if rule.remove:
            left = left[~hit]
        rows.append(snapshot(left, rule.name, int(hit.sum()) if rule.remove else 0, rule.decision))
    return left, pd.DataFrame(rows)


def assign_samples(population: pd.DataFrame, seed: int = S.SEED) -> pd.DataFrame:
    """Label every loan train, test or oot. Train/test is stratified by issue year x target.

    The loans are sorted by key first: the database returns rows in a different order on every
    run, and a seeded random split is only reproducible if its input order is fixed (D-022).
    """
    pop = population.sort_values("loan_key").reset_index(drop=True)
    issue = pop["issue_date"]
    in_dev = issue < pd.Timestamp(S.OOT_START)
    in_oot = (issue >= pd.Timestamp(S.OOT_START)) & (issue < pd.Timestamp(S.OOT_END))
    if not (in_dev | in_oot).all():
        raise ValueError("a loan falls outside both sample windows")

    dev = pop[in_dev]
    strata = dev["issue_date"].dt.year.astype(str) + "_" + dev["y"].astype(int).astype(str)
    train_idx, test_idx = train_test_split(
        dev.index, test_size=S.TEST_SHARE, random_state=seed, stratify=strata
    )
    pop["sample"] = "oot"
    pop.loc[train_idx, "sample"] = "train"
    pop.loc[test_idx, "sample"] = "test"
    pop["y"] = pop["y"].astype(int)
    return pop[["loan_key", "issue_date", "country_name", "sample", "y"]].reset_index(drop=True)


def build(db: Path = S.DB_PATH, out: Path | None = S.PROCESSED / "model_samples.parquet"):
    """Warehouse -> samples. Returns (samples, waterfall); writes the samples if out is given."""
    con = duckdb.connect(str(db), read_only=True)
    try:
        base = load_base(con)
    finally:
        con.close()
    population, waterfall = exclusions_waterfall(base)
    samples = assign_samples(population)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        samples.to_parquet(out, index=False)
    return samples, waterfall


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the modelling samples (notebook 03).")
    p.add_argument("--db", type=Path, default=S.DB_PATH)
    p.add_argument("--out", type=Path, default=S.PROCESSED / "model_samples.parquet")
    args = p.parse_args(argv)
    samples, waterfall = build(args.db, args.out)
    print(waterfall.to_string(index=False))
    print(samples.groupby("sample")["y"].agg(["size", "mean"]).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
