from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from hfmd.privacy.export import SYNTHETIC_RESULT_PATHS, export_public_repository


def _allowlist(source: Path, entries: list[dict[str, object]]) -> Path:
    path = source / "allowlist.json"
    path.write_text(json.dumps({"schema_version": 1, "entries": entries}), encoding="utf-8")
    return path


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "private"
    source.mkdir()
    (source / "code.py").write_text("VALUE = 1\n", encoding="utf-8")
    (source / "README.md").write_text("# Safe public documentation\n", encoding="utf-8")
    allowlist = _allowlist(
        source,
        [
            {
                "pattern": "code.py",
                "classification": "code",
                "license": "BSD-3-Clause",
            },
            {
                "pattern": "README.md",
                "classification": "documentation",
                "license": "CC-BY-4.0",
            },
        ],
    )
    return source, allowlist


def test_export_is_allowlist_only_and_writes_audit_receipts(tmp_path: Path) -> None:
    source, allowlist = _source(tmp_path)
    (source / "not_selected.txt").write_text("private but not selected\n", encoding="utf-8")
    destination = tmp_path / "public"
    receipt = export_public_repository(
        source_root=source,
        destination=destination,
        allowlist_path=allowlist,
        initialize_git=False,
    )
    assert receipt["status"] == "exported"
    assert (destination / "code.py").is_file()
    assert not (destination / "not_selected.txt").exists()
    audit = json.loads((destination / "PRIVACY_AUDIT.json").read_text())
    manifest = json.loads((destination / "PUBLIC_EXPORT_MANIFEST.json").read_text())
    actual = {
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(destination).parts
    }
    registered = {record["destination"] for record in manifest["files"]}
    assert audit["status"] == "passed"
    assert set(audit["audited_paths"]) == actual
    assert registered == actual
    assert receipt["audited_files"] == receipt["classified_files"] == len(actual)
    generated = {
        record["destination"]: record for record in manifest["files"] if record.get("generated")
    }
    assert set(generated) == {"PUBLIC_EXPORT_MANIFEST.json", "PRIVACY_AUDIT.json"}
    assert all(record["classification"] == "documentation" for record in generated.values())


def test_repository_allowlist_excludes_static_manuscript_and_submission_artifacts() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads((root / "public_repo" / "allowlist.json").read_text())
    patterns = {str(entry["pattern"]) for entry in payload["entries"]}
    assert not any("synthetic_results/manuscript" in pattern for pattern in patterns)
    assert not any("synthetic_results/submission" in pattern for pattern in patterns)
    assert "synthetic_results/**/*.svg" not in patterns
    assert "synthetic_results/**/*.txt" not in patterns


def test_export_refuses_existing_or_in_tree_destination(tmp_path: Path) -> None:
    source, allowlist = _source(tmp_path)
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(FileExistsError):
        export_public_repository(
            source_root=source,
            destination=existing,
            allowlist_path=allowlist,
            initialize_git=False,
        )
    with pytest.raises(ValueError, match="outside"):
        export_public_repository(
            source_root=source,
            destination=source / "public",
            allowlist_path=allowlist,
            initialize_git=False,
        )


def test_export_refuses_allowlisted_symlink(tmp_path: Path) -> None:
    source = tmp_path / "private"
    source.mkdir()
    target = source / "target.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    link = source / "link.py"
    link.symlink_to(target)
    allowlist = _allowlist(
        source,
        [
            {
                "pattern": "link.py",
                "classification": "code",
                "license": "BSD-3-Clause",
            }
        ],
    )
    with pytest.raises(ValueError, match="symbolic link"):
        export_public_repository(
            source_root=source,
            destination=tmp_path / "public",
            allowlist_path=allowlist,
            initialize_git=False,
        )


def test_export_refuses_small_cells_before_destination_exists(tmp_path: Path) -> None:
    source = tmp_path / "private"
    source.mkdir()
    (source / "data.csv").write_text("synthetic_region,cases\nA,4\n", encoding="utf-8")
    allowlist = _allowlist(
        source,
        [
            {
                "pattern": "data.csv",
                "classification": "synthetic",
                "license": "CC0-1.0",
            }
        ],
    )
    destination = tmp_path / "public"
    with pytest.raises(ValueError, match="small_cell"):
        export_public_repository(
            source_root=source,
            destination=destination,
            allowlist_path=allowlist,
            initialize_git=False,
        )
    assert not destination.exists()


def test_fresh_git_export_has_one_local_commit_and_no_remote(tmp_path: Path) -> None:
    source, allowlist = _source(tmp_path)
    destination = tmp_path / "public"
    export_public_repository(
        source_root=source,
        destination=destination,
        allowlist_path=allowlist,
        initialize_git=True,
    )
    count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=destination,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert count == "1"
    assert remotes == ""


def test_safe_synthetic_bundle_can_be_exported_with_explicit_scope(tmp_path: Path) -> None:
    source = tmp_path / "private"
    synthetic = source / "synthetic_data"
    synthetic.mkdir(parents=True)
    (synthetic / "weekly.csv").write_text(
        "synthetic_region,year,iso_week,n_cases\nAster,2020,1,10\n",
        encoding="utf-8",
    )
    (synthetic / "synthetic_manifest.json").write_text(
        json.dumps(
            {
                "provenance": "fully_synthetic_not_derived_from_restricted_cells",
                "files": [{"path": "weekly.csv", "bytes": 55}],
            }
        ),
        encoding="utf-8",
    )
    allowlist = _allowlist(
        source,
        [
            {
                "pattern": "synthetic_data/**/*.csv",
                "classification": "synthetic",
                "license": "CC0-1.0",
            },
            {
                "pattern": "synthetic_data/**/*.json",
                "classification": "synthetic",
                "license": "CC0-1.0",
            },
        ],
    )
    destination = tmp_path / "public"
    export_public_repository(
        source_root=source,
        destination=destination,
        allowlist_path=allowlist,
        initialize_git=False,
    )
    assert (destination / "synthetic_data" / "weekly.csv").is_file()
    assert (destination / "synthetic_data" / "synthetic_manifest.json").is_file()


def test_run_scoped_synthetic_overlay_is_validated_and_exported(tmp_path: Path) -> None:
    from hfmd.data.synthetic import generate_synthetic_directory

    source, allowlist = _source(tmp_path)
    synthetic = tmp_path / "run" / "data" / "synthetic"
    generate_synthetic_directory(synthetic, profile="ci", seed=7)
    destination = tmp_path / "public"

    export_public_repository(
        source_root=source,
        destination=destination,
        allowlist_path=allowlist,
        synthetic_source=synthetic,
        initialize_git=False,
    )

    exported = destination / "synthetic_data"
    assert (exported / "synthetic_manifest.json").is_file()
    assert (exported / "weekly_surveillance.csv").is_file()
    assert (exported / "README.md").is_file()
    manifest = json.loads((destination / "PUBLIC_EXPORT_MANIFEST.json").read_text())
    records = {record["destination"]: record for record in manifest["files"]}
    assert records["synthetic_data/weekly_surveillance.csv"]["license"] == "CC0-1.0"
    assert records["synthetic_data/README.md"]["license"] == "CC-BY-4.0"


def test_run_scoped_synthetic_overlay_rejects_unregistered_file(tmp_path: Path) -> None:
    from hfmd.data.synthetic import generate_synthetic_directory

    source, allowlist = _source(tmp_path)
    synthetic = tmp_path / "run" / "data" / "synthetic"
    generate_synthetic_directory(synthetic, profile="ci", seed=7)
    (synthetic / "extra.csv").write_text("cases\n10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file set mismatch"):
        export_public_repository(
            source_root=source,
            destination=tmp_path / "public",
            allowlist_path=allowlist,
            synthetic_source=synthetic,
            initialize_git=False,
        )


def test_run_scoped_synthetic_results_are_explicit_and_inference_prohibited(
    tmp_path: Path,
) -> None:
    source, allowlist = _source(tmp_path)
    results = tmp_path / "run" / "staging"
    for relative_text in SYNTHETIC_RESULT_PATHS:
        path = results / relative_text
        path.parent.mkdir(parents=True, exist_ok=True)
        if relative_text.endswith("summary.json"):
            content = json.dumps(
                {
                    "purpose": "synthetic_validation",
                    "scientific_inference_allowed": False,
                    "profile": "ci",
                    "run_id": "20260717T120000Z-01234567-test",
                }
            )
        elif relative_text.endswith(".json"):
            content = "{}"
        elif relative_text.endswith(".csv"):
            content = "synthetic_region,cases\nAster,10\n"
        elif relative_text.endswith(".svg"):
            content = '<svg xmlns="http://www.w3.org/2000/svg"><text>SYNTHETIC</text></svg>'
        else:
            content = "SYNTHETIC VALIDATION ONLY\n"
        path.write_text(content, encoding="utf-8")

    destination = tmp_path / "public"
    export_public_repository(
        source_root=source,
        destination=destination,
        allowlist_path=allowlist,
        synthetic_results_source=results,
        initialize_git=False,
    )

    expected = {f"synthetic_results/{relative}" for relative in SYNTHETIC_RESULT_PATHS}
    observed = {
        path.relative_to(destination).as_posix()
        for path in (destination / "synthetic_results").rglob("*")
        if path.is_file()
    }
    assert observed == expected


def test_run_scoped_results_reject_non_synthetic_summary(tmp_path: Path) -> None:
    source, allowlist = _source(tmp_path)
    results = tmp_path / "run" / "staging"
    for relative_text in SYNTHETIC_RESULT_PATHS:
        path = results / relative_text
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="inference-prohibited synthetic"):
        export_public_repository(
            source_root=source,
            destination=tmp_path / "public",
            allowlist_path=allowlist,
            synthetic_results_source=results,
            initialize_git=False,
        )


def test_repository_allowlist_includes_workflow_configs_r_lock_and_scoped_synthetic_data() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    allowlist = json.loads(
        (repository_root / "public_repo" / "allowlist.json").read_text(encoding="utf-8")
    )
    entries = {entry["pattern"]: entry for entry in allowlist["entries"]}
    assert "workflow/config/**/*.yaml" in entries
    assert "workflow/profiles/**/*.yaml" in entries
    assert "config/**/*.yaml" in entries
    assert "Script_r/renv.lock" in entries
    assert entries["Script_r/renv.lock"]["classification"] == "configuration"
    assert entries["synthetic_data/**/*.csv"]["classification"] == "synthetic"
    assert entries["synthetic_data/**/*.json"]["license"] == "CC0-1.0"
    assert entries["public_data/*.csv"]["classification"] == "aggregate_result_data"
    assert entries["public_data/*.csv"]["license"] == "CC-BY-4.0"
    assert "public_repo/sync_public_data.py" in entries


def test_repository_public_export_is_self_hosting(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    first = tmp_path / "public-first"
    second = tmp_path / "public-second"

    export_public_repository(
        source_root=repository_root,
        destination=first,
        allowlist_path=repository_root / "public_repo" / "allowlist.json",
        initialize_git=False,
    )
    export_public_repository(
        source_root=first,
        destination=second,
        allowlist_path=first / "public_repo" / "allowlist.json",
        initialize_git=False,
    )

    assert (first / ".github" / "workflows" / "synthetic-ci.yml").is_file()
    assert (second / ".github" / "workflows" / "synthetic-ci.yml").is_file()
    assert (second / "Containerfile").is_file()
    assert (second / "public_repo" / "templates" / "synthetic-ci.yml").is_file()
    audit = json.loads((second / "PRIVACY_AUDIT.json").read_text(encoding="utf-8"))
    assert audit["status"] == "passed"
