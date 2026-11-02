"""Offline tests for pdengine.warehouse, using tiny fake raw files."""

import json

import duckdb
import pandas as pd
import pytest

from pdengine import warehouse as wh

KAGGLE_ROWS = [
    # LoanId stored in mixed case on purpose: the join must not depend on it.
    {"LoanId": "aaaa-1", "LoanDate": "2019-01-02", "Country": "EE", "Amount": 500.0, "Age": 30},
    {"LoanId": "BBBB-2", "LoanDate": "2020-06-30", "Country": "ES", "Amount": 1000.0, "Age": 45},
]
OFFICIAL_ROWS = [
    {"loan_id": "AAAA-1", "country": "Estonia", "loan_issued_at": "2019-01-02",
     "issued_amount": 500.0, "has_default_within_12_months": 0.0},
    {"loan_id": "BBBB-2", "country": "Spain", "loan_issued_at": "2020-06-30",
     "issued_amount": 1000.0, "has_default_within_12_months": 1.0},
    {"loan_id": "CCCC-3", "country": "Finland", "loan_issued_at": "2024-03-01",
     "issued_amount": 750.0, "has_default_within_12_months": None},
]  # fmt: skip


def make_raw(root, kaggle_rows=KAGGLE_ROWS, official_rows=OFFICIAL_ROWS):
    raw = root / "raw"
    (raw / "kaggle").mkdir(parents=True)
    (raw / "official").mkdir(parents=True)
    pd.DataFrame(kaggle_rows).to_csv(raw / wh.KAGGLE_RAW, index=False)
    official = pd.DataFrame(official_rows)
    official["loan_issued_at"] = pd.to_datetime(official["loan_issued_at"])
    official.to_excel(raw / wh.OFFICIAL_RAW, index=False)
    for source, name in [
        ("kaggle", "LoanData_Bondora.csv"),
        ("official", "loan_dataset_investor.xlsx"),
    ]:
        manifest = {
            "source": source,
            "files": [
                {"path": f"data/raw/{source}/{name}", "bytes": 1, "sha256": f"{source}-hash"}
            ],
        }
        (raw / source / "manifest.json").write_text(json.dumps(manifest))
    return wh.Paths(raw, root / "processed", root / "bondora.duckdb")


@pytest.fixture
def paths(tmp_path):
    return make_raw(tmp_path)


def query(paths, sql):
    con = duckdb.connect(str(paths.db), read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()


def test_build_creates_parquet_tables_and_view(paths):
    wh.build(paths)
    assert paths.kaggle_parquet.exists() and paths.official_parquet.exists()
    counts = query(
        paths,
        """
        SELECT (SELECT count(*) FROM kaggle_loans)   AS k,
               (SELECT count(*) FROM official_loans) AS o,
               (SELECT count(*) FROM loans)          AS j
    """,
    ).iloc[0]
    assert (counts.k, counts.o, counts.j) == (2, 3, 2)


def test_loans_view_joins_case_insensitively_and_prefixes_official(paths):
    wh.build(paths)
    loans = query(paths, "SELECT * FROM loans ORDER BY loan_key")
    assert loans["loan_key"].tolist() == ["AAAA-1", "BBBB-2"]
    assert loans["country_name"].tolist() == ["Estonia", "Spain"]
    assert loans["off_has_default_within_12_months"].tolist() == [0.0, 1.0]
    assert "LoanId" in loans.columns and "off_loan_id" in loans.columns
    assert "loan_id" not in loans.columns  # official columns only appear prefixed


def test_load_log_records_manifest_hashes(paths):
    wh.build(paths)
    log = query(paths, "SELECT tbl, raw_sha256, n_rows FROM _load_log ORDER BY tbl")
    assert log.to_dict("records") == [
        {"tbl": "kaggle_loans", "raw_sha256": "kaggle-hash", "n_rows": 2},
        {"tbl": "official_loans", "raw_sha256": "official-hash", "n_rows": 3},
    ]


def test_parquet_is_not_rebuilt_when_up_to_date(paths, monkeypatch):
    wh.build(paths)
    calls = []
    monkeypatch.setattr(wh, "convert_official", lambda s, d: calls.append(d) or 0)
    monkeypatch.setattr(wh, "convert_kaggle", lambda s, d: calls.append(d) or 0)
    wh.build_parquet(paths)
    assert calls == []
    wh.build_parquet(paths, force=True)
    assert len(calls) == 2


def test_unmatched_kaggle_loan_fails_and_keeps_old_db(tmp_path):
    paths = make_raw(tmp_path)
    wh.build(paths)
    bad = make_raw(
        tmp_path / "bad", kaggle_rows=[*KAGGLE_ROWS, {**KAGGLE_ROWS[0], "LoanId": "ZZZZ-9"}]
    )
    bad = wh.Paths(bad.raw, bad.processed, paths.db)  # point at the existing good DB
    with pytest.raises(wh.IntegrityError, match="2 of 3"):
        wh.build(bad)
    assert query(paths, "SELECT count(*) AS n FROM kaggle_loans").n[0] == 2
    assert not paths.db.with_suffix(".duckdb.tmp").exists()


def test_duplicate_ids_fail(tmp_path):
    paths = make_raw(tmp_path, kaggle_rows=[*KAGGLE_ROWS, {**KAGGLE_ROWS[1], "LoanId": "bbbb-2"}])
    with pytest.raises(wh.IntegrityError, match="duplicate"):
        wh.build(paths)


def test_missing_raw_file_explains_how_to_download(tmp_path):
    paths = wh.Paths(tmp_path / "raw", tmp_path / "processed", tmp_path / "w.duckdb")
    with pytest.raises(SystemExit, match="download_data --source kaggle"):
        wh.build(paths)


def test_country_mismatch_is_flagged_not_fatal(tmp_path):
    rows = [{**KAGGLE_ROWS[0], "Country": "FI"}, KAGGLE_ROWS[1]]  # official says Estonia
    paths = make_raw(tmp_path, kaggle_rows=rows)
    wh.build(paths)
    flags = query(paths, "SELECT loan_key, country_mismatch FROM loans ORDER BY loan_key")
    assert flags["country_mismatch"].tolist() == [True, False]
    checks = query(paths, "SELECT check_name, n_failing FROM _checks WHERE severity = 'warning'")
    assert checks["n_failing"].tolist() == [1]
