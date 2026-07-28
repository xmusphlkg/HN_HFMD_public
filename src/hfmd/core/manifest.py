"""Immutable run manifests with exact artifact-set and parent-chain checks."""

from __future__ import annotations

import json
import mimetypes
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.environment import EnvironmentState, GitState
from hfmd.core.hashing import (
    HashingError,
    atomic_write_json,
    iter_regular_files,
    safe_relative_path,
    sha256_file,
    sha256_object,
)

RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}(?:-[a-z0-9][a-z0-9-]{0,31})?$")
ManifestStage = Literal[
    "data", "analysis", "figures", "manuscript", "submission", "public_export", "all"
]


class ManifestError(RuntimeError):
    """Raised when a manifest cannot be built or trusted."""


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArtifactRecord(ManifestModel):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    media_type: str | None = None

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("artifact path must be a normalised relative POSIX path")
        return value


class InputRecord(ManifestModel):
    id: str
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    classification: Literal["public", "synthetic", "restricted", "controlled_derived"]

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("input path must be a normalised workspace-relative POSIX path")
        return value


class ParentManifestRef(ManifestModel):
    manifest_path: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    run_id: str
    stage: str

    @field_validator("manifest_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("parent manifest path must be workspace relative")
        return value


class RunManifest(ManifestModel):
    schema_version: Literal["hfmd-run-manifest-v1"] = "hfmd-run-manifest-v1"
    run_id: str
    stage: ManifestStage
    profile: ProfileName
    formal: bool
    created_at: datetime
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    config_snapshot: str
    git: GitState
    environment: EnvironmentState
    parent: ParentManifestRef | None = None
    inputs: tuple[InputRecord, ...] = ()
    artifacts: tuple[ArtifactRecord, ...]
    expected_artifacts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not RUN_ID.fullmatch(value):
            raise ValueError("invalid run_id")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone aware")
        return value.astimezone(UTC)

    @field_validator("config_snapshot")
    @classmethod
    def validate_snapshot_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute() or ".." in path.parts or value != path.as_posix():
            raise ValueError("config_snapshot must be artifact-root relative")
        return value

    @model_validator(mode="after")
    def validate_artifact_registry(self) -> RunManifest:
        paths = [artifact.path for artifact in self.artifacts]
        if paths != sorted(paths):
            raise ValueError("artifact records must be sorted by path")
        if len(paths) != len(set(paths)):
            raise ValueError("artifact paths must be unique")
        if self.config_snapshot not in set(paths):
            raise ValueError("config snapshot must be included in artifacts")
        expected = sha256_object(paths)
        if self.expected_artifacts_sha256 != expected:
            raise ValueError("expected artifact-set digest does not match artifact paths")
        if self.formal and self.profile != ProfileName.RESTRICTED:
            raise ValueError("only the restricted profile may create a formal manifest")
        if self.formal and self.git.dirty:
            raise ValueError("a formal manifest cannot record a dirty Git state")
        if self.profile in {ProfileName.CI, ProfileName.SYNTHETIC} and any(
            record.classification in {"restricted", "controlled_derived"} for record in self.inputs
        ):
            raise ValueError("public profiles cannot register restricted inputs")
        return self


class ManifestValidation(ManifestModel):
    ok: bool
    manifest_path: str
    manifest_sha256: str | None
    issues: tuple[str, ...]


def _artifact_record(root: Path, path: str | Path) -> ArtifactRecord:
    relative = safe_relative_path(path, root)
    source = root / relative
    media_type, _ = mimetypes.guess_type(source.name)
    return ArtifactRecord(
        path=relative,
        sha256=sha256_file(source),
        size_bytes=source.stat().st_size,
        media_type=media_type,
    )


def create_input_record(
    workspace: str | Path,
    path: str | Path,
    *,
    input_id: str,
    classification: Literal["public", "synthetic", "restricted", "controlled_derived"],
) -> InputRecord:
    """Hash one workspace-relative immutable model input."""

    root = Path(workspace).resolve(strict=True)
    relative = safe_relative_path(path, root)
    source = root / relative
    return InputRecord(
        id=input_id,
        path=relative,
        sha256=sha256_file(source),
        size_bytes=source.stat().st_size,
        classification=classification,
    )


def parent_manifest_ref(
    workspace: str | Path,
    parent_manifest: str | Path,
) -> ParentManifestRef:
    """Create a verified, portable reference to a parent-stage manifest."""

    root = Path(workspace).resolve(strict=True)
    relative = safe_relative_path(parent_manifest, root)
    source = root / relative
    with source.open("r", encoding="utf-8") as handle:
        parsed = RunManifest.model_validate(json.load(handle))
    return ParentManifestRef(
        manifest_path=relative,
        manifest_sha256=sha256_file(source),
        run_id=parsed.run_id,
        stage=parsed.stage,
    )


def build_manifest(
    *,
    artifact_root: str | Path,
    expected_paths: Sequence[str | Path],
    run_id: str,
    stage: ManifestStage,
    profile: ProfileName,
    formal: bool,
    config_sha256: str,
    config_snapshot: str | Path,
    git: GitState,
    environment: EnvironmentState,
    inputs: Sequence[InputRecord] = (),
    parent: ParentManifestRef | None = None,
    metadata: dict[str, Any] | None = None,
    require_exact_preexisting_set: bool = True,
) -> RunManifest:
    """Hash an explicitly declared artifact set and build an immutable manifest."""

    root = Path(artifact_root).resolve(strict=True)
    records = tuple(
        sorted((_artifact_record(root, path) for path in expected_paths), key=lambda x: x.path)
    )
    paths = [record.path for record in records]
    if len(paths) != len(set(paths)):
        raise ManifestError("expected artifact paths contain duplicates")
    snapshot_relative = safe_relative_path(config_snapshot, root)
    if require_exact_preexisting_set:
        actual = {safe_relative_path(path, root) for path in iter_regular_files(root)}
        expected = set(paths)
        if actual != expected:
            missing = sorted(expected - actual)
            extra = sorted(actual - expected)
            raise ManifestError(
                f"artifact set mismatch before manifest: missing={missing}, extra={extra}"
            )
    return RunManifest(
        run_id=run_id,
        stage=stage,
        profile=profile,
        formal=formal,
        created_at=datetime.now(UTC),
        config_sha256=config_sha256,
        config_snapshot=snapshot_relative,
        git=git,
        environment=environment,
        parent=parent,
        inputs=tuple(sorted(inputs, key=lambda item: item.id)),
        artifacts=records,
        expected_artifacts_sha256=sha256_object(paths),
        metadata=metadata or {},
    )


def write_manifest(
    manifest: RunManifest,
    artifact_root: str | Path,
    *,
    name: str = "manifest.json",
) -> Path:
    """Atomically write the manifest beside (but not inside) its artifact list."""

    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise ManifestError("manifest name must be a safe artifact-root relative path")
    destination = Path(artifact_root) / name
    atomic_write_json(destination, manifest)
    return destination


def _discover_workspace(manifest_path: Path) -> Path | None:
    for candidate in (manifest_path.parent, *manifest_path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def validate_manifest(
    manifest_path: str | Path,
    *,
    artifact_root: str | Path | None = None,
    workspace: str | Path | None = None,
    exact: bool = True,
    verify_inputs: bool = True,
    verify_parent: bool = True,
) -> ManifestValidation:
    """Validate schema, exact files, hashes, snapshot, inputs, and parent link."""

    source = Path(manifest_path).resolve()
    issues: list[str] = []
    digest: str | None = None
    try:
        digest = sha256_file(source)
        with source.open("r", encoding="utf-8") as handle:
            manifest = RunManifest.model_validate(json.load(handle))
    except Exception as exc:
        return ManifestValidation(
            ok=False,
            manifest_path=source.as_posix(),
            manifest_sha256=digest,
            issues=(f"manifest cannot be parsed: {exc}",),
        )

    root = Path(artifact_root).resolve() if artifact_root else source.parent
    declared = {artifact.path: artifact for artifact in manifest.artifacts}
    try:
        actual = {
            safe_relative_path(path, root)
            for path in iter_regular_files(root)
            if path.resolve() != source
        }
    except Exception as exc:
        actual = set()
        issues.append(f"artifact tree cannot be enumerated: {exc}")
    if exact:
        missing = sorted(set(declared) - actual)
        extra = sorted(actual - set(declared))
        if missing:
            issues.append(f"missing artifacts: {missing}")
        if extra:
            issues.append(f"unexpected artifacts: {extra}")
    for relative, artifact_record in declared.items():
        path = root / relative
        if not path.is_file() or path.is_symlink():
            if relative not in actual:
                continue
            issues.append(f"artifact is not a regular file: {relative}")
            continue
        if path.stat().st_size != artifact_record.size_bytes:
            issues.append(f"artifact size mismatch: {relative}")
            continue
        try:
            observed = sha256_file(path)
        except (OSError, HashingError) as exc:
            issues.append(f"artifact cannot be hashed: {relative}: {exc}")
            continue
        if observed != artifact_record.sha256:
            issues.append(f"artifact hash mismatch: {relative}")

    snapshot_path = root / manifest.config_snapshot
    try:
        loaded = read_config_snapshot(snapshot_path)
        if loaded.config_sha256 != manifest.config_sha256:
            issues.append("manifest and configuration snapshot hashes differ")
    except Exception as exc:
        issues.append(f"configuration snapshot is invalid: {exc}")

    workspace_path = Path(workspace).resolve() if workspace else _discover_workspace(source)
    if verify_inputs and manifest.inputs:
        if workspace_path is None:
            issues.append("cannot verify inputs without a workspace root")
        else:
            for input_record in manifest.inputs:
                path = workspace_path / input_record.path
                if not path.is_file() or path.is_symlink():
                    issues.append(f"input is missing or not a regular file: {input_record.path}")
                elif (
                    path.stat().st_size != input_record.size_bytes
                    or sha256_file(path) != input_record.sha256
                ):
                    issues.append(f"input hash or size mismatch: {input_record.path}")

    if verify_parent and manifest.parent is not None:
        if workspace_path is None:
            issues.append("cannot verify parent manifest without a workspace root")
        else:
            parent_path = workspace_path / manifest.parent.manifest_path
            try:
                if sha256_file(parent_path) != manifest.parent.manifest_sha256:
                    issues.append("parent manifest hash mismatch")
                with parent_path.open("r", encoding="utf-8") as handle:
                    parent = RunManifest.model_validate(json.load(handle))
                if parent.run_id != manifest.parent.run_id or parent.stage != manifest.parent.stage:
                    issues.append("parent manifest identity mismatch")
                if parent.run_id != manifest.run_id:
                    issues.append("parent manifest belongs to a different run_id")
            except Exception as exc:
                issues.append(f"parent manifest cannot be verified: {exc}")

    return ManifestValidation(
        ok=not issues,
        manifest_path=source.as_posix(),
        manifest_sha256=digest,
        issues=tuple(issues),
    )


def assert_valid_manifest(manifest_path: str | Path, **kwargs: Any) -> RunManifest:
    """Validate a manifest and return it, raising on any inconsistency."""

    report = validate_manifest(manifest_path, **kwargs)
    if not report.ok:
        raise ManifestError("; ".join(report.issues))
    with Path(manifest_path).open("r", encoding="utf-8") as handle:
        return RunManifest.model_validate(json.load(handle))
