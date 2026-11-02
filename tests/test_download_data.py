"""Offline tests for src/pdengine/download_data.py (no network, stdlib only)."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from pdengine import download_data as dd


def test_sha256sum(tmp_path):
    f = tmp_path / "a.txt"
    f.write_bytes(b"bondora")
    assert dd.sha256sum(f) == hashlib.sha256(b"bondora").hexdigest()


def test_html_error_page_rejected(tmp_path):
    f = tmp_path / "LoanData.zip"
    f.write_text("<!DOCTYPE html><html>Access denied</html>")
    assert not dd.looks_like_data_file(f)


def test_safe_extract_and_zip_detected(tmp_path):
    z = tmp_path / "LoanData.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("LoanData.csv", "LoanId,Status\n1,Repaid\n")
    assert dd.looks_like_data_file(z)
    out = dd.safe_extract(z, tmp_path / "out")
    assert [p.name for p in out] == ["LoanData.csv"]


def test_safe_extract_blocks_path_traversal(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../escape.csv", "x")
    with pytest.raises(ValueError):
        dd.safe_extract(z, tmp_path / "out")


def test_register_local_writes_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(dd, "PROJECT_ROOT", tmp_path)
    src = tmp_path / "dl" / "Bondora_dataset.zip"
    src.parent.mkdir()
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("LoanData.csv", "LoanId\n1\n")
    out_dir = tmp_path / "data" / "raw" / "ieee"
    files = dd.register_local(out_dir, "ieee", src)
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["source"] == "ieee"
    assert len(manifest["files"]) == len(files) == 2
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])


# ---------------------------------------------------------------- kaggle source (offline)


def _fake_kaggle_cli(calls, make_zip=True):
    """Stand-in for subprocess.run: records the command and drops a zip in the -p folder."""

    def run(cmd, check):
        calls.append(cmd)
        out = Path(cmd[cmd.index("-p") + 1])
        if make_zip:
            with zipfile.ZipFile(out / "bondora-peer-to-peer-lending-loan-data.zip", "w") as zf:
                zf.writestr(
                    "LoanData_Bondora.csv", "LoanId,LoanDate,Status\nA1,2019-01-02,Repaid\n"
                )

    return run


def test_fetch_kaggle_cli_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(dd.shutil, "which", lambda _: None)
    with pytest.raises(SystemExit, match="Kaggle CLI is not installed"):
        dd.fetch_kaggle(tmp_path / "kaggle", force=False)


def test_fetch_kaggle_downloads_extracts_and_writes_manifest(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dd, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(dd.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(dd.subprocess, "run", _fake_kaggle_cli(calls))
    out_dir = tmp_path / "data" / "raw" / "kaggle"

    files = dd.fetch_kaggle(out_dir, force=False)

    assert calls[0][:4] == ["kaggle", "datasets", "download", "-d"]
    assert dd.KAGGLE_DATASET in calls[0] and "--force" not in calls[0]
    assert sorted(p.name for p in files) == [
        "LoanData_Bondora.csv",
        "bondora-peer-to-peer-lending-loan-data.zip",
    ]
    manifest = json.loads((out_dir / "manifest.json").read_text())
    assert manifest["source"] == "kaggle"
    assert manifest["origin"] == dd.KAGGLE_PAGE
    assert {f["path"] for f in manifest["files"]} == {
        "data/raw/kaggle/LoanData_Bondora.csv",
        "data/raw/kaggle/bondora-peer-to-peer-lending-loan-data.zip",
    }


def test_fetch_kaggle_passes_force_flag(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dd, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(dd.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(dd.subprocess, "run", _fake_kaggle_cli(calls))
    dd.fetch_kaggle(tmp_path / "data" / "raw" / "kaggle", force=True)
    assert calls[0][-1] == "--force"


def test_fetch_kaggle_without_zip_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(dd.shutil, "which", lambda _: "kaggle")
    monkeypatch.setattr(dd.subprocess, "run", _fake_kaggle_cli([], make_zip=False))
    with pytest.raises(SystemExit, match="no zip was found"):
        dd.fetch_kaggle(tmp_path / "kaggle", force=False)


def test_main_routes_kaggle_source(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        dd, "fetch_kaggle", lambda out_dir, force: seen.update(out=out_dir, force=force)
    )
    assert dd.main(["--source", "kaggle", "--out", str(tmp_path)]) == 0
    assert seen == {"out": tmp_path / "kaggle", "force": False}


# --------------------------------------------------------------------------- kaggle data on disk
# These run only where the data has been downloaded (your machine), and are skipped in CI.

KAGGLE_DIR = Path(__file__).resolve().parents[1] / "data" / "raw" / "kaggle"
KAGGLE_CSV = KAGGLE_DIR / "LoanData_Bondora.csv"
needs_kaggle_data = pytest.mark.skipif(
    not KAGGLE_CSV.exists(),
    reason="Kaggle snapshot not downloaded (python -m pdengine.download_data --source kaggle)",
)

KAGGLE_REQUIRED_COLUMNS = {
    "LoanId",
    "LoanDate",
    "Country",
    "Amount",
    "Interest",
    "LoanDuration",
    "MonthlyPayment",
    "Age",
    "Gender",
    "Education",
    "EmploymentStatus",
    "HomeOwnershipType",
    "IncomeTotal",
    "DebtToIncome",
    "LiabilitiesTotal",
    "NewCreditCustomer",
    "Status",
    "DefaultDate",
}


@needs_kaggle_data
def test_kaggle_files_match_manifest():
    manifest = json.loads((KAGGLE_DIR / "manifest.json").read_text())
    root = Path(__file__).resolve().parents[1]
    for entry in manifest["files"]:
        path = root / entry["path"]
        assert path.stat().st_size == entry["bytes"], entry["path"]
        assert dd.sha256sum(path) == entry["sha256"], entry["path"]


@needs_kaggle_data
def test_kaggle_csv_schema_and_keys():
    import pandas as pd

    header = pd.read_csv(KAGGLE_CSV, nrows=0).columns
    missing = KAGGLE_REQUIRED_COLUMNS - set(header)
    assert not missing, f"missing columns: {sorted(missing)}"

    df = pd.read_csv(KAGGLE_CSV, usecols=["LoanId", "LoanDate"], parse_dates=["LoanDate"])
    assert len(df) > 100_000
    assert df["LoanId"].notna().all() and df["LoanId"].is_unique
    assert df["LoanDate"].min() >= pd.Timestamp("2009-01-01")
    assert df["LoanDate"].max() <= pd.Timestamp("2021-12-31")
