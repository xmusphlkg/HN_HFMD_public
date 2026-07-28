from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

import hfmd.core.environment as environment_module
import hfmd.core.publish as publish_module
import hfmd.core.run as run_module
from hfmd.core.config import EnvironmentConfig, ProfileName, load_config, write_config_snapshot
from hfmd.core.environment import (
    EnvironmentFailure,
    EnvironmentReport,
    EnvironmentState,
    GitState,
    check_environment,
    collect_environment,
    get_git_state,
    reproducible_environment,
    require_clean_worktree,
)
from hfmd.core.hashing import sha256_file
from hfmd.core.locking import FileLock, LockTimeout
from hfmd.core.manifest import (
    ManifestError,
    ManifestValidation,
    ParentManifestRef,
    RunManifest,
    assert_valid_manifest,
    build_manifest,
    create_input_record,
    parent_manifest_ref,
    validate_manifest,
    write_manifest,
)
from hfmd.core.publish import PublicationError, publish_run
from hfmd.core.run import RunContext, discover_workspace, make_run_id

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-lifecycle"
OTHER_RUN_ID = "20260717T120001Z-01234567-lifecycle"


def _environment(
    *,
    python: str = "3.13.5",
    r: str | None = "4.5.0",
    timezone: str = "UTC",
    locale: str = "C.UTF-8",
    threads: str = "1",
    locks: bool = True,
) -> EnvironmentState:
    return EnvironmentState(
        python_version=python,
        python_implementation="CPython",
        r_version=r,
        platform="test-platform",
        machine="x86_64",
        timezone=timezone,
        locale=locale,
        thread_environment={
            "OMP_NUM_THREADS": threads,
            "OPENBLAS_NUM_THREADS": threads,
            "MKL_NUM_THREADS": threads,
            "VECLIB_MAXIMUM_THREADS": threads,
            "NUMEXPR_NUM_THREADS": threads,
        },
        configured_threads=int(threads),
        random_seed=20260717,
        dependency_locks={
            "uv.lock": "a" * 64 if locks else None,
            "Script_r/renv.lock": "b" * 64 if locks else None,
        },
    )


def _git(*, dirty: bool = False) -> GitState:
    return GitState(
        commit="a" * 40,
        tree="b" * 40,
        dirty=dirty,
        changed_entry_count=int(dirty),
        status_sha256="c" * 64,
    )


def _write_candidate_manifest(
    context: RunContext,
    *,
    inputs: tuple[Any, ...] = (),
    parent: ParentManifestRef | None = None,
) -> Path:
    context.staging.mkdir(parents=True)
    write_config_snapshot(context.loaded_config, context.config_snapshot)
    payload = context.staging / "results" / "identity.txt"
    payload.parent.mkdir(parents=True)
    payload.write_text(f"candidate={context.run_id}\n", encoding="utf-8")
    manifest = build_manifest(
        artifact_root=context.staging,
        expected_paths=(context.config_snapshot, payload),
        run_id=context.run_id,
        stage="all",
        profile=ProfileName.RESTRICTED,
        formal=True,
        config_sha256=context.loaded_config.config_sha256,
        config_snapshot=context.config_snapshot,
        git=_git(),
        environment=_environment(),
        inputs=inputs,
        parent=parent,
    )
    return write_manifest(manifest, context.staging)


def _formal_context(tmp_path: Path, *, target: str = "all") -> RunContext:
    loaded = load_config(ROOT / "config" / "project.yaml", "restricted")
    return RunContext(
        workspace=tmp_path,
        loaded_config=loaded,
        run_id=RUN_ID,
        target=target,  # type: ignore[arg-type]
    )


def _patch_clean_publication(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(publish_module, "require_clean_worktree", lambda _: _git())


def _git_call(repository: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )


def test_git_state_distinguishes_clean_dirty_and_ignored_runtime_paths(tmp_path: Path) -> None:
    _git_call(tmp_path, "init", "--quiet")
    _git_call(tmp_path, "config", "user.email", "test@example.invalid")
    _git_call(tmp_path, "config", "user.name", "HFMD test")
    tracked = tmp_path / "tracked.txt"
    tracked.write_text("baseline\n", encoding="utf-8")
    _git_call(tmp_path, "add", "tracked.txt")
    _git_call(tmp_path, "commit", "--quiet", "-m", "baseline")

    clean = get_git_state(tmp_path)
    assert clean.dirty is False
    assert clean.changed_entry_count == 0
    assert len(clean.commit) == 40
    assert len(clean.tree) == 40

    runtime_file = tmp_path / ".runs" / "candidate" / "private.txt"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_text("ignored by provenance boundary\n", encoding="utf-8")
    assert get_git_state(tmp_path).dirty is False

    tracked.write_text("changed\n", encoding="utf-8")
    dirty = get_git_state(tmp_path)
    assert dirty.dirty is True
    assert dirty.changed_entry_count == 1
    with pytest.raises(EnvironmentFailure, match="clean Git worktree"):
        require_clean_worktree(tmp_path)


def test_git_state_fails_closed_outside_repository(tmp_path: Path) -> None:
    with pytest.raises(EnvironmentFailure, match="not a git repository"):
        get_git_state(tmp_path)


def test_r_version_detection_and_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        environment_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="R version 4.5.0 (2025-04-11)",
            stderr="",
        ),
    )
    assert environment_module._r_version() == "4.5.0"

    def missing(*args: Any, **kwargs: Any) -> Any:
        raise FileNotFoundError("R")

    monkeypatch.setattr(environment_module.subprocess, "run", missing)
    assert environment_module._r_version() is None


def test_collect_environment_hashes_locks_and_captures_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "uv.lock").write_text("python-lock\n", encoding="utf-8")
    renv = tmp_path / "Script_r" / "renv.lock"
    renv.parent.mkdir()
    renv.write_text("r-lock\n", encoding="utf-8")
    monkeypatch.setattr(environment_module, "_r_version", lambda: "4.5.0")
    monkeypatch.setattr(environment_module.platform, "python_version", lambda: "3.13.5")
    monkeypatch.setattr(environment_module.platform, "python_implementation", lambda: "CPython")
    monkeypatch.setattr(environment_module.platform, "platform", lambda: "test-platform")
    monkeypatch.setattr(environment_module.platform, "machine", lambda: "test-machine")
    monkeypatch.setenv("TZ", "UTC")
    for variable in (
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        monkeypatch.setenv(variable, "2")

    state = collect_environment(tmp_path, random_seed=7, threads=2)
    assert state.python_version == "3.13.5"
    assert state.r_version == "4.5.0"
    assert state.machine == "test-machine"
    assert state.timezone == "UTC"
    assert state.random_seed == 7
    assert set(state.thread_environment.values()) == {"2"}
    assert state.dependency_locks == {
        "uv.lock": sha256_file(tmp_path / "uv.lock"),
        "Script_r/renv.lock": sha256_file(renv),
    }


def test_environment_contract_warns_for_development_and_fails_formal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = EnvironmentConfig()
    bad = _environment(
        python="0.0.0",
        r=None,
        timezone="Mars/Olympus",
        locale="not-the-locale",
        threads="3",
        locks=False,
    )
    monkeypatch.setattr(environment_module, "collect_environment", lambda *args, **kwargs: bad)

    development = check_environment(expected, tmp_path, random_seed=1, threads=1, formal=False)
    assert development.ok is True
    assert development.messages
    assert {message.level for message in development.messages} == {"warning"}
    assert {
        "python_version",
        "r_version",
        "timezone",
        "locale",
        "dependency_lock",
        "blas_threads",
    } <= {message.code for message in development.messages}

    formal = check_environment(expected, tmp_path, random_seed=1, threads=1, formal=True)
    assert formal.ok is False
    assert {message.level for message in formal.messages} == {"error"}

    monkeypatch.setattr(
        environment_module, "collect_environment", lambda *args, **kwargs: _environment()
    )
    assert check_environment(expected, tmp_path, random_seed=1, threads=1, formal=True).ok


def test_reproducible_environment_sets_and_restores_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variables = (
        "TZ",
        "LC_ALL",
        "LANG",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "MKL_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    )
    for variable in variables:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("LANG", "original-locale")
    random.seed(991)
    original_random_state = random.getstate()

    with reproducible_environment(
        threads=3,
        timezone_name="UTC",
        locale_name="C.UTF-8",
        seed=17,
    ):
        assert os.environ["TZ"] == "UTC"
        assert os.environ["LANG"] == "C.UTF-8"
        assert {os.environ[name] for name in variables[3:]} == {"3"}
        assert random.random() == random.Random(17).random()

    assert os.environ.get("TZ") is None
    assert os.environ["LANG"] == "original-locale"
    assert random.getstate() == original_random_state


def test_file_lock_metadata_double_acquire_release_and_hardlink_rejection(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        FileLock(tmp_path / "negative.lock", timeout=-1)
    with pytest.raises(ValueError, match="positive"):
        FileLock(tmp_path / "poll.lock", poll_interval=0)

    lock_path = tmp_path / "run.lock"
    lock = FileLock(lock_path, timeout=0)
    assert lock.acquired is False
    lock.acquire()
    assert lock.acquired is True
    metadata = json.loads(lock_path.read_text(encoding="utf-8"))
    assert metadata["pid"] == os.getpid()
    assert metadata["host"]
    with pytest.raises(RuntimeError, match="already acquired"):
        lock.acquire()
    lock.release()
    lock.release()
    assert lock.acquired is False

    with FileLock(lock_path, timeout=0), pytest.raises(LockTimeout):
        FileLock(lock_path, timeout=0).acquire()
    assert not FileLock(lock_path, timeout=0).acquire().release()

    hardlink = tmp_path / "hardlink.lock"
    os.link(lock_path, hardlink)
    with pytest.raises(RuntimeError, match="single-link regular file"):
        FileLock(hardlink, timeout=0).acquire()


def test_manifest_verifies_external_inputs_and_reports_hash_mismatch(tmp_path: Path) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    snapshot = root / "config" / "config.snapshot.json"
    write_config_snapshot(loaded, snapshot)
    artifact = root / "result.csv"
    artifact.write_text("value\n10\n", encoding="utf-8")
    source = tmp_path / "inputs" / "source.csv"
    source.parent.mkdir()
    source.write_text("source\n10\n", encoding="utf-8")
    input_record = create_input_record(
        tmp_path,
        source,
        input_id="source",
        classification="synthetic",
    )
    manifest = build_manifest(
        artifact_root=root,
        expected_paths=(snapshot, artifact),
        run_id=RUN_ID,
        stage="analysis",
        profile=ProfileName.CI,
        formal=False,
        config_sha256=loaded.config_sha256,
        config_snapshot=snapshot,
        git=_git(),
        environment=_environment(),
        inputs=(input_record,),
    )
    manifest_path = write_manifest(manifest, root)
    assert assert_valid_manifest(manifest_path, artifact_root=root, workspace=tmp_path) == manifest

    source.write_text("source\n11\n", encoding="utf-8")
    report = validate_manifest(manifest_path, artifact_root=root, workspace=tmp_path)
    assert not report.ok
    assert "input hash or size mismatch" in ";".join(report.issues)
    no_workspace = validate_manifest(manifest_path, artifact_root=root, workspace=None)
    assert "cannot verify inputs without a workspace root" in ";".join(no_workspace.issues)
    with pytest.raises(ManifestError, match="input hash or size mismatch"):
        assert_valid_manifest(manifest_path, artifact_root=root, workspace=tmp_path)


def test_manifest_parent_chain_detects_hash_identity_and_cross_run_errors(tmp_path: Path) -> None:
    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    parent_root = tmp_path / "parent"
    parent_root.mkdir()
    parent_snapshot = parent_root / "config.snapshot.json"
    write_config_snapshot(loaded, parent_snapshot)
    parent = build_manifest(
        artifact_root=parent_root,
        expected_paths=(parent_snapshot,),
        run_id=RUN_ID,
        stage="data",
        profile=ProfileName.CI,
        formal=False,
        config_sha256=loaded.config_sha256,
        config_snapshot=parent_snapshot,
        git=_git(),
        environment=_environment(),
    )
    parent_path = write_manifest(parent, parent_root)
    parent_ref = parent_manifest_ref(tmp_path, parent_path)

    child_root = tmp_path / "child"
    child_root.mkdir()
    child_snapshot = child_root / "config.snapshot.json"
    write_config_snapshot(loaded, child_snapshot)
    child = build_manifest(
        artifact_root=child_root,
        expected_paths=(child_snapshot,),
        run_id=RUN_ID,
        stage="figures",
        profile=ProfileName.CI,
        formal=False,
        config_sha256=loaded.config_sha256,
        config_snapshot=child_snapshot,
        git=_git(),
        environment=_environment(),
        parent=parent_ref,
    )
    child_path = write_manifest(child, child_root)
    assert validate_manifest(child_path, artifact_root=child_root, workspace=tmp_path).ok

    parent_path.write_text(parent_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    tampered = validate_manifest(child_path, artifact_root=child_root, workspace=tmp_path)
    assert "parent manifest hash mismatch" in ";".join(tampered.issues)

    bad_ref = ParentManifestRef(
        manifest_path=parent_path.relative_to(tmp_path).as_posix(),
        manifest_sha256=sha256_file(parent_path),
        run_id=OTHER_RUN_ID,
        stage="analysis",
    )
    bad_child = child.model_copy(update={"parent": bad_ref})
    write_manifest(bad_child, child_root)
    identity = validate_manifest(child_path, artifact_root=child_root, workspace=tmp_path)
    joined = ";".join(identity.issues)
    assert "parent manifest identity mismatch" in joined

    other_parent = parent.model_copy(update={"run_id": OTHER_RUN_ID})
    write_manifest(other_parent, parent_root)
    cross_run_ref = ParentManifestRef(
        manifest_path=parent_path.relative_to(tmp_path).as_posix(),
        manifest_sha256=sha256_file(parent_path),
        run_id=OTHER_RUN_ID,
        stage="data",
    )
    write_manifest(child.model_copy(update={"parent": cross_run_ref}), child_root)
    cross_run = validate_manifest(child_path, artifact_root=child_root, workspace=tmp_path)
    assert "parent manifest belongs to a different run_id" in ";".join(cross_run.issues)


def test_manifest_rejects_unsafe_paths_and_handles_unparseable_or_missing_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationError, match="artifact-root relative"):
        RunManifest.model_validate(
            {
                "run_id": RUN_ID,
                "stage": "data",
                "profile": "ci",
                "formal": False,
                "created_at": "2026-07-17T12:00:00Z",
                "config_sha256": "a" * 64,
                "config_snapshot": "../snapshot.json",
                "git": _git().model_dump(mode="json"),
                "environment": _environment().model_dump(mode="json"),
                "artifacts": [],
                "expected_artifacts_sha256": "b" * 64,
            }
        )

    root = tmp_path / "candidate"
    root.mkdir()
    malformed = root / "manifest.json"
    malformed.write_text("not json\n", encoding="utf-8")
    report = validate_manifest(malformed, artifact_root=root, workspace=tmp_path)
    assert not report.ok
    assert "manifest cannot be parsed" in report.issues[0]

    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    snapshot = root / "config.snapshot.json"
    write_config_snapshot(loaded, snapshot)
    manifest = build_manifest(
        artifact_root=root,
        expected_paths=(snapshot,),
        run_id=RUN_ID,
        stage="data",
        profile=ProfileName.CI,
        formal=False,
        config_sha256="f" * 64,
        config_snapshot=snapshot,
        git=_git(),
        environment=_environment(),
        require_exact_preexisting_set=False,
    )
    write_manifest(manifest, root)
    mismatch = validate_manifest(malformed, artifact_root=root, workspace=tmp_path)
    assert "manifest and configuration snapshot hashes differ" in ";".join(mismatch.issues)
    snapshot.unlink()
    missing = validate_manifest(malformed, artifact_root=root, workspace=tmp_path)
    joined = ";".join(missing.issues)
    assert "missing artifacts" in joined
    assert "configuration snapshot is invalid" in joined


def test_run_context_prepare_seal_and_failure_receipts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    context = RunContext(tmp_path, loaded, RUN_ID, "data")
    assert context.run_root == tmp_path / ".runs" / RUN_ID
    assert context.current == tmp_path / "artifacts" / "current"
    context.prepare()
    started = json.loads((context.receipts / "started.json").read_text(encoding="utf-8"))
    assert started["run_id"] == RUN_ID
    assert started["config_sha256"] == loaded.config_sha256
    with pytest.raises(FileExistsError, match="non-empty staging"):
        context.prepare()

    result = context.staging / "result.csv"
    result.write_text("value\n10\n", encoding="utf-8")
    monkeypatch.setattr(run_module, "get_git_state", lambda _: _git(dirty=True))
    monkeypatch.setattr(
        run_module,
        "check_environment",
        lambda *args, **kwargs: EnvironmentReport(
            ok=True,
            state=_environment(),
            messages=(),
        ),
    )
    monkeypatch.setattr(run_module, "collect_environment", lambda *args, **kwargs: _environment())
    sealed = context.seal(expected_paths=(result,), metadata={"validated": True})
    assert sealed.git.dirty is True
    assert sealed.metadata == {"target": "data", "validated": True}
    assert (context.receipts / "manifest.json").read_bytes() == context.manifest_path.read_bytes()
    assert json.loads((context.receipts / "sealed.json").read_text(encoding="utf-8"))[
        "manifest_sha256"
    ] == sha256_file(context.manifest_path)
    with pytest.raises(FileExistsError, match="already been sealed"):
        context.seal(expected_paths=(result,))

    failure = context.record_failure(RuntimeError("model failed"))
    failure_payload = json.loads(failure.read_text(encoding="utf-8"))
    assert failure_payload["exception_type"] == "RuntimeError"
    assert failure_payload["message"] == "model failed"


def test_run_context_formal_seal_fails_for_dirty_environment_and_missing_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    context.prepare()
    monkeypatch.setattr(
        run_module,
        "require_clean_worktree",
        lambda _: (_ for _ in ()).throw(EnvironmentFailure("dirty formal tree")),
    )
    with pytest.raises(EnvironmentFailure, match="dirty formal tree"):
        context.seal(expected_paths=())

    monkeypatch.setattr(run_module, "require_clean_worktree", lambda _: _git())
    monkeypatch.setattr(
        run_module,
        "check_environment",
        lambda *args, **kwargs: EnvironmentReport(
            ok=False,
            state=_environment(),
            messages=(
                environment_module.CheckMessage(
                    level="error",
                    code="dependency_lock",
                    message="missing dependency lock",
                ),
            ),
        ),
    )
    with pytest.raises(EnvironmentFailure, match="missing dependency lock"):
        context.seal(expected_paths=())

    monkeypatch.setattr(
        run_module,
        "check_environment",
        lambda *args, **kwargs: EnvironmentReport(ok=True, state=_environment(), messages=()),
    )
    monkeypatch.setattr(run_module, "collect_environment", lambda *args, **kwargs: _environment())
    with pytest.raises(RuntimeError, match="missing configured artifacts"):
        context.seal(expected_paths=())


def test_concurrent_prepare_serializes_and_never_reuses_staging(tmp_path: Path) -> None:
    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    contexts = [RunContext(tmp_path, loaded, RUN_ID, "data") for _ in range(2)]

    def prepare(context: RunContext) -> str:
        try:
            context.prepare()
        except FileExistsError:
            return "refused"
        return "prepared"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(prepare, contexts))
    assert sorted(outcomes) == ["prepared", "refused"]
    assert contexts[0].config_snapshot.is_file()
    started = json.loads((contexts[0].receipts / "started.json").read_text(encoding="utf-8"))
    assert started["run_id"] == RUN_ID


def test_workspace_discovery_run_id_and_configured_artifact_routing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    shutil.copytree(ROOT / "config", workspace / "config")
    shutil.copy2(ROOT / "pyproject.toml", workspace / "pyproject.toml")
    nested = workspace / "nested" / "deeper"
    nested.mkdir(parents=True)
    assert discover_workspace(nested) == workspace
    marker = nested / "marker.txt"
    marker.write_text("x", encoding="utf-8")
    assert discover_workspace(marker) == workspace
    with pytest.raises(FileNotFoundError, match="Could not locate"):
        discover_workspace(tmp_path / "outside")
    with pytest.raises(ValueError, match="no usable characters"):
        make_run_id("a" * 64, label="!!!")

    loaded = load_config(ROOT / "config" / "project.yaml", "ci")
    all_context = RunContext(tmp_path, loaded, RUN_ID, "all")
    analysis_context = RunContext(tmp_path, loaded, RUN_ID, "analysis")
    public_context = RunContext(tmp_path, loaded, RUN_ID, "public_export")
    assert (
        "figures/main/figure1_ecological_atlas.pdf" in all_context.expected_configured_artifacts()
    )
    assert all("figures/" not in path for path in analysis_context.expected_configured_artifacts())
    assert public_context.expected_configured_artifacts() == ()


def test_publish_new_formal_candidate_and_write_bound_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    candidate_manifest = _write_candidate_manifest(context)
    candidate_digest = sha256_file(candidate_manifest)
    _patch_clean_publication(monkeypatch)

    published = publish_run(context)
    assert published == context.current
    assert not context.staging.exists()
    assert (published / "results" / "identity.txt").read_text(encoding="utf-8") == (
        f"candidate={RUN_ID}\n"
    )
    receipt = json.loads((context.receipts / "published.json").read_text(encoding="utf-8"))
    assert receipt["manifest_sha256"] == candidate_digest
    assert receipt["rollback_removed"] is True
    assert not (context.receipts / "publication_transaction.json").exists()


def test_publish_atomically_replaces_existing_current_and_removes_old_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    context.current.mkdir(parents=True)
    (context.current / "old-only.txt").write_text("old publication\n", encoding="utf-8")
    _patch_clean_publication(monkeypatch)

    publish_run(context)
    assert (context.current / "manifest.json").is_file()
    assert not (context.current / "old-only.txt").exists()
    assert not context.staging.exists()


def test_publish_postflight_failure_rolls_back_existing_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    context.current.mkdir(parents=True)
    old = context.current / "old-only.txt"
    old.write_text("trusted old publication\n", encoding="utf-8")
    _patch_clean_publication(monkeypatch)
    real_validate = publish_module.validate_manifest
    calls = 0

    def fail_postflight(*args: Any, **kwargs: Any) -> ManifestValidation:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_validate(*args, **kwargs)
        return ManifestValidation(
            ok=False,
            manifest_path=Path(args[0]).as_posix(),
            manifest_sha256=None,
            issues=("forced postflight failure",),
        )

    monkeypatch.setattr(publish_module, "validate_manifest", fail_postflight)
    with pytest.raises(ManifestError, match="forced postflight failure"):
        publish_run(context)

    assert old.read_text(encoding="utf-8") == "trusted old publication\n"
    assert context.manifest_path.is_file()
    assert (context.receipts / "publication_transaction.json").is_file()
    assert not (context.receipts / "published.json").exists()


def test_publish_postflight_failure_without_current_restores_candidate_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    _patch_clean_publication(monkeypatch)
    real_validate = publish_module.validate_manifest
    calls = 0

    def fail_postflight(*args: Any, **kwargs: Any) -> ManifestValidation:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_validate(*args, **kwargs)
        return ManifestValidation(
            ok=False,
            manifest_path=Path(args[0]).as_posix(),
            manifest_sha256=None,
            issues=("forced postflight failure",),
        )

    monkeypatch.setattr(publish_module, "validate_manifest", fail_postflight)
    with pytest.raises(ManifestError, match="forced postflight failure"):
        publish_run(context)
    assert not context.current.exists()
    assert context.manifest_path.is_file()


def test_publish_rejects_dirty_tree_wrong_target_and_config_or_input_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    monkeypatch.setattr(
        publish_module,
        "require_clean_worktree",
        lambda _: (_ for _ in ()).throw(EnvironmentFailure("dirty worktree")),
    )
    with pytest.raises(EnvironmentFailure, match="dirty worktree"):
        publish_run(context)

    _patch_clean_publication(monkeypatch)
    wrong_target = RunContext(
        workspace=context.workspace,
        loaded_config=context.loaded_config,
        run_id=context.run_id,
        target="figures",
    )
    with pytest.raises(PublicationError, match="target all"):
        publish_run(wrong_target)

    wrong_config = RunContext(
        workspace=context.workspace,
        loaded_config=replace(context.loaded_config, config_sha256="f" * 64),
        run_id=context.run_id,
        target="all",
    )
    with pytest.raises(PublicationError, match="config_sha256"):
        publish_run(wrong_config)

    second = _formal_context(tmp_path / "input-mismatch")
    source = second.workspace / "AnalysisData" / "restricted" / "input.csv"
    source.parent.mkdir(parents=True)
    source.write_text("value\n10\n", encoding="utf-8")
    record = create_input_record(
        second.workspace,
        source,
        input_id="restricted-source",
        classification="restricted",
    )
    _write_candidate_manifest(second, inputs=(record,))
    source.write_text("value\n11\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="input hash or size mismatch"):
        publish_run(second)


@pytest.mark.parametrize("current_kind", ["file", "symlink"])
def test_publish_refuses_non_directory_current(
    current_kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    context.current.parent.mkdir(parents=True)
    if current_kind == "file":
        context.current.write_text("unsafe\n", encoding="utf-8")
    else:
        target = tmp_path / "elsewhere"
        target.mkdir()
        context.current.symlink_to(target, target_is_directory=True)
    _patch_clean_publication(monkeypatch)

    with pytest.raises(PublicationError, match="not a regular directory"):
        publish_run(context)


def test_publish_cleanup_failure_keeps_valid_new_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = _formal_context(tmp_path)
    _write_candidate_manifest(context)
    context.current.mkdir(parents=True)
    (context.current / "old-only.txt").write_text("old\n", encoding="utf-8")
    _patch_clean_publication(monkeypatch)
    monkeypatch.setattr(
        publish_module.shutil,
        "rmtree",
        lambda _: (_ for _ in ()).throw(OSError("cleanup denied")),
    )

    with pytest.raises(PublicationError, match="cleanup failed"):
        publish_run(context)
    assert (context.current / "manifest.json").is_file()
    assert not (context.current / "old-only.txt").exists()
    assert (context.staging / "old-only.txt").is_file()
