from __future__ import annotations

import csv
import json

import pytest

from hfmd.core.receipts import StageReceipt, validate_stage_receipt
from hfmd.ecological.pipeline import (
    RestrictedEcologicalBlocked,
    run_ecological_analysis,
)

from .conftest import RUN_ID, StagedRun


def _run(staged: StagedRun) -> dict[str, object]:
    return run_ecological_analysis(
        run_id=RUN_ID,
        profile=staged.profile,
        run_root=staged.run_root,
        data_receipt=staged.data_receipt,
        receipt_path=staged.analysis_receipt,
        workspace=staged.workspace,
    )


def test_ci_ecological_pipeline_computes_run_bound_synthetic_contract(
    staged_run_factory,
) -> None:
    staged = staged_run_factory(profile="ci", line="ecological")

    result = _run(staged)

    output_root = staged.run_root / "analysis" / "ecological"
    assert result["status"] == "synthetic_validation"
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    contract = json.loads((output_root / "data_contract.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == RUN_ID
    assert summary["purpose"] == "synthetic_validation"
    assert summary["scientific_inference_allowed"] is False
    assert summary["formal_models_executed"] == 0
    assert summary["registered_model_count"] == 55
    assert summary["computed_totals"]["reported_cases"] > 0
    assert contract["run_id"] == RUN_ID
    assert contract["scientific_inference_allowed"] is False

    with (output_root / "annual_validation_metrics.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert {row["run_id"] for row in rows} == {RUN_ID}
    assert {row["validation_scope"] for row in rows} == {"synthetic_validation"}
    assert all(int(row["typed_cases"]) == int(row["resolved_typing_cases"]) for row in rows)

    validation = validate_stage_receipt(
        staged.analysis_receipt,
        run_root=staged.run_root,
        workspace=staged.workspace,
    )
    assert validation.ok, validation.issues
    receipt = StageReceipt.model_validate_json(staged.analysis_receipt.read_text(encoding="utf-8"))
    assert receipt.stage == "ecological"
    assert [parent.stage for parent in receipt.parents] == ["data"]
    assert receipt.metadata["purpose"] == "synthetic_validation"
    assert {item.path for item in receipt.inputs} == {
        "data/synthetic/typing_selection.csv",
        "data/synthetic/weekly_surveillance.csv",
    }


def test_ecological_pipeline_validates_data_receipt_before_writing(
    staged_run_factory,
) -> None:
    staged = staged_run_factory(profile="ci", line="ecological")
    weekly = staged.run_root / "data" / "synthetic" / "weekly_surveillance.csv"
    weekly.write_bytes(weekly.read_bytes() + b"\n")

    with pytest.raises(RuntimeError, match="data receipt validation failed"):
        _run(staged)

    assert not (staged.run_root / "analysis" / "ecological").exists()
    assert not staged.analysis_receipt.exists()


def test_restricted_ecological_pipeline_fails_closed_without_output(
    staged_run_factory,
) -> None:
    staged = staged_run_factory(profile="restricted", line="ecological")

    with pytest.raises(RestrictedEcologicalBlocked, match="legacy AnalysisOutput"):
        _run(staged)

    assert not (staged.run_root / "analysis" / "ecological").exists()
    assert not staged.analysis_receipt.exists()
