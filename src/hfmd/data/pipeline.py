"""Register synthetic or sealed restricted data as a hash-bound workflow stage."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from hfmd.core.hashing import iter_regular_files
from hfmd.core.receipts import (
    build_stage_receipt,
    receipt_file,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.data.synthetic import validate_synthetic_directory


def _verify_restricted_deletion(workspace: Path) -> dict[str, object]:
    verifier = workspace / "Script_py" / "delete_raw_after_validation.py"
    completed = subprocess.run(
        [sys.executable, str(verifier), "--verify-only"],
        cwd=workspace,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("restricted-data deletion verifier returned no receipt")
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError as error:
        raise RuntimeError("restricted-data deletion verifier returned invalid JSON") from error
    if not isinstance(result, dict) or not all(isinstance(key, str) for key in result):
        raise RuntimeError("restricted-data deletion verifier returned a non-object receipt")
    if (workspace / "Data").exists() or (workspace / "Data").is_symlink():
        raise RuntimeError("raw Data exists; restricted registration refuses to continue")
    return {str(key): value for key, value in result.items()}


def register_data_stage(
    *,
    profile: str,
    run_id: str,
    run_root: Path,
    workspace: Path,
    data_root: Path,
    environment_receipt: Path,
    receipt_path: Path,
) -> dict[str, object]:
    workspace = workspace.resolve(strict=True)
    run_root = run_root.resolve(strict=True)
    data_root = data_root.resolve(strict=True)
    config_snapshot = run_root / "config" / "config.snapshot.json"
    if profile in {"ci", "synthetic"}:
        validation = validate_synthetic_directory(data_root)
        outputs = tuple(iter_regular_files(data_root))
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="data",
            config_snapshot=config_snapshot,
            output_paths=outputs,
            output_classification="synthetic",
            parent_receipts=(environment_receipt,),
            exact_output_roots=(data_root,),
            metadata={
                "data_profile": profile,
                "data_kind": "fully_synthetic",
                "validation": validation,
            },
        )
    elif profile == "restricted":
        expected_root = (workspace / "AnalysisData").resolve(strict=True)
        if data_root != expected_root:
            raise ValueError("restricted data root must be the sealed AnalysisData directory")
        deletion = _verify_restricted_deletion(workspace)
        input_records = tuple(
            receipt_file(
                path,
                scope="workspace",
                run_root=run_root,
                workspace=workspace,
                classification="controlled_derived",
            )
            for path in iter_regular_files(data_root)
        )
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="data",
            config_snapshot=config_snapshot,
            output_paths=(),
            parent_receipts=(environment_receipt,),
            input_files=input_records,
            exact_input_roots=(("workspace", data_root),),
            metadata={
                "data_profile": profile,
                "data_kind": "sealed_controlled_derived",
                "raw_data_present": False,
                "deletion_verification": deletion,
            },
        )
    else:
        raise ValueError(f"unsupported data profile: {profile}")
    write_stage_receipt(receipt, receipt_path)
    report = validate_stage_receipt(
        receipt_path,
        run_root=run_root,
        workspace=workspace,
    )
    if not report.ok:
        raise RuntimeError("data receipt failed self-validation: " + "; ".join(report.issues))
    return {
        "status": "registered",
        "profile": profile,
        "run_id": run_id,
        "receipt_sha256": report.receipt_sha256,
        "input_files": len(receipt.inputs),
        "output_files": len(receipt.outputs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("ci", "synthetic", "restricted"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--environment-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = register_data_stage(
        profile=args.profile,
        run_id=args.run_id,
        run_root=args.run_root,
        workspace=args.workspace,
        data_root=args.data_root,
        environment_receipt=args.environment_receipt,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
