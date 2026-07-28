"""Create a new-history public repository from an explicit allowlist."""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from hfmd.data.synthetic import validate_synthetic_directory

from .audit import FileMetadata, PrivacyPolicy, audit_tree

SYNTHETIC_RESULT_PATHS = (
    "analysis/ecological/annual_validation_metrics.csv",
    "analysis/ecological/data_contract.json",
    "analysis/ecological/summary.json",
    "analysis/dynamics/annual_pathogen_validation.csv",
    "analysis/dynamics/data_contract.json",
    "analysis/dynamics/rolling_origin_validation.csv",
    "analysis/dynamics/summary.json",
    "analysis/dynamics/typing_selection_validation.csv",
    "figures/main/figure1_ecological_atlas.svg",
    "figures/main/figure2_county_ecological_effects.svg",
    "figures/main/figure3_community_balance.svg",
    "figures/main/figure4_age_ecology.svg",
    "figures/main/figure5_evidence_boundaries.svg",
    "reporting/claim_occurrences.json",
    "reporting/claims.json",
    "manuscript/manuscript.md",
    "manuscript/supplementary.md",
    "submission/declarations.md",
    "submission/graphical_abstract/graphical_abstract.svg",
    "submission/highlights.txt",
)


@dataclass(frozen=True, slots=True)
class ExportRecord:
    source: str
    destination: str
    classification: str
    license: str
    bytes: int
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str, *, label: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"Unsafe {label}: {value!r}")
    if path.parts[0] == ".git":
        raise ValueError(f"The .git directory may not be exported: {value!r}")
    return path


def _has_glob(value: str) -> bool:
    return any(character in value for character in "*?[")


def _assert_regular_with_regular_ancestors(path: Path, root: Path) -> None:
    relative = path.relative_to(root)
    current = root
    if current.is_symlink() or not current.is_dir():
        raise ValueError(f"Unsafe source root: {root}")
    for part in relative.parts:
        current = current / part
        mode = current.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise ValueError(f"Allowlist matched a symbolic link: {current}")
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"Allowlist matched a non-regular file: {path}")


def _load_allowlist(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Allowlist must be a regular file: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Public allowlist must contain a JSON object")
    if payload.get("schema_version") != 1 or not isinstance(payload.get("entries"), list):
        raise ValueError("Unsupported public allowlist schema")
    return cast(dict[str, Any], payload)


def _expand_records(
    source_root: Path, allowlist: dict[str, Any]
) -> list[tuple[Path, PurePosixPath, dict[str, Any]]]:
    selected: list[tuple[Path, PurePosixPath, dict[str, Any]]] = []
    seen_destinations: set[str] = set()
    for index, entry in enumerate(allowlist["entries"]):
        if not isinstance(entry, dict):
            raise ValueError(f"Allowlist entry {index} must be an object")
        pattern = str(entry.get("pattern", ""))
        _safe_relative(pattern, label="allowlist pattern")
        classification = str(entry.get("classification", ""))
        license_name = str(entry.get("license", ""))
        required = bool(entry.get("required", True))
        matches = [
            Path(value)
            for value in sorted(glob.glob(str(source_root / pattern), recursive=True))
            if Path(value).is_file() or Path(value).is_symlink()
        ]
        if not matches and required:
            raise FileNotFoundError(f"Required allowlist pattern matched no files: {pattern}")
        explicit_destination = entry.get("destination")
        if explicit_destination is not None and (_has_glob(pattern) or len(matches) > 1):
            raise ValueError("destination remapping requires one exact source file")
        for source in matches:
            _assert_regular_with_regular_ancestors(source, source_root)
            source_relative = source.relative_to(source_root).as_posix()
            destination = _safe_relative(
                str(explicit_destination or source_relative), label="export destination"
            )
            destination_text = destination.as_posix()
            if destination_text in seen_destinations:
                raise ValueError(f"Multiple allowlist entries target {destination_text}")
            seen_destinations.add(destination_text)
            selected.append(
                (
                    source,
                    destination,
                    {
                        "classification": classification,
                        "license": license_name,
                        "source": source_relative,
                    },
                )
            )
    if not selected:
        raise ValueError("Public allowlist selected no files")
    return selected


def _expand_synthetic_overlay(
    synthetic_root: Path,
    *,
    occupied_destinations: set[str],
) -> list[tuple[Path, PurePosixPath, dict[str, Any]]]:
    """Register one validated run-scoped synthetic bundle for public export."""

    root = synthetic_root.resolve(strict=True)
    validate_synthetic_directory(root)
    selected: list[tuple[Path, PurePosixPath, dict[str, Any]]] = []
    documentation = {"README.md", "DATA_DICTIONARY.md"}
    for source in sorted(root.iterdir()):
        _assert_regular_with_regular_ancestors(source, root)
        destination = PurePosixPath("synthetic_data", source.name)
        destination_text = destination.as_posix()
        if destination_text in occupied_destinations:
            raise ValueError(f"Synthetic overlay conflicts with allowlisted {destination_text}")
        occupied_destinations.add(destination_text)
        if source.name in documentation:
            classification, license_name = "documentation", "CC-BY-4.0"
        else:
            classification, license_name = "synthetic", "CC0-1.0"
        selected.append(
            (
                source,
                destination,
                {
                    "classification": classification,
                    "license": license_name,
                    "source": f"run-scoped-synthetic/{source.name}",
                },
            )
        )
    return selected


def _expand_synthetic_results_overlay(
    result_root: Path,
    *,
    occupied_destinations: set[str],
) -> list[tuple[Path, PurePosixPath, dict[str, Any]]]:
    """Select a small, explicit, inference-prohibited synthetic result bundle."""

    root = result_root.resolve(strict=True)
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"Synthetic result root is not a regular directory: {root}")
    identities: set[tuple[str, str]] = set()
    for summary_relative in (
        "analysis/ecological/summary.json",
        "analysis/dynamics/summary.json",
    ):
        payload = json.loads((root / summary_relative).read_text(encoding="utf-8"))
        if (
            payload.get("purpose") != "synthetic_validation"
            or payload.get("scientific_inference_allowed") is not False
            or payload.get("profile") not in {"ci", "synthetic"}
        ):
            raise ValueError(
                "Result is not an inference-prohibited synthetic artifact: "
                f"{summary_relative}"
            )
        identities.add((str(payload.get("run_id")), str(payload.get("profile"))))
    if len(identities) != 1:
        raise ValueError("Synthetic result summaries disagree on run identity")

    selected: list[tuple[Path, PurePosixPath, dict[str, Any]]] = []
    for relative_text in SYNTHETIC_RESULT_PATHS:
        result_relative = PurePosixPath(relative_text)
        source = root.joinpath(*result_relative.parts)
        _assert_regular_with_regular_ancestors(source, root)
        destination = PurePosixPath("synthetic_results", *result_relative.parts)
        destination_text = destination.as_posix()
        if destination_text in occupied_destinations:
            raise ValueError(f"Synthetic results conflict with allowlisted {destination_text}")
        occupied_destinations.add(destination_text)
        if source.suffix.lower() in {".md", ".txt"}:
            classification, license_name = "documentation", "CC-BY-4.0"
        else:
            classification, license_name = "synthetic", "CC0-1.0"
        selected.append(
            (
                source,
                destination,
                {
                    "classification": classification,
                    "license": license_name,
                    "source": f"run-scoped-synthetic-result/{result_relative.as_posix()}",
                },
            )
        )
    return selected


def _copy_selected(
    selected: list[tuple[Path, PurePosixPath, dict[str, Any]]], staging: Path
) -> tuple[list[ExportRecord], dict[str, FileMetadata]]:
    records: list[ExportRecord] = []
    metadata: dict[str, FileMetadata] = {}
    for source, destination, meta in selected:
        before = _sha256(source)
        target = staging.joinpath(*destination.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as input_handle, target.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        target.chmod(0o644)
        source_after = _sha256(source)
        copied = _sha256(target)
        if before != source_after or before != copied:
            raise RuntimeError(f"Source changed during public export: {source}")
        relative = destination.as_posix()
        record = ExportRecord(
            source=meta["source"],
            destination=relative,
            classification=meta["classification"],
            license=meta["license"],
            bytes=target.stat().st_size,
            sha256=copied,
        )
        records.append(record)
        metadata[relative] = FileMetadata(
            classification=record.classification,
            license=record.license,
            source=record.source,
        )
    return records, metadata


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    path.chmod(0o644)


def _initialize_fresh_git(staging: Path) -> None:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_DATE", "2000-01-01T00:00:00Z")
    env.setdefault("GIT_COMMITTER_DATE", env["GIT_AUTHOR_DATE"])
    subprocess.run(
        ["git", "init", "--initial-branch", "main"],
        cwd=staging,
        env=env,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "config", "user.name", "HFMD public exporter"], cwd=staging, check=True)
    subprocess.run(
        ["git", "config", "user.email", "noreply@invalid.example"], cwd=staging, check=True
    )
    subprocess.run(["git", "add", "--all"], cwd=staging, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial public release"],
        cwd=staging,
        env=env,
        check=True,
        capture_output=True,
    )


def export_public_repository(
    *,
    source_root: Path | str,
    destination: Path | str,
    allowlist_path: Path | str,
    synthetic_source: Path | str | None = None,
    synthetic_results_source: Path | str | None = None,
    initialize_git: bool = True,
    policy: PrivacyPolicy | None = None,
) -> dict[str, Any]:
    source = Path(source_root).resolve()
    target = Path(destination).resolve()
    allowlist_file = Path(allowlist_path).resolve()
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Source root must be a regular directory: {source}")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"Public destination must not already exist: {target}")
    try:
        target.relative_to(source)
    except ValueError:
        pass
    else:
        raise ValueError("Public destination must be outside the private source repository")
    allowlist = _load_allowlist(allowlist_file)
    selected = _expand_records(source, allowlist)
    if synthetic_source is not None:
        occupied = {destination.as_posix() for _, destination, _ in selected}
        selected.extend(
            _expand_synthetic_overlay(
                Path(synthetic_source),
                occupied_destinations=occupied,
            )
        )
    if synthetic_results_source is not None:
        occupied = {destination.as_posix() for _, destination, _ in selected}
        selected.extend(
            _expand_synthetic_results_overlay(
                Path(synthetic_results_source),
                occupied_destinations=occupied,
            )
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent))
    try:
        records, metadata = _copy_selected(selected, staging)
        effective_policy = policy or PrivacyPolicy()
        payload_audit = audit_tree(staging, metadata, policy=effective_policy)
        if not payload_audit.passed:
            details = "; ".join(f"{item.path}:{item.code}" for item in payload_audit.findings[:12])
            raise ValueError(f"Public privacy audit failed: {details}")
        manifest_path = staging / "PUBLIC_EXPORT_MANIFEST.json"
        audit_path = staging / "PRIVACY_AUDIT.json"
        generated_receipts = (
            (manifest_path.name, "Public export file registry"),
            (audit_path.name, "Transactional privacy audit receipt"),
        )
        generated_records = [
            {
                "source": None,
                "destination": name,
                "classification": "documentation",
                "license": "CC-BY-4.0",
                "bytes": None,
                "sha256": None,
                "generated": True,
                "integrity": "covered_by_terminal_export_audit",
                "description": description,
            }
            for name, description in generated_receipts
        ]
        manifest = {
            "schema_version": 1,
            "export_policy": "deny_by_default_allowlist",
            "minimum_public_cell": effective_policy.minimum_public_cell,
            "files": [
                *[asdict(item) for item in sorted(records, key=lambda item: item.destination)],
                *generated_records,
            ],
        }
        _write_json(manifest_path, manifest)
        for name, _ in generated_receipts:
            metadata[name] = FileMetadata("documentation", "CC-BY-4.0", source=None)
        manifest_audit = audit_tree(
            staging,
            {key: value for key, value in metadata.items() if key != audit_path.name},
            policy=effective_policy,
        )
        if not manifest_audit.passed:
            details = "; ".join(f"{item.path}:{item.code}" for item in manifest_audit.findings[:12])
            raise ValueError(f"Generated public manifest failed audit: {details}")
        expected_paths = sorted(metadata)
        _write_json(
            audit_path,
            {
                "schema_version": 1,
                "status": "passed",
                "audit_mode": "terminal_transactional_full_tree",
                "files_scanned": len(expected_paths),
                "classified_files": len(expected_paths),
                "audited_paths": expected_paths,
                "payload_preflight": {
                    "status": payload_audit.status,
                    "files_scanned": payload_audit.files_scanned,
                    "bytes_scanned": payload_audit.bytes_scanned,
                    "findings": len(payload_audit.findings),
                    "file_hashes": dict(sorted(payload_audit.file_hashes.items())),
                },
                "manifest_sha256": _sha256(manifest_path),
                "policy": "no direct identifiers, event-level records, county/finer quasi-"
                "identifiers, exact dates, positive cells below ten, secrets, symlinks, or "
                "unknown licenses",
                "receipt_integrity": "This receipt and the export manifest are both "
                "classified, listed in the manifest, and included in the terminal audit. "
                "Their returned SHA-256 values bind the generated receipts without an "
                "impossible self-referential hash.",
            },
        )
        final_audit = audit_tree(staging, metadata, policy=effective_policy)
        if not final_audit.passed:
            details = "; ".join(f"{item.path}:{item.code}" for item in final_audit.findings[:12])
            raise ValueError(f"Terminal public privacy audit failed: {details}")
        if set(final_audit.file_hashes) != set(expected_paths):
            raise RuntimeError("Terminal audit did not cover the exact classified file set")
        if initialize_git:
            _initialize_fresh_git(staging)
            post_git_audit = audit_tree(staging, metadata, policy=effective_policy)
            if not post_git_audit.passed or post_git_audit.file_hashes != final_audit.file_hashes:
                raise RuntimeError("Git initialization changed or bypassed the audited file set")
        staging.replace(target)
        return {
            "status": "exported",
            "destination": str(target),
            "payload_files": len(records),
            "audited_files": final_audit.files_scanned,
            "classified_files": len(metadata),
            "git_initialized": initialize_git,
            "manifest_sha256": _sha256(target / manifest_path.name),
            "privacy_audit_sha256": _sha256(target / audit_path.name),
        }
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--synthetic-source", type=Path)
    parser.add_argument("--synthetic-results-source", type=Path)
    parser.add_argument("--no-git", action="store_true")
    parser.add_argument("--minimum-cell", type=int, default=10)
    args = parser.parse_args()
    result = export_public_repository(
        source_root=args.source_root,
        destination=args.destination,
        allowlist_path=args.allowlist,
        synthetic_source=args.synthetic_source,
        synthetic_results_source=args.synthetic_results_source,
        initialize_git=not args.no_git,
        policy=PrivacyPolicy(minimum_public_cell=args.minimum_cell),
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
