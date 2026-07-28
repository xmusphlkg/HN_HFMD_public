"""Single-source numerical claim records and deterministic JSON I/O."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_PATTERN = r"^[0-9a-f]{64}$"
PLACEHOLDER_PATTERN = re.compile(
    r"\{\{claim:(?P<claim_id>[A-Za-z][A-Za-z0-9_-]*)"
    r"(?:\.(?P<field>estimate|unit|lower|upper|interval|full))?"
    r"(?:=(?P<assertion>[^{}]+))?\}\}"
)


class ClaimInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["confidence", "credible", "bootstrap_percentile", "prediction", "none"]
    level: float | None = Field(default=None, gt=0, lt=1)
    lower: float | None = None
    upper: float | None = None

    @model_validator(mode="after")
    def validate_bounds(self) -> ClaimInterval:
        if self.kind == "none":
            if any(value is not None for value in (self.level, self.lower, self.upper)):
                raise ValueError("an interval of kind 'none' cannot contain bounds")
            return self
        if self.level is None or self.lower is None or self.upper is None:
            raise ValueError("an interval requires level, lower, and upper")
        if not math.isfinite(self.lower) or not math.isfinite(self.upper):
            raise ValueError("interval bounds must be finite")
        if self.lower > self.upper:
            raise ValueError("interval lower bound exceeds upper bound")
        return self

    @property
    def label(self) -> str:
        if self.kind == "none":
            return ""
        prefix = {
            "confidence": "CI",
            "credible": "CrI",
            "bootstrap_percentile": "bootstrap interval",
            "prediction": "PI",
        }[self.kind]
        assert self.level is not None
        return f"{100 * self.level:g}% {prefix}"


class ClaimRecord(BaseModel):
    """A publication number tied to an estimand, model, inputs, and run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # A dot is deliberately reserved as the placeholder field separator.
    claim_id: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    estimand: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    estimate: float
    interval: ClaimInterval = Field(default_factory=lambda: ClaimInterval(kind="none"))
    unit: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    input_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    run_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    source_artifacts: tuple[str, ...] = Field(min_length=1)
    status: Literal["supported", "gated", "downgraded", "exploratory"]
    precision: int = Field(default=1, ge=0, le=8)
    thousands_separator: bool = True
    notes: str | None = None

    @field_validator("estimate")
    @classmethod
    def require_finite_estimate(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("claim estimate must be finite")
        return value

    def format_number(self, value: float) -> str:
        grouping = "," if self.thousands_separator else ""
        return format(value, f"{grouping}.{self.precision}f")

    def render(self, field: str = "full") -> str:
        if field == "estimate":
            return self.format_number(self.estimate)
        if field == "unit":
            return self.unit
        if field in {"lower", "upper"}:
            value = getattr(self.interval, field)
            if value is None:
                raise ValueError(f"claim {self.claim_id} has no {field} interval bound")
            return self.format_number(value)
        if field == "interval":
            if self.interval.kind == "none":
                raise ValueError(f"claim {self.claim_id} has no interval")
            assert self.interval.lower is not None and self.interval.upper is not None
            return (
                f"{self.interval.label} "
                f"{self.format_number(self.interval.lower)}–"
                f"{self.format_number(self.interval.upper)}"
            )
        if field == "full":
            estimate = self.format_number(self.estimate)
            if self.interval.kind == "none":
                return f"{estimate} {self.unit}".strip()
            return f"{estimate} ({self.render('interval')}) {self.unit}".strip()
        raise ValueError(f"unsupported claim field: {field}")


class ClaimsBundle(BaseModel):
    """The immutable claims.json payload for a single formal run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str
    run_id: str = Field(min_length=1)
    run_manifest_sha256: str = Field(pattern=SHA256_PATTERN)
    claims: tuple[ClaimRecord, ...]

    @model_validator(mode="after")
    def validate_bundle(self) -> ClaimsBundle:
        ids = [claim.claim_id for claim in self.claims]
        duplicates = sorted({claim_id for claim_id in ids if ids.count(claim_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate claim IDs: {', '.join(duplicates)}")
        wrong_run = [claim.claim_id for claim in self.claims if claim.run_id != self.run_id]
        if wrong_run:
            raise ValueError("claim run_id does not match bundle for: " + ", ".join(wrong_run))
        wrong_manifest = [
            claim.claim_id
            for claim in self.claims
            if claim.run_manifest_sha256 != self.run_manifest_sha256
        ]
        if wrong_manifest:
            raise ValueError(
                "claim manifest does not match bundle for: " + ", ".join(wrong_manifest)
            )
        return self

    @property
    def by_id(self) -> dict[str, ClaimRecord]:
        return {claim.claim_id: claim for claim in self.claims}


def load_claims(path: str | Path) -> ClaimsBundle:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return ClaimsBundle.model_validate(payload)


def write_claims(bundle: ClaimsBundle, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(
        bundle.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    )
    target.write_text(rendered + "\n", encoding="utf-8")
