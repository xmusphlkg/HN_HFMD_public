"""Run-directory lifecycle and configuration-bound execution context."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

from hfmd.core.config import LoadedConfig, load_config, write_config_snapshot
from hfmd.core.environment import (
    EnvironmentFailure,
    check_environment,
    collect_environment,
    get_git_state,
    require_clean_worktree,
)
from hfmd.core.hashing import atomic_write_bytes, atomic_write_json, sha256_file
from hfmd.core.locking import FileLock
from hfmd.core.manifest import (
    RUN_ID,
    InputRecord,
    ManifestStage,
    ParentManifestRef,
    RunManifest,
    build_manifest,
    validate_manifest,
    write_manifest,
)

Target = Literal[
    "data",
    "ecological",
    "dynamics",
    "analysis",
    "figures",
    "manuscript",
    "submission",
    "public_export",
    "all",
]


def discover_workspace(start: str | Path = ".") -> Path:
    """Find the nearest project root containing config/project.yaml."""

    candidate = Path(start).resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "config" / "project.yaml").is_file() and (
            directory / "pyproject.toml"
        ).is_file():
            return directory
    raise FileNotFoundError("Could not locate an HFMD workspace from the current directory")


def make_run_id(
    config_sha256: str, *, label: str | None = None, now: datetime | None = None
) -> str:
    """Create a sortable run ID tied to the effective configuration hash."""

    instant = (now or datetime.now(UTC)).astimezone(UTC)
    prefix = instant.strftime("%Y%m%dT%H%M%SZ")
    suffix = ""
    if label:
        cleaned = re.sub(r"[^a-z0-9-]+", "-", label.lower()).strip("-")[:32]
        if not cleaned:
            raise ValueError("run label contains no usable characters")
        suffix = f"-{cleaned}"
    return f"{prefix}-{config_sha256[:8]}{suffix}"


@dataclass(frozen=True, slots=True)
class RunContext:
    """Paths and provenance for one isolated candidate run."""

    workspace: Path
    loaded_config: LoadedConfig
    run_id: str
    target: Target

    @classmethod
    def create(
        cls,
        *,
        workspace: str | Path = ".",
        profile: str = "synthetic",
        target: Target = "all",
        run_id: str | None = None,
        label: str | None = None,
    ) -> RunContext:
        root = discover_workspace(workspace)
        loaded = load_config(root / "config" / "project.yaml", profile)
        identifier = run_id or make_run_id(loaded.config_sha256, label=label)
        if not RUN_ID.fullmatch(identifier):
            raise ValueError(f"invalid run_id: {identifier!r}")
        return cls(workspace=root, loaded_config=loaded, run_id=identifier, target=target)

    @property
    def run_root(self) -> Path:
        return self.workspace / self.loaded_config.config.paths.runs / self.run_id

    @property
    def staging(self) -> Path:
        return self.run_root / "staging"

    @property
    def receipts(self) -> Path:
        return self.run_root / "receipts"

    @property
    def lock_path(self) -> Path:
        return (
            self.workspace / self.loaded_config.config.paths.runs / ".locks" / f"{self.run_id}.lock"
        )

    @property
    def config_snapshot(self) -> Path:
        return self.staging / "config" / "config.snapshot.json"

    @property
    def manifest_path(self) -> Path:
        return self.staging / "manifest.json"

    @property
    def current(self) -> Path:
        return self.workspace / self.loaded_config.config.paths.current

    def prepare(self) -> Path:
        """Create a fresh staging directory and write its immutable config snapshot."""

        with FileLock(self.lock_path):
            if self.staging.exists() and any(self.staging.iterdir()):
                raise FileExistsError(
                    f"Refusing to reuse non-empty staging directory: {self.staging}"
                )
            self.staging.mkdir(parents=True, exist_ok=True)
            self.receipts.mkdir(parents=True, exist_ok=True)
            write_config_snapshot(self.loaded_config, self.config_snapshot)
            atomic_write_json(
                self.receipts / "started.json",
                {
                    "schema_version": "hfmd-run-receipt-v1",
                    "run_id": self.run_id,
                    "target": self.target,
                    "profile": self.loaded_config.config.runtime.profile,
                    "config_sha256": self.loaded_config.config_sha256,
                    "started_at": datetime.now(UTC),
                },
            )
        return self.staging

    def expected_configured_artifacts(self) -> tuple[str, ...]:
        """Return formal artifact paths relevant to this run target."""

        stages: set[str]
        if self.target == "all":
            stages = {
                "data",
                "ecological",
                "dynamics",
                "figures",
                "manuscript",
                "submission",
            }
        elif self.target == "analysis":
            stages = {"ecological", "dynamics"}
        elif self.target == "public_export":
            stages = set()
        else:
            stages = {self.target}
        return tuple(
            sorted(
                artifact.path.as_posix()
                for artifact in self.loaded_config.config.artifacts
                if artifact.required and artifact.stage in stages
            )
        )

    def seal(
        self,
        *,
        expected_paths: Sequence[str | Path],
        inputs: Sequence[InputRecord] = (),
        parent: ParentManifestRef | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RunManifest:
        """Validate the environment and seal an exact staging artifact set."""

        runtime = self.loaded_config.config.runtime
        formal = runtime.formal
        with FileLock(self.lock_path):
            if not self.config_snapshot.is_file():
                raise FileNotFoundError("run has not been prepared or config snapshot is missing")
            if self.manifest_path.exists():
                raise FileExistsError("run staging has already been sealed")
            git = (
                require_clean_worktree(self.workspace) if formal else get_git_state(self.workspace)
            )
            environment_report = check_environment(
                self.loaded_config.config.environment,
                self.workspace,
                random_seed=runtime.random_seed,
                threads=runtime.cores,
                formal=formal,
            )
            if not environment_report.ok:
                messages = "; ".join(message.message for message in environment_report.messages)
                raise EnvironmentFailure(messages)
            environment = collect_environment(
                self.workspace,
                random_seed=runtime.random_seed,
                threads=runtime.cores,
            )
            declared = {Path(path).as_posix() for path in expected_paths}
            declared.add(self.config_snapshot.relative_to(self.staging).as_posix())
            if formal:
                required = set(self.expected_configured_artifacts())
                missing_required = sorted(required - declared)
                if missing_required:
                    raise RuntimeError(
                        "formal run is missing configured artifacts: " + ", ".join(missing_required)
                    )
            manifest_stage = cast(
                ManifestStage,
                "analysis" if self.target in {"ecological", "dynamics"} else self.target,
            )
            manifest = build_manifest(
                artifact_root=self.staging,
                expected_paths=tuple(sorted(declared)),
                run_id=self.run_id,
                stage=manifest_stage,
                profile=runtime.profile,
                formal=formal,
                config_sha256=self.loaded_config.config_sha256,
                config_snapshot=self.config_snapshot,
                git=git,
                environment=environment,
                inputs=inputs,
                parent=parent,
                metadata={"target": self.target, **(metadata or {})},
                require_exact_preexisting_set=True,
            )
            write_manifest(manifest, self.staging)
            report = validate_manifest(
                self.manifest_path,
                artifact_root=self.staging,
                workspace=self.workspace,
            )
            if not report.ok:
                raise RuntimeError(
                    "Sealed manifest failed self-validation: " + "; ".join(report.issues)
                )
            receipt_manifest = self.receipts / "manifest.json"
            atomic_write_bytes(receipt_manifest, self.manifest_path.read_bytes(), mode=0o600)
            atomic_write_json(
                self.receipts / "sealed.json",
                {
                    "schema_version": "hfmd-run-receipt-v1",
                    "run_id": self.run_id,
                    "manifest_sha256": sha256_file(self.manifest_path),
                    "receipt_manifest": receipt_manifest.relative_to(self.workspace).as_posix(),
                    "sealed_at": datetime.now(UTC),
                },
            )
            return manifest

    def record_failure(self, exc: BaseException) -> Path:
        """Record a failed stage outside the candidate artifact tree."""

        self.receipts.mkdir(parents=True, exist_ok=True)
        destination = self.receipts / "failure.json"
        atomic_write_json(
            destination,
            {
                "schema_version": "hfmd-run-receipt-v1",
                "run_id": self.run_id,
                "target": self.target,
                "exception_type": type(exc).__name__,
                "message": str(exc)[:2000],
                "failed_at": datetime.now(UTC),
            },
        )
        return destination
