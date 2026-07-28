from __future__ import annotations

import json
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from hfmd.core.config import (
    ConfigurationError,
    ProfileName,
    load_config,
    read_config_snapshot,
    write_config_snapshot,
)
from hfmd.core.environment import EnvironmentState, GitState
from hfmd.core.hashing import (
    HashingError,
    atomic_write_bytes,
    canonical_json_bytes,
    iter_regular_files,
    safe_relative_path,
    sha256_file,
    sha256_object,
)
from hfmd.core.locking import FileLock, LockTimeout
from hfmd.core.manifest import (
    ManifestError,
    RunManifest,
    build_manifest,
    validate_manifest,
    write_manifest,
)
from hfmd.core.publish import PublicationError, _exchange_directories, publish_run
from hfmd.core.receipts import (
    build_stage_receipt,
    receipt_file,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.core.run import RunContext, make_run_id

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-test"


def _environment() -> EnvironmentState:
    return EnvironmentState(
        python_version="3.13.5",
        python_implementation="CPython",
        r_version="4.5.0",
        platform="test",
        machine="x86_64",
        timezone="UTC",
        locale="C.UTF-8",
        thread_environment={
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "VECLIB_MAXIMUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        },
        configured_threads=1,
        random_seed=1,
        dependency_locks={"uv.lock": "a" * 64, "Script_r/renv.lock": "b" * 64},
    )


def _git(*, dirty: bool = False) -> GitState:
    return GitState(
        commit="a" * 40,
        tree="b" * 40,
        dirty=dirty,
        changed_entry_count=int(dirty),
        status_sha256="c" * 64,
    )


def _snapshot(tmp_path: Path, profile: str = "ci") -> tuple[Path, object]:
    loaded = load_config(ROOT / "config" / "project.yaml", profile)
    path = tmp_path / "config" / "config.snapshot.json"
    write_config_snapshot(loaded, path)
    return path, loaded


def test_contract_sources_participate_in_config_hash(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    shutil.copytree(ROOT / "config", config_dir)
    before = load_config(config_dir / "project.yaml", "ci")
    visual = config_dir / "visual_contract.yaml"
    visual.write_text(visual.read_text(encoding="utf-8") + "\n# audited change\n", encoding="utf-8")
    after = load_config(config_dir / "project.yaml", "ci")
    assert before.config_sha256 != after.config_sha256
    assert (
        before.source_hashes["visual_contract.yaml"] != after.source_hashes["visual_contract.yaml"]
    )
    assert set(after.resources) == {"model_registry", "science_gates", "visual_contract"}


def test_snapshot_is_deterministic_and_detects_resource_tampering(tmp_path: Path) -> None:
    path, loaded = _snapshot(tmp_path)
    first = path.read_bytes()
    write_config_snapshot(loaded, path)
    assert path.read_bytes() == first
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["resources"]["science_gates"]["schema_version"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigurationError, match="hash mismatch"):
        read_config_snapshot(path)


def test_run_ids_are_stable_and_traversal_is_rejected() -> None:
    instant = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)
    assert make_run_id("a" * 64, label="CI smoke", now=instant) == (
        "20260717T120000Z-aaaaaaaa-ci-smoke"
    )
    with pytest.raises(ValueError, match="invalid run_id"):
        RunContext.create(workspace=ROOT, profile="ci", run_id="../../escape")


def test_canonical_hashing_and_atomic_permissions(tmp_path: Path) -> None:
    left = {"b": {3, 1, 2}, "a": -0.0}
    right = {"a": 0.0, "b": {2, 3, 1}}
    assert canonical_json_bytes(left) == canonical_json_bytes(right)
    assert sha256_object(left) == sha256_object(right)
    with pytest.raises(HashingError, match="NaN"):
        canonical_json_bytes({"value": float("nan")})
    target = tmp_path / "private" / "value.bin"
    atomic_write_bytes(target, b"abc", mode=0o600)
    assert target.read_bytes() == b"abc"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(target.parent.glob("*.tmp"))


def test_hashing_rejects_symlinks_and_paths_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    file_path = root / "value.txt"
    file_path.write_text("value", encoding="utf-8")
    link = root / "link.txt"
    link.symlink_to(file_path)
    with pytest.raises(HashingError, match="symlink"):
        sha256_file(link)
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    with pytest.raises(HashingError, match="escapes"):
        safe_relative_path(outside, root)
    with pytest.raises(HashingError, match="Symlink"):
        tuple(iter_regular_files(root))


def test_file_lock_times_out_and_rejects_symlink(tmp_path: Path) -> None:
    lock_path = tmp_path / "locks" / "run.lock"
    with FileLock(lock_path, timeout=0.1), pytest.raises(LockTimeout):
        FileLock(lock_path, timeout=0, poll_interval=0.01).acquire()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
    unsafe = tmp_path / "unsafe.lock"
    unsafe.symlink_to(lock_path)
    with pytest.raises(OSError):
        FileLock(unsafe, timeout=0).acquire()


def test_manifest_exact_set_and_tamper_detection(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    snapshot, loaded = _snapshot(root)
    artifact = root / "results" / "summary.csv"
    artifact.parent.mkdir()
    artifact.write_text("run_id,value\nexample,10\n", encoding="utf-8")
    manifest = build_manifest(
        artifact_root=root,
        expected_paths=(snapshot, artifact),
        run_id=RUN_ID,
        stage="data",
        profile=ProfileName.CI,
        formal=False,
        config_sha256=loaded.config_sha256,
        config_snapshot=snapshot,
        git=_git(),
        environment=_environment(),
    )
    path = write_manifest(manifest, root)
    assert validate_manifest(path, artifact_root=root, workspace=tmp_path).ok
    artifact.write_text("run_id,value\nexample,11\n", encoding="utf-8")
    report = validate_manifest(path, artifact_root=root, workspace=tmp_path)
    assert not report.ok
    assert "artifact hash mismatch" in ";".join(report.issues)
    artifact.write_text("run_id,value\nexample,10\n", encoding="utf-8")
    (root / "extra.txt").write_text("stale", encoding="utf-8")
    report = validate_manifest(path, artifact_root=root, workspace=tmp_path)
    assert not report.ok
    assert "unexpected artifacts" in ";".join(report.issues)


def test_manifest_refuses_preexisting_extra_and_invalid_formal_profile(tmp_path: Path) -> None:
    root = tmp_path / "staging"
    root.mkdir()
    snapshot, loaded = _snapshot(root)
    (root / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ManifestError, match="artifact set mismatch"):
        build_manifest(
            artifact_root=root,
            expected_paths=(snapshot,),
            run_id=RUN_ID,
            stage="data",
            profile=ProfileName.CI,
            formal=False,
            config_sha256=loaded.config_sha256,
            config_snapshot=snapshot,
            git=_git(),
            environment=_environment(),
        )
    (root / "extra.txt").unlink()
    valid = build_manifest(
        artifact_root=root,
        expected_paths=(snapshot,),
        run_id=RUN_ID,
        stage="data",
        profile=ProfileName.CI,
        formal=False,
        config_sha256=loaded.config_sha256,
        config_snapshot=snapshot,
        git=_git(),
        environment=_environment(),
    )
    payload = valid.model_dump(mode="python")
    payload["formal"] = True
    with pytest.raises(ValidationError, match="restricted profile"):
        RunManifest.model_validate(payload)


def test_stage_receipts_bind_parent_outputs_and_exact_sets(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot, _ = _snapshot(run_root)
    environment = build_stage_receipt(
        run_root=run_root,
        workspace=tmp_path,
        run_id=RUN_ID,
        stage="environment",
        config_snapshot=snapshot,
        output_paths=(),
    )
    environment_path = run_root / "receipts" / "environment.json"
    write_stage_receipt(environment, environment_path)
    output_dir = run_root / "data" / "synthetic"
    output_dir.mkdir(parents=True)
    output = output_dir / "table.csv"
    output.write_text("synthetic_region,cases\nAster,10\n", encoding="utf-8")
    data = build_stage_receipt(
        run_root=run_root,
        workspace=tmp_path,
        run_id=RUN_ID,
        stage="data",
        config_snapshot=snapshot,
        output_paths=(output,),
        output_classification="synthetic",
        parent_receipts=(environment_path,),
        exact_output_roots=(output_dir,),
    )
    data_path = run_root / "receipts" / "data.json"
    write_stage_receipt(data, data_path)
    assert validate_stage_receipt(data_path, run_root=run_root, workspace=tmp_path).ok
    (output_dir / "stale.csv").write_text("x\n", encoding="utf-8")
    report = validate_stage_receipt(data_path, run_root=run_root, workspace=tmp_path)
    assert not report.ok
    assert "exact output set mismatch" in ";".join(report.issues)


def test_public_profile_receipt_rejects_restricted_workspace_input(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    snapshot, _ = _snapshot(run_root)
    restricted = tmp_path / "AnalysisData" / "restricted" / "table.csv"
    restricted.parent.mkdir(parents=True)
    restricted.write_text("count\n10\n", encoding="utf-8")
    record = receipt_file(
        restricted,
        scope="workspace",
        run_root=run_root,
        workspace=tmp_path,
        classification="controlled_derived",
    )
    with pytest.raises(ValidationError, match="restricted-data inputs"):
        build_stage_receipt(
            run_root=run_root,
            workspace=tmp_path,
            run_id=RUN_ID,
            stage="data",
            config_snapshot=snapshot,
            output_paths=(),
            input_files=(record,),
        )


def test_atomic_directory_exchange_and_nonformal_publish_refusal(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "identity").write_text("first", encoding="utf-8")
    (second / "identity").write_text("second", encoding="utf-8")
    _exchange_directories(first, second)
    assert (first / "identity").read_text(encoding="utf-8") == "second"
    assert (second / "identity").read_text(encoding="utf-8") == "first"

    loaded = load_config(ROOT / "config" / "project.yaml", "synthetic")
    context = RunContext(
        workspace=tmp_path,
        loaded_config=loaded,
        run_id=RUN_ID,
        target="all",
    )
    with pytest.raises(PublicationError, match="formal restricted"):
        publish_run(context)
