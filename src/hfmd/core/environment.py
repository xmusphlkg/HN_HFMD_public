"""Capture and enforce the reproducible runtime boundary."""

from __future__ import annotations

import contextlib
import locale
import os
import platform
import random
import re
import subprocess
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from hfmd.core.config import EnvironmentConfig
from hfmd.core.hashing import sha256_file, sha256_object


class EnvironmentFailure(RuntimeError):
    """Raised when a formal run does not satisfy its runtime contract."""


class GitState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    tree: str = Field(pattern=r"^[0-9a-f]{40}$")
    dirty: bool
    changed_entry_count: int = Field(ge=0)
    status_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EnvironmentState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    python_version: str
    python_implementation: str
    r_version: str | None
    platform: str
    machine: str
    timezone: str
    locale: str
    thread_environment: dict[str, str]
    configured_threads: int = Field(ge=1)
    random_seed: int = Field(ge=0)
    dependency_locks: dict[str, str | None]


class CheckMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    level: Literal["error", "warning"]
    code: str
    message: str


class EnvironmentReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ok: bool
    state: EnvironmentState
    messages: tuple[CheckMessage, ...]


def _run_git(workspace: Path, arguments: Sequence[str]) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=workspace,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        raise EnvironmentFailure(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def get_git_state(
    workspace: str | Path,
    *,
    exclude_paths: Sequence[str] = (".runs", "artifacts", "dist"),
) -> GitState:
    """Capture commit/tree and a non-leaking digest of worktree changes."""

    root = Path(workspace).resolve()
    commit = _run_git(root, ["rev-parse", "HEAD"])
    tree = _run_git(root, ["rev-parse", "HEAD^{tree}"])
    pathspecs = [".", *(f":(exclude){path}/**" for path in exclude_paths)]
    status = _run_git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all", "--", *pathspecs],
    )
    entries = tuple(line for line in status.splitlines() if line.strip())
    return GitState(
        commit=commit,
        tree=tree,
        dirty=bool(entries),
        changed_entry_count=len(entries),
        status_sha256=sha256_object(entries),
    )


def require_clean_worktree(workspace: str | Path) -> GitState:
    """Fail closed unless source-controlled state is clean."""

    state = get_git_state(workspace)
    if state.dirty:
        raise EnvironmentFailure(
            "Formal publication requires a clean Git worktree "
            f"({state.changed_entry_count} changed entries; status digest {state.status_sha256})"
        )
    return state


def _r_version() -> str | None:
    try:
        result = subprocess.run(
            ["R", "--version"], check=False, capture_output=True, text=True, encoding="utf-8"
        )
    except FileNotFoundError:
        return None
    text = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"R version\s+([0-9]+\.[0-9]+\.[0-9]+)", text)
    return match.group(1) if match else None


def _timezone_name() -> str:
    configured = os.environ.get("TZ")
    if configured:
        return configured
    if time.timezone == 0 and (not time.daylight or time.altzone == 0):
        return "UTC"
    return time.tzname[0]


def collect_environment(
    workspace: str | Path,
    *,
    random_seed: int,
    threads: int,
) -> EnvironmentState:
    """Collect runtime versions and submitted lock-file digests."""

    root = Path(workspace).resolve()
    lock_paths = {
        "uv.lock": root / "uv.lock",
        "Script_r/renv.lock": root / "Script_r" / "renv.lock",
    }
    locks = {
        name: sha256_file(path) if path.is_file() else None for name, path in lock_paths.items()
    }
    thread_variables = (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    return EnvironmentState(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        r_version=_r_version(),
        platform=platform.platform(),
        machine=platform.machine(),
        timezone=_timezone_name(),
        locale=locale.setlocale(locale.LC_ALL, None),
        thread_environment={name: os.environ.get(name, "") for name in thread_variables},
        configured_threads=threads,
        random_seed=random_seed,
        dependency_locks=locks,
    )


def check_environment(
    expected: EnvironmentConfig,
    workspace: str | Path,
    *,
    random_seed: int,
    threads: int,
    formal: bool = False,
) -> EnvironmentReport:
    """Compare the active runtime with the declared reproducibility contract."""

    state = collect_environment(workspace, random_seed=random_seed, threads=threads)
    messages: list[CheckMessage] = []

    def add(code: str, message: str, *, hard: bool = True) -> None:
        messages.append(
            CheckMessage(
                level="error" if formal and hard else "warning", code=code, message=message
            )
        )

    if state.python_version != expected.python:
        add("python_version", f"expected Python {expected.python}, observed {state.python_version}")
    if state.r_version != expected.r:
        add("r_version", f"expected R {expected.r}, observed {state.r_version or 'not found'}")
    if state.timezone != expected.timezone:
        add("timezone", f"expected timezone {expected.timezone}, observed {state.timezone}")
    if expected.locale not in state.locale:
        add("locale", f"expected locale containing {expected.locale}, observed {state.locale}")
    for name, digest in state.dependency_locks.items():
        if digest is None:
            add("dependency_lock", f"missing required dependency lock: {name}")
    expected_threads = str(expected.blas_threads)
    for name, observed in state.thread_environment.items():
        if observed != expected_threads:
            add(
                "blas_threads",
                f"expected {name}={expected_threads}, observed {observed or 'unset'}",
            )
    if formal and any(message.level == "error" for message in messages):
        return EnvironmentReport(ok=False, state=state, messages=tuple(messages))
    return EnvironmentReport(ok=True, state=state, messages=tuple(messages))


@contextlib.contextmanager
def reproducible_environment(
    *,
    threads: int = 1,
    timezone_name: str = "UTC",
    locale_name: str = "C.UTF-8",
    seed: int | None = None,
) -> Iterator[None]:
    """Temporarily fix process environment inherited by Python/R children."""

    names = (
        "TZ",
        "LC_ALL",
        "LANG",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    original = {name: os.environ.get(name) for name in names}
    random_state = random.getstate()
    try:
        os.environ.update(
            {
                "TZ": timezone_name,
                "LC_ALL": locale_name,
                "LANG": locale_name,
                "OMP_NUM_THREADS": str(threads),
                "OPENBLAS_NUM_THREADS": str(threads),
                "MKL_NUM_THREADS": str(threads),
                "VECLIB_MAXIMUM_THREADS": str(threads),
                "NUMEXPR_NUM_THREADS": str(threads),
            }
        )
        if hasattr(time, "tzset"):
            time.tzset()
        if seed is not None:
            random.seed(seed)
        yield
    finally:
        random.setstate(random_state)
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        if hasattr(time, "tzset"):
            time.tzset()
