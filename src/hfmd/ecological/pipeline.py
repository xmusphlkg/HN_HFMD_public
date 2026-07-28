"""Receipt-bound ecological smoke analysis for synthetic workflow profiles.

This module intentionally does not run or imitate the formal ecological model
registry.  It computes small, reproducible summaries from the fully synthetic
fixture so the data and workflow contracts can be exercised end to end.  A
restricted profile is blocked until a formal restricted-data adapter and every
required scientific upgrade are implemented.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import atomic_write_bytes, atomic_write_json, sha256_object
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    receipt_file,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.core.run import discover_workspace
from hfmd.data.synthetic import validate_synthetic_directory
from hfmd.reporting.contracts import ModelRegistry

PURPOSE = "synthetic_validation"
ANALYSIS_LINE = "ecological"
ANNUAL_COLUMNS = (
    "run_id",
    "validation_scope",
    "synthetic_region",
    "year",
    "weeks_observed",
    "reported_cases",
    "typed_cases",
    "resolved_typing_cases",
    "untyped_cases",
    "typing_resolution_fraction",
    "ev_a71_cases",
    "non_ev_a71_cases",
    "ev_a71_case_fraction",
    "under_six_cases",
    "under_six_case_fraction",
    "population",
    "cases_per_100000",
    "mean_vaccine_proxy",
)


class RestrictedEcologicalBlocked(RuntimeError):
    """Raised instead of treating legacy restricted outputs as a completed run."""


def _load_valid_data_receipt(
    data_receipt: Path,
    *,
    run_root: Path,
    workspace: Path,
    run_id: str,
    profile: ProfileName,
) -> StageReceipt:
    report = validate_stage_receipt(
        data_receipt,
        run_root=run_root,
        workspace=workspace,
    )
    if not report.ok:
        raise RuntimeError("data receipt validation failed: " + "; ".join(report.issues))
    with data_receipt.open("r", encoding="utf-8") as handle:
        receipt = StageReceipt.model_validate(json.load(handle))
    if receipt.stage != "data":
        raise ValueError(f"expected a data StageReceipt, found {receipt.stage!r}")
    if receipt.run_id != run_id:
        raise ValueError("data receipt belongs to another run_id")
    if receipt.profile != profile:
        raise ValueError("data receipt profile does not match the requested profile")
    return receipt


def _registry_from_snapshot(run_root: Path) -> tuple[ModelRegistry, str]:
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    payload = loaded.resources.get("model_registry")
    if not isinstance(payload, Mapping):
        raise ValueError("configuration snapshot has no unique model_registry resource")
    registry = ModelRegistry.model_validate(payload)
    return registry, sha256_object(payload)


def _outstanding_science(registry: ModelRegistry) -> tuple[str, ...]:
    required_models = (
        f"model:{model.model_id}"
        for model in registry.models
        if model.implementation_status in {"required", "planned"}
    )
    required_families = (
        f"sensitivity:{family.family_id}"
        for family in registry.sensitivity_families
        if family.implementation_status in {"required", "planned"}
    )
    return tuple(sorted((*required_models, *required_families)))


def _require_synthetic_sources(
    run_root: Path, data_receipt: StageReceipt
) -> tuple[Path, Path, dict[str, Any]]:
    data_root = run_root / "data" / "synthetic"
    validation = validate_synthetic_directory(data_root)
    weekly = data_root / "weekly_surveillance.csv"
    typing = data_root / "typing_selection.csv"
    registered = {
        record.path
        for record in data_receipt.outputs
        if record.scope == "run" and record.classification == "synthetic"
    }
    for source in (weekly, typing):
        relative = source.relative_to(run_root).as_posix()
        if relative not in registered:
            raise ValueError(f"synthetic analysis source is absent from data receipt: {relative}")
    return weekly, typing, validation


def _read_annual_metrics(weekly: Path, typing: Path, run_id: str) -> list[dict[str, Any]]:
    annual: dict[tuple[str, int], dict[str, Any]] = defaultdict(
        lambda: {
            "reported_cases": 0,
            "typed_cases": 0,
            "resolved_typing_cases": 0,
            "untyped_cases": 0,
            "ev_a71_cases": 0,
            "under_six_cases": 0,
            "weeks": set(),
            "population": None,
            "vaccine_by_week": {},
        }
    )
    with weekly.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = (row["synthetic_region"], int(row["year"]))
            item = annual[key]
            cases = int(row["cases"])
            item["reported_cases"] += cases
            item["typed_cases"] += int(row["typed_cases"])
            if row["pathogen_group"] == "ev_a71":
                item["ev_a71_cases"] += cases
            if row["age_group"] in {"lt1", "age1_2", "age3_5"}:
                item["under_six_cases"] += cases
            week = int(row["iso_week"])
            item["weeks"].add(week)
            population = int(row["population"])
            if item["population"] not in {None, population}:
                raise ValueError(f"population is inconsistent within synthetic cell {key}")
            item["population"] = population
            vaccine = float(row["ev_a71_vaccine_proxy"])
            previous = item["vaccine_by_week"].setdefault(week, vaccine)
            if previous != vaccine:
                raise ValueError(
                    f"vaccine proxy is inconsistent within synthetic week {key + (week,)}"
                )

    with typing.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = (row["synthetic_region"], int(row["year"]))
            if key not in annual:
                raise ValueError(f"typing table contains an unmatched region-year cell: {key}")
            count = int(row["reported_cases"])
            if row["testing_stage"] == "resolved_pathogen":
                annual[key]["resolved_typing_cases"] += count
            elif row["testing_stage"] == "not_tested":
                annual[key]["untyped_cases"] += count
            else:  # The synthetic contract should make this unreachable.
                raise ValueError(f"unexpected testing stage: {row['testing_stage']!r}")

    rows: list[dict[str, Any]] = []
    for (region, year), item in sorted(annual.items()):
        reported = int(item["reported_cases"])
        typed = int(item["typed_cases"])
        resolved = int(item["resolved_typing_cases"])
        untyped = int(item["untyped_cases"])
        if typed != resolved or reported != resolved + untyped:
            raise ValueError(
                f"weekly and typing synthetic totals do not reconcile for {(region, year)}"
            )
        ev_cases = int(item["ev_a71_cases"])
        under_six = int(item["under_six_cases"])
        population = int(item["population"])
        vaccine_values = list(item["vaccine_by_week"].values())
        rows.append(
            {
                "run_id": run_id,
                "validation_scope": PURPOSE,
                "synthetic_region": region,
                "year": year,
                "weeks_observed": len(item["weeks"]),
                "reported_cases": reported,
                "typed_cases": typed,
                "resolved_typing_cases": resolved,
                "untyped_cases": untyped,
                "typing_resolution_fraction": resolved / reported,
                "ev_a71_cases": ev_cases,
                "non_ev_a71_cases": reported - ev_cases,
                "ev_a71_case_fraction": ev_cases / reported,
                "under_six_cases": under_six,
                "under_six_case_fraction": under_six / reported,
                "population": population,
                "cases_per_100000": reported / population * 100_000.0,
                "mean_vaccine_proxy": sum(vaccine_values) / len(vaccine_values),
            }
        )
    if not rows:
        raise ValueError("synthetic weekly surveillance contains no rows")
    return rows


def _csv_bytes(fieldnames: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        rendered = {
            key: (format(value, ".12g") if isinstance(value, float) else value)
            for key, value in row.items()
        }
        writer.writerow(rendered)
    return buffer.getvalue().encode("utf-8")


def _write_outputs(
    destination: Path,
    *,
    run_id: str,
    profile: ProfileName,
    registry: ModelRegistry,
    registry_sha256: str,
    weekly: Path,
    typing: Path,
) -> tuple[tuple[Path, ...], dict[str, Any]]:
    rows = _read_annual_metrics(weekly, typing, run_id)
    annual_path = destination / "annual_validation_metrics.csv"
    atomic_write_bytes(annual_path, _csv_bytes(ANNUAL_COLUMNS, rows), mode=0o600)
    totals = {
        "region_year_cells": len(rows),
        "reported_cases": sum(int(row["reported_cases"]) for row in rows),
        "typed_cases": sum(int(row["typed_cases"]) for row in rows),
        "first_year": min(int(row["year"]) for row in rows),
        "last_year": max(int(row["year"]) for row in rows),
    }
    ecological_models = registry.select(line="ecological")
    summary = {
        "schema_version": "hfmd-synthetic-analysis-summary-v1",
        "run_id": run_id,
        "profile": profile.value,
        "analysis_line": ANALYSIS_LINE,
        "purpose": PURPOSE,
        "scientific_inference_allowed": False,
        "formal_models_executed": 0,
        "registered_model_count": len(ecological_models),
        "model_registry_sha256": registry_sha256,
        "computed_totals": totals,
    }
    summary_path = destination / "summary.json"
    atomic_write_json(summary_path, summary, mode=0o600)
    contract = {
        "schema_version": "hfmd-analysis-data-contract-v1",
        "run_id": run_id,
        "profile": profile.value,
        "analysis_line": ANALYSIS_LINE,
        "purpose": PURPOSE,
        "classification": "synthetic",
        "scientific_inference_allowed": False,
        "sources": [
            weekly.relative_to(destination.parents[1]).as_posix(),
            typing.relative_to(destination.parents[1]).as_posix(),
        ],
        "tables": [
            {
                "path": annual_path.name,
                "columns": list(ANNUAL_COLUMNS),
                "primary_key": ["run_id", "synthetic_region", "year"],
                "rows": len(rows),
            }
        ],
        "json_documents": ["summary.json"],
    }
    contract_path = destination / "data_contract.json"
    atomic_write_json(contract_path, contract, mode=0o600)
    return (annual_path, summary_path, contract_path), totals


def run_ecological_analysis(
    *,
    run_id: str,
    profile: str,
    run_root: Path,
    data_receipt: Path,
    receipt_path: Path,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Run the synthetic ecological validation stage or fail closed."""

    run_root = run_root.resolve(strict=True)
    workspace = (workspace or discover_workspace(run_root)).resolve(strict=True)
    requested_profile = ProfileName(profile)
    data_receipt = data_receipt.resolve(strict=True)
    data_stage = _load_valid_data_receipt(
        data_receipt,
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=requested_profile,
    )
    snapshot = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    if snapshot.config.runtime.profile != requested_profile:
        raise ValueError("requested profile does not match the configuration snapshot")
    registry, registry_sha256 = _registry_from_snapshot(run_root)

    if requested_profile == ProfileName.RESTRICTED:
        outstanding = _outstanding_science(registry)
        detail = ", ".join(outstanding[:8])
        suffix = f" Outstanding registry requirements include: {detail}." if detail else ""
        raise RestrictedEcologicalBlocked(
            "Restricted ecological execution is blocked: this synthetic validator cannot "
            "copy or certify legacy AnalysisOutput, and a formal restricted-data adapter "
            "has not been implemented." + suffix
        )
    if requested_profile not in {ProfileName.CI, ProfileName.SYNTHETIC}:
        raise ValueError(f"unsupported profile: {requested_profile.value}")

    weekly, typing, synthetic_validation = _require_synthetic_sources(run_root, data_stage)
    output_root = run_root / "analysis" / ANALYSIS_LINE
    receipt_path = receipt_path.absolute()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(f"refusing to reuse ecological output root: {output_root}")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace ecological receipt: {receipt_path}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".ecological.staging-", dir=output_root.parent))
    try:
        temporary_outputs, totals = _write_outputs(
            temporary,
            run_id=run_id,
            profile=requested_profile,
            registry=registry,
            registry_sha256=registry_sha256,
            weekly=weekly,
            typing=typing,
        )
        temporary.replace(output_root)
        outputs = tuple(output_root / path.name for path in temporary_outputs)
        inputs = tuple(
            receipt_file(
                path,
                scope="run",
                run_root=run_root,
                workspace=workspace,
                classification="synthetic",
            )
            for path in (weekly, typing)
        )
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="ecological",
            config_snapshot=run_root / "config" / "config.snapshot.json",
            output_paths=outputs,
            output_classification="synthetic",
            parent_receipts=(data_receipt,),
            input_files=inputs,
            exact_output_roots=(output_root,),
            metadata={
                "analysis_line": ANALYSIS_LINE,
                "purpose": PURPOSE,
                "scientific_inference_allowed": False,
                "formal_models_executed": 0,
                "model_registry_sha256": registry_sha256,
                "registered_model_count": len(registry.select(line="ecological")),
                "synthetic_data_validation": synthetic_validation,
                "computed_totals": totals,
            },
        )
        write_stage_receipt(receipt, receipt_path)
        report = validate_stage_receipt(
            receipt_path,
            run_root=run_root,
            workspace=workspace,
        )
        if not report.ok:
            raise RuntimeError(
                "ecological receipt failed self-validation: " + "; ".join(report.issues)
            )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)
        receipt_path.unlink(missing_ok=True)
        raise

    return {
        "status": "synthetic_validation",
        "run_id": run_id,
        "profile": requested_profile.value,
        "analysis_line": ANALYSIS_LINE,
        "scientific_inference_allowed": False,
        "output_files": len(outputs),
        "receipt_sha256": report.receipt_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("ci", "synthetic", "restricted"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--data-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run_ecological_analysis(
        run_id=args.run_id,
        profile=args.profile,
        run_root=args.run_root,
        data_receipt=args.data_receipt,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
