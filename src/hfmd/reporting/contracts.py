"""Machine-readable scientific and reporting contracts.

The objects in this module are deliberately small and serialization friendly.
They are shared by fitters, validators, figure-data builders, and manuscript
renderers so that model identity and inferential role are defined once.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

AnalysisLine = Literal["ecological", "dynamics"]
ImplementationStatus = Literal["migrated", "required", "planned", "retired"]


class ModelSpec(BaseModel):
    """A declarative model specification with an explicit inferential role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]+$")
    line: AnalysisLine
    group: str = Field(min_length=1)
    outcome: str = Field(min_length=1)
    estimand: str = Field(min_length=1)
    family: str = Field(min_length=1)
    effect_scale: str = Field(min_length=1)
    implementation_status: ImplementationStatus = "required"
    formula: str | None = None
    formula_ref: str | None = None
    formula_args: dict[str, str] = Field(default_factory=dict)
    offset_column: str | None = None
    primary: bool = False
    tags: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_one_formula_source_for_ecological_model(self) -> ModelSpec:
        if self.line == "ecological" and bool(self.formula) == bool(self.formula_ref):
            raise ValueError("ecological ModelSpec requires exactly one of formula or formula_ref")
        return self


class SensitivityFamily(BaseModel):
    """A prespecified family of analyses, including not-yet-fitted requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    family_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    purpose: str = Field(min_length=1)
    implementation_status: ImplementationStatus
    values: tuple[Any, ...] = ()
    requirements: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)


class ModelRegistry(BaseModel):
    """Validated registry for both analysis lines."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    formula_templates: dict[str, str] = Field(default_factory=dict)
    models: tuple[ModelSpec, ...]
    sensitivity_families: tuple[SensitivityFamily, ...] = ()
    expected_counts: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_registry(self) -> ModelRegistry:
        counts = Counter(model.model_id for model in self.models)
        duplicates = sorted(model_id for model_id, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(f"duplicate model_id values: {', '.join(duplicates)}")

        missing_templates = sorted(
            {
                model.formula_ref
                for model in self.models
                if model.formula_ref and model.formula_ref not in self.formula_templates
            }
        )
        if missing_templates:
            raise ValueError("unknown formula template(s): " + ", ".join(missing_templates))

        for line, expected in self.expected_counts.items():
            observed = sum(model.line == line for model in self.models)
            if observed != expected:
                raise ValueError(f"registry contains {observed} {line} models; expected {expected}")

        family_counts = Counter(item.family_id for item in self.sensitivity_families)
        duplicate_families = sorted(
            family_id for family_id, count in family_counts.items() if count > 1
        )
        if duplicate_families:
            raise ValueError(
                "duplicate sensitivity family values: " + ", ".join(duplicate_families)
            )
        return self

    def get(self, model_id: str) -> ModelSpec:
        for model in self.models:
            if model.model_id == model_id:
                return model
        raise KeyError(f"unknown model_id: {model_id}")

    def select(
        self,
        *,
        line: AnalysisLine | None = None,
        group: str | None = None,
        status: ImplementationStatus | None = None,
    ) -> tuple[ModelSpec, ...]:
        return tuple(
            model
            for model in self.models
            if (line is None or model.line == line)
            and (group is None or model.group == group)
            and (status is None or model.implementation_status == status)
        )

    def resolved_formula(self, model_id: str) -> str:
        spec = self.get(model_id)
        if spec.formula is not None:
            return spec.formula
        if spec.formula_ref is None:
            raise ValueError(f"model {model_id} has no formula")
        template = self.formula_templates[spec.formula_ref]
        try:
            return template.format_map(spec.formula_args)
        except KeyError as error:
            raise ValueError(
                f"model {model_id} does not define formula argument {error.args[0]!r}"
            ) from error


def load_model_registry(path: str | Path) -> ModelRegistry:
    """Load a registry without resolving formulas against mutable source state."""

    registry_path = Path(path)
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"model registry must be a mapping: {registry_path}")
    return ModelRegistry.model_validate(payload)


class FigureSpec(BaseModel):
    """Conclusion-led contract for a single manuscript figure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    figure_id: str = Field(pattern=r"^figure(?:[1-9][0-9]*|S[1-9][0-9]*)$")
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    conclusion: str = Field(min_length=1)
    evidence_logic: tuple[str, ...] = Field(min_length=1)
    archetype: str = Field(min_length=1)
    reviewer_risk: str = Field(min_length=1)
    source_script: str = Field(min_length=1)
    output_name: str = Field(pattern=r"^figure(?:[1-9][0-9]*|S[1-9][0-9]*)(?:_[a-z0-9_]+)?$")
    legacy_design_source: str | None = None
    width_in: float = Field(gt=0)
    height_in: float = Field(gt=0)
    panels: tuple[str, ...] = Field(min_length=1)
    export_formats: tuple[Literal["pdf", "svg", "png", "tiff"], ...]
    implementation_status: ImplementationStatus


class VisualContract(BaseModel):
    """Five-main/ten-supplement visual system contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    backend: Literal["R"]
    font_family: str
    palette: dict[str, str]
    semantic_colours: dict[str, str]
    layout_rules: tuple[str, ...]
    audit_requirements: tuple[str, ...]
    main_figures: tuple[FigureSpec, ...]
    supplementary_figures: tuple[FigureSpec, ...]

    @field_validator("font_family")
    @classmethod
    def require_embedded_dejavu(cls, value: str) -> str:
        if value != "DejaVu Sans":
            raise ValueError("canonical font must be DejaVu Sans")
        return value

    @model_validator(mode="after")
    def validate_figure_set(self) -> VisualContract:
        if len(self.main_figures) != 5:
            raise ValueError("visual contract requires exactly five main figures")
        if len(self.supplementary_figures) != 10:
            raise ValueError("visual contract requires exactly ten supplementary figures")
        expected_main = [f"figure{i}" for i in range(1, 6)]
        expected_supp = [f"figureS{i}" for i in range(1, 11)]
        if [item.figure_id for item in self.main_figures] != expected_main:
            raise ValueError("main figures must be ordered figure1 through figure5")
        if [item.figure_id for item in self.supplementary_figures] != expected_supp:
            raise ValueError("supplementary figures must be ordered figureS1 through figureS10")
        all_ids = [item.figure_id for item in self.main_figures + self.supplementary_figures]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError("figure IDs must be unique")
        return self


def load_visual_contract(path: str | Path) -> VisualContract:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("visual contract must be a YAML mapping")
    return VisualContract.model_validate(payload)
