#!/usr/bin/env python3
"""Synchronize the deny-by-default aggregate result-data release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

PUBLIC_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PUBLIC_ROOT / "src"))

from hfmd.privacy.audit import FileMetadata, audit_tree  # noqa: E402


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def safe_relative(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe {label}: {value!r}")
    return path


def write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o644)
    temporary.replace(path)


def parse_integer(value: str) -> int:
    return int(value.replace(",", "").strip())


def parse_percent(value: str) -> float:
    return float(value.replace("%", "").strip())


def observation_summary(payload: bytes) -> bytes:
    rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
    years = [row for row in rows if row["Row type"] == "Stratum" and row["Stratum type"] == "Year"]
    summaries = {
        row["Stratum or statistic"]: row["Summary value"]
        for row in rows
        if row["Row type"] == "Summary"
    }
    reported = sum(parse_integer(row["Reported cases"]) for row in years)
    labelled = sum(parse_integer(row["Labelled cases"]) for row in years)
    annual_fractions = [parse_percent(row["Observed labelled fraction"]) for row in years]
    output_rows = [
        {
            "metric": "complete_week_reported_cases",
            "value": str(reported),
            "unit": "reports",
            "description": "Reports in the 834 complete province-wide surveillance weeks",
        },
        {
            "metric": "reports_with_resolvable_final_pathogen_label",
            "value": str(labelled),
            "unit": "reports",
            "description": "Reports carrying a resolvable final nucleic-acid pathogen label",
        },
        {
            "metric": "overall_resolvable_label_fraction",
            "value": summaries["Overall labelled fraction"].replace("%", ""),
            "unit": "percent",
            "description": "Resolvable-label reports divided by complete-week reports",
        },
        {
            "metric": "annual_resolvable_label_fraction_range",
            "value": f"{min(annual_fractions):.2f}–{max(annual_fractions):.2f}",
            "unit": "percent",
            "description": "Minimum and maximum annual resolvable-label fraction",
        },
        {
            "metric": "median_fitted_label_probability",
            "value": summaries["Median fitted label probability"].replace("%", ""),
            "unit": "percent",
            "description": "Median fitted probability of a resolvable final pathogen label",
        },
        {
            "metric": "reports_in_cells_below_probability_0_05",
            "value": summaries["Reports in cells with fitted probability <0.05"].replace("%", ""),
            "unit": "percent",
            "description": "Reported-case burden in observation cells with fitted probability below 0.05",
        },
        {
            "metric": "stabilized_weight_truncation_limits",
            "value": summaries["Stabilized-weight truncation limits"].replace(" to ", "–"),
            "unit": "ratio",
            "description": "Lower and upper limits applied to stabilized selection weights",
        },
        {
            "metric": "resolved_records_affected_by_weight_truncation",
            "value": summaries["Resolved records affected by weight truncation"].replace("%", ""),
            "unit": "percent",
            "description": "Resolved-label records whose stabilized weights were truncated",
        },
        {
            "metric": "effective_labelled_sample_size",
            "value": summaries["Effective sample size"].replace(",", ""),
            "unit": "reports",
            "description": "Inverse-probability-weighted effective labelled sample size",
        },
        {
            "metric": "effective_sample_fraction",
            "value": summaries["Effective sample fraction"].replace("%", ""),
            "unit": "percent",
            "description": "Effective labelled sample size divided by resolvable-label reports",
        },
        {
            "metric": "observation_model_optimization",
            "value": summaries["Observation-model optimization"],
            "unit": "status",
            "description": "Optimization status of the one-stage label-resolution model",
        },
    ]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=["metric", "value", "unit", "description"],
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(output_rows)
    return stream.getvalue().encode("utf-8")


TRANSFORMS = {
    "copy": lambda payload: payload,
    "observation_summary": observation_summary,
}


def git_value(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def load_allowlist(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("policy") != "deny_by_default":
        raise ValueError("Unsupported public-data allowlist")
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Public-data allowlist must contain entries")
    return payload


def synchronize(source_root: Path, destination_root: Path) -> dict[str, Any]:
    source = source_root.expanduser().resolve(strict=True)
    destination = destination_root.expanduser().resolve(strict=True)
    if source.is_symlink() or destination.is_symlink():
        raise ValueError("Repository roots must not be symbolic links")
    allowlist_path = destination / "public_data" / "SOURCE_ALLOWLIST.json"
    allowlist = load_allowlist(allowlist_path)
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for entry in allowlist["entries"]:
        source_relative = safe_relative(str(entry["source"]), label="source")
        destination_relative = safe_relative(str(entry["destination"]), label="destination")
        if destination_relative.parts[0] != "public_data":
            raise ValueError("Every public result-data destination must stay within public_data/")
        destination_text = destination_relative.as_posix()
        if destination_text in seen:
            raise ValueError(f"Duplicate destination: {destination_text}")
        seen.add(destination_text)
        source_path = source.joinpath(*source_relative.parts)
        if source_path.is_symlink() or not source_path.is_file():
            raise ValueError(f"Source must be a regular non-symlink file: {source_path}")
        transform_name = str(entry.get("transform", ""))
        if transform_name not in TRANSFORMS:
            raise ValueError(f"Unknown transform: {transform_name}")
        source_payload = source_path.read_bytes()
        public_payload = TRANSFORMS[transform_name](source_payload)
        target = destination.joinpath(*destination_relative.parts)
        write_atomic(target, public_payload)
        records.append(
            {
                "source": source_relative.as_posix(),
                "destination": destination_text,
                "purpose": str(entry["purpose"]),
                "transform": transform_name,
                "classification": "aggregate_result_data",
                "license": "CC-BY-4.0",
                "bytes": len(public_payload),
                "source_sha256": sha256_bytes(source_payload),
                "sha256": sha256_bytes(public_payload),
            }
        )

    manifest = {
        "schema_version": 1,
        "release_scope": "disclosure-selected aggregate result data",
        "source_repository": source.name,
        "source_revision": git_value(source, "rev-parse", "HEAD"),
        "source_worktree_dirty": bool(git_value(source, "status", "--porcelain", "--untracked-files=no")),
        "export_policy": "deny_by_default_allowlist",
        "excluded": [
            "manuscript and submission files",
            "individual and event-level records",
            "county/city identifiers and exact dates",
            "weekly surveillance and small-area exposure series",
            "bootstrap replicates and fitted unit-level panels",
            "internal candidate, audit and disclosure-review artifacts",
            "nonessential result tables and private analysis code",
        ],
        "files": sorted(records, key=lambda item: item["destination"]),
    }
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_atomic(destination / "public_data" / "PUBLIC_DATA_MANIFEST.json", manifest_payload)

    metadata: dict[str, FileMetadata] = {}
    for path in sorted((destination / "public_data").iterdir()):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"Unexpected non-regular public_data entry: {path}")
        relative = path.name
        if path.suffix.lower() == ".csv":
            metadata[relative] = FileMetadata(
                "aggregate_result_data", "CC-BY-4.0", source=None
            )
        elif path.suffix.lower() in {".json", ".md"}:
            metadata[relative] = FileMetadata("documentation", "CC-BY-4.0", source=None)
        else:
            raise ValueError(f"Unexpected public_data file type: {path.name}")
    audit = audit_tree(destination / "public_data", metadata)
    if not audit.passed:
        details = "; ".join(
            f"{finding.path}:{finding.code}" for finding in audit.findings[:12]
        )
        raise ValueError(f"Public-data privacy audit failed: {details}")
    return {
        "status": "synchronized",
        "source_root": str(source),
        "destination_root": str(destination),
        "data_files": len(records),
        "audited_files": audit.files_scanned,
        "manifest_sha256": sha256_bytes(manifest_payload),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination-root", type=Path, default=PUBLIC_ROOT)
    args = parser.parse_args()
    result = synchronize(args.source_root, args.destination_root)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
