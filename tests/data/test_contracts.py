from __future__ import annotations

import csv
import math
from pathlib import Path

import pytest

from hfmd.data.contracts import ContractViolation, FieldSpec, TableContract, validate_csv


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["key", "count"], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _contract() -> TableContract:
    return TableContract(
        "example",
        (
            FieldSpec("key"),
            FieldSpec("count", "integer", minimum=0),
        ),
        primary_key=("key",),
    )


def test_contract_accepts_canonical_rows(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    _write(path, [{"key": "a", "count": 10}, {"key": "b", "count": 0}])
    receipt = validate_csv(path, _contract())
    assert receipt["status"] == "valid"
    assert receipt["rows"] == 2


def test_contract_rejects_duplicate_primary_key(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    _write(path, [{"key": "a", "count": 10}, {"key": "a", "count": 11}])
    with pytest.raises(ContractViolation, match="duplicate primary key"):
        validate_csv(path, _contract())


def test_contract_rejects_noncanonical_integer(tmp_path: Path) -> None:
    path = tmp_path / "table.csv"
    _write(path, [{"key": "a", "count": "10.0"}])
    with pytest.raises(ContractViolation, match="invalid integer"):
        validate_csv(path, _contract())


def test_contract_rejects_symlink(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    _write(source, [{"key": "a", "count": 10}])
    link = tmp_path / "link.csv"
    link.symlink_to(source)
    with pytest.raises(ContractViolation, match="regular file"):
        validate_csv(link, _contract())


def test_field_spec_rejects_unknown_type_and_reversed_bounds() -> None:
    with pytest.raises(ValueError, match="Unsupported field type"):
        FieldSpec("value", "date")
    with pytest.raises(ValueError, match="Invalid numeric bounds"):
        FieldSpec("value", "number", minimum=2, maximum=1)


def test_table_contract_serializes_and_exposes_ordered_columns() -> None:
    contract = _contract()
    assert contract.columns == ("key", "count")
    assert contract.as_dict()["primary_key"] == ("key",)


def test_contract_rejects_missing_and_extra_columns(tmp_path: Path) -> None:
    missing = tmp_path / "missing.csv"
    missing.write_text("key\na\n", encoding="utf-8")
    with pytest.raises(ContractViolation, match=r"missing=\['count'\]"):
        validate_csv(missing, _contract())

    extra = tmp_path / "extra.csv"
    extra.write_text("key,count,note\na,10,safe\n", encoding="utf-8")
    with pytest.raises(ContractViolation, match=r"extra=\['note'\]"):
        validate_csv(extra, _contract())

    permissive = TableContract(
        "permissive",
        _contract().fields,
        primary_key=("key",),
        allow_extra_columns=True,
    )
    assert validate_csv(extra, permissive)["columns"] == ["key", "count", "note"]


def test_contract_rejects_missing_header_and_minimum_rows(tmp_path: Path) -> None:
    empty = tmp_path / "empty.csv"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ContractViolation, match="CSV header is missing"):
        validate_csv(empty, _contract())

    header_only = tmp_path / "header-only.csv"
    header_only.write_text("key,count\n", encoding="utf-8")
    contract = TableContract("needs_two", _contract().fields, minimum_rows=2)
    with pytest.raises(ContractViolation, match="expected at least 2 rows, found 0"):
        validate_csv(header_only, contract)


@pytest.mark.parametrize("value", ["", "NaN", "inf", "-inf", "not-a-number"])
def test_number_contract_rejects_empty_nonfinite_and_invalid_values(
    value: str, tmp_path: Path
) -> None:
    path = tmp_path / "number.csv"
    encoded = '""' if value == "" else value
    path.write_text(f"value\n{encoded}\n", encoding="utf-8")
    contract = TableContract("number", (FieldSpec("value", "number"),))
    match = "empty value" if value == "" else "invalid number"
    with pytest.raises(ContractViolation, match=match):
        validate_csv(path, contract)


@pytest.mark.parametrize(
    ("value", "message"),
    [("-0.1", "below 0"), ("1.1", "above 1")],
)
def test_number_contract_enforces_bounds(value: str, message: str, tmp_path: Path) -> None:
    path = tmp_path / "bounded.csv"
    path.write_text(f"value\n{value}\n", encoding="utf-8")
    contract = TableContract("bounded", (FieldSpec("value", "number", minimum=0, maximum=1),))
    with pytest.raises(ContractViolation, match=message):
        validate_csv(path, contract)


@pytest.mark.parametrize("value", ["true", "false", "TRUE", "0", "1"])
def test_boolean_contract_accepts_declared_encodings(value: str, tmp_path: Path) -> None:
    path = tmp_path / f"boolean-{value}.csv"
    path.write_text(f"flag\n{value}\n", encoding="utf-8")
    contract = TableContract("boolean", (FieldSpec("flag", "boolean"),))
    assert validate_csv(path, contract)["status"] == "valid"


def test_boolean_choice_and_nullable_contracts(tmp_path: Path) -> None:
    invalid_boolean = tmp_path / "invalid-boolean.csv"
    invalid_boolean.write_text("flag\nyes\n", encoding="utf-8")
    boolean = TableContract("boolean", (FieldSpec("flag", "boolean"),))
    with pytest.raises(ContractViolation, match="invalid boolean"):
        validate_csv(invalid_boolean, boolean)

    invalid_choice = tmp_path / "invalid-choice.csv"
    invalid_choice.write_text("group\nother\n", encoding="utf-8")
    choice = TableContract("choice", (FieldSpec("group", choices=("a", "b")),))
    with pytest.raises(ContractViolation, match="outside the declared choices"):
        validate_csv(invalid_choice, choice)

    nullable = tmp_path / "nullable.csv"
    nullable.write_text('value\n""\n', encoding="utf-8")
    nullable_contract = TableContract("nullable", (FieldSpec("value", "number", nullable=True),))
    assert validate_csv(nullable, nullable_contract)["rows"] == 1


def test_plus_prefixed_integer_is_canonical_but_leading_zero_is_not(tmp_path: Path) -> None:
    plus = tmp_path / "plus.csv"
    plus.write_text("value\n+10\n", encoding="utf-8")
    contract = TableContract("integer", (FieldSpec("value", "integer"),))
    assert validate_csv(plus, contract)["rows"] == 1

    leading_zero = tmp_path / "leading-zero.csv"
    leading_zero.write_text("value\n010\n", encoding="utf-8")
    with pytest.raises(ContractViolation, match="invalid integer"):
        validate_csv(leading_zero, contract)


def test_number_contract_accepts_finite_value(tmp_path: Path) -> None:
    path = tmp_path / "finite.csv"
    value = math.nextafter(1.0, 0.0)
    path.write_text(f"value\n{value}\n", encoding="utf-8")
    contract = TableContract("finite", (FieldSpec("value", "number", minimum=0, maximum=1),))
    assert validate_csv(path, contract)["rows"] == 1
