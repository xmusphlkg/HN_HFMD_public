"""Validated, single-source project configuration and immutable snapshots."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hfmd.core.hashing import (
    atomic_write_json,
    canonical_json_bytes,
    sha256_file,
    sha256_object,
)

IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]*$")


class ConfigurationError(ValueError):
    """Raised when configuration sources or snapshots are inconsistent."""


class StrictModel(BaseModel):
    """Base for immutable configuration contracts with no silent extra fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ProfileName(StrEnum):
    CI = "ci"
    SYNTHETIC = "synthetic"
    RESTRICTED = "restricted"


class DateWindow(StrictModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> DateWindow:
        if self.end < self.start:
            raise ValueError("date window end must not precede start")
        return self


class AgeGroup(StrictModel):
    id: str
    label: str
    min_years: float = Field(ge=0)
    max_years: float | None = Field(default=None, gt=0)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("age-group id must be lower snake_case")
        return value

    @model_validator(mode="after")
    def validate_bounds(self) -> AgeGroup:
        if self.max_years is not None and self.max_years <= self.min_years:
            raise ValueError("age-group max_years must exceed min_years")
        return self


class PathogenGroup(StrictModel):
    id: str
    label: str
    aliases: tuple[str, ...] = ()

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("pathogen id must be lower snake_case")
        return value


class ArtifactSpec(StrictModel):
    id: str
    stage: Literal["data", "ecological", "dynamics", "figures", "manuscript", "submission"]
    path: Path
    required: bool = True
    public: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not IDENTIFIER.fullmatch(value):
            raise ValueError("artifact id must be lower snake_case")
        return value

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("artifact paths must be traversal-free relative paths")
        return value


class StudyConfig(StrictModel):
    id: str
    title: str
    jurisdiction: str
    surveillance: DateWindow
    fitting: DateWindow
    vaccine_rollout: date
    age_groups: tuple[AgeGroup, ...]
    pathogen_groups: tuple[PathogenGroup, ...]

    @model_validator(mode="after")
    def validate_study(self) -> StudyConfig:
        if not (self.surveillance.start <= self.vaccine_rollout <= self.surveillance.end):
            raise ValueError("vaccine rollout must lie within surveillance dates")
        if self.fitting.start < self.surveillance.start or self.fitting.end > self.surveillance.end:
            raise ValueError("fitting dates must lie within surveillance dates")
        _require_unique((group.id for group in self.age_groups), "age-group id")
        _require_unique((group.id for group in self.pathogen_groups), "pathogen id")
        ordered = sorted(self.age_groups, key=lambda group: group.min_years)
        for previous, current in zip(ordered, ordered[1:], strict=False):
            if previous.max_years is None or previous.max_years > current.min_years:
                raise ValueError(f"age groups overlap: {previous.id} and {current.id}")
        if ordered and any(group.max_years is None for group in ordered[:-1]):
            raise ValueError("only the final age group may be open ended")
        return self


class PathConfig(StrictModel):
    raw_data: Path = Path("Data")
    restricted_data: Path = Path("AnalysisData/restricted")
    analysis_data: Path = Path("AnalysisData")
    runs: Path = Path(".runs")
    current: Path = Path("artifacts/current")
    distribution: Path = Path("dist")

    @field_validator(
        "raw_data", "restricted_data", "analysis_data", "runs", "current", "distribution"
    )
    @classmethod
    def validate_relative_path(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("configured paths must be traversal-free relative paths")
        return value


class EnvironmentConfig(StrictModel):
    python: str = "3.13.5"
    r: str = "4.5.0"
    timezone: str = "UTC"
    locale: str = "C.UTF-8"
    blas_threads: int = Field(default=1, ge=1)
    font: str = "DejaVu Sans"


class RuntimeConfig(StrictModel):
    profile: ProfileName
    cores: int = Field(ge=1)
    memory_gb: float = Field(gt=0)
    random_seed: int = Field(ge=0)
    conditional_bootstrap: int = Field(ge=0)
    full_state_bootstrap: int = Field(ge=0)
    full_state_bootstrap_max: int = Field(ge=0)
    optimisation_starts: int = Field(ge=1)
    formal: bool = False

    @model_validator(mode="after")
    def validate_bootstrap(self) -> RuntimeConfig:
        if self.full_state_bootstrap_max < self.full_state_bootstrap:
            raise ValueError("full_state_bootstrap_max must be at least the initial count")
        return self


class PrivacyConfig(StrictModel):
    small_cell_threshold: int = Field(default=10, ge=1)
    forbidden_granularities: tuple[str, ...] = ("event", "county", "exact_date")
    public_regions_are_synthetic: bool = True


class ContractFiles(StrictModel):
    """External declarative contracts included verbatim in every run snapshot."""

    model_registry: Path = Path("model_registry.yaml")
    science_gates: Path = Path("science_gates.yaml")
    visual_contract: Path = Path("visual_contract.yaml")

    @field_validator("model_registry", "science_gates", "visual_contract")
    @classmethod
    def validate_relative_path(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("contract paths must be traversal-free and config-relative")
        return value


class ProjectConfig(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    study: StudyConfig
    paths: PathConfig = PathConfig()
    environment: EnvironmentConfig = EnvironmentConfig()
    runtime: RuntimeConfig
    contracts: ContractFiles = ContractFiles()
    artifacts: tuple[ArtifactSpec, ...]
    privacy: PrivacyConfig = PrivacyConfig()

    @model_validator(mode="after")
    def validate_registries(self) -> ProjectConfig:
        _require_unique((artifact.id for artifact in self.artifacts), "artifact id")
        _require_unique((artifact.path.as_posix() for artifact in self.artifacts), "artifact path")
        return self


class ConfigSnapshot(StrictModel):
    snapshot_schema: Literal["hfmd-config-v1"] = "hfmd-config-v1"
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_hashes: dict[str, str]
    config: ProjectConfig
    resources: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LoadedConfig:
    """A validated configuration together with its immutable provenance."""

    config: ProjectConfig
    config_sha256: str
    source_hashes: dict[str, str]
    resources: dict[str, Any]
    canonical_json: str
    project_path: Path | None = None
    profile_path: Path | None = None


def _require_unique(values: Any, description: str) -> None:
    items = list(values)
    duplicate = next((item for item in items if items.count(item) > 1), None)
    if duplicate is not None:
        raise ValueError(f"duplicate {description}: {duplicate}")


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ConfigurationError(f"Configuration source must contain a mapping: {path}")
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_profile(project_path: Path, profile_path: str | Path | None) -> Path | None:
    if profile_path is None:
        return None
    candidate = Path(profile_path)
    if not candidate.is_absolute() and len(candidate.parts) == 1 and candidate.suffix == "":
        candidate = project_path.parent / "profiles" / f"{candidate.name}.yaml"
    elif not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    return candidate.resolve()


def load_config(
    project_path: str | Path = "config/project.yaml",
    profile_path: str | Path | None = None,
) -> LoadedConfig:
    """Load, merge, validate, canonicalise, and hash YAML configuration.

    A bare profile name (for example ``"ci"``) resolves to
    ``<project-dir>/profiles/ci.yaml``. Profiles may only override fields that
    exist in :class:`ProjectConfig`; Pydantic rejects stale or misspelled keys.
    """

    project = Path(project_path).resolve()
    profile = _resolve_profile(project, profile_path)
    raw = _read_yaml(project)
    source_hashes = {project.name: sha256_file(project)}
    if profile is not None:
        raw = _deep_merge(raw, _read_yaml(profile))
        try:
            profile_label = profile.relative_to(project.parent).as_posix()
        except ValueError:
            profile_label = profile.name
        source_hashes[profile_label] = sha256_file(profile)
    parsed = ProjectConfig.model_validate(raw)
    resources: dict[str, Any] = {}
    for name, relative in parsed.contracts.model_dump(mode="python").items():
        resource_path = (project.parent / relative).resolve()
        try:
            resource_path.relative_to(project.parent.resolve())
        except ValueError as error:
            raise ConfigurationError(
                f"Contract path escapes config directory: {relative}"
            ) from error
        resources[name] = _read_yaml(resource_path)
        source_hashes[resource_path.relative_to(project.parent).as_posix()] = sha256_file(
            resource_path
        )
    combined = {
        "config": parsed,
        "resources": resources,
        "source_hashes": dict(sorted(source_hashes.items())),
    }
    canonical = canonical_json_bytes(combined).decode("utf-8")
    return LoadedConfig(
        config=parsed,
        config_sha256=sha256_object(combined),
        source_hashes=dict(sorted(source_hashes.items())),
        resources=resources,
        canonical_json=canonical,
        project_path=project,
        profile_path=profile,
    )


def write_config_snapshot(loaded: LoadedConfig, destination: str | Path) -> Path:
    """Write a deterministic, self-verifying run configuration snapshot."""

    snapshot = ConfigSnapshot(
        config_sha256=loaded.config_sha256,
        source_hashes=loaded.source_hashes,
        config=loaded.config,
        resources=loaded.resources,
    )
    path = Path(destination)
    atomic_write_json(path, snapshot, mode=0o600)
    return path


def read_config_snapshot(path: str | Path) -> LoadedConfig:
    """Read a snapshot and fail if its embedded configuration hash is stale."""

    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        snapshot = ConfigSnapshot.model_validate(json.load(handle))
    combined = {
        "config": snapshot.config,
        "resources": snapshot.resources,
        "source_hashes": dict(sorted(snapshot.source_hashes.items())),
    }
    observed = sha256_object(combined)
    if observed != snapshot.config_sha256:
        detail = f"expected {snapshot.config_sha256}, got {observed}"
        raise ConfigurationError(f"Configuration snapshot hash mismatch: {detail}")
    return LoadedConfig(
        config=snapshot.config,
        config_sha256=observed,
        source_hashes=dict(sorted(snapshot.source_hashes.items())),
        resources=snapshot.resources,
        canonical_json=canonical_json_bytes(combined).decode("utf-8"),
    )
