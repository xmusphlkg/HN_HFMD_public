"""Crash-aware publication of a fully sealed formal run."""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

from hfmd.core.environment import require_clean_worktree
from hfmd.core.hashing import atomic_write_json, sha256_file
from hfmd.core.locking import FileLock
from hfmd.core.manifest import ManifestError, RunManifest, validate_manifest
from hfmd.core.run import RunContext


class PublicationError(RuntimeError):
    """Raised when a candidate cannot safely replace the current publication."""


def _path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_regular_directory(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_dir() or not stat.S_ISDIR(path.lstat().st_mode):
        raise PublicationError(f"{label} is not a regular directory: {path}")


def _exchange_directories(first: Path, second: Path) -> None:
    """Atomically exchange two Linux directory entries using renameat2."""

    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise PublicationError("atomic directory exchange requires Linux renameat2")
    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(first),
        -100,
        os.fsencode(second),
        2,
    )
    if result != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, os.strerror(error_number), f"{first} <-> {second}")


def _load_bound_manifest(context: RunContext) -> RunManifest:
    preflight = validate_manifest(
        context.manifest_path,
        artifact_root=context.staging,
        workspace=context.workspace,
    )
    if not preflight.ok:
        raise ManifestError("; ".join(preflight.issues))
    with context.manifest_path.open("r", encoding="utf-8") as handle:
        manifest = RunManifest.model_validate(json.load(handle))
    runtime = context.loaded_config.config.runtime
    mismatches: list[str] = []
    if manifest.run_id != context.run_id:
        mismatches.append("run_id")
    if manifest.profile != runtime.profile:
        mismatches.append("profile")
    if not manifest.formal:
        mismatches.append("formal")
    if manifest.config_sha256 != context.loaded_config.config_sha256:
        mismatches.append("config_sha256")
    if manifest.stage != "all":
        mismatches.append("stage")
    if manifest.git.dirty:
        mismatches.append("git.dirty")
    if mismatches:
        raise PublicationError(
            "sealed manifest does not match publication context: " + ", ".join(mismatches)
        )
    return manifest


def publish_run(context: RunContext) -> Path:
    """Atomically replace artifacts/current with a formal restricted run.

    When a current directory already exists, Linux RENAME_EXCHANGE swaps the
    two directory entries in one filesystem operation. The old result then
    occupies the run staging path only for validation rollback and is deleted
    immediately after the new current validates.
    """

    runtime = context.loaded_config.config.runtime
    if not runtime.formal or runtime.profile.value != "restricted":
        raise PublicationError("only a formal restricted run may replace artifacts/current")
    if context.target != "all":
        raise PublicationError("only a completely sealed --target all run may be published")
    require_clean_worktree(context.workspace)

    staging = context.staging
    current = context.current
    publish_lock = context.workspace / context.loaded_config.config.paths.runs / ".publish.lock"
    with FileLock(publish_lock):
        _require_regular_directory(staging, label="sealed staging directory")
        if not context.manifest_path.is_file() or context.manifest_path.is_symlink():
            raise PublicationError("sealed staging manifest is missing")
        _load_bound_manifest(context)
        current.parent.mkdir(parents=True, exist_ok=True)
        if current.parent.is_symlink():
            raise PublicationError("publication parent must not be a symlink")
        had_current = _path_exists(current)
        if had_current:
            _require_regular_directory(current, label="current publication")

        transaction = context.receipts / "publication_transaction.json"
        atomic_write_json(
            transaction,
            {
                "schema_version": "hfmd-publication-transaction-v1",
                "run_id": context.run_id,
                "staging": staging.relative_to(context.workspace).as_posix(),
                "current": current.relative_to(context.workspace).as_posix(),
                "had_current": had_current,
                "state": "prepared",
            },
            mode=0o600,
        )
        try:
            if had_current:
                _exchange_directories(staging, current)
            else:
                staging.rename(current)
            _fsync_directory(current.parent)
            postflight = validate_manifest(
                current / "manifest.json",
                artifact_root=current,
                workspace=context.workspace,
            )
            if not postflight.ok:
                raise ManifestError("; ".join(postflight.issues))
        except BaseException as error:
            try:
                if had_current and _path_exists(current) and _path_exists(staging):
                    _exchange_directories(staging, current)
                elif not had_current and _path_exists(current) and not _path_exists(staging):
                    current.rename(staging)
                _fsync_directory(current.parent)
            except BaseException as recovery_error:
                error.add_note(
                    "Automatic publication recovery did not complete; preserve current "
                    f"and staging for manual audit: {recovery_error}"
                )
            raise

        if had_current:
            try:
                shutil.rmtree(staging)
                _fsync_directory(staging.parent)
            except BaseException as error:
                raise PublicationError(
                    "new publication is valid, but temporary old-current cleanup failed"
                ) from error

        manifest_path = current / "manifest.json"
        atomic_write_json(
            context.receipts / "published.json",
            {
                "schema_version": "hfmd-run-receipt-v1",
                "run_id": context.run_id,
                "current": current.relative_to(context.workspace).as_posix(),
                "manifest_sha256": sha256_file(manifest_path),
                "rollback_removed": True,
                "published_at": datetime.now(UTC),
            },
            mode=0o600,
        )
        transaction.unlink(missing_ok=True)
        _fsync_directory(transaction.parent)
        return current
