"""The feature registry: which Kaggle columns a model is allowed to use.

Why it exists
-------------
The Kaggle snapshot was frozen on 20 July 2021. Many of its columns describe what happened after
a loan started (2021 balance, late-payment category, recoveries). A model trained on them looks
excellent in testing and is useless on a new application: this is data leakage. The registry
gives every column exactly one class (see config/feature_registry.yaml) and this module enforces
it: `check_model_columns` raises an error if anything other than a candidate feature reaches a
model matrix.

Usage
-----
    from pdengine.registry import load_registry, candidate_features, check_model_columns

    reg = load_registry()
    features = candidate_features(reg)      # the raw columns a model may use
    check_model_columns(X.columns, reg)     # call before every model fit
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/pdengine/ -> repo root
DEFAULT_PATH = PROJECT_ROOT / "config" / "feature_registry.yaml"

CLASSES = ("key", "application", "protected", "personal", "benchmark", "outcome", "leak")


class RegistryError(ValueError):
    """The registry file itself is invalid (unknown class, impossible candidate, bad input)."""


class LeakageError(ValueError):
    """A model matrix contains a column that is not an allowed feature."""


@dataclass(frozen=True)
class Column:
    name: str
    cls: str  # "class" is a Python keyword, so the attribute is called cls
    candidate: bool
    source: str = ""
    note: str = ""


@dataclass(frozen=True)
class Registry:
    columns: dict[str, Column]
    derived: dict[str, tuple[str, ...]]  # engineered feature -> raw columns it is computed from


def load_registry(path: Path | str = DEFAULT_PATH) -> Registry:
    """Read the YAML file and check that it obeys the rules before anyone uses it."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    columns = {}
    for name, spec in (raw.get("columns") or {}).items():
        col = Column(
            name=name,
            cls=spec["class"],
            candidate=bool(spec.get("candidate", False)),
            source=spec.get("source", ""),
            note=spec.get("note", ""),
        )
        if col.cls not in CLASSES:
            raise RegistryError(f"{name}: unknown class {col.cls!r}; expected one of {CLASSES}")
        # The core rule: only information known at application may ever be a model input.
        if col.candidate and col.cls != "application":
            raise RegistryError(f"{name}: class {col.cls!r} can never be a candidate feature")
        columns[name] = col

    derived = {}
    for name, spec in (raw.get("derived") or {}).items():
        inputs = tuple(spec["inputs"])
        if name in columns:
            raise RegistryError(f"derived feature {name!r} has the same name as a raw column")
        # A derived feature is only as clean as its inputs: a ratio built from a leak is a leak.
        bad = [c for c in inputs if c not in columns or not columns[c].candidate]
        if bad:
            raise RegistryError(f"derived feature {name!r} uses non-candidate inputs: {bad}")
        derived[name] = inputs

    return Registry(columns=columns, derived=derived)


def candidate_features(reg: Registry) -> list[str]:
    """Raw columns a model may use, in file order."""
    return [c.name for c in reg.columns.values() if c.candidate]


def columns_of(reg: Registry, cls: str) -> list[str]:
    """All columns of one class, for example columns_of(reg, "protected") for the fairness step."""
    if cls not in CLASSES:
        raise RegistryError(f"unknown class {cls!r}")
    return [c.name for c in reg.columns.values() if c.cls == cls]


def check_model_columns(columns, reg: Registry) -> None:
    """Raise LeakageError unless every column is a candidate or a registered derived feature.

    Call this right before fitting or scoring any model.
    """
    allowed = set(candidate_features(reg)) | set(reg.derived)
    bad = [c for c in columns if c not in allowed]
    if bad:
        reasons = [
            f"{c} ({reg.columns[c].cls}{': ' + reg.columns[c].note if reg.columns[c].note else ''})"
            if c in reg.columns
            else f"{c} (not in the registry)"
            for c in bad
        ]
        raise LeakageError("Not allowed in a model matrix: " + "; ".join(reasons))
