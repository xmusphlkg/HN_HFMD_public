"""Validation and receipt generation for an Epidemics submission package."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import (
    atomic_write_bytes,
    atomic_write_json,
    iter_regular_files,
    sha256_file,
)
from hfmd.core.receipts import (
    ReceiptFile,
    StageReceipt,
    build_stage_receipt,
    receipt_file,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.core.run import discover_workspace

WORD_PATTERN = re.compile(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*")
PLACEHOLDER_PATTERN = re.compile(r"(?:\bTBD\b|\bTODO\b|\bUNKNOWN\b|\[.+?\]|<.+?>)", re.IGNORECASE)


def _require_authored_value(value: str) -> str:
    cleaned = value.strip()
    if not cleaned or PLACEHOLDER_PATTERN.search(cleaned):
        raise ValueError("required authored metadata is empty or contains a placeholder")
    return cleaned


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    affiliations: tuple[str, ...] = Field(min_length=1)
    email: str | None = None
    corresponding: bool = False

    _name = field_validator("name")(_require_authored_value)


class EthicsMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_status: Literal["approved", "exempt"]
    committee: str
    approval_number: str | None = None
    exemption_statement: str | None = None

    _committee = field_validator("committee")(_require_authored_value)

    @model_validator(mode="after")
    def require_review_evidence(self) -> EthicsMetadata:
        if self.review_status == "approved":
            if self.approval_number is None:
                raise ValueError("approved studies require an ethics approval number")
            _require_authored_value(self.approval_number)
        elif self.exemption_statement is None:
            raise ValueError("exempt studies require an authored exemption statement")
        else:
            _require_authored_value(self.exemption_statement)
        return self


class ControlledDataAccess(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_controller: str
    request_route: str
    access_conditions: str

    _controller = field_validator("data_controller")(_require_authored_value)
    _route = field_validator("request_route")(_require_authored_value)
    _conditions = field_validator("access_conditions")(_require_authored_value)


class SubmissionFiles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manuscript: str
    supplementary_material: str
    title_page: str
    cover_letter: str
    graphical_abstract: str
    record_checklist: str
    strobe_checklist: str
    credit_statement: str


class EpidemicsSubmissionMetadata(BaseModel):
    """Required authored metadata; values are validated, never inferred."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    journal: Literal["Epidemics"] = "Epidemics"
    title: str
    abstract: str
    keywords: tuple[str, ...] = Field(min_length=1, max_length=7)
    highlights: tuple[str, ...] = Field(min_length=3, max_length=5)
    authors: tuple[Author, ...] = Field(min_length=1)
    ethics: EthicsMetadata
    controlled_data_access: ControlledDataAccess
    funding_statement: str
    competing_interests_statement: str
    data_availability_statement: str
    code_availability_statement: str
    ai_disclosure: str
    files: SubmissionFiles

    _title = field_validator("title")(_require_authored_value)
    _funding = field_validator("funding_statement")(_require_authored_value)
    _coi = field_validator("competing_interests_statement")(_require_authored_value)
    _data = field_validator("data_availability_statement")(_require_authored_value)
    _code = field_validator("code_availability_statement")(_require_authored_value)
    _ai = field_validator("ai_disclosure")(_require_authored_value)

    @field_validator("abstract")
    @classmethod
    def validate_abstract(cls, value: str) -> str:
        value = _require_authored_value(value)
        word_count = len(WORD_PATTERN.findall(value))
        if word_count > 250:
            raise ValueError(f"Epidemics abstract has {word_count} words; maximum is 250")
        return value

    @field_validator("keywords")
    @classmethod
    def validate_keywords(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_require_authored_value(value) for value in values)
        normalized = [value.casefold() for value in cleaned]
        if len(set(normalized)) != len(normalized):
            raise ValueError("keywords must be unique")
        return cleaned

    @field_validator("highlights")
    @classmethod
    def validate_highlights(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_require_authored_value(value) for value in values)
        too_long = [value for value in cleaned if len(value) > 85]
        if too_long:
            raise ValueError("each Epidemics highlight must contain at most 85 characters")
        return cleaned

    @model_validator(mode="after")
    def require_corresponding_author(self) -> EpidemicsSubmissionMetadata:
        corresponding = [author for author in self.authors if author.corresponding]
        if not corresponding:
            raise ValueError("at least one corresponding author must be declared")
        if any(not author.email for author in corresponding):
            raise ValueError("every corresponding author requires an email address")
        return self


def validate_submission_files(
    metadata: EpidemicsSubmissionMetadata, base_directory: str | Path
) -> dict[str, dict[str, str | int]]:
    """Validate every declared deliverable and return its immutable receipt."""

    root = Path(base_directory).resolve()
    receipt: dict[str, dict[str, str | int]] = {}
    for role, relative_value in metadata.files.model_dump().items():
        relative = Path(relative_value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"submission path for {role} must remain package-relative")
        path = (root / relative).resolve()
        if not path.is_file():
            raise ValueError(f"missing required submission file for {role}: {relative}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt[role] = {
            "path": relative.as_posix(),
            "sha256": digest,
            "size_bytes": path.stat().st_size,
        }
    graphical = Path(metadata.files.graphical_abstract).suffix.casefold()
    if graphical not in {".pdf", ".svg", ".png", ".tif", ".tiff"}:
        raise ValueError("graphical abstract must be a PDF, SVG, PNG, or TIFF")
    return receipt


PURPOSE = "synthetic_validation"
SYNTHETIC_WARNING = "SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE OR SUBMISSION"
GA_MANIFEST_COLUMNS = {
    "file",
    "format",
    "run_id",
    "profile",
    "synthetic_validation",
    "parent_manifest_sha256",
    "summary_sha256",
    "visual_contract_source_sha256",
    "visual_contract_resource_sha256",
    "bytes",
    "sha256",
}


class RestrictedSubmissionBlocked(RuntimeError):
    """Raised when authored metadata or formal evidence is incomplete."""


GraphicalAbstractRenderer = Callable[[Path, Path, Path, Path, str, ProfileName], None]


def _path_below(path: Path, root: Path, *, label: str) -> Path:
    root = root.resolve(strict=True)
    candidate = path.resolve(strict=path.exists())
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes the run staging root") from exc
    if candidate.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    return candidate


def _load_manuscript_receipt(
    path: Path,
    *,
    run_root: Path,
    workspace: Path,
    run_id: str,
    profile: ProfileName,
) -> StageReceipt:
    path = _path_below(path.resolve(strict=True), run_root, label="manuscript receipt")
    report = validate_stage_receipt(path, run_root=run_root, workspace=workspace)
    if not report.ok:
        raise RuntimeError("manuscript receipt validation failed: " + "; ".join(report.issues))
    receipt = StageReceipt.model_validate_json(path.read_text(encoding="utf-8"))
    if receipt.stage != "manuscript":
        raise ValueError(f"expected a manuscript receipt, found {receipt.stage!r}")
    if receipt.run_id != run_id or receipt.profile != profile:
        raise ValueError("manuscript receipt identity does not match the submission run")
    return receipt


def _metadata_path(workspace: Path, profile: ProfileName) -> Path:
    name = (
        "submission.synthetic.yaml"
        if profile is not ProfileName.RESTRICTED
        else "submission.restricted.yaml"
    )
    return workspace / "config" / name


def load_submission_metadata(path: Path) -> EpidemicsSubmissionMetadata:
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError(path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("submission metadata must contain a YAML mapping")
    return EpidemicsSubmissionMetadata.model_validate(payload)


def _graphical_abstract_summary(
    path: Path,
    *,
    run_id: str,
    profile: ProfileName,
    parent_sha256: str,
) -> None:
    fields = (
        "run_id",
        "parent_manifest_sha256",
        "profile",
        "evidence_layer",
        "label",
        "estimate",
        "interval_low",
        "interval_high",
        "unit",
        "gate_status",
        "display_order",
    )
    layers = (
        ("data_contract", "Synthetic data contract"),
        ("ecological_models", "Ecological models"),
        ("dynamics_models", "Dynamics mechanisms"),
        ("science_gates", "Scientific conclusions"),
    )
    buffer: list[str] = []
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for order, (layer, label) in enumerate(layers, start=1):
        writer.writerow(
            {
                "run_id": run_id,
                "parent_manifest_sha256": parent_sha256,
                "profile": profile.value,
                "evidence_layer": layer,
                "label": label,
                "estimate": "",
                "interval_low": "",
                "interval_high": "",
                "unit": "",
                "gate_status": "not_evaluated",
                "display_order": order,
            }
        )
    buffer.append(stream.getvalue())
    atomic_write_bytes(path, "".join(buffer).encode("utf-8"), mode=0o600)


def _r_graphical_abstract_renderer(
    workspace: Path,
    run_root: Path,
    summary: Path,
    output: Path,
    run_id: str,
    profile: ProfileName,
) -> None:
    configured_runner = os.environ.get("HFMD_R_RUNNER", "Rscript")
    rscript = shutil.which(configured_runner)
    if rscript is None:
        raise FileNotFoundError(
            f"configured R runner is required to build the graphical abstract: {configured_runner}"
        )
    environment = os.environ.copy()
    environment.update(
        {
            "HFMD_RUN_ID": run_id,
            "HFMD_PROFILE": profile.value,
            "HFMD_FORMAL": "false",
            "HFMD_VISUAL_CONTRACT": (run_root / "config" / "config.snapshot.json").as_posix(),
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
            (workspace / "Script_r" / "render_graphical_abstract.R").as_posix(),
            run_root.as_posix(),
            summary.as_posix(),
            output.as_posix(),
        ],
        cwd=workspace,
        env=environment,
        check=True,
    )


def _validate_graphical_abstract(
    directory: Path,
    *,
    summary: Path,
    run_id: str,
    profile: ProfileName,
    parent_sha256: str,
    snapshot_sha256: str,
    resource_sha256: str,
) -> None:
    expected_files = {
        "graphical_abstract.pdf",
        "graphical_abstract.svg",
        "graphical_abstract_manifest.csv",
    }
    observed = {path.name for path in iter_regular_files(directory)}
    if observed != expected_files:
        raise ValueError(
            "graphical abstract output set mismatch: "
            f"missing={sorted(expected_files - observed)}, "
            f"extra={sorted(observed - expected_files)}"
        )
    manifest = directory / "graphical_abstract_manifest.csv"
    with manifest.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != GA_MANIFEST_COLUMNS:
            raise ValueError("graphical abstract manifest columns are invalid")
        rows = list(reader)
    if len(rows) != 2 or {row["file"] for row in rows} != {
        "graphical_abstract.pdf",
        "graphical_abstract.svg",
    }:
        raise ValueError("graphical abstract manifest file set is invalid")
    for row in rows:
        path = directory / row["file"]
        if row["run_id"] != run_id or row["profile"] != profile.value:
            raise ValueError("graphical abstract run identity mismatch")
        if row["synthetic_validation"].casefold() != "true":
            raise ValueError("public graphical abstract must be marked synthetic")
        if row["parent_manifest_sha256"] != parent_sha256:
            raise ValueError("graphical abstract parent hash mismatch")
        if row["summary_sha256"] != sha256_file(summary):
            raise ValueError("graphical abstract summary hash mismatch")
        if row["visual_contract_source_sha256"] != snapshot_sha256:
            raise ValueError("graphical abstract snapshot hash mismatch")
        if row["visual_contract_resource_sha256"] != resource_sha256:
            raise ValueError("graphical abstract resource hash mismatch")
        if int(float(row["bytes"])) != path.stat().st_size:
            raise ValueError("graphical abstract byte-size mismatch")
        if row["sha256"] != sha256_file(path):
            raise ValueError("graphical abstract file hash mismatch")


def _docx(path: Path, text: str) -> None:
    from hfmd.reporting.manuscript import _minimal_docx_bytes

    atomic_write_bytes(path, _minimal_docx_bytes(text), mode=0o600)


def _authored_documents(
    root: Path,
    metadata: EpidemicsSubmissionMetadata,
) -> None:
    warning = SYNTHETIC_WARNING
    authors = "\n".join(
        f"- {author.name}; {', '.join(author.affiliations)}" for author in metadata.authors
    )
    _docx(
        root / metadata.files.title_page,
        f"# {warning}\n\n# {metadata.title}\n\n{authors}\n",
    )
    _docx(
        root / metadata.files.cover_letter,
        f"# {warning}\n\nDear Editor,\n\nThis package is an automated synthetic "
        "workflow test. It must not be submitted and contains no study findings.\n",
    )
    _docx(
        root / metadata.files.record_checklist,
        f"# RECORD checklist\n\n{warning}\n\nNot applicable to generated fixture records.\n",
    )
    _docx(
        root / metadata.files.strobe_checklist,
        f"# STROBE checklist\n\n{warning}\n\nNot applicable to this software validation.\n",
    )
    _docx(
        root / metadata.files.credit_statement,
        f"# CRediT statement\n\n{warning}\n\n"
        "Synthetic Validation Author: software, validation, and workflow testing.\n",
    )
    atomic_write_bytes(
        root / "highlights.txt",
        (warning + "\n\n" + "\n".join(f"• {item}" for item in metadata.highlights) + "\n").encode(
            "utf-8"
        ),
        mode=0o600,
    )
    declarations = (
        f"# {warning}\n\n"
        f"## Ethics\n\n{metadata.ethics.exemption_statement}\n\n"
        f"## Funding\n\n{metadata.funding_statement}\n\n"
        f"## Competing interests\n\n{metadata.competing_interests_statement}\n\n"
        f"## Data availability\n\n{metadata.data_availability_statement}\n\n"
        f"## Code availability\n\n{metadata.code_availability_statement}\n\n"
        f"## AI disclosure\n\n{metadata.ai_disclosure}\n"
    )
    atomic_write_bytes(root / "declarations.md", declarations.encode("utf-8"), mode=0o600)


def _copy_manuscript_sources(run_root: Path, root: Path) -> None:
    for source_name, destination_name in (
        ("manuscript.docx", "manuscript.docx"),
        ("supplementary.docx", "supplementary.docx"),
    ):
        source = run_root / "manuscript" / source_name
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError(source)
        shutil.copyfile(source, root / destination_name)
        os.chmod(root / destination_name, 0o600)


def _unique_receipt_inputs(
    manuscript: StageReceipt,
    metadata_record: ReceiptFile,
) -> tuple[ReceiptFile, ...]:
    records = {(record.scope, record.path): record for record in manuscript.outputs}
    records[(metadata_record.scope, metadata_record.path)] = metadata_record
    return tuple(records[key] for key in sorted(records))


def run_submission_pipeline(
    *,
    run_id: str,
    profile: ProfileName | str,
    run_root: Path,
    manuscript_receipt: Path,
    receipt_path: Path,
    journal: str = "epidemics",
    workspace: Path | None = None,
    graphical_abstract_renderer: GraphicalAbstractRenderer = _r_graphical_abstract_renderer,
) -> dict[str, Any]:
    """Build a synthetic Epidemics package or fail closed for formal submission."""

    if journal.casefold() != "epidemics":
        raise ValueError("only the Epidemics submission contract is implemented")
    run_root = run_root.resolve(strict=True)
    workspace = (workspace or discover_workspace(run_root)).resolve(strict=True)
    requested_profile = ProfileName(profile)
    snapshot_path = run_root / "config" / "config.snapshot.json"
    snapshot = read_config_snapshot(snapshot_path)
    if snapshot.config.runtime.profile != requested_profile:
        raise ValueError("requested profile does not match the configuration snapshot")
    receipt_path = _path_below(receipt_path.absolute(), run_root, label="submission receipt")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace submission receipt: {receipt_path}")
    manuscript_receipt = manuscript_receipt.resolve(strict=True)
    manuscript = _load_manuscript_receipt(
        manuscript_receipt,
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=requested_profile,
    )
    metadata_path = _metadata_path(workspace, requested_profile)
    if requested_profile is ProfileName.RESTRICTED:
        if not metadata_path.is_file():
            raise RestrictedSubmissionBlocked(
                "authored config/submission.restricted.yaml is missing; author, ethics, "
                "data-controller, funding, conflict, and AI metadata are never inferred"
            )
        load_submission_metadata(metadata_path)
        raise RestrictedSubmissionBlocked(
            "formal submission remains blocked until the restricted manuscript receipt "
            "certifies completed models, uncertainty analyses, and science gates"
        )
    metadata = load_submission_metadata(metadata_path)
    if manuscript.metadata.get("submission_allowed") is not False:
        raise ValueError("synthetic manuscript receipt lacks the submission prohibition")

    output_root = run_root / "submission"
    if output_root.exists() or output_root.is_symlink():
        raise FileExistsError(f"refusing to reuse submission output root: {output_root}")
    temporary = Path(tempfile.mkdtemp(prefix=".submission.staging-", dir=run_root))
    try:
        _copy_manuscript_sources(run_root, temporary)
        _authored_documents(temporary, metadata)
        atomic_write_json(
            temporary / "submission_metadata.json",
            metadata.model_dump(mode="json"),
            mode=0o600,
        )
        parent_sha256 = sha256_file(manuscript_receipt)
        summary = temporary / "graphical_abstract_summary.csv"
        _graphical_abstract_summary(
            summary,
            run_id=run_id,
            profile=requested_profile,
            parent_sha256=parent_sha256,
        )
        graphical = temporary / "graphical_abstract"
        graphical_abstract_renderer(
            workspace,
            run_root,
            summary,
            graphical,
            run_id,
            requested_profile,
        )
        snapshot_sha256 = sha256_file(snapshot_path)
        _validate_graphical_abstract(
            graphical,
            summary=summary,
            run_id=run_id,
            profile=requested_profile,
            parent_sha256=parent_sha256,
            snapshot_sha256=snapshot_sha256,
            resource_sha256=snapshot.source_hashes["visual_contract.yaml"],
        )
        declared_files = validate_submission_files(metadata, temporary)
        premanifest_files = tuple(iter_regular_files(temporary))
        package_manifest = {
            "schema_version": "hfmd-epidemics-submission-manifest-v1",
            "package_version": "synthetic-validation-v0.1.0",
            "run_id": run_id,
            "profile": requested_profile.value,
            "journal": "Epidemics",
            "purpose": PURPOSE,
            "scientific_inference_allowed": False,
            "submission_allowed": False,
            "warning": SYNTHETIC_WARNING,
            "config_sha256": snapshot.config_sha256,
            "parent_manuscript_receipt_sha256": parent_sha256,
            "declared_submission_files": declared_files,
            "files": [
                {
                    "path": path.relative_to(temporary).as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in premanifest_files
            ],
        }
        atomic_write_json(temporary / "submission_manifest.json", package_manifest, mode=0o600)
        temporary.replace(output_root)
        outputs = tuple(iter_regular_files(output_root))
        metadata_record = receipt_file(
            metadata_path,
            scope="workspace",
            run_root=run_root,
            workspace=workspace,
            classification="public",
        )
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="submission",
            config_snapshot=snapshot_path,
            output_paths=outputs,
            output_classification="synthetic",
            parent_receipts=(manuscript_receipt,),
            input_files=_unique_receipt_inputs(manuscript, metadata_record),
            exact_input_roots=(("run", "reporting"), ("run", "manuscript")),
            exact_output_roots=(output_root,),
            metadata={
                "journal": "Epidemics",
                "purpose": PURPOSE,
                "scientific_inference_allowed": False,
                "submission_allowed": False,
                "metadata_authored_fixture": metadata_path.relative_to(workspace).as_posix(),
                "graphical_abstract_renderer": "R_vector_code",
                "generative_imagery_used": False,
                "declared_submission_file_count": len(declared_files),
            },
        )
        write_stage_receipt(receipt, receipt_path)
        report = validate_stage_receipt(receipt_path, run_root=run_root, workspace=workspace)
        if not report.ok:
            raise RuntimeError(
                "submission receipt failed self-validation: " + "; ".join(report.issues)
            )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        shutil.rmtree(output_root, ignore_errors=True)
        receipt_path.unlink(missing_ok=True)
        raise

    return {
        "status": PURPOSE,
        "run_id": run_id,
        "profile": requested_profile.value,
        "journal": "epidemics",
        "scientific_inference_allowed": False,
        "submission_allowed": False,
        "output_files": len(outputs),
        "receipt_sha256": report.receipt_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("ci", "synthetic", "restricted"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--journal", default="epidemics")
    parser.add_argument("--manuscript-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run_submission_pipeline(
        run_id=args.run_id,
        profile=args.profile,
        run_root=args.run_root,
        manuscript_receipt=args.manuscript_receipt,
        receipt_path=args.receipt,
        journal=args.journal,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
