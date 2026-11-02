"""Download the public Bondora loan dataset into data/raw/.

Bondora publishes a loan-level dataset of every loan issued on its platform
since February 2009. The Bondora investor product has been rebranded
Go & Grow, and the public statistics page now lives on goandgrow.eu. Three
sources are supported:

    official  Bondora / Go & Grow public statistics (default, most recent data)
              Page: https://goandgrow.eu/en/public-statistics/
              File: loan_dataset_investor.xlsx (hosted on Azure blob storage)
              Fallback: the legacy LoanData.zip URL used before the rebrand.

    kaggle    Community snapshot on Kaggle (static, covers 2009 to mid-2021)
              https://www.kaggle.com/datasets/sid321axn/bondora-peer-to-peer-lending-loan-data
              Needs the `kaggle` package and an API token (~/.kaggle/kaggle.json).

    ieee      IEEE DataPort snapshot (static, 2009-03-01 to 2020-01-27)
              https://ieee-dataport.org/open-access/bondora-peer-peer-lending-data
              DOI 10.21227/33kz-0s65. Download requires an IEEE account login,
              so the script only registers a zip you downloaded by hand
              (pass it with --file).

Every run writes the raw file(s) to data/raw/<source>/ and a manifest
(data/raw/<source>/manifest.json) recording the URL, timestamp, size and
SHA-256, so a model run can always be traced back to the exact file used.

Raw data is never committed: data/* is git-ignored.

Usage
-----
    python -m pdengine.download_data                       # official source
    python -m pdengine.download_data --source kaggle
    python -m pdengine.download_data --source ieee --file ~/Downloads/Bondora_dataset.zip
    python -m pdengine.download_data --force               # re-download even if present

Only the Python standard library is needed (plus `kaggle` for --source kaggle).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/pdengine/ -> repo root
RAW_DIR = PROJECT_ROOT / "data" / "raw"

# Official Bondora / Go & Grow public statistics. Tried in order; the first
# URL that answers with a real file wins.
OFFICIAL_URLS = [
    "https://sabanners001.blob.core.windows.net/statistics/public/loan_dataset_investor.xlsx",
    # Legacy location used on bondora.com/en/public-reports before the rebrand.
    "https://www.bondora.com/marketing/media/LoanData.zip",
]
OFFICIAL_PAGE = "https://goandgrow.eu/en/public-statistics/"

KAGGLE_DATASET = "sid321axn/bondora-peer-to-peer-lending-loan-data"
KAGGLE_PAGE = f"https://www.kaggle.com/datasets/{KAGGLE_DATASET}"

IEEE_PAGE = "https://ieee-dataport.org/open-access/bondora-peer-peer-lending-data"
IEEE_DOI = "10.21227/33kz-0s65"

USER_AGENT = "credit-risk-pd-engine-ifrs9/0.1 (+https://github.com/Langsi97)"
CHUNK = 1 << 20  # 1 MiB
MIN_BYTES = 1_000_000  # the real dataset is tens of MB; anything tiny is an error page


# --------------------------------------------------------------------------- helpers


def sha256sum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def safe_extract(zip_path: Path, dest: Path) -> list[Path]:
    """Extract a zip, refusing any member that would escape `dest`."""
    dest = dest.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            if dest != target and dest not in target.parents:
                raise ValueError(f"Unsafe path in archive: {member.filename!r}")
            if member.is_dir():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as out:
                shutil.copyfileobj(src, out)
            extracted.append(target)
    return extracted


def looks_like_data_file(path: Path) -> bool:
    """Reject HTML error pages saved under a .zip/.xlsx name."""
    with path.open("rb") as fh:
        head = fh.read(512).lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return False
    # .zip and .xlsx are both zip containers and start with PK\x03\x04
    if path.suffix.lower() in {".zip", ".xlsx"}:
        return head.startswith(b"pk\x03\x04")
    return True


def download(url: str, dest: Path, timeout: int = 120) -> Path:
    """Stream `url` to `dest` with a progress readout; write via a .part file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            block = resp.read(CHUNK)
            if not block:
                break
            out.write(block)
            done += len(block)
            if total:
                print(f"\r  {done / 1e6:7.1f} / {total / 1e6:.1f} MB", end="", flush=True)
            else:
                print(f"\r  {done / 1e6:7.1f} MB", end="", flush=True)
    print()
    if tmp.stat().st_size < MIN_BYTES or not looks_like_data_file(tmp):
        tmp.unlink(missing_ok=True)
        raise ValueError("response was not the dataset (too small or an HTML page)")
    tmp.replace(dest)
    return dest


def write_manifest(out_dir: Path, source: str, origin: str, files: list[Path]) -> Path:
    manifest = {
        "source": source,
        "origin": origin,
        "retrieved_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "files": [
            {
                "path": str(p.relative_to(PROJECT_ROOT)).replace("\\", "/"),
                "bytes": p.stat().st_size,
                "sha256": sha256sum(p),
            }
            for p in sorted(files)
        ],
    }
    path = out_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return path


def _finalise(out_dir: Path, source: str, origin: str, downloaded: Path) -> list[Path]:
    files = [downloaded]
    if downloaded.suffix.lower() == ".zip":
        print(f"Extracting {downloaded.name} ...")
        files += safe_extract(downloaded, out_dir)
    manifest = write_manifest(out_dir, source, origin, files)
    print(f"Wrote {len(files)} file(s) to {out_dir}")
    print(f"Manifest: {manifest}")
    return files


# --------------------------------------------------------------------------- sources


def fetch_official(out_dir: Path, force: bool) -> list[Path]:
    errors = []
    for url in OFFICIAL_URLS:
        dest = out_dir / url.rsplit("/", 1)[-1]
        if dest.exists() and not force:
            print(f"{dest.name} already present, skipping (use --force to refresh).")
            return _finalise(out_dir, "official", url, dest)
        print(f"Downloading {url}")
        try:
            download(url, dest)
            return _finalise(out_dir, "official", url, dest)
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            print(f"  failed: {exc}")
            errors.append(f"{url}: {exc}")
    raise SystemExit(
        "Could not download the official Bondora dataset.\n  "
        + "\n  ".join(errors)
        + f"\nOpen {OFFICIAL_PAGE}, download the loan dataset by hand, and register it with:\n"
        "  python -m pdengine.download_data --source official --file <path-to-file>"
    )


def fetch_kaggle(out_dir: Path, force: bool) -> list[Path]:
    if shutil.which("kaggle") is None:
        raise SystemExit(
            "The Kaggle CLI is not installed. Run `pip install kaggle`, place your API token "
            "in ~/.kaggle/kaggle.json (Windows: C:\\Users\\<you>\\.kaggle\\kaggle.json), "
            f"or download manually from {KAGGLE_PAGE} and pass --file."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = ["kaggle", "datasets", "download", "-d", KAGGLE_DATASET, "-p", str(out_dir)]
    if force:
        cmd.append("--force")
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    zips = sorted(out_dir.glob("*.zip"))
    if not zips:
        raise SystemExit("Kaggle CLI finished but no zip was found in " + str(out_dir))
    return _finalise(out_dir, "kaggle", KAGGLE_PAGE, zips[0])


def register_local(out_dir: Path, source: str, file: Path) -> list[Path]:
    file = file.expanduser().resolve()
    if not file.is_file():
        raise SystemExit(f"File not found: {file}")
    if not looks_like_data_file(file):
        raise SystemExit(f"{file.name} does not look like the dataset (HTML or not a zip).")
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / file.name
    if dest.resolve() != file:
        shutil.copy2(file, dest)
    origin = {
        "official": OFFICIAL_PAGE,
        "kaggle": KAGGLE_PAGE,
        "ieee": f"{IEEE_PAGE} (doi:{IEEE_DOI})",
    }[source]
    return _finalise(out_dir, source, f"manual download from {origin}", dest)


# --------------------------------------------------------------------------- CLI


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--source", choices=["official", "kaggle", "ieee"], default="official")
    p.add_argument("--file", type=Path, help="register a file you downloaded by hand")
    p.add_argument(
        "--out", type=Path, default=RAW_DIR, help="base output folder (default data/raw)"
    )
    p.add_argument("--force", action="store_true", help="re-download even if the file exists")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_dir = args.out / args.source
    if args.file:
        register_local(out_dir, args.source, args.file)
    elif args.source == "official":
        fetch_official(out_dir, args.force)
    elif args.source == "kaggle":
        fetch_kaggle(out_dir, args.force)
    else:
        raise SystemExit(
            f"IEEE DataPort needs a login. Download 'Bondora_dataset' from {IEEE_PAGE}, then run:\n"
            "  python -m pdengine.download_data --source ieee --file <path-to-zip>"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
