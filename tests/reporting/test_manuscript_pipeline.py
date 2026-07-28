from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pytest

from hfmd.core.config import (
    ProfileName,
    load_config,
    read_config_snapshot,
    write_config_snapshot,
)
from hfmd.core.hashing import sha256_file
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.reporting.claims import load_claims
from hfmd.reporting.manuscript import (
    RestrictedManuscriptBlocked,
    run_manuscript_pipeline,
)
from hfmd.reporting.submission import (
    RestrictedSubmissionBlocked,
    run_submission_pipeline,
)

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-manuscript-test"


def _evidence_chain(tmp_path: Path, profile: str) -> tuple[Path, Path]:
    run_root = tmp_path / ".runs" / RUN_ID / "staging"
    (run_root / "config").mkdir(parents=True)
    (run_root / "receipts").mkdir()
    write_config_snapshot(
        load_config(ROOT / "config" / "project.yaml", profile),
        run_root / "config" / "config.snapshot.json",
    )
    classification = "synthetic" if profile != "restricted" else "controlled_derived"
    parents: list[Path] = []
    for stage, totals in (
        (
            "ecological",
            {"reported_cases": 100, "typed_cases": 50, "region_year_cells": 12},
        ),
        (
            "dynamics",
            {
                "reported_cases": 100,
                "resolved_typing_cases": 50,
                "rolling_origin_folds": 7,
            },
        ),
    ):
        output_root = run_root / "analysis" / stage
        output_root.mkdir(parents=True)
        summary = output_root / "summary.json"
        summary.write_text(
            json.dumps(
                {
                    "schema_version": "hfmd-synthetic-analysis-summary-v1",
                    "run_id": RUN_ID,
                    "profile": profile,
                    "analysis_line": stage,
                    "purpose": "synthetic_validation",
                    "scientific_inference_allowed": False,
                    "formal_models_executed": 0,
                    "computed_totals": totals,
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
            output_paths=(summary,),
            output_classification=classification,  # type: ignore[arg-type]
            exact_output_roots=(output_root,),
        )
        path = run_root / "receipts" / f"{stage}.json"
        write_stage_receipt(receipt, path)
        parents.append(path)

    figure_root = run_root / "figures"
    figure_root.mkdir()
    figure = figure_root / "synthetic-validation.svg"
    figure.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>\n', encoding="utf-8")
    figure_receipt = build_stage_receipt(
        run_root=run_root,
        workspace=ROOT,
        run_id=RUN_ID,
        stage="figures",
        config_snapshot=run_root / "config" / "config.snapshot.json",
        output_paths=(figure,),
        output_classification=classification,  # type: ignore[arg-type]
        parent_receipts=tuple(parents),
        exact_output_roots=(figure_root,),
        metadata={"scientific_inference_allowed": False},
    )
    figure_receipt_path = run_root / "receipts" / "figures.json"
    write_stage_receipt(figure_receipt, figure_receipt_path)
    return run_root, figure_receipt_path


def test_synthetic_manuscript_is_editable_labelled_and_receipted(tmp_path: Path) -> None:
    run_root, figures = _evidence_chain(tmp_path, "ci")
    receipt_path = run_root / "receipts" / "manuscript.json"

    result = run_manuscript_pipeline(
        run_id=RUN_ID,
        profile="ci",
        run_root=run_root,
        figures_receipt=figures,
        receipt_path=receipt_path,
        workspace=ROOT,
    )

    assert result["status"] == "synthetic_validation"
    assert result["submission_allowed"] is False
    assert result["output_files"] == 8
    report = validate_stage_receipt(receipt_path, run_root=run_root, workspace=ROOT)
    assert report.ok, report.issues
    receipt = StageReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    assert [parent.stage for parent in receipt.parents] == ["figures"]
    assert receipt.metadata["formal_submission_ready"] is False

    claims = load_claims(run_root / "reporting" / "claims.json")
    assert len(claims.claims) == 3
    manuscript = (run_root / "manuscript" / "manuscript.md").read_text(encoding="utf-8")
    assert "SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE" in manuscript
    assert "{{claim:" not in manuscript
    with zipfile.ZipFile(run_root / "manuscript" / "manuscript.docx") as archive:
        assert "word/document.xml" in archive.namelist()


def test_manuscript_rejects_tampered_analysis_parent(tmp_path: Path) -> None:
    run_root, figures = _evidence_chain(tmp_path, "ci")
    (run_root / "analysis" / "dynamics" / "summary.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="dynamics receipt validation failed"):
        run_manuscript_pipeline(
            run_id=RUN_ID,
            profile="ci",
            run_root=run_root,
            figures_receipt=figures,
            receipt_path=run_root / "receipts" / "manuscript.json",
            workspace=ROOT,
        )
    assert not (run_root / "manuscript").exists()


def test_restricted_manuscript_fails_before_writing(tmp_path: Path) -> None:
    run_root, figures = _evidence_chain(tmp_path, "restricted")
    with pytest.raises(RestrictedManuscriptBlocked, match="author-supplied ethics"):
        run_manuscript_pipeline(
            run_id=RUN_ID,
            profile="restricted",
            run_root=run_root,
            figures_receipt=figures,
            receipt_path=run_root / "receipts" / "manuscript.json",
            workspace=ROOT,
        )
    assert not (run_root / "manuscript").exists()
    assert not (run_root / "receipts" / "manuscript.json").exists()


def _fake_graphical_abstract(
    _: Path,
    run_root: Path,
    summary: Path,
    output: Path,
    run_id: str,
    profile: ProfileName,
) -> None:
    output.mkdir()
    files = []
    for extension in ("pdf", "svg"):
        path = output / f"graphical_abstract.{extension}"
        path.write_bytes(f"synthetic graphical abstract {extension}\n".encode())
        files.append(path)
    with summary.open("r", encoding="utf-8", newline="") as handle:
        parent_hash = next(csv.DictReader(handle))["parent_manifest_sha256"]
    loaded = read_config_snapshot(run_root / "config" / "config.snapshot.json")
    snapshot_hash = sha256_file(run_root / "config" / "config.snapshot.json")
    rows = [
        {
            "file": path.name,
            "format": path.suffix.removeprefix("."),
            "run_id": run_id,
            "profile": profile.value,
            "synthetic_validation": "TRUE",
            "parent_manifest_sha256": parent_hash,
            "summary_sha256": sha256_file(summary),
            "visual_contract_source_sha256": snapshot_hash,
            "visual_contract_resource_sha256": loaded.source_hashes["visual_contract.yaml"],
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in files
    ]
    with (output / "graphical_abstract_manifest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_synthetic_submission_package_is_explicitly_non_submittable(
    tmp_path: Path,
) -> None:
    run_root, figures = _evidence_chain(tmp_path, "ci")
    manuscript_receipt = run_root / "receipts" / "manuscript.json"
    run_manuscript_pipeline(
        run_id=RUN_ID,
        profile="ci",
        run_root=run_root,
        figures_receipt=figures,
        receipt_path=manuscript_receipt,
        workspace=ROOT,
    )

    submission_receipt = run_root / "receipts" / "submission.json"
    result = run_submission_pipeline(
        run_id=RUN_ID,
        profile="ci",
        run_root=run_root,
        manuscript_receipt=manuscript_receipt,
        receipt_path=submission_receipt,
        workspace=ROOT,
        graphical_abstract_renderer=_fake_graphical_abstract,
    )

    assert result["status"] == "synthetic_validation"
    assert result["submission_allowed"] is False
    assert result["output_files"] == 15
    report = validate_stage_receipt(submission_receipt, run_root=run_root, workspace=ROOT)
    assert report.ok, report.issues
    package = json.loads(
        (run_root / "submission" / "submission_manifest.json").read_text(encoding="utf-8")
    )
    assert package["submission_allowed"] is False
    assert package["scientific_inference_allowed"] is False
    assert package["journal"] == "Epidemics"
    assert len(package["declared_submission_files"]) == 8


def test_restricted_submission_requires_authored_metadata(tmp_path: Path) -> None:
    run_root, figures = _evidence_chain(tmp_path, "restricted")
    reporting = run_root / "reporting"
    manuscript_root = run_root / "manuscript"
    reporting.mkdir()
    manuscript_root.mkdir()
    claims = reporting / "claims.json"
    main = manuscript_root / "manuscript.docx"
    supplementary = manuscript_root / "supplementary.docx"
    claims.write_text("{}\n", encoding="utf-8")
    main.write_bytes(b"formal placeholder")
    supplementary.write_bytes(b"formal placeholder")
    manuscript = build_stage_receipt(
        run_root=run_root,
        workspace=ROOT,
        run_id=RUN_ID,
        stage="manuscript",
        config_snapshot=run_root / "config" / "config.snapshot.json",
        output_paths=(claims, main, supplementary),
        output_classification="controlled_derived",
        parent_receipts=(figures,),
        exact_output_roots=(reporting, manuscript_root),
        metadata={"formal_submission_ready": False},
    )
    manuscript_receipt = run_root / "receipts" / "manuscript.json"
    write_stage_receipt(manuscript, manuscript_receipt)

    with pytest.raises(RestrictedSubmissionBlocked, match="never inferred"):
        run_submission_pipeline(
            run_id=RUN_ID,
            profile="restricted",
            run_root=run_root,
            manuscript_receipt=manuscript_receipt,
            receipt_path=run_root / "receipts" / "submission.json",
            workspace=ROOT,
        )
    assert not (run_root / "submission").exists()
