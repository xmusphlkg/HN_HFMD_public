"""Generate deterministic, aggregation-safe synthetic HFMD data.

The generator creates fictional regions and index-based epidemiological time.
It does not sample, perturb, or otherwise derive from restricted Hunan cells.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import FieldSpec, TableContract, validate_csv

GENERATOR_VERSION = "1.0.0"
REGIONS = (
    "Aster",
    "Brindle",
    "Cobalt",
    "Driftwood",
    "Ember",
    "Fable",
    "Garnet",
    "Harbor",
)
AGE_GROUPS = ("lt1", "age1_2", "age3_5", "age6_14", "age15plus")
PATHOGENS = ("ev_a71", "cv_a16", "other_enterovirus")
SEVERITY = ("non_severe", "severe")


WEEKLY_CONTRACT = TableContract(
    name="synthetic_weekly_surveillance",
    fields=(
        FieldSpec("synthetic_region", choices=REGIONS),
        FieldSpec("year", "integer", minimum=2000, maximum=2100),
        FieldSpec("iso_week", "integer", minimum=1, maximum=53),
        FieldSpec("age_group", choices=AGE_GROUPS),
        FieldSpec("pathogen_group", choices=PATHOGENS),
        FieldSpec("severity_group", choices=SEVERITY),
        FieldSpec("cases", "integer", minimum=10),
        FieldSpec("typed_cases", "integer", minimum=10),
        FieldSpec("population", "integer", minimum=10_000),
        FieldSpec("ev_a71_vaccine_proxy", "number", minimum=0, maximum=1),
    ),
    primary_key=(
        "synthetic_region",
        "year",
        "iso_week",
        "age_group",
        "pathogen_group",
        "severity_group",
    ),
)

CONTACT_CONTRACT = TableContract(
    name="synthetic_contact_matrix",
    fields=(
        FieldSpec("age_from", choices=AGE_GROUPS),
        FieldSpec("age_to", choices=AGE_GROUPS),
        FieldSpec("contact_rate", "number", minimum=0, maximum=50),
    ),
    primary_key=("age_from", "age_to"),
)

REGION_CONTRACT = TableContract(
    name="synthetic_region_metadata",
    fields=(
        FieldSpec("synthetic_region", choices=REGIONS),
        FieldSpec("population_scale", "integer", minimum=100_000),
        FieldSpec("climate_index", "number", minimum=-2, maximum=2),
    ),
    primary_key=("synthetic_region",),
)

TYPING_SELECTION_CONTRACT = TableContract(
    name="synthetic_typing_selection",
    fields=(
        FieldSpec("synthetic_region", choices=REGIONS),
        FieldSpec("year", "integer", minimum=2000, maximum=2100),
        FieldSpec("iso_week", "integer", minimum=1, maximum=53),
        FieldSpec("age_group", choices=AGE_GROUPS),
        FieldSpec("severity_status", choices=("nonsevere", "severe", "unknown")),
        FieldSpec("case_class", choices=("clinical", "confirmed")),
        FieldSpec("testing_stage", choices=("not_tested", "resolved_pathogen")),
        FieldSpec("pathogen_group", choices=(*PATHOGENS, "untyped")),
        FieldSpec("reported_cases", "integer", minimum=10),
    ),
    primary_key=(
        "synthetic_region",
        "year",
        "iso_week",
        "age_group",
        "severity_status",
        "case_class",
        "testing_stage",
        "pathogen_group",
    ),
)


@dataclass(frozen=True, slots=True)
class SyntheticShape:
    regions: int
    start_year: int
    years: int
    weeks_per_year: int


SHAPES = {
    "ci": SyntheticShape(regions=3, start_year=2012, years=14, weeks_per_year=13),
    "synthetic": SyntheticShape(regions=len(REGIONS), start_year=2012, years=14, weeks_per_year=52),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _unit_interval(seed: int, *parts: object) -> float:
    payload = "|".join([str(seed), *(str(part) for part in parts)]).encode()
    raw = hashlib.sha256(payload).digest()[:8]
    return int.from_bytes(raw, "big") / float(2**64)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


def _weekly_rows(shape: SyntheticShape, seed: int) -> Iterable[dict[str, Any]]:
    age_weight = {
        "lt1": 1.75,
        "age1_2": 2.2,
        "age3_5": 1.45,
        "age6_14": 0.55,
        "age15plus": 0.18,
    }
    pathogen_weight = {"ev_a71": 1.0, "cv_a16": 0.72, "other_enterovirus": 0.86}
    for region_index, region in enumerate(REGIONS[: shape.regions]):
        population = 420_000 + region_index * 73_000
        for year in range(shape.start_year, shape.start_year + shape.years):
            rollout = 1.0 / (1.0 + math.exp(-(year - 2018.0) / 1.35))
            for week in range(1, shape.weeks_per_year + 1):
                seasonal = 1.0 + 0.34 * math.sin(2 * math.pi * (week - 7) / 52)
                for age in AGE_GROUPS:
                    for pathogen in PATHOGENS:
                        vaccine_factor = 1.0
                        if pathogen == "ev_a71":
                            vaccine_factor = 1.0 - 0.58 * rollout
                        elif pathogen == "cv_a16":
                            vaccine_factor = 1.0 + 0.10 * rollout
                        for severity in SEVERITY:
                            severity_factor = 0.13 if severity == "severe" else 1.0
                            noise = 0.86 + 0.28 * _unit_interval(
                                seed, region, year, week, age, pathogen, severity
                            )
                            expected = (
                                95
                                * (1 + region_index * 0.055)
                                * age_weight[age]
                                * pathogen_weight[pathogen]
                                * seasonal
                                * vaccine_factor
                                * severity_factor
                                * noise
                            )
                            cases = max(20, int(round(expected)))
                            typing_fraction = 0.56 if severity == "severe" else 0.38
                            typed = max(
                                10,
                                min(cases - 10, int(round(cases * typing_fraction))),
                            )
                            yield {
                                "synthetic_region": region,
                                "year": year,
                                "iso_week": week,
                                "age_group": age,
                                "pathogen_group": pathogen,
                                "severity_group": severity,
                                "cases": cases,
                                "typed_cases": typed,
                                "population": population,
                                "ev_a71_vaccine_proxy": f"{rollout:.6f}",
                            }


def _typing_rows(shape: SyntheticShape, seed: int) -> Iterable[dict[str, Any]]:
    untyped_counts: dict[tuple[Any, ...], int] = {}
    for row in _weekly_rows(shape, seed):
        severe = row["severity_group"] == "severe"
        common = {
            "synthetic_region": row["synthetic_region"],
            "year": row["year"],
            "iso_week": row["iso_week"],
            "age_group": row["age_group"],
            "severity_status": "severe" if severe else "nonsevere",
            "case_class": "confirmed" if severe else "clinical",
        }
        yield {
            **common,
            "testing_stage": "resolved_pathogen",
            "pathogen_group": row["pathogen_group"],
            "reported_cases": row["typed_cases"],
        }
        key = (
            common["synthetic_region"],
            common["year"],
            common["iso_week"],
            common["age_group"],
            common["severity_status"],
            common["case_class"],
        )
        untyped_counts[key] = untyped_counts.get(key, 0) + (row["cases"] - row["typed_cases"])
    for key in sorted(untyped_counts):
        region, year, week, age, severity_status, case_class = key
        yield {
            "synthetic_region": region,
            "year": year,
            "iso_week": week,
            "age_group": age,
            "severity_status": severity_status,
            "case_class": case_class,
            "testing_stage": "not_tested",
            "pathogen_group": "untyped",
            "reported_cases": untyped_counts[key],
        }


def _contact_rows() -> Iterable[dict[str, Any]]:
    for i, source in enumerate(AGE_GROUPS):
        for j, target in enumerate(AGE_GROUPS):
            distance = abs(i - j)
            rate = 2.1 + 8.5 * math.exp(-0.9 * distance) + (2.0 if i == j else 0)
            yield {
                "age_from": source,
                "age_to": target,
                "contact_rate": f"{rate:.6f}",
            }


def _region_rows(shape: SyntheticShape, seed: int) -> Iterable[dict[str, Any]]:
    for index, region in enumerate(REGIONS[: shape.regions]):
        yield {
            "synthetic_region": region,
            "population_scale": 420_000 + index * 73_000,
            "climate_index": f"{-0.8 + 1.6 * _unit_interval(seed, region, 'climate'):.6f}",
        }


def _atomic_text(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o644)


def validate_synthetic_directory(path: Path | str) -> dict[str, Any]:
    root = Path(path)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Synthetic data root is not a regular directory: {root}")
    reports = [
        validate_csv(root / "weekly_surveillance.csv", WEEKLY_CONTRACT),
        validate_csv(root / "typing_selection.csv", TYPING_SELECTION_CONTRACT),
        validate_csv(root / "contact_matrix.csv", CONTACT_CONTRACT),
        validate_csv(root / "region_metadata.csv", REGION_CONTRACT),
    ]
    manifest_path = root / "synthetic_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Synthetic manifest is missing or unsafe")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported synthetic manifest schema")
    if manifest.get("provenance") != "fully_synthetic_not_derived_from_restricted_cells":
        raise ValueError("Synthetic provenance declaration is missing")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError("Synthetic manifest has no file registry")
    registered_paths: list[str] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("Synthetic manifest contains a missing path")
        relative = Path(record["path"])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 1:
            raise ValueError(f"Unsafe synthetic manifest path: {relative}")
        registered_paths.append(relative.as_posix())
    if len(set(registered_paths)) != len(records):
        raise ValueError("Synthetic manifest contains duplicate paths")
    expected = set(registered_paths) | {"synthetic_manifest.json"}
    entries = tuple(root.iterdir())
    unsafe_entries = sorted(
        path.name for path in entries if path.is_symlink() or not path.is_file()
    )
    if unsafe_entries:
        raise ValueError(
            f"Synthetic directory may contain only regular top-level files: unsafe={unsafe_entries}"
        )
    actual = {path.name for path in entries}
    if actual != expected:
        raise ValueError(
            f"Synthetic directory file set mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )
    for record in records:
        relative = Path(record["path"])
        candidate = root / record["path"]
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError(f"Synthetic manifest file is missing or unsafe: {candidate}")
        if candidate.stat().st_size != record["bytes"]:
            raise ValueError(f"Synthetic manifest byte mismatch: {candidate}")
        if sha256_file(candidate) != record["sha256"]:
            raise ValueError(f"Synthetic manifest hash mismatch: {candidate}")
    return {"status": "valid", "tables": reports, "manifest_files": len(manifest["files"])}


def generate_synthetic_directory(
    output: Path | str,
    *,
    profile: str = "synthetic",
    seed: int = 20260717,
    replace: bool = False,
) -> dict[str, Any]:
    if profile not in SHAPES:
        raise ValueError(f"Unknown synthetic profile: {profile}")
    destination = Path(output).resolve()
    if destination.exists() and not replace:
        raise FileExistsError(f"Refusing to replace existing synthetic output: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=destination.parent))
    backup: Path | None = None
    try:
        shape = SHAPES[profile]
        _write_csv(
            staging / "weekly_surveillance.csv",
            WEEKLY_CONTRACT.columns,
            _weekly_rows(shape, seed),
        )
        _write_csv(
            staging / "typing_selection.csv",
            TYPING_SELECTION_CONTRACT.columns,
            _typing_rows(shape, seed),
        )
        _write_csv(staging / "contact_matrix.csv", CONTACT_CONTRACT.columns, _contact_rows())
        _write_csv(
            staging / "region_metadata.csv",
            REGION_CONTRACT.columns,
            _region_rows(shape, seed),
        )
        _atomic_text(
            staging / "README.md",
            "# Synthetic HFMD data\n\n"
            "These records were generated from deterministic mathematical functions over "
            "fictional regions. They are not sampled from, perturbed from, or linked to "
            "restricted Hunan observations.\n",
        )
        _atomic_text(
            staging / "DATA_DICTIONARY.md",
            "# Data dictionary\n\n"
            "`synthetic_region` is a fictional label; `year` and `iso_week` are aggregate "
            "time indices; counts are deliberately bounded at ten or more; "
            "`ev_a71_vaccine_proxy` is a generated sigmoid exposure.\n",
        )
        _atomic_text(
            staging / "DATA_LICENSE.txt",
            "CC0 1.0 Universal. To the extent possible under law, the synthetic data "
            "generator output is dedicated to the public domain.\n",
        )
        payload_files = sorted(
            path for path in staging.iterdir() if path.name != "synthetic_manifest.json"
        )
        manifest = {
            "schema_version": 1,
            "generator": "hfmd.data.synthetic",
            "generator_version": GENERATOR_VERSION,
            "profile": profile,
            "seed": seed,
            "provenance": "fully_synthetic_not_derived_from_restricted_cells",
            "shape": {
                "regions": shape.regions,
                "start_year": shape.start_year,
                "years": shape.years,
                "weeks_per_year": shape.weeks_per_year,
            },
            "files": [
                {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in payload_files
            ],
        }
        _atomic_text(
            staging / "synthetic_manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        validate_synthetic_directory(staging)
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.rollback-{os.getpid()}")
            if backup.exists() or backup.is_symlink():
                raise FileExistsError(f"Unsafe rollback path already exists: {backup}")
            destination.replace(backup)
        staging.replace(destination)
        if backup is not None:
            shutil.rmtree(backup)
        return validate_synthetic_directory(destination)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup is not None and backup.exists() and not destination.exists():
            backup.replace(destination)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--profile", choices=sorted(SHAPES), default="synthetic")
    parser.add_argument("--seed", type=int, default=20260717)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.validate_only:
        result = validate_synthetic_directory(args.output)
    else:
        result = generate_synthetic_directory(
            args.output, profile=args.profile, seed=args.seed, replace=args.replace
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
