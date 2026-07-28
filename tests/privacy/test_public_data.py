from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath

from hfmd.privacy.audit import FileMetadata, audit_tree


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_public_data_allowlist_is_minimal_and_excludes_private_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    payload = json.loads(
        (root / "public_data" / "SOURCE_ALLOWLIST.json").read_text(encoding="utf-8")
    )
    assert payload["policy"] == "deny_by_default"
    entries = payload["entries"]
    assert len(entries) == 7
    forbidden = ("manuscript/", "AnalysisData/", "AnalysisOutput/", "Script_py/")
    for entry in entries:
        source = str(entry["source"])
        destination = PurePosixPath(str(entry["destination"]))
        assert not source.startswith(forbidden)
        assert destination.parts[0] == "public_data"
        assert destination.suffix == ".csv"


def test_public_data_manifest_binds_exact_csv_release() -> None:
    root = Path(__file__).resolve().parents[2]
    data_root = root / "public_data"
    payload = json.loads(
        (data_root / "PUBLIC_DATA_MANIFEST.json").read_text(encoding="utf-8")
    )
    records = payload["files"]
    manifest_paths = {record["destination"] for record in records}
    observed_paths = {
        path.relative_to(root).as_posix() for path in data_root.glob("*.csv")
    }
    assert manifest_paths == observed_paths
    for record in records:
        path = root / record["destination"]
        assert record["classification"] == "aggregate_result_data"
        assert record["license"] == "CC-BY-4.0"
        assert record["sha256"] == _sha256(path)
        assert record["bytes"] == path.stat().st_size


def test_public_data_passes_deny_by_default_privacy_audit() -> None:
    root = Path(__file__).resolve().parents[2]
    data_root = root / "public_data"
    metadata: dict[str, FileMetadata] = {}
    for path in data_root.iterdir():
        if path.suffix == ".csv":
            metadata[path.name] = FileMetadata(
                "aggregate_result_data", "CC-BY-4.0"
            )
        elif path.suffix in {".json", ".md"}:
            metadata[path.name] = FileMetadata("documentation", "CC-BY-4.0")
    result = audit_tree(data_root, metadata)
    assert result.passed, result.findings
