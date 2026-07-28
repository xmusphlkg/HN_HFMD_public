"""Transmission-dynamics candidate and sensitivity registry accessors."""

from __future__ import annotations

from pathlib import Path

from hfmd.reporting.contracts import (
    ModelRegistry,
    ModelSpec,
    SensitivityFamily,
    load_model_registry,
)

DEFAULT_MODEL_REGISTRY = Path(__file__).resolve().parents[3] / "config" / "model_registry.yaml"
REQUIRED_DYNAMICS_GROUPS = frozenset(
    {
        "candidate_set",
        "alternative_explanations",
        "observation_models",
        "pathogen_pair_structures",
    }
)


def load_dynamics_registry(path: str | Path = DEFAULT_MODEL_REGISTRY) -> ModelRegistry:
    registry = load_model_registry(path)
    models = registry.select(line="dynamics")
    if not models:
        raise ValueError("dynamics registry is empty")
    missing_groups = sorted(REQUIRED_DYNAMICS_GROUPS - {model.group for model in models})
    if missing_groups:
        raise ValueError("missing dynamics model groups: " + ", ".join(missing_groups))
    if not registry.sensitivity_families:
        raise ValueError("dynamics sensitivity-family registry is empty")
    return registry


def dynamics_model_specs(
    *,
    group: str | None = None,
    include_planned: bool = True,
    path: str | Path = DEFAULT_MODEL_REGISTRY,
) -> tuple[ModelSpec, ...]:
    models = load_dynamics_registry(path).select(line="dynamics", group=group)
    if include_planned:
        return models
    return tuple(model for model in models if model.implementation_status == "migrated")


def dynamics_sensitivity_families(
    path: str | Path = DEFAULT_MODEL_REGISTRY,
) -> tuple[SensitivityFamily, ...]:
    return load_dynamics_registry(path).sensitivity_families
