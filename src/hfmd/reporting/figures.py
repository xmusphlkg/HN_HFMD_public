"""Receipt-bound rendering of the five-main/ten-supplement figure contract.

The public profiles render conspicuously labelled synthetic validation figures
from the current run's calculated summaries.  They never read ``AnalysisOutput``
or ``Outcome``.  Restricted rendering remains closed until the formal model and
figure-data contracts are implemented and validated.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import iter_regular_files, sha256_file
from hfmd.core.receipts import (
    ReceiptFile,
    StageReceipt,
    build_stage_receipt,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.core.run import discover_workspace
from hfmd.reporting.contracts import FigureSpec, VisualContract

PURPOSE = "synthetic_validation"
EXPECTED_MANIFEST_COLUMNS = {
    "file",
    "figure_id",
    "format",
    "width_in",
    "height_in",
    "run_id",
    "visual_contract_source_sha256",
    "visual_contract_resource_sha256",
    "bytes",
    "sha256",
}


class RestrictedFiguresBlocked(RuntimeError):
    """Raised instead of rendering legacy or incomplete formal results."""


Renderer = Callable[[Path, Path, Path, Path, str, ProfileName], None]


def _load_parent(
    path: Path,
    *,
    expected_stage: str,
    run_root: Path,
    workspace: Path,
    run_id: str,
    profile: ProfileName,
) -> StageReceipt:
    report = validate_stage_receipt(path, run_root=run_root, workspace=workspace)
    if not report.ok:
        raise RuntimeError(
            f"{expected_stage} receipt validation failed: " + "; ".join(report.issues)
        )
    with path.open("r", encoding="utf-8") as handle:
        receipt = StageReceipt.model_validate(json.load(handle))
    if receipt.stage != expected_stage:
        raise ValueError(f"expected {expected_stage!r} receipt, found {receipt.stage!r}")
    if receipt.run_id != run_id:
        raise ValueError(f"{expected_stage} receipt belongs to another run_id")
    if receipt.profile != profile:
        raise ValueError(f"{expected_stage} receipt profile mismatch")
    return receipt


def _visual_contract(run_root: Path) -> VisualContract:
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    return VisualContract.model_validate(loaded.resources["visual_contract"])


def _expected_figure_files(
    contract: VisualContract,
) -> tuple[dict[str, FigureSpec], dict[str, FigureSpec]]:
    main = {
        f"{figure.output_name}.{extension}": figure
        for figure in contract.main_figures
        for extension in figure.export_formats
    }
    supplementary = {
        f"{figure.output_name}.{extension}": figure
        for figure in contract.supplementary_figures
        for extension in figure.export_formats
    }
    return main, supplementary


def _validate_figure_manifest(
    directory: Path,
    expected: dict[str, FigureSpec],
    *,
    run_id: str,
    snapshot_sha256: str,
    resource_sha256: str,
) -> None:
    manifest_path = directory / "figure_manifest.csv"
    with manifest_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != EXPECTED_MANIFEST_COLUMNS:
            raise ValueError(f"invalid figure manifest columns: {manifest_path}")
        rows = list(reader)
    by_file = {row["file"]: row for row in rows}
    if len(by_file) != len(rows) or set(by_file) != set(expected):
        raise ValueError(f"figure manifest file set mismatch: {manifest_path}")
    for filename, figure in expected.items():
        row = by_file[filename]
        path = directory / filename
        extension = path.suffix.removeprefix(".")
        if row["figure_id"] != figure.figure_id or row["format"] != extension:
            raise ValueError(f"figure identity mismatch for {filename}")
        if row["run_id"] != run_id:
            raise ValueError(f"figure run_id mismatch for {filename}")
        if row["visual_contract_source_sha256"] != snapshot_sha256:
            raise ValueError(f"figure visual-contract source hash mismatch for {filename}")
        if row["visual_contract_resource_sha256"] != resource_sha256:
            raise ValueError(f"figure visual-contract resource hash mismatch for {filename}")
        if float(row["width_in"]) != figure.width_in:
            raise ValueError(f"figure width mismatch for {filename}")
        if float(row["height_in"]) != figure.height_in:
            raise ValueError(f"figure height mismatch for {filename}")
        if int(float(row["bytes"])) != path.stat().st_size:
            raise ValueError(f"figure byte-size mismatch for {filename}")
        if row["sha256"] != sha256_file(path):
            raise ValueError(f"figure hash mismatch for {filename}")


def _validate_rendered_tree(
    root: Path,
    contract: VisualContract,
    *,
    run_id: str,
    snapshot_sha256: str,
    resource_sha256: str,
) -> None:
    main_expected, supplementary_expected = _expected_figure_files(contract)
    main = root / "main"
    supplementary = root / "supplementary"
    for directory, expected, allowed_receipts in (
        (main, main_expected, {"figure_manifest.csv", "synthetic_render_success.json"}),
        (supplementary, supplementary_expected, {"figure_manifest.csv"}),
    ):
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError(f"figure output directory is missing or unsafe: {directory}")
        observed = {path.name for path in iter_regular_files(directory)}
        required = set(expected) | allowed_receipts
        if observed != required:
            raise ValueError(
                f"rendered figure set mismatch below {directory}: "
                f"missing={sorted(required - observed)}, extra={sorted(observed - required)}"
            )
        _validate_figure_manifest(
            directory,
            expected,
            run_id=run_id,
            snapshot_sha256=snapshot_sha256,
            resource_sha256=resource_sha256,
        )
    success_path = main / "synthetic_render_success.json"
    success = json.loads(success_path.read_text(encoding="utf-8"))
    if success.get("schema_version") != "hfmd-synthetic-figure-render-v1":
        raise ValueError("synthetic render success record has an unknown schema")
    if success.get("run_id") != run_id or success.get("status") != PURPOSE:
        raise ValueError("synthetic render success identity mismatch")
    if success.get("scientific_inference_allowed") is not False:
        raise ValueError("synthetic render record must prohibit scientific inference")
    if success.get("visual_contract_source_sha256") != snapshot_sha256:
        raise ValueError("synthetic render record is not bound to the run snapshot")
    if success.get("visual_contract_resource_sha256") != resource_sha256:
        raise ValueError("synthetic render record has a visual-contract resource mismatch")


def _r_renderer(
    workspace: Path,
    run_root: Path,
    main: Path,
    supplementary: Path,
    run_id: str,
    profile: ProfileName,
) -> None:
    configured_runner = os.environ.get("HFMD_R_RUNNER", "Rscript")
    rscript = shutil.which(configured_runner)
    if rscript is None:
        raise FileNotFoundError(
            f"configured R runner is required to render the visual contract: {configured_runner}"
        )
    snapshot = run_root / "config" / "config.snapshot.json"
    environment = os.environ.copy()
    environment.update(
        {
            "HFMD_RUN_ID": run_id,
            "HFMD_PROFILE": profile.value,
            "HFMD_FORMAL": "false",
            "HFMD_VISUAL_CONTRACT": snapshot.as_posix(),
            "R_LIBS_USER": (workspace / ".r_library").as_posix(),
            "TZ": "UTC",
            "LC_ALL": "C.UTF-8",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    subprocess.run(
        [
            rscript,
            (workspace / "Script_r" / "render_synthetic_contract.R").as_posix(),
            run_root.as_posix(),
            main.as_posix(),
            supplementary.as_posix(),
        ],
        cwd=workspace,
        env=environment,
        check=True,
    )


def _parent_inputs(receipts: Sequence[StageReceipt]) -> tuple[ReceiptFile, ...]:
    records: dict[tuple[str, str], ReceiptFile] = {}
    for receipt in receipts:
        for record in receipt.outputs:
            key = (record.scope, record.path)
            if key in records and records[key] != record:
                raise ValueError(f"conflicting parent output record: {record.path}")
            records[key] = record
    return tuple(records[key] for key in sorted(records))


def run_figures(
    *,
    run_id: str,
    profile: ProfileName | str,
    run_root: Path,
    ecological_receipt: Path,
    dynamics_receipt: Path,
    receipt_path: Path,
    workspace: Path | None = None,
    renderer: Renderer = _r_renderer,
) -> dict[str, Any]:
    """Render and receipt one immutable visual-contract candidate."""

    requested_profile = ProfileName(profile)
    run_root = run_root.resolve(strict=True)
    workspace = (workspace or discover_workspace(Path(__file__))).resolve(strict=True)
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    if loaded.config.runtime.profile != requested_profile:
        raise ValueError("requested profile disagrees with the run configuration snapshot")
    ecological = _load_parent(
        ecological_receipt,
        expected_stage="ecological",
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=requested_profile,
    )
    dynamics = _load_parent(
        dynamics_receipt,
        expected_stage="dynamics",
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=requested_profile,
    )
    if requested_profile is ProfileName.RESTRICTED:
        raise RestrictedFiguresBlocked(
            "formal figure rendering is blocked until all required model, figure-data, "
            "panel-value, font, and perceptual audits are implemented; legacy caches are refused"
        )

    output_root = run_root / "figures"
    receipt_path = receipt_path.absolute()
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(f"refusing to reuse figure output root: {output_root}")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace figure receipt: {receipt_path}")

    contract = _visual_contract(run_root)
    temporary = Path(tempfile.mkdtemp(prefix=".figures.staging-", dir=run_root))
    try:
        main = temporary / "main"
        supplementary = temporary / "supplementary"
        renderer(workspace, run_root, main, supplementary, run_id, requested_profile)
        snapshot_sha256 = sha256_file(run_root / "config" / "config.snapshot.json")
        _validate_rendered_tree(
            temporary,
            contract,
            run_id=run_id,
            snapshot_sha256=snapshot_sha256,
            resource_sha256=loaded.source_hashes["visual_contract.yaml"],
        )
        temporary.replace(output_root)
        outputs = tuple(iter_regular_files(output_root))
        input_files = _parent_inputs((ecological, dynamics))
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="figures",
            config_snapshot=run_root / "config" / "config.snapshot.json",
            output_paths=outputs,
            output_classification="synthetic",
            parent_receipts=(ecological_receipt, dynamics_receipt),
            input_files=input_files,
            exact_input_roots=(("run", "analysis/ecological"), ("run", "analysis/dynamics")),
            exact_output_roots=(output_root,),
            metadata={
                "purpose": PURPOSE,
                "scientific_inference_allowed": False,
                "main_figure_count": len(contract.main_figures),
                "supplementary_figure_count": len(contract.supplementary_figures),
                "legacy_visual_language_preserved": True,
                "legacy_numeric_results_used": False,
                "formal_visual_audit_executed": False,
            },
        )
        write_stage_receipt(receipt, receipt_path)
        report = validate_stage_receipt(
            receipt_path,
            run_root=run_root,
            workspace=workspace,
        )
        if not report.ok:
            raise RuntimeError("figure receipt failed self-validation: " + "; ".join(report.issues))
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)
        receipt_path.unlink(missing_ok=True)
        raise

    return {
        "status": PURPOSE,
        "run_id": run_id,
        "profile": requested_profile.value,
        "scientific_inference_allowed": False,
        "main_figure_count": 5,
        "supplementary_figure_count": 10,
        "output_files": len(outputs),
        "receipt_sha256": report.receipt_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("ci", "synthetic", "restricted"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--ecological-receipt", type=Path, required=True)
    parser.add_argument("--dynamics-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run_figures(
        run_id=args.run_id,
        profile=args.profile,
        run_root=args.run_root,
        ecological_receipt=args.ecological_receipt,
        dynamics_receipt=args.dynamics_receipt,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
