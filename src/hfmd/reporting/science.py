"""Conservative evaluation of prespecified scientific decision gates."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

GateOperator = Literal["eq", "gte", "gt", "lte", "lt", "between_inclusive", "all_gte", "all_gt"]


class GateCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    check_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    metric: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    operator: GateOperator
    value: Any
    denominator: int | None = Field(default=None, ge=1)
    evidence_required: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> GateCheck:
        if self.operator == "between_inclusive":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between_inclusive requires a two-value list")
            if self.value[0] > self.value[1]:
                raise ValueError("between_inclusive bounds are reversed")
        return self


class GateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1)
    pass_language: str = Field(min_length=1)
    downgrade_language: str = Field(min_length=1)
    not_evaluated_language: str = Field(min_length=1)
    checks: tuple[GateCheck, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_checks(self) -> GateSpec:
        identifiers = [check.check_id for check in self.checks]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("science gate check IDs must be unique")
        return self


class ScienceGateConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    evaluation_policy: dict[str, str]
    gates: dict[str, GateSpec] = Field(min_length=1)


def validate_science_gate_configuration(payload: dict[str, Any]) -> ScienceGateConfiguration:
    return ScienceGateConfiguration.model_validate(payload)


class GateEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str
    decision: Literal["pass", "downgrade", "not_evaluated"]
    passed_checks: tuple[str, ...] = ()
    failed_checks: tuple[str, ...] = ()
    missing_metrics: tuple[str, ...] = ()
    publication_language: str


def load_science_gates(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("gates"), dict):
        raise ValueError("science gate configuration requires a top-level gates mapping")
    validate_science_gate_configuration(payload)
    return payload


def _nested(metrics: dict[str, Any], path: str) -> Any:
    current: Any = metrics
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def evaluate_science_gate(
    gate_id: str, metrics: dict[str, Any], configuration: dict[str, Any]
) -> GateEvaluation:
    """Evaluate declarative checks without treating missing results as success."""

    try:
        gate = configuration["gates"][gate_id]
    except KeyError as error:
        raise KeyError(f"unknown science gate: {gate_id}") from error

    passed: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    for check in gate["checks"]:
        check_id = check["check_id"]
        metric_path = check["metric"]
        try:
            value = _nested(metrics, metric_path)
        except KeyError:
            missing.append(metric_path)
            continue
        operator = check["operator"]
        target = check.get("value")
        if operator == "eq":
            result = value == target
        elif operator == "gte":
            result = value >= target
        elif operator == "gt":
            result = value > target
        elif operator == "lte":
            result = value <= target
        elif operator == "lt":
            result = value < target
        elif operator == "between_inclusive":
            result = target[0] <= value <= target[1]
        elif operator == "all_gte":
            result = bool(value) and all(item >= target for item in value)
        elif operator == "all_gt":
            result = bool(value) and all(item > target for item in value)
        else:
            raise ValueError(f"unsupported gate operator: {operator}")
        (passed if result else failed).append(check_id)

    decision: Literal["pass", "downgrade", "not_evaluated"]
    if missing:
        decision = "not_evaluated"
        language = gate["not_evaluated_language"]
    elif failed:
        decision = "downgrade"
        language = gate["downgrade_language"]
    else:
        decision = "pass"
        language = gate["pass_language"]
    return GateEvaluation(
        gate_id=gate_id,
        decision=decision,
        passed_checks=tuple(passed),
        failed_checks=tuple(failed),
        missing_metrics=tuple(sorted(set(missing))),
        publication_language=language,
    )


def evaluate_all_science_gates(
    metrics: dict[str, Any], configuration: dict[str, Any]
) -> tuple[GateEvaluation, ...]:
    return tuple(
        evaluate_science_gate(gate_id, metrics, configuration) for gate_id in configuration["gates"]
    )
