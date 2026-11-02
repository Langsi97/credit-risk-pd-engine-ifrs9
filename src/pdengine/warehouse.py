"""Build the local Bondora data warehouse: raw files -> Parquet -> DuckDB.

Inputs (written by `python -m pdengine.download_data`):

    data/raw/kaggle/LoanData_Bondora.csv            borrower features, 2009 to mid-2021
    data/raw/official/loan_dataset_investor.xlsx    loan outcomes, refreshed monthly

Outputs:

    data/processed/kaggle_loans.parquet     Kaggle snapshot, original column names
    data/processed/official_loans.parquet   official feed, original column names
    data/bondora.duckdb                     the warehouse:
        kaggle_loans     table, one row per Kaggle loan
        official_loans   table, one row per official loan
        loans            view, Kaggle loans joined to their official outcomes;
                         official columns are prefixed `off_` so the source of
                         every value is visible, plus `loan_key`, `country_name`
                         (Kaggle ISO code mapped to a name) and `country_mismatch`
        _load_log        table, which raw file (and SHA-256) each table came from
        _checks          table, result of every integrity check in this build

The join and its checks follow notebooks/01_preliminary_eda.ipynb: loans are
matched on the GUID (`LoanId` = `loan_id`, compared in upper case), and the
Kaggle ISO country code is mapped to the official country name.

Integrity checks: duplicate loan IDs or Kaggle loans missing from the official
feed stop the build (the previous warehouse is kept). Joined loans whose two
sources disagree on country are flagged (`country_mismatch`) and counted, not
dropped: the real data has one such loan.

Parquet files are rebuilt only when missing, older than their source, or with
--force. The DuckDB file is always rebuilt from the Parquet files.

Usage
-----
    python -m pdengine.warehouse
    python -m pdengine.warehouse --force      # re-convert the raw files
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/pdengine/ -> repo root
DATA_DIR = PROJECT_ROOT / "data"

KAGGLE_RAW = Path("kaggle") / "LoanData_Bondora.csv"
OFFICIAL_RAW = Path("official") / "loan_dataset_investor.xlsx"

OFFICIAL_PREFIX = "off_"
ISO_TO_NAME = {"EE": "Estonia", "FI": "Finland", "ES": "Spain", "SK": "Slovakia"}


@dataclass(frozen=True)
class Paths:
    raw: Path
    processed: Path
    db: Path

    @classmethod
    def default(cls) -> Paths:
        return cls(DATA_DIR / "raw", DATA_DIR / "processed", DATA_DIR / "bondora.duckdb")

    @property
    def kaggle_raw(self) -> Path:
        return self.raw / KAGGLE_RAW

    @property
    def official_raw(self) -> Path:
        return self.raw / OFFICIAL_RAW

    @property
    def kaggle_parquet(self) -> Path:
        return self.processed / "kaggle_loans.parquet"

    @property
    def official_parquet(self) -> Path:
        return self.processed / "official_loans.parquet"


# --------------------------------------------------------------------------- step 1: Parquet


def _is_stale(target: Path, source: Path) -> bool:
    return not target.exists() or target.stat().st_mtime < source.stat().st_mtime


def convert_kaggle(src: Path, dest: Path) -> int:
    """CSV -> Parquet with DuckDB (fast, types inferred from the whole file)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(
        f"COPY (SELECT * FROM read_csv('{_sql_path(src)}', header = true, sample_size = -1)) "
        f"TO '{_sql_path(dest)}' (FORMAT parquet)"
    )
    return con.execute(f"SELECT count(*) FROM '{_sql_path(dest)}'").fetchone()[0]


def convert_official(src: Path, dest: Path) -> int:
    """Excel -> Parquet with pandas. Slow (minutes), which is why it runs only once."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_excel(src, dtype={"loan_id": "string"})
    df.to_parquet(dest, index=False)
    return len(df)


def build_parquet(paths: Paths, force: bool = False) -> None:
    steps = [
        ("kaggle", paths.kaggle_raw, paths.kaggle_parquet, convert_kaggle),
        ("official", paths.official_raw, paths.official_parquet, convert_official),
    ]
    for name, src, dest, convert in steps:
        if not src.exists():
            raise SystemExit(
                f"Missing raw file: {src}\nRun: python -m pdengine.download_data --source {name}"
            )
        if force or _is_stale(dest, src):
            print(f"Converting {src.name} -> {dest.name} ...")
            rows = convert(src, dest)
            print(f"  {rows:,} rows")
        else:
            print(f"{dest.name} is up to date, skipping (use --force to rebuild).")


# --------------------------------------------------------------------------- step 2: DuckDB


def _sql_path(path: Path) -> str:
    return path.resolve().as_posix().replace("'", "''")


def _manifest_hashes(raw_dir: Path) -> dict[str, str]:
    """Map raw file name -> SHA-256 recorded by the download script."""
    hashes = {}
    for manifest in raw_dir.glob("*/manifest.json"):
        for f in json.loads(manifest.read_text(encoding="utf-8"))["files"]:
            hashes[Path(f["path"]).name] = f["sha256"]
    return hashes


def _loans_view_sql(con: duckdb.DuckDBPyConnection) -> str:
    official_cols = [r[0] for r in con.execute("DESCRIBE official_loans").fetchall()]
    prefixed = ",\n    ".join(f'o."{c}" AS "{OFFICIAL_PREFIX}{c}"' for c in official_cols)
    country_case = " ".join(f"WHEN '{iso}' THEN '{name}'" for iso, name in ISO_TO_NAME.items())
    return f"""
CREATE OR REPLACE VIEW loans AS
SELECT
    upper(trim(k."LoanId")) AS loan_key,
    CASE k."Country" {country_case} ELSE k."Country" END AS country_name,
    (CASE k."Country" {country_case} ELSE k."Country" END) IS DISTINCT FROM o.country
        AS country_mismatch,
    k.*,
    {prefixed}
FROM kaggle_loans AS k
JOIN official_loans AS o
  ON upper(trim(k."LoanId")) = upper(trim(o.loan_id))
"""


def build_duckdb(paths: Paths) -> None:
    paths.db.parent.mkdir(parents=True, exist_ok=True)
    tmp_db = paths.db.with_suffix(".duckdb.tmp")
    tmp_db.unlink(missing_ok=True)

    con = duckdb.connect(str(tmp_db))
    try:
        for table, parquet in [
            ("kaggle_loans", paths.kaggle_parquet),
            ("official_loans", paths.official_parquet),
        ]:
            con.execute(f"CREATE TABLE {table} AS SELECT * FROM '{_sql_path(parquet)}'")
        con.execute(_loans_view_sql(con))

        hashes = _manifest_hashes(paths.raw)
        loaded_at = datetime.now(UTC).replace(tzinfo=None)
        con.execute(
            "CREATE TABLE _load_log (tbl VARCHAR, raw_file VARCHAR, raw_sha256 VARCHAR, "
            "n_rows BIGINT, loaded_at_utc TIMESTAMP)"
        )
        for table, raw in [
            ("kaggle_loans", paths.kaggle_raw),
            ("official_loans", paths.official_raw),
        ]:
            n = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            con.execute(
                "INSERT INTO _load_log VALUES (?, ?, ?, ?, ?)",
                [table, raw.name, hashes.get(raw.name), n, loaded_at],
            )
        for warning in check_integrity(con):
            print(f"  warning: {warning}")
    except BaseException:
        con.close()
        tmp_db.unlink(missing_ok=True)
        raise
    con.close()
    tmp_db.replace(paths.db)  # swap in only a complete, checked warehouse


# --------------------------------------------------------------------------- checks + summary


class IntegrityError(RuntimeError):
    pass


def check_integrity(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Check the assumptions from the preliminary EDA and record them in `_checks`.

    Raises IntegrityError for a broken key or join; returns warnings otherwise.
    """
    con.execute("CREATE TABLE _checks (check_name VARCHAR, n_failing BIGINT, severity VARCHAR)")

    def record(name: str, n: int, severity: str) -> int:
        con.execute("INSERT INTO _checks VALUES (?, ?, ?)", [name, n, severity])
        return n

    def scalar(sql: str) -> int:
        return con.execute(sql).fetchone()[0]

    errors = []
    for table, key in [("kaggle_loans", '"LoanId"'), ("official_loans", "loan_id")]:
        dupes = scalar(f"SELECT count(*) - count(DISTINCT upper(trim({key}))) FROM {table}")
        if record(f"{table}: duplicate loan IDs", dupes, "error"):
            errors.append(f"{table}: {dupes} duplicate loan IDs")

    n_kaggle = scalar("SELECT count(*) FROM kaggle_loans")
    n_joined = scalar("SELECT count(*) FROM loans")
    if record("kaggle loans missing from official feed", n_kaggle - n_joined, "error"):
        errors.append(f"Only {n_joined:,} of {n_kaggle:,} Kaggle loans matched the official feed")
    if errors:
        raise IntegrityError("; ".join(errors))

    warnings = []
    mismatched = scalar("SELECT count(*) FROM loans WHERE country_mismatch")
    if record("joined loans disagreeing on country", mismatched, "warning"):
        warnings.append(
            f"{mismatched:,} joined loan(s) disagree on country (flagged in loans.country_mismatch)"
        )
    return warnings


def summary(db: Path) -> pd.DataFrame:
    con = duckdb.connect(str(db), read_only=True)
    try:
        return con.execute(
            """
            SELECT 'kaggle_loans' AS object, count(*) AS n_rows,
                   min("LoanDate")::DATE AS first_loan, max("LoanDate")::DATE AS last_loan
            FROM kaggle_loans
            UNION ALL
            SELECT 'official_loans', count(*),
                   min(loan_issued_at)::DATE, max(loan_issued_at)::DATE
            FROM official_loans
            UNION ALL
            SELECT 'loans (joined view)', count(*),
                   min("LoanDate")::DATE, max("LoanDate")::DATE
            FROM loans
            """
        ).df()
    finally:
        con.close()


# --------------------------------------------------------------------------- CLI


def build(paths: Paths, force: bool = False) -> pd.DataFrame:
    build_parquet(paths, force=force)
    print(f"Building {paths.db.name} ...")
    build_duckdb(paths)
    result = summary(paths.db)
    print(result.to_string(index=False))
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    d = Paths.default()
    p.add_argument("--raw", type=Path, default=d.raw, help="raw data folder (default data/raw)")
    p.add_argument("--processed", type=Path, default=d.processed, help="Parquet output folder")
    p.add_argument(
        "--db", type=Path, default=d.db, help="DuckDB file (default data/bondora.duckdb)"
    )
    p.add_argument("--force", action="store_true", help="re-convert raw files to Parquet")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        build(Paths(args.raw, args.processed, args.db), force=args.force)
    except IntegrityError as exc:
        print(f"Integrity check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
