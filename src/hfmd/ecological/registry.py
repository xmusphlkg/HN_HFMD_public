"""Ecological model registry accessors."""

from __future__ import annotations

from pathlib import Path

from hfmd.reporting.contracts import ModelRegistry, ModelSpec, load_model_registry

ECOLOGICAL_GROUPS = frozenset(
    {
        "primary_outcomes",
        "mechanistic_secondary",
        "population_weather_sensitivity",
        "exploratory",
    }
)
DEFAULT_MODEL_REGISTRY = Path(__file__).resolve().parents[3] / "config" / "model_registry.yaml"


def load_ecological_registry(path: str | Path = DEFAULT_MODEL_REGISTRY) -> ModelRegistry:
    registry = load_model_registry(path)
    models = registry.select(line="ecological")
    if len(models) != 55:
        raise ValueError(f"ecological registry requires 55 models, found {len(models)}")
    unknown_groups = sorted({model.group for model in models} - ECOLOGICAL_GROUPS)
    if unknown_groups:
        raise ValueError("unknown ecological model groups: " + ", ".join(unknown_groups))
    missing_groups = sorted(ECOLOGICAL_GROUPS - {model.group for model in models})
    if missing_groups:
        raise ValueError("empty ecological model groups: " + ", ".join(missing_groups))
    return registry


def ecological_model_specs(
    *,
    group: str | None = None,
    path: str | Path = DEFAULT_MODEL_REGISTRY,
) -> tuple[ModelSpec, ...]:
    if group is not None and group not in ECOLOGICAL_GROUPS:
        raise ValueError(f"unknown ecological group: {group}")
    return load_ecological_registry(path).select(line="ecological", group=group)


def ecological_formula(model_id: str, path: str | Path = DEFAULT_MODEL_REGISTRY) -> str:
    registry = load_ecological_registry(path)
    spec = registry.get(model_id)
    if spec.line != "ecological":
        raise ValueError(f"model is not ecological: {model_id}")
    return registry.resolved_formula(model_id)
