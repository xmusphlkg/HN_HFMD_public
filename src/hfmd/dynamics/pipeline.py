"""Receipt-bound dynamics smoke analysis for synthetic workflow profiles.

The calculations below are validation baselines, not substitutes for the
formal transmission model.  They exercise annual pathogen aggregation,
typing-selection reconciliation, and rolling-origin score plumbing on fully
synthetic data.  Restricted execution fails closed while required model and
sensitivity specifications remain outstanding.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
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
from hfmd.data.synthetic import PATHOGENS, validate_synthetic_directory
from hfmd.reporting.contracts import ModelRegistry

PURPOSE = "synthetic_validation"
ANALYSIS_LINE = "dynamics"
ANNUAL_PATHOGEN_COLUMNS = (
    "run_id",
    "validation_scope",
    "year",
    "pathogen_group",
    "reported_cases",
    "typed_cases",
    "reported_case_fraction",
    "typed_case_fraction",
    "mean_vaccine_proxy",
)
TYPING_COLUMNS = (
    "run_id",
    "validation_scope",
    "synthetic_region",
    "year",
    "resolved_pathogen_cases",
    "not_tested_cases",
    "typing_eligible_cases",
    "resolved_pathogen_fraction",
)
ROLLING_COLUMNS = (
    "run_id",
    "validation_scope",
    "validation_model",
    "test_year",
    "training_start_year",
    "training_end_year",
    "observed_total_cases",
    "predicted_total_cases",
    "total_case_log_score",
    "typing_log_score",
    "joint_log_score",
)


class RestrictedDynamicsBlocked(RuntimeError):
    """Raised while formal dynamics requirements remain unimplemented."""


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


def _outstanding_dynamics(registry: ModelRegistry) -> tuple[str, ...]:
    models = (
        f"model:{model.model_id}"
        for model in registry.select(line="dynamics")
        if model.implementation_status in {"required", "planned"}
    )
    families = (
        f"sensitivity:{family.family_id}"
        for family in registry.sensitivity_families
        if family.implementation_status in {"required", "planned"}
    )
    return tuple(sorted((*models, *families)))


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


def _read_weekly_aggregates(
    weekly: Path,
) -> tuple[
    dict[tuple[int, str], dict[str, float]],
    dict[int, int],
    dict[int, dict[str, int]],
]:
    annual_pathogen: dict[tuple[int, str], dict[str, float]] = defaultdict(
        lambda: {"reported": 0.0, "typed": 0.0, "vaccine_sum": 0.0, "rows": 0.0}
    )
    annual_total: dict[int, int] = defaultdict(int)
    annual_typed: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    with weekly.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year = int(row["year"])
            pathogen = row["pathogen_group"]
            if pathogen not in PATHOGENS:
                raise ValueError(f"unexpected pathogen group: {pathogen!r}")
            cases = int(row["cases"])
            typed = int(row["typed_cases"])
            key = (year, pathogen)
            annual_pathogen[key]["reported"] += cases
            annual_pathogen[key]["typed"] += typed
            annual_pathogen[key]["vaccine_sum"] += float(row["ev_a71_vaccine_proxy"])
            annual_pathogen[key]["rows"] += 1
            annual_total[year] += cases
            annual_typed[year][pathogen] += typed
    if not annual_pathogen:
        raise ValueError("synthetic weekly surveillance contains no rows")
    return annual_pathogen, dict(annual_total), annual_typed


def _read_typing_metrics(
    typing: Path,
    run_id: str,
) -> tuple[list[dict[str, Any]], dict[int, dict[str, int]], dict[int, int]]:
    cells: dict[tuple[str, int], dict[str, int]] = defaultdict(
        lambda: {"resolved": 0, "not_tested": 0}
    )
    resolved_by_year_pathogen: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    eligible_by_year: dict[int, int] = defaultdict(int)
    with typing.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            region = row["synthetic_region"]
            year = int(row["year"])
            count = int(row["reported_cases"])
            if row["testing_stage"] == "resolved_pathogen":
                cells[(region, year)]["resolved"] += count
                pathogen = row["pathogen_group"]
                if pathogen not in PATHOGENS:
                    raise ValueError(f"unexpected resolved pathogen group: {pathogen!r}")
                resolved_by_year_pathogen[year][pathogen] += count
            elif row["testing_stage"] == "not_tested":
                cells[(region, year)]["not_tested"] += count
            else:
                raise ValueError(f"unexpected testing stage: {row['testing_stage']!r}")
            eligible_by_year[year] += count
    rows: list[dict[str, Any]] = []
    for (region, year), counts in sorted(cells.items()):
        eligible = counts["resolved"] + counts["not_tested"]
        rows.append(
            {
                "run_id": run_id,
                "validation_scope": PURPOSE,
                "synthetic_region": region,
                "year": year,
                "resolved_pathogen_cases": counts["resolved"],
                "not_tested_cases": counts["not_tested"],
                "typing_eligible_cases": eligible,
                "resolved_pathogen_fraction": counts["resolved"] / eligible,
            }
        )
    if not rows:
        raise ValueError("synthetic typing selection contains no rows")
    return rows, resolved_by_year_pathogen, dict(eligible_by_year)


def _annual_pathogen_rows(
    annual_pathogen: Mapping[tuple[int, str], Mapping[str, float]],
    run_id: str,
) -> list[dict[str, Any]]:
    reported_totals: dict[int, float] = defaultdict(float)
    typed_totals: dict[int, float] = defaultdict(float)
    for (year, _), values in annual_pathogen.items():
        reported_totals[year] += values["reported"]
        typed_totals[year] += values["typed"]
    rows: list[dict[str, Any]] = []
    for (year, pathogen), values in sorted(annual_pathogen.items()):
        rows.append(
            {
                "run_id": run_id,
                "validation_scope": PURPOSE,
                "year": year,
                "pathogen_group": pathogen,
                "reported_cases": int(values["reported"]),
                "typed_cases": int(values["typed"]),
                "reported_case_fraction": values["reported"] / reported_totals[year],
                "typed_case_fraction": values["typed"] / typed_totals[year],
                "mean_vaccine_proxy": values["vaccine_sum"] / values["rows"],
            }
        )
    return rows


def _multinomial_log_score(counts: Mapping[str, int], probability: Mapping[str, float]) -> float:
    total = sum(counts.get(pathogen, 0) for pathogen in PATHOGENS)
    score = math.lgamma(total + 1)
    for pathogen in PATHOGENS:
        count = counts.get(pathogen, 0)
        score -= math.lgamma(count + 1)
        score += count * math.log(probability[pathogen])
    return score


def _rolling_rows(
    annual_total: Mapping[int, int],
    resolved_by_year_pathogen: Mapping[int, Mapping[str, int]],
    run_id: str,
) -> list[dict[str, Any]]:
    years = sorted(set(annual_total) & set(resolved_by_year_pathogen))
    rows: list[dict[str, Any]] = []
    for test_year in (2019, 2020, 2021, 2022, 2023, 2024, 2025):
        training = [year for year in years if year < test_year]
        if test_year not in years or not training:
            continue
        predicted_total = sum(annual_total[year] for year in training) / len(training)
        observed_total = annual_total[test_year]
        total_score = (
            observed_total * math.log(predicted_total)
            - predicted_total
            - math.lgamma(observed_total + 1)
        )
        pooled = {
            pathogen: sum(resolved_by_year_pathogen[year].get(pathogen, 0) for year in training)
            for pathogen in PATHOGENS
        }
        denominator = sum(pooled.values()) + len(PATHOGENS)
        probability = {pathogen: (pooled[pathogen] + 1.0) / denominator for pathogen in PATHOGENS}
        typing_score = _multinomial_log_score(resolved_by_year_pathogen[test_year], probability)
        rows.append(
            {
                "run_id": run_id,
                "validation_scope": PURPOSE,
                "validation_model": "trailing_mean_and_pooled_share_not_formal_model",
                "test_year": test_year,
                "training_start_year": min(training),
                "training_end_year": max(training),
                "observed_total_cases": observed_total,
                "predicted_total_cases": predicted_total,
                "total_case_log_score": total_score,
                "typing_log_score": typing_score,
                "joint_log_score": total_score + typing_score,
            }
        )
    if not rows:
        raise ValueError("synthetic data do not support any declared rolling validation year")
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
    annual_source, annual_total, annual_typed = _read_weekly_aggregates(weekly)
    typing_rows, resolved_by_year_pathogen, eligible_by_year = _read_typing_metrics(typing, run_id)
    for year, typed_counts in annual_typed.items():
        resolved = resolved_by_year_pathogen.get(year, {})
        if any(
            typed_counts.get(pathogen, 0) != resolved.get(pathogen, 0) for pathogen in PATHOGENS
        ):
            raise ValueError(f"weekly typed and selection-resolved totals differ for {year}")
        if annual_total[year] != eligible_by_year.get(year):
            raise ValueError(f"weekly and typing eligible totals differ for {year}")

    annual_rows = _annual_pathogen_rows(annual_source, run_id)
    rolling_rows = _rolling_rows(annual_total, resolved_by_year_pathogen, run_id)
    annual_path = destination / "annual_pathogen_validation.csv"
    typing_path = destination / "typing_selection_validation.csv"
    rolling_path = destination / "rolling_origin_validation.csv"
    atomic_write_bytes(annual_path, _csv_bytes(ANNUAL_PATHOGEN_COLUMNS, annual_rows), mode=0o600)
    atomic_write_bytes(typing_path, _csv_bytes(TYPING_COLUMNS, typing_rows), mode=0o600)
    atomic_write_bytes(rolling_path, _csv_bytes(ROLLING_COLUMNS, rolling_rows), mode=0o600)

    outstanding = _outstanding_dynamics(registry)
    totals = {
        "annual_pathogen_cells": len(annual_rows),
        "typing_region_year_cells": len(typing_rows),
        "rolling_origin_folds": len(rolling_rows),
        "reported_cases": sum(annual_total.values()),
        "resolved_typing_cases": sum(
            sum(values.values()) for values in resolved_by_year_pathogen.values()
        ),
    }
    summary = {
        "schema_version": "hfmd-synthetic-analysis-summary-v1",
        "run_id": run_id,
        "profile": profile.value,
        "analysis_line": ANALYSIS_LINE,
        "purpose": PURPOSE,
        "scientific_inference_allowed": False,
        "formal_models_executed": 0,
        "validation_baselines_executed": 1,
        "registered_model_count": len(registry.select(line="dynamics")),
        "outstanding_formal_requirement_count": len(outstanding),
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
                "columns": list(ANNUAL_PATHOGEN_COLUMNS),
                "primary_key": ["run_id", "year", "pathogen_group"],
                "rows": len(annual_rows),
            },
            {
                "path": typing_path.name,
                "columns": list(TYPING_COLUMNS),
                "primary_key": ["run_id", "synthetic_region", "year"],
                "rows": len(typing_rows),
            },
            {
                "path": rolling_path.name,
                "columns": list(ROLLING_COLUMNS),
                "primary_key": ["run_id", "test_year"],
                "rows": len(rolling_rows),
            },
        ],
        "json_documents": ["summary.json"],
    }
    contract_path = destination / "data_contract.json"
    atomic_write_json(contract_path, contract, mode=0o600)
    return (
        annual_path,
        typing_path,
        rolling_path,
        summary_path,
        contract_path,
    ), totals


def run_dynamics_analysis(
    *,
    run_id: str,
    profile: str,
    run_root: Path,
    data_receipt: Path,
    receipt_path: Path,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Run synthetic dynamics validation, never a restricted placeholder fit."""

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
        outstanding = _outstanding_dynamics(registry)
        if outstanding:
            detail = ", ".join(outstanding[:12])
            raise RestrictedDynamicsBlocked(
                "Restricted dynamics execution is blocked because required transmission, "
                "typing_selection, and scientific-upgrade registry items remain: "
                f"{detail}. "
                "No formal result or receipt was written."
            )
        raise RestrictedDynamicsBlocked(
            "Restricted dynamics execution is blocked because the formal restricted fitter "
            "has not been connected to this receipt-bound pipeline. No result was written."
        )
    if requested_profile not in {ProfileName.CI, ProfileName.SYNTHETIC}:
        raise ValueError(f"unsupported profile: {requested_profile.value}")

    weekly, typing, synthetic_validation = _require_synthetic_sources(run_root, data_stage)
    output_root = run_root / "analysis" / ANALYSIS_LINE
    receipt_path = receipt_path.absolute()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(f"refusing to reuse dynamics output root: {output_root}")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace dynamics receipt: {receipt_path}")

    output_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".dynamics.staging-", dir=output_root.parent))
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
            stage="dynamics",
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
                "validation_baselines_executed": 1,
                "model_registry_sha256": registry_sha256,
                "registered_model_count": len(registry.select(line="dynamics")),
                "outstanding_formal_requirement_count": len(_outstanding_dynamics(registry)),
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
                "dynamics receipt failed self-validation: " + "; ".join(report.issues)
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
    result = run_dynamics_analysis(
        run_id=args.run_id,
        profile=args.profile,
        run_root=args.run_root,
        data_receipt=args.data_receipt,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
