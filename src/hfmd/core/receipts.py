"""Hash-linked stage receipts for the Snakemake execution graph."""

from __future__ import annotations

import json
import mimetypes
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import atomic_write_json, iter_regular_files, safe_relative_path, sha256_file
from hfmd.core.manifest import RUN_ID

StageName = Literal[
    "environment",
    "data",
    "ecological",
    "dynamics",
    "figures",
    "manuscript",
    "submission",
    "public_export",
]
FileScope = Literal["run", "workspace"]
type Classification = Literal[
    "public", "synthetic", "restricted", "controlled_derived", "code", "receipt"
]


class ReceiptError(RuntimeError):
    """Raised when a stage receipt or its parent chain cannot be trusted."""


class ReceiptModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReceiptFile(ReceiptModel):
    scope: FileScope
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str | None = None
    classification: Classification

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("receipt file path must be a normalized relative POSIX path")
        return value


class ParentReceipt(ReceiptModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    stage: StageName
    run_id: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("parent receipt path must be run-relative")
        return value


class ReceiptRoot(ReceiptModel):
    scope: FileScope
    path: str

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("receipt root path must be normalized and relative")
        return value


class StageReceipt(ReceiptModel):
    schema_version: Literal["hfmd-stage-receipt-v1"] = "hfmd-stage-receipt-v1"
    run_id: str
    stage: StageName
    profile: ProfileName
    formal: bool
    status: Literal["success"] = "success"
    created_at: datetime
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_snapshot: str
    config_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parents: tuple[ParentReceipt, ...] = ()
    inputs: tuple[ReceiptFile, ...] = ()
    outputs: tuple[ReceiptFile, ...] = ()
    exact_input_roots: tuple[ReceiptRoot, ...] = ()
    exact_output_roots: tuple[ReceiptRoot, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not RUN_ID.fullmatch(value):
            raise ValueError("invalid run_id")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone aware")
        return value.astimezone(UTC)

    @field_validator("config_snapshot")
    @classmethod
    def validate_snapshot_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("config snapshot must be run-relative")
        return value

    @model_validator(mode="after")
    def validate_sets(self) -> StageReceipt:
        for label, records in (("input", self.inputs), ("output", self.outputs)):
            keys = [(record.scope, record.path) for record in records]
            if keys != sorted(keys):
                raise ValueError(f"{label} records must be sorted")
            if len(keys) != len(set(keys)):
                raise ValueError(f"duplicate {label} records")
        parent_paths = [parent.path for parent in self.parents]
        if parent_paths != sorted(parent_paths) or len(parent_paths) != len(set(parent_paths)):
            raise ValueError("parent receipt records must be unique and sorted")
        for label, roots in (
            ("input", self.exact_input_roots),
            ("output", self.exact_output_roots),
        ):
            keys = [(root.scope, root.path) for root in roots]
            if keys != sorted(keys) or len(keys) != len(set(keys)):
                raise ValueError(f"exact {label} roots must be unique and sorted")
        if self.profile in {ProfileName.CI, ProfileName.SYNTHETIC}:
            forbidden = [
                record
                for record in self.inputs
                if record.classification in {"restricted", "controlled_derived"}
                or record.path == "Data"
                or record.path.startswith("Data/")
                or record.path == "AnalysisData"
                or record.path.startswith("AnalysisData/")
            ]
            if forbidden:
                raise ValueError("public profiles cannot register restricted-data inputs")
        return self


class ReceiptValidation(ReceiptModel):
    ok: bool
    receipt_path: str
    receipt_sha256: str | None
    issues: tuple[str, ...]


def receipt_file(
    path: str | Path,
    *,
    scope: FileScope,
    run_root: str | Path,
    workspace: str | Path,
    classification: Classification,
) -> ReceiptFile:
    """Create one file record without allowing symlinks or path traversal."""

    base = Path(run_root if scope == "run" else workspace).resolve(strict=True)
    relative = safe_relative_path(path, base)
    source = base / relative
    media_type, _ = mimetypes.guess_type(source.name)
    return ReceiptFile(
        scope=scope,
        path=relative,
        sha256=sha256_file(source),
        size_bytes=source.stat().st_size,
        media_type=media_type,
        classification=classification,
    )


def _parent_ref(path: Path, run_root: Path) -> ParentReceipt:
    relative = safe_relative_path(path, run_root)
    with path.open("r", encoding="utf-8") as handle:
        parent = StageReceipt.model_validate(json.load(handle))
    return ParentReceipt(
        path=relative,
        sha256=sha256_file(path),
        stage=parent.stage,
        run_id=parent.run_id,
    )


def build_stage_receipt(
    *,
    run_root: str | Path,
    workspace: str | Path,
    run_id: str,
    stage: StageName,
    config_snapshot: str | Path,
    output_paths: Sequence[str | Path],
    output_classification: Classification = "controlled_derived",
    parent_receipts: Sequence[str | Path] = (),
    input_files: Sequence[ReceiptFile] = (),
    exact_input_roots: Sequence[tuple[FileScope, str | Path]] = (),
    exact_output_roots: Sequence[str | Path] = (),
    metadata: Mapping[str, Any] | None = None,
) -> StageReceipt:
    """Build a stage receipt and verify its exact declared output directories."""

    root = Path(run_root).resolve(strict=True)
    workspace_root = Path(workspace).resolve(strict=True)
    snapshot_relative = safe_relative_path(config_snapshot, root)
    loaded = read_config_snapshot(root / snapshot_relative)
    outputs = tuple(
        sorted(
            (
                receipt_file(
                    path,
                    scope="run",
                    run_root=root,
                    workspace=workspace_root,
                    classification=output_classification,
                )
                for path in output_paths
            ),
            key=lambda item: (item.scope, item.path),
        )
    )
    output_keys = {item.path for item in outputs}
    output_root_records: list[ReceiptRoot] = []
    for directory_value in exact_output_roots:
        directory = Path(directory_value)
        if not directory.is_absolute():
            directory = root / directory
        directory = directory.resolve(strict=True)
        try:
            relative_root = directory.relative_to(root).as_posix()
        except ValueError as error:
            raise ReceiptError(f"output root escapes run directory: {directory}") from error
        output_root_records.append(ReceiptRoot(scope="run", path=relative_root))
        actual = {safe_relative_path(path, root) for path in iter_regular_files(directory)}
        declared_below = {path for path in output_keys if (root / path).is_relative_to(directory)}
        if actual != declared_below:
            missing = sorted(declared_below - actual)
            extra = sorted(actual - declared_below)
            raise ReceiptError(
                f"stage output set mismatch below {directory}: missing={missing}, extra={extra}"
            )
    input_root_records: list[ReceiptRoot] = []
    input_keys = {(item.scope, item.path) for item in input_files}
    for scope, directory_value in exact_input_roots:
        base = root if scope == "run" else workspace_root
        directory = Path(directory_value)
        if not directory.is_absolute():
            directory = base / directory
        directory = directory.resolve(strict=True)
        try:
            relative_root = directory.relative_to(base).as_posix()
        except ValueError as error:
            raise ReceiptError(f"input root escapes {scope} directory: {directory}") from error
        input_root_records.append(ReceiptRoot(scope=scope, path=relative_root))
        actual_inputs = {
            (scope, safe_relative_path(path, base)) for path in iter_regular_files(directory)
        }
        declared_inputs_below = {
            key
            for key in input_keys
            if key[0] == scope and (base / key[1]).is_relative_to(directory)
        }
        if actual_inputs != declared_inputs_below:
            missing_inputs = sorted(declared_inputs_below - actual_inputs)
            extra_inputs = sorted(actual_inputs - declared_inputs_below)
            raise ReceiptError(
                f"stage input set mismatch below {directory}: "
                f"missing={missing_inputs}, extra={extra_inputs}"
            )
    parents = tuple(
        sorted((_parent_ref(Path(path), root) for path in parent_receipts), key=lambda x: x.path)
    )
    for parent in parents:
        if parent.run_id != run_id:
            raise ReceiptError("parent receipt belongs to another run")
    runtime = loaded.config.runtime
    return StageReceipt(
        run_id=run_id,
        stage=stage,
        profile=runtime.profile,
        formal=runtime.formal,
        created_at=datetime.now(UTC),
        config_sha256=loaded.config_sha256,
        config_snapshot=snapshot_relative,
        config_snapshot_sha256=sha256_file(root / snapshot_relative),
        parents=parents,
        inputs=tuple(sorted(input_files, key=lambda item: (item.scope, item.path))),
        outputs=outputs,
        exact_input_roots=tuple(
            sorted(input_root_records, key=lambda item: (item.scope, item.path))
        ),
        exact_output_roots=tuple(
            sorted(output_root_records, key=lambda item: (item.scope, item.path))
        ),
        metadata=dict(metadata or {}),
    )


def write_stage_receipt(receipt: StageReceipt, destination: str | Path) -> Path:
    target = Path(destination)
    atomic_write_json(target, receipt, mode=0o600)
    return target


def validate_stage_receipt(
    receipt_path: str | Path,
    *,
    run_root: str | Path,
    workspace: str | Path,
    verify_parents: bool = True,
) -> ReceiptValidation:
    source = Path(receipt_path)
    root = Path(run_root).resolve()
    workspace_root = Path(workspace).resolve()
    issues: list[str] = []
    digest: str | None = None
    try:
        digest = sha256_file(source)
        with source.open("r", encoding="utf-8") as handle:
            receipt = StageReceipt.model_validate(json.load(handle))
    except Exception as error:
        return ReceiptValidation(
            ok=False,
            receipt_path=source.as_posix(),
            receipt_sha256=digest,
            issues=(f"receipt cannot be parsed: {error}",),
        )
    snapshot = root / receipt.config_snapshot
    try:
        loaded = read_config_snapshot(snapshot)
        if loaded.config_sha256 != receipt.config_sha256:
            issues.append("configuration hash mismatch")
        if sha256_file(snapshot) != receipt.config_snapshot_sha256:
            issues.append("configuration snapshot file hash mismatch")
    except Exception as error:
        issues.append(f"configuration snapshot is invalid: {error}")
    for record in (*receipt.inputs, *receipt.outputs):
        base = root if record.scope == "run" else workspace_root
        path = base / record.path
        if not path.is_file() or path.is_symlink():
            issues.append(f"recorded file is missing or unsafe: {record.scope}:{record.path}")
            continue
        if path.stat().st_size != record.size_bytes or sha256_file(path) != record.sha256:
            issues.append(f"recorded file hash or size mismatch: {record.scope}:{record.path}")
    for label, roots, records in (
        ("input", receipt.exact_input_roots, receipt.inputs),
        ("output", receipt.exact_output_roots, receipt.outputs),
    ):
        recorded = {(item.scope, item.path) for item in records}
        for root_record in roots:
            base = root if root_record.scope == "run" else workspace_root
            directory = base / root_record.path
            try:
                actual = {
                    (root_record.scope, safe_relative_path(path, base))
                    for path in iter_regular_files(directory)
                }
            except Exception as error:
                issues.append(
                    f"exact {label} root cannot be enumerated: {root_record.path}: {error}"
                )
                continue
            expected = {
                key
                for key in recorded
                if key[0] == root_record.scope and (base / key[1]).is_relative_to(directory)
            }
            if actual != expected:
                issues.append(
                    f"exact {label} set mismatch below {root_record.scope}:{root_record.path}"
                )
    if verify_parents:
        for parent_ref in receipt.parents:
            path = root / parent_ref.path
            try:
                if sha256_file(path) != parent_ref.sha256:
                    issues.append(f"parent hash mismatch: {parent_ref.path}")
                    continue
                with path.open("r", encoding="utf-8") as handle:
                    parent = StageReceipt.model_validate(json.load(handle))
                if parent.run_id != receipt.run_id or parent.stage != parent_ref.stage:
                    issues.append(f"parent identity mismatch: {parent_ref.path}")
                if parent.config_sha256 != receipt.config_sha256:
                    issues.append(f"parent configuration mismatch: {parent_ref.path}")
            except Exception as error:
                issues.append(f"parent cannot be verified: {parent_ref.path}: {error}")
    return ReceiptValidation(
        ok=not issues,
        receipt_path=source.as_posix(),
        receipt_sha256=digest,
        issues=tuple(issues),
    )
