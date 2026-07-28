"""Receipt-bound construction of a self-contained public repository."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import atomic_write_json, iter_regular_files
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.privacy.export import export_public_repository


def _validated_parent(
    path: Path,
    *,
    stage: str,
    run_root: Path,
    workspace: Path,
    run_id: str,
    profile: ProfileName,
) -> StageReceipt:
    report = validate_stage_receipt(path, run_root=run_root, workspace=workspace)
    if not report.ok:
        raise RuntimeError(f"{stage} receipt validation failed: " + "; ".join(report.issues))
    receipt = StageReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    if receipt.stage != stage or receipt.run_id != run_id or receipt.profile != profile:
        raise ValueError(f"{stage} receipt identity mismatch")
    return receipt


def run_public_export(
    *,
    run_id: str,
    run_root: Path,
    workspace: Path,
    data_receipt: Path,
    submission_receipt: Path,
    synthetic_source: Path,
    destination: Path,
    receipt_path: Path,
) -> dict[str, Any]:
    """Export code, validated synthetic data/results, and a hash-bound receipt."""

    run_root = run_root.resolve(strict=True)
    workspace = workspace.resolve(strict=True)
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    profile = loaded.config.runtime.profile
    if profile not in {ProfileName.CI, ProfileName.SYNTHETIC}:
        raise ValueError("public export is allowed only for ci or synthetic profiles")
    _validated_parent(
        data_receipt,
        stage="data",
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=profile,
    )
    _validated_parent(
        submission_receipt,
        stage="submission",
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=profile,
    )

    output_root = run_root / "public_export"
    receipt_path = receipt_path.absolute()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(f"refusing to reuse public-export output root: {output_root}")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace public-export receipt: {receipt_path}")

    target = destination.expanduser().resolve()
    exported = False
    try:
        result = export_public_repository(
            source_root=workspace,
            destination=target,
            allowlist_path=workspace / "public_repo" / "allowlist.json",
            synthetic_source=synthetic_source,
            synthetic_results_source=run_root,
            initialize_git=True,
        )
        exported = True
        output_root.mkdir(mode=0o700)
        shutil.copyfile(
            target / "PUBLIC_EXPORT_MANIFEST.json",
            output_root / "PUBLIC_EXPORT_MANIFEST.json",
        )
        shutil.copyfile(
            target / "PRIVACY_AUDIT.json",
            output_root / "PRIVACY_AUDIT.json",
        )
        summary = {
            key: value
            for key, value in result.items()
            if key != "destination"
        }
        summary.update(
            {
                "schema_version": "hfmd-public-export-summary-v1",
                "run_id": run_id,
                "profile": profile.value,
                "includes_synthetic_data": True,
                "includes_synthetic_results": True,
                "restricted_data_included": False,
            }
        )
        atomic_write_json(output_root / "export_summary.json", summary, mode=0o600)

        outputs = tuple(iter_regular_files(output_root))
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="public_export",
            config_snapshot=run_root / "config" / "config.snapshot.json",
            output_paths=outputs,
            output_classification="public",
            parent_receipts=(data_receipt, submission_receipt),
            exact_output_roots=(output_root,),
            metadata=summary,
        )
        write_stage_receipt(receipt, receipt_path)
        report = validate_stage_receipt(
            receipt_path,
            run_root=run_root,
            workspace=workspace,
        )
        if not report.ok:
            raise RuntimeError(
                "public-export receipt failed self-validation: " + "; ".join(report.issues)
            )
    except BaseException:
        shutil.rmtree(output_root, ignore_errors=True)
        receipt_path.unlink(missing_ok=True)
        if exported:
            shutil.rmtree(target, ignore_errors=True)
        raise

    return {
        **summary,
        "receipt_sha256": report.receipt_sha256,
        "receipt_outputs": len(outputs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--data-receipt", type=Path, required=True)
    parser.add_argument("--submission-receipt", type=Path, required=True)
    parser.add_argument("--synthetic-source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run_public_export(
        run_id=args.run_id,
        run_root=args.run_root,
        workspace=args.workspace,
        data_receipt=args.data_receipt,
        submission_receipt=args.submission_receipt,
        synthetic_source=args.synthetic_source,
        destination=args.destination,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
