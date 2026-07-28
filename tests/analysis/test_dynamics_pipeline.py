from __future__ import annotations

import csv
import json
import math

import pytest

from hfmd.core.receipts import StageReceipt, validate_stage_receipt
from hfmd.dynamics.pipeline import RestrictedDynamicsBlocked, run_dynamics_analysis

from .conftest import RUN_ID, StagedRun


def _run(staged: StagedRun) -> dict[str, object]:
    return run_dynamics_analysis(
        run_id=RUN_ID,
        profile=staged.profile,
        run_root=staged.run_root,
        data_receipt=staged.data_receipt,
        receipt_path=staged.analysis_receipt,
        workspace=staged.workspace,
    )


def test_ci_dynamics_pipeline_computes_typing_and_rolling_validation(
    staged_run_factory,
) -> None:
    staged = staged_run_factory(profile="ci", line="dynamics")

    result = _run(staged)

    output_root = staged.run_root / "analysis" / "dynamics"
    assert result["status"] == "synthetic_validation"
    summary = json.loads((output_root / "summary.json").read_text(encoding="utf-8"))
    contract = json.loads((output_root / "data_contract.json").read_text(encoding="utf-8"))
    assert summary["run_id"] == RUN_ID
    assert summary["scientific_inference_allowed"] is False
    assert summary["formal_models_executed"] == 0
    assert summary["outstanding_formal_requirement_count"] > 0
    assert summary["computed_totals"]["rolling_origin_folds"] == 7
    assert contract["purpose"] == "synthetic_validation"
    assert len(contract["tables"]) == 3

    with (output_root / "rolling_origin_validation.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rolling = list(csv.DictReader(handle))
    assert [int(row["test_year"]) for row in rolling] == list(range(2019, 2026))
    assert {row["run_id"] for row in rolling} == {RUN_ID}
    assert all(math.isfinite(float(row["joint_log_score"])) for row in rolling)
    assert {row["validation_model"] for row in rolling} == {
        "trailing_mean_and_pooled_share_not_formal_model"
    }

    validation = validate_stage_receipt(
        staged.analysis_receipt,
        run_root=staged.run_root,
        workspace=staged.workspace,
    )
    assert validation.ok, validation.issues
    receipt = StageReceipt.model_validate_json(staged.analysis_receipt.read_text(encoding="utf-8"))
    assert receipt.stage == "dynamics"
    assert [parent.stage for parent in receipt.parents] == ["data"]
    assert receipt.metadata["formal_models_executed"] == 0
    assert {item.path for item in receipt.inputs} == {
        "data/synthetic/typing_selection.csv",
        "data/synthetic/weekly_surveillance.csv",
    }


def test_restricted_dynamics_pipeline_lists_requirements_and_writes_nothing(
    staged_run_factory,
) -> None:
    staged = staged_run_factory(profile="restricted", line="dynamics")

    with pytest.raises(RestrictedDynamicsBlocked, match="typing_selection"):
        _run(staged)

    assert not (staged.run_root / "analysis" / "dynamics").exists()
    assert not staged.analysis_receipt.exists()
