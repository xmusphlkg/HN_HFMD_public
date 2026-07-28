from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hfmd.core.config import load_config, write_config_snapshot
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.data import pipeline
from hfmd.data.synthetic import generate_synthetic_directory

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-data-test"


def _run_boundary(tmp_path: Path, profile: str) -> tuple[Path, Path, Path]:
    workspace = tmp_path / "workspace"
    run_root = workspace / ".runs" / RUN_ID / "staging"
    run_root.mkdir(parents=True)
    snapshot = run_root / "config" / "config.snapshot.json"
    write_config_snapshot(load_config(ROOT / "config" / "project.yaml", profile), snapshot)
    environment_path = run_root / "receipts" / "environment.json"
    write_stage_receipt(
        build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=RUN_ID,
            stage="environment",
            config_snapshot=snapshot,
            output_paths=(),
        ),
        environment_path,
    )
    return workspace, run_root, environment_path


def _completed(stdout: str = '{"status": "verified", "deleted_files": 63}\n') -> Any:
    return SimpleNamespace(stdout=stdout, returncode=0)


def test_restricted_deletion_verifier_accepts_final_json_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    verifier = workspace / "Script_py" / "delete_raw_after_validation.py"
    verifier.parent.mkdir(parents=True)
    verifier.write_text("# fixture\n", encoding="utf-8")
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        captured["command"] = command
        captured.update(kwargs)
        return _completed('diagnostic\n{"status": "verified", "files": 63}\n')

    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    result = pipeline._verify_restricted_deletion(workspace)

    assert result == {"status": "verified", "files": 63}
    assert captured["command"] == [sys.executable, str(verifier), "--verify-only"]
    assert captured["cwd"] == workspace
    assert captured["check"] is True


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("\n", "returned no receipt"),
        ("not-json\n", "returned invalid JSON"),
        ("[]\n", "non-object receipt"),
    ],
)
def test_restricted_deletion_verifier_rejects_bad_receipt(
    stdout: str,
    message: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *_args, **_kwargs: _completed(stdout))

    with pytest.raises(RuntimeError, match=message):
        pipeline._verify_restricted_deletion(workspace)


def test_restricted_deletion_verifier_propagates_failed_script(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def failed(command: list[str], **_kwargs: Any) -> Any:
        raise subprocess.CalledProcessError(2, command)

    monkeypatch.setattr(pipeline.subprocess, "run", failed)
    with pytest.raises(subprocess.CalledProcessError):
        pipeline._verify_restricted_deletion(workspace)


def test_restricted_deletion_verifier_refuses_reappearing_raw_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "Data").mkdir()
    monkeypatch.setattr(pipeline.subprocess, "run", lambda *_args, **_kwargs: _completed())

    with pytest.raises(RuntimeError, match="raw Data exists"):
        pipeline._verify_restricted_deletion(workspace)


def test_synthetic_data_stage_is_exact_hash_bound_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_root, environment_path = _run_boundary(tmp_path, "ci")
    data_root = run_root / "data" / "synthetic"
    generate_synthetic_directory(data_root, profile="ci", seed=7)
    receipt_path = run_root / "receipts" / "data.json"

    result = pipeline.register_data_stage(
        profile="ci",
        run_id=RUN_ID,
        run_root=run_root,
        workspace=workspace,
        data_root=data_root,
        environment_receipt=environment_path,
        receipt_path=receipt_path,
    )

    receipt = StageReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    assert result["status"] == "registered"
    assert result["input_files"] == 0
    assert result["output_files"] == 8
    assert receipt.stage == "data"
    assert receipt.metadata["data_kind"] == "fully_synthetic"
    assert receipt.exact_output_roots[0].path == "data/synthetic"
    assert {item.classification for item in receipt.outputs} == {"synthetic"}
    assert validate_stage_receipt(receipt_path, run_root=run_root, workspace=workspace).ok

    (data_root / "late-extra.csv").write_text("value\n10\n", encoding="utf-8")
    report = validate_stage_receipt(receipt_path, run_root=run_root, workspace=workspace)
    assert not report.ok
    assert "exact output set mismatch" in "; ".join(report.issues)


def test_restricted_data_stage_registers_every_sealed_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_root, environment_path = _run_boundary(tmp_path, "restricted")
    data_root = workspace / "AnalysisData"
    (data_root / "restricted").mkdir(parents=True)
    (data_root / "restricted" / "cases.csv.gz").write_bytes(b"sealed")
    (data_root / "raw_manifest.json").write_text("{}\n", encoding="utf-8")
    receipt_path = run_root / "receipts" / "data.json"
    verification = {"status": "verified", "raw_data_present": False}
    monkeypatch.setattr(pipeline, "_verify_restricted_deletion", lambda _: verification)

    result = pipeline.register_data_stage(
        profile="restricted",
        run_id=RUN_ID,
        run_root=run_root,
        workspace=workspace,
        data_root=data_root,
        environment_receipt=environment_path,
        receipt_path=receipt_path,
    )

    receipt = StageReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    assert result["input_files"] == 2
    assert result["output_files"] == 0
    assert receipt.formal is True
    assert receipt.metadata["deletion_verification"] == verification
    assert receipt.exact_input_roots[0].path == "AnalysisData"
    assert {record.classification for record in receipt.inputs} == {"controlled_derived"}
    assert validate_stage_receipt(receipt_path, run_root=run_root, workspace=workspace).ok


def test_restricted_data_stage_requires_exact_analysis_data_root(tmp_path: Path) -> None:
    workspace, run_root, environment_path = _run_boundary(tmp_path, "restricted")
    wrong = workspace / "AnalysisData" / "restricted"
    wrong.mkdir(parents=True)

    with pytest.raises(ValueError, match="sealed AnalysisData directory"):
        pipeline.register_data_stage(
            profile="restricted",
            run_id=RUN_ID,
            run_root=run_root,
            workspace=workspace,
            data_root=wrong,
            environment_receipt=environment_path,
            receipt_path=run_root / "receipts" / "data.json",
        )


def test_register_data_stage_rejects_unknown_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, run_root, environment_path = _run_boundary(tmp_path, "ci")
    data_root = run_root / "data"
    data_root.mkdir()

    with pytest.raises(ValueError, match="unsupported data profile"):
        pipeline.register_data_stage(
            profile="unknown",
            run_id=RUN_ID,
            run_root=run_root,
            workspace=workspace,
            data_root=data_root,
            environment_receipt=environment_path,
            receipt_path=run_root / "receipts" / "data.json",
        )


def test_pipeline_main_forwards_all_arguments_and_prints_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured: dict[str, Any] = {}

    def fake_register(**kwargs: Any) -> dict[str, object]:
        captured.update(kwargs)
        return {"status": "registered", "profile": kwargs["profile"]}

    monkeypatch.setattr(pipeline, "register_data_stage", fake_register)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hfmd.data.pipeline",
            "--profile",
            "synthetic",
            "--run-id",
            RUN_ID,
            "--run-root",
            str(tmp_path / "run"),
            "--workspace",
            str(tmp_path),
            "--data-root",
            str(tmp_path / "data"),
            "--environment-receipt",
            str(tmp_path / "environment.json"),
            "--receipt",
            str(tmp_path / "data.json"),
        ],
    )

    pipeline.main()

    assert captured["profile"] == "synthetic"
    assert captured["run_id"] == RUN_ID
    assert captured["receipt_path"] == tmp_path / "data.json"
    assert json.loads(capsys.readouterr().out)["status"] == "registered"
