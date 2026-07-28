from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hfmd.privacy.audit import FileMetadata, audit_tree


def _csv(path: Path, fieldnames: list[str], row: dict[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)


def _codes(result) -> set[str]:
    return {finding.code for finding in result.findings}


@pytest.mark.parametrize(
    ("column", "code"),
    [
        ("patient_name", "direct_identifier_column"),
        ("event_id", "event_level_identifier"),
        ("county_code", "geographic_quasi_identifier"),
        ("onset_date", "exact_time_column"),
    ],
)
def test_forbidden_columns_are_hard_failures(tmp_path: Path, column: str, code: str) -> None:
    path = tmp_path / "unsafe.csv"
    _csv(path, [column, "cases"], {column: "x", "cases": 10})
    result = audit_tree(tmp_path, {path.name: FileMetadata("synthetic", "CC0-1.0")})
    assert not result.passed
    assert code in _codes(result)


def test_positive_small_cell_is_rejected_but_structural_zero_is_allowed(tmp_path: Path) -> None:
    unsafe = tmp_path / "unsafe.csv"
    _csv(unsafe, ["synthetic_region", "cases"], {"synthetic_region": "A", "cases": 9})
    result = audit_tree(tmp_path, {unsafe.name: FileMetadata("synthetic", "CC0-1.0")})
    assert "small_cell" in _codes(result)

    unsafe.unlink()
    safe = tmp_path / "safe.csv"
    _csv(safe, ["synthetic_region", "cases"], {"synthetic_region": "A", "cases": 0})
    result = audit_tree(tmp_path, {safe.name: FileMetadata("synthetic", "CC0-1.0")})
    assert result.passed, result.findings


def test_exact_date_value_is_rejected_even_without_date_header(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.csv"
    _csv(path, ["label", "cases"], {"label": "seen 2020-01-15", "cases": 10})
    result = audit_tree(tmp_path, {path.name: FileMetadata("synthetic", "CC0-1.0")})
    assert "exact_date_value" in _codes(result)


def test_secret_and_credential_filename_are_rejected(tmp_path: Path) -> None:
    token = "AK" + "IA" + "A" * 16
    secret_file = tmp_path / "notes.txt"
    secret_file.write_text(token, encoding="utf-8")
    environment = tmp_path / ".env"
    environment.write_text("SAFE=placeholder\n", encoding="utf-8")
    metadata = {
        secret_file.name: FileMetadata("documentation", "CC-BY-4.0"),
        environment.name: FileMetadata("configuration", "BSD-3-Clause"),
    }
    result = audit_tree(tmp_path, metadata)
    assert {"secret_pattern", "forbidden_filename"}.issubset(_codes(result))


def test_unknown_license_and_unclassified_file_are_rejected(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    second = tmp_path / "second.md"
    first.write_text("safe\n", encoding="utf-8")
    second.write_text("safe\n", encoding="utf-8")
    result = audit_tree(tmp_path, {first.name: FileMetadata("documentation", "unknown")})
    assert {"unknown_license", "unclassified_file"}.issubset(_codes(result))


def test_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.md"
    target.write_text("safe\n", encoding="utf-8")
    link = tmp_path / "link.md"
    link.symlink_to(target)
    result = audit_tree(
        tmp_path,
        {
            target.name: FileMetadata("documentation", "CC-BY-4.0"),
            link.name: FileMetadata("documentation", "CC-BY-4.0"),
        },
    )
    assert "symbolic_link" in _codes(result)


@pytest.mark.parametrize(
    ("suffix", "payload", "expected"),
    [
        (".json", {"rows": [{"patient_name": "Li Ming"}]}, "direct_identifier_field"),
        (".json", {"rows": [{"county_label": "Real County"}]}, "geographic_quasi_identifier"),
        (".json", {"rows": [{"admin_code": "430101"}]}, "geographic_quasi_identifier"),
        (".json", {"rows": [{"n_cases": 4}]}, "small_cell"),
        (".json", {"rows": [{"positive": 1}]}, "small_cell"),
        (".json", {"rows": [{"onset_date": "2020-01-15"}]}, "exact_date_value"),
        (".yaml", "rows:\n  - patient_id: P0001\n", "event_level_identifier"),
        (".yaml", "n_positive: [2, 12]\n", "small_cell"),
    ],
)
def test_structured_synthetic_content_cannot_bypass_policy(
    tmp_path: Path, suffix: str, payload: object, expected: str
) -> None:
    path = tmp_path / f"unsafe{suffix}"
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    result = audit_tree(tmp_path, {path.name: FileMetadata("synthetic", "CC0-1.0")})
    assert expected in _codes(result)


def test_embedded_json_and_general_text_are_audited(tmp_path: Path) -> None:
    nested = tmp_path / "nested.json"
    nested.write_text(
        json.dumps({"payload": json.dumps({"county_label": "Real County", "n_cases": 3})}),
        encoding="utf-8",
    )
    note = tmp_path / "records.txt"
    note.write_text("patient_id=P0001\npositive: 5\n", encoding="utf-8")
    result = audit_tree(
        tmp_path,
        {
            nested.name: FileMetadata("synthetic", "CC0-1.0"),
            note.name: FileMetadata("synthetic", "CC0-1.0"),
        },
    )
    assert {"geographic_quasi_identifier", "small_cell", "event_level_identifier"}.issubset(
        _codes(result)
    )


def test_svg_metadata_attributes_labels_and_dates_are_audited(tmp_path: Path) -> None:
    path = tmp_path / "unsafe.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<metadata data-county-label="Real County">n_cases: 3</metadata>'
        "<text>2020-01-15</text>"
        "</svg>",
        encoding="utf-8",
    )
    result = audit_tree(tmp_path, {path.name: FileMetadata("visual_template", "BSD-3-Clause")})
    assert {
        "geographic_quasi_identifier",
        "small_cell",
        "exact_date_value",
    }.issubset(_codes(result))


@pytest.mark.parametrize(
    "embedded",
    [
        "patient_email: actual.person@hospital.cn",
        "patient_phone: 13800138000",
        "national_id: 11010519491231002X",
    ],
)
def test_embedded_direct_identifiers_are_rejected(tmp_path: Path, embedded: str) -> None:
    path = tmp_path / "unsafe.txt"
    path.write_text(embedded + "\n", encoding="utf-8")
    result = audit_tree(tmp_path, {path.name: FileMetadata("synthetic", "CC0-1.0")})
    assert "embedded_direct_identifier" in _codes(result)


def test_code_docs_placeholders_and_dependency_metadata_do_not_create_false_positives(
    tmp_path: Path,
) -> None:
    code = tmp_path / "example.py"
    code.write_text(
        'example = {"patient_id": "P0001", "county_label": "Example", "n_cases": 4}\n',
        encoding="utf-8",
    )
    docs = tmp_path / "policy.md"
    docs.write_text(
        "Example only: `patient_id=P0001`, `onset_date=2020-01-15`, `positive=4`.\n",
        encoding="utf-8",
    )
    lock = tmp_path / "dependency.lock"
    lock.write_text(
        json.dumps(
            {
                "Package": {
                    "name": "example-package",
                    "Date": "2022-04-03",
                    "email": "maintainer@posit.co",
                }
            }
        ),
        encoding="utf-8",
    )
    result = audit_tree(
        tmp_path,
        {
            code.name: FileMetadata("code", "BSD-3-Clause"),
            docs.name: FileMetadata("documentation", "CC-BY-4.0"),
            lock.name: FileMetadata("configuration", "BSD-3-Clause"),
        },
    )
    assert result.passed, result.findings


def test_placeholder_in_general_text_is_not_treated_as_a_record(tmp_path: Path) -> None:
    path = tmp_path / "example.txt"
    path.write_text("patient_id=placeholder\nemail=person@example.org\n", encoding="utf-8")
    result = audit_tree(tmp_path, {path.name: FileMetadata("documentation", "CC-BY-4.0")})
    assert result.passed, result.findings
