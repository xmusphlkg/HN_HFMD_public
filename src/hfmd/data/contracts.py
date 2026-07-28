"""Small, dependency-free contracts for tabular pipeline boundaries.

The production configuration is validated with Pydantic elsewhere.  These
contracts deliberately use the standard library so that the public synthetic
fixture can be checked before any scientific dependency is imported.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


class ContractViolation(ValueError):
    """Raised when a table does not match its declared boundary contract."""


@dataclass(frozen=True, slots=True)
class FieldSpec:
    name: str
    dtype: str = "string"
    nullable: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        if self.dtype not in {"string", "integer", "number", "boolean"}:
            raise ValueError(f"Unsupported field type for {self.name}: {self.dtype}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(f"Invalid numeric bounds for {self.name}")


@dataclass(frozen=True, slots=True)
class TableContract:
    name: str
    fields: tuple[FieldSpec, ...]
    primary_key: tuple[str, ...] = ()
    minimum_rows: int = 1
    allow_extra_columns: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def columns(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.fields)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_value(value: str, spec: FieldSpec, *, row_number: int) -> Any:
    if value == "":
        if spec.nullable:
            return None
        raise ContractViolation(f"{spec.name}: empty value is not allowed at CSV row {row_number}")
    try:
        if spec.dtype == "integer":
            parsed: Any = int(value)
            if str(parsed) != value and not (value.startswith("+") and str(parsed) == value[1:]):
                raise ValueError("not a canonical integer")
        elif spec.dtype == "number":
            parsed = float(value)
            if not math.isfinite(parsed):
                raise ValueError("not finite")
        elif spec.dtype == "boolean":
            normalized = value.lower()
            if normalized not in {"true", "false", "0", "1"}:
                raise ValueError("not a boolean")
            parsed = normalized in {"true", "1"}
        else:
            parsed = value
    except ValueError as error:
        raise ContractViolation(
            f"{spec.name}: invalid {spec.dtype} value {value!r} at CSV row {row_number}"
        ) from error

    if spec.choices and str(value) not in spec.choices:
        raise ContractViolation(
            f"{spec.name}: value {value!r} is outside the declared choices at CSV row {row_number}"
        )
    if isinstance(parsed, (int, float)) and not isinstance(parsed, bool):
        if spec.minimum is not None and parsed < spec.minimum:
            raise ContractViolation(
                f"{spec.name}: value {parsed} is below {spec.minimum} at CSV row {row_number}"
            )
        if spec.maximum is not None and parsed > spec.maximum:
            raise ContractViolation(
                f"{spec.name}: value {parsed} is above {spec.maximum} at CSV row {row_number}"
            )
    return parsed


def validate_rows(
    rows: Iterable[Mapping[str, str]],
    contract: TableContract,
    *,
    fieldnames: Iterable[str],
) -> dict[str, Any]:
    """Validate an iterable once and return a JSON-serializable receipt."""

    observed = tuple(fieldnames)
    expected = contract.columns
    missing = sorted(set(expected) - set(observed))
    extra = sorted(set(observed) - set(expected))
    if missing or (extra and not contract.allow_extra_columns):
        raise ContractViolation(
            f"{contract.name}: column mismatch; missing={missing}, extra={extra}"
        )

    specs = {item.name: item for item in contract.fields}
    seen_keys: set[tuple[Any, ...]] = set()
    row_count = 0
    for row_number, row in enumerate(rows, start=2):
        row_count += 1
        parsed = {
            name: _parse_value(row.get(name, ""), spec, row_number=row_number)
            for name, spec in specs.items()
        }
        if contract.primary_key:
            key = tuple(parsed[name] for name in contract.primary_key)
            if key in seen_keys:
                raise ContractViolation(
                    f"{contract.name}: duplicate primary key {key!r} at CSV row {row_number}"
                )
            seen_keys.add(key)
    if row_count < contract.minimum_rows:
        raise ContractViolation(
            f"{contract.name}: expected at least {contract.minimum_rows} rows, found {row_count}"
        )
    return {
        "status": "valid",
        "table": contract.name,
        "rows": row_count,
        "columns": list(observed),
        "primary_key_unique": bool(contract.primary_key),
    }


def validate_csv(path: Path | str, contract: TableContract) -> dict[str, Any]:
    candidate = Path(path)
    if candidate.is_symlink() or not candidate.is_file():
        raise ContractViolation(f"{contract.name}: expected a regular file: {candidate}")
    with candidate.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ContractViolation(f"{contract.name}: CSV header is missing")
        return validate_rows(reader, contract, fieldnames=reader.fieldnames)
