from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from hfmd.data import synthetic
from hfmd.data.synthetic import generate_synthetic_directory, validate_synthetic_directory
from hfmd.privacy.audit import FileMetadata, audit_tree


def _hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.iterdir())
        if path.is_file()
    }


@pytest.fixture(scope="module")
def generated_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("synthetic-fixture") / "data"
    generate_synthetic_directory(root, profile="ci", seed=314159)
    return root


def _copy_fixture(source: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "synthetic"
    shutil.copytree(source, destination)
    return destination


def _manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "synthetic_manifest.json").read_text(encoding="utf-8"))


def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
    (root / "synthetic_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_synthetic_generation_is_byte_deterministic(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    generate_synthetic_directory(first, profile="ci", seed=42)
    generate_synthetic_directory(second, profile="ci", seed=42)
    assert _hashes(first) == _hashes(second)


def test_synthetic_manifest_and_contracts_validate(tmp_path: Path) -> None:
    root = tmp_path / "synthetic"
    receipt = generate_synthetic_directory(root, profile="ci", seed=20260717)
    assert receipt["status"] == "valid"
    manifest = json.loads((root / "synthetic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["provenance"] == "fully_synthetic_not_derived_from_restricted_cells"
    assert validate_synthetic_directory(root)["manifest_files"] == 7


def test_synthetic_tree_passes_public_privacy_policy(tmp_path: Path) -> None:
    root = tmp_path / "synthetic"
    generate_synthetic_directory(root, profile="ci", seed=9)
    metadata = {
        path.name: FileMetadata("synthetic", "CC0-1.0") for path in root.iterdir() if path.is_file()
    }
    result = audit_tree(root, metadata)
    assert result.passed, result.findings


def test_replacement_is_explicit_and_atomic(tmp_path: Path) -> None:
    root = tmp_path / "synthetic"
    generate_synthetic_directory(root, profile="ci", seed=1)
    before = _hashes(root)
    generate_synthetic_directory(root, profile="ci", seed=2, replace=True)
    after = _hashes(root)
    assert before != after
    assert not list(tmp_path.glob(".synthetic.rollback-*"))
    assert not list(tmp_path.glob(".synthetic.staging-*"))


def test_generator_rejects_unknown_profile_and_implicit_replacement(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown synthetic profile"):
        generate_synthetic_directory(tmp_path / "unknown", profile="private")

    root = tmp_path / "synthetic"
    generate_synthetic_directory(root, profile="ci", seed=3)
    with pytest.raises(FileExistsError, match="Refusing to replace"):
        generate_synthetic_directory(root, profile="ci", seed=4)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("schema_version", 2, "Unsupported synthetic manifest schema"),
        ("provenance", "derived_from_real_data", "provenance declaration is missing"),
        ("files", [], "no file registry"),
        ("files", "not-a-list", "no file registry"),
    ],
)
def test_validator_rejects_invalid_manifest_declarations(
    field: str,
    value: object,
    message: str,
    generated_fixture: Path,
    tmp_path: Path,
) -> None:
    root = _copy_fixture(generated_fixture, tmp_path)
    manifest = _manifest(root)
    manifest[field] = value
    _write_manifest(root, manifest)

    with pytest.raises(ValueError, match=message):
        validate_synthetic_directory(root)


def test_validator_rejects_missing_duplicate_and_unsafe_manifest_paths(
    generated_fixture: Path, tmp_path: Path
) -> None:
    root = _copy_fixture(generated_fixture, tmp_path)
    manifest = _manifest(root)
    records = manifest["files"]
    assert isinstance(records, list)
    assert isinstance(records[0], dict)
    records[0].pop("path")
    _write_manifest(root, manifest)
    with pytest.raises(ValueError, match="missing path"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "duplicate")
    manifest = _manifest(root)
    records = manifest["files"]
    assert isinstance(records, list)
    records.append(dict(records[0]))
    _write_manifest(root, manifest)
    with pytest.raises(ValueError, match="duplicate paths"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "unsafe")
    manifest = _manifest(root)
    records = manifest["files"]
    assert isinstance(records, list)
    assert isinstance(records[0], dict)
    records[0]["path"] = "../escape.csv"
    _write_manifest(root, manifest)
    with pytest.raises(ValueError, match="Unsafe synthetic manifest path"):
        validate_synthetic_directory(root)


def test_validator_rejects_extra_missing_nested_and_symlink_files(
    generated_fixture: Path, tmp_path: Path
) -> None:
    root = _copy_fixture(generated_fixture, tmp_path)
    (root / "extra.csv").write_text("count\n10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file set mismatch.*extra"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "missing")
    (root / "README.md").unlink()
    with pytest.raises(ValueError, match="file set mismatch.*missing"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "nested")
    (root / "nested").mkdir()
    (root / "nested" / "hidden.csv").write_text("count\n10\n", encoding="utf-8")
    with pytest.raises(ValueError, match="only regular top-level files"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "symlink")
    (root / "unsafe-link").symlink_to(root / "README.md")
    with pytest.raises(ValueError, match="only regular top-level files"):
        validate_synthetic_directory(root)


def test_validator_rejects_byte_and_hash_mismatch(generated_fixture: Path, tmp_path: Path) -> None:
    root = _copy_fixture(generated_fixture, tmp_path)
    manifest = _manifest(root)
    records = manifest["files"]
    assert isinstance(records, list)
    record = next(item for item in records if item["path"] == "README.md")
    record["bytes"] += 1
    _write_manifest(root, manifest)
    with pytest.raises(ValueError, match="byte mismatch"):
        validate_synthetic_directory(root)

    root = _copy_fixture(generated_fixture, tmp_path / "hash")
    manifest = _manifest(root)
    records = manifest["files"]
    assert isinstance(records, list)
    record = next(item for item in records if item["path"] == "README.md")
    record["sha256"] = "0" * 64
    _write_manifest(root, manifest)
    with pytest.raises(ValueError, match="hash mismatch"):
        validate_synthetic_directory(root)


def test_validator_rejects_small_cells_before_manifest_hash_check(
    generated_fixture: Path, tmp_path: Path
) -> None:
    root = _copy_fixture(generated_fixture, tmp_path)
    weekly = root / "weekly_surveillance.csv"
    with weekly.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fieldnames = reader.fieldnames
    assert fieldnames is not None
    rows[0]["cases"] = "9"
    with weekly.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(ValueError, match="cases: value 9 is below 10"):
        validate_synthetic_directory(root)


def test_validator_rejects_non_directory_and_symlink_root(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="not a regular directory"):
        validate_synthetic_directory(missing)

    target = tmp_path / "target"
    generate_synthetic_directory(target, profile="ci", seed=6)
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="not a regular directory"):
        validate_synthetic_directory(link)


def test_synthetic_main_generates_and_validates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "synthetic"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hfmd.data.synthetic",
            "--output",
            str(root),
            "--profile",
            "ci",
            "--seed",
            "88",
        ],
    )
    synthetic.main()
    assert json.loads(capsys.readouterr().out)["status"] == "valid"

    monkeypatch.setattr(
        sys,
        "argv",
        ["hfmd.data.synthetic", "--output", str(root), "--validate-only"],
    )
    synthetic.main()
    assert json.loads(capsys.readouterr().out)["manifest_files"] == 7
