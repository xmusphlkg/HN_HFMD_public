from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hfmd.core.config import load_config, read_config_snapshot, write_config_snapshot
from hfmd.core.hashing import sha256_file
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.reporting.contracts import VisualContract
from hfmd.reporting.figures import RestrictedFiguresBlocked, run_figures

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-figure-test"


def _parents(tmp_path: Path, profile: str) -> tuple[Path, Path, Path]:
    run_root = tmp_path / ".runs" / RUN_ID / "staging"
    (run_root / "config").mkdir(parents=True)
    (run_root / "receipts").mkdir()
    write_config_snapshot(
        load_config(ROOT / "config" / "project.yaml", profile),
        run_root / "config" / "config.snapshot.json",
    )
    paths: list[Path] = []
    for stage in ("ecological", "dynamics"):
        output_root = run_root / "analysis" / stage
        output_root.mkdir(parents=True)
        output = output_root / "summary.json"
        output.write_text(
            json.dumps(
                {
                    "run_id": RUN_ID,
                    "purpose": "synthetic_validation" if profile != "restricted" else "formal",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=ROOT,
            run_id=RUN_ID,
            stage=stage,  # type: ignore[arg-type]
            config_snapshot=run_root / "config" / "config.snapshot.json",
            output_paths=(output,),
            output_classification="synthetic" if profile != "restricted" else "controlled_derived",
            exact_output_roots=(output_root,),
        )
        receipt_path = run_root / "receipts" / f"{stage}.json"
        write_stage_receipt(receipt, receipt_path)
        paths.append(receipt_path)
    return run_root, paths[0], paths[1]


def _fake_renderer(
    _: Path,
    run_root: Path,
    main: Path,
    supplementary: Path,
    run_id: str,
    __: object,
) -> None:
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    contract = VisualContract.model_validate(loaded.resources["visual_contract"])
    contract_hash = sha256_file(run_root / "config" / "config.snapshot.json")
    resource_hash = loaded.source_hashes["visual_contract.yaml"]
    for directory, figures in (
        (main, contract.main_figures),
        (supplementary, contract.supplementary_figures),
    ):
        directory.mkdir(parents=True)
        rows: list[dict[str, object]] = []
        for figure in figures:
            for extension in figure.export_formats:
                path = directory / f"{figure.output_name}.{extension}"
                path.write_bytes(f"synthetic {figure.figure_id} {extension}\n".encode())
                rows.append(
                    {
                        "file": path.name,
                        "figure_id": figure.figure_id,
                        "format": extension,
                        "width_in": figure.width_in,
                        "height_in": figure.height_in,
                        "run_id": run_id,
                        "visual_contract_source_sha256": contract_hash,
                        "visual_contract_resource_sha256": resource_hash,
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
        with (directory / "figure_manifest.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    (main / "synthetic_render_success.json").write_text(
        json.dumps(
            {
                "schema_version": "hfmd-synthetic-figure-render-v1",
                "status": "synthetic_validation",
                "run_id": run_id,
                "scientific_inference_allowed": False,
                "visual_contract_source_sha256": contract_hash,
                "visual_contract_resource_sha256": resource_hash,
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_synthetic_figures_are_exact_and_receipt_bound(tmp_path: Path) -> None:
    run_root, ecological, dynamics = _parents(tmp_path, "ci")
    receipt_path = run_root / "receipts" / "figures.json"

    result = run_figures(
        run_id=RUN_ID,
        profile="ci",
        run_root=run_root,
        ecological_receipt=ecological,
        dynamics_receipt=dynamics,
        receipt_path=receipt_path,
        workspace=ROOT,
        renderer=_fake_renderer,
    )

    assert result["status"] == "synthetic_validation"
    assert result["main_figure_count"] == 5
    assert result["supplementary_figure_count"] == 10
    assert result["output_files"] == 63
    report = validate_stage_receipt(receipt_path, run_root=run_root, workspace=ROOT)
    assert report.ok, report.issues
    receipt = StageReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    assert [parent.stage for parent in receipt.parents] == ["dynamics", "ecological"]
    assert receipt.metadata["legacy_visual_language_preserved"] is True
    assert receipt.metadata["legacy_numeric_results_used"] is False


def test_figures_validate_parent_before_rendering(tmp_path: Path) -> None:
    run_root, ecological, dynamics = _parents(tmp_path, "ci")
    (run_root / "analysis" / "ecological" / "summary.json").write_text(
        "tampered\n", encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="ecological receipt validation failed"):
        run_figures(
            run_id=RUN_ID,
            profile="ci",
            run_root=run_root,
            ecological_receipt=ecological,
            dynamics_receipt=dynamics,
            receipt_path=run_root / "receipts" / "figures.json",
            workspace=ROOT,
            renderer=_fake_renderer,
        )
    assert not (run_root / "figures").exists()


def test_restricted_figures_fail_closed_without_outputs(tmp_path: Path) -> None:
    run_root, ecological, dynamics = _parents(tmp_path, "restricted")
    with pytest.raises(RestrictedFiguresBlocked, match="legacy caches"):
        run_figures(
            run_id=RUN_ID,
            profile="restricted",
            run_root=run_root,
            ecological_receipt=ecological,
            dynamics_receipt=dynamics,
            receipt_path=run_root / "receipts" / "figures.json",
            workspace=ROOT,
            renderer=_fake_renderer,
        )
    assert not (run_root / "figures").exists()
    assert not (run_root / "receipts" / "figures.json").exists()
