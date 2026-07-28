"""Deterministic hashing and atomic file-writing utilities."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

CHUNK_SIZE = 1024 * 1024


class HashingError(ValueError):
    """Raised when an object cannot be represented deterministically."""


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 digest for *data*."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, *, reject_symlink: bool = True) -> str:
    """Stream a file into SHA-256, rejecting symlinks by default."""

    source = Path(path)
    if reject_symlink and source.is_symlink():
        raise HashingError(f"Refusing to hash symlink: {source}")
    if not source.is_file():
        raise FileNotFoundError(source)
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalise(value: Any) -> Any:
    """Convert supported values to a canonical JSON-compatible form."""

    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python", exclude_none=False)
    elif dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise HashingError("NaN and infinite floats are forbidden in canonical JSON")
        return 0.0 if value == 0.0 else value
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise HashingError("Naive datetimes are forbidden in canonical JSON")
        utc_value = value.astimezone(UTC)
        return utc_value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, Enum):
        return _normalise(value.value)
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise HashingError("Canonical JSON mappings must have string keys")
        return {key: _normalise(value[key]) for key in sorted(value)}
    if isinstance(value, (set, frozenset)):
        normalised = [_normalise(item) for item in value]
        return sorted(normalised, key=lambda item: canonical_json_bytes(item))
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    raise HashingError(f"Unsupported canonical JSON type: {type(value).__name__}")


def canonical_json_bytes(value: Any) -> bytes:
    """Serialise *value* into deterministic UTF-8 JSON bytes."""

    return (
        json.dumps(
            _normalise(value),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def sha256_object(value: Any) -> str:
    """Hash an object after canonical JSON serialisation."""

    return sha256_bytes(canonical_json_bytes(value))


def safe_relative_path(path: str | Path, root: str | Path) -> str:
    """Return a POSIX path below *root*, rejecting traversal and symlinks."""

    base = Path(root).resolve(strict=True)
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = base / candidate
    if candidate.is_symlink():
        raise HashingError(f"Symlink is not an auditable artifact: {candidate}")
    resolved = candidate.resolve(strict=True)
    try:
        relative = resolved.relative_to(base)
    except ValueError as exc:
        raise HashingError(f"Path escapes artifact root: {path}") from exc
    if relative == Path("."):
        raise HashingError("Artifact path must name a file below the root")
    return relative.as_posix()


def iter_regular_files(root: str | Path) -> Iterable[Path]:
    """Yield regular non-symlink files below *root* in lexical order."""

    base = Path(root)
    if not base.is_dir():
        raise NotADirectoryError(base)
    for path in sorted(base.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise HashingError(f"Symlink is not allowed in an artifact tree: {path}")
        if path.is_file():
            yield path


def atomic_write_bytes(path: str | Path, data: bytes, *, mode: int = 0o644) -> None:
    """Write bytes durably and atomically within the destination directory."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, destination)
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def atomic_write_json(path: str | Path, value: Any, *, mode: int = 0o644) -> None:
    """Atomically write canonical JSON."""

    atomic_write_bytes(path, canonical_json_bytes(value), mode=mode)
