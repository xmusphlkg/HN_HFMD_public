from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from hfmd.core.config import load_config, write_config_snapshot
from hfmd.core.receipts import StageReceipt
from hfmd.data import preflight

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "20260717T120000Z-01234567-preflight"
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)


def _valid_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pandoc: bool = True
) -> Path:
    workspace = tmp_path / "workspace"
    (workspace / "Script_r").mkdir(parents=True)
    (workspace / "uv.lock").write_text("lock\n", encoding="utf-8")
    (workspace / "Script_r" / "renv.lock").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(preflight.sys, "version_info", (3, 13, 5))
    monkeypatch.setattr(preflight, "_r_version", lambda: "4.5.0")

    def command_output(arguments: list[str]) -> str | None:
        return {
            "uv": "uv 0.11.29",
            "fc-match": "DejaVu Sans",
            "pandoc": "pandoc 3.7.0\nFeatures: test" if pandoc else None,
        }[arguments[0]]

    monkeypatch.setattr(preflight, "_command_output", command_output)
    monkeypatch.setattr(preflight.locale, "getlocale", lambda _category: ("C", "UTF-8"))
    monkeypatch.setenv("TZ", "UTC")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    for name in THREAD_VARIABLES:
        monkeypatch.setenv(name, "1")
    return workspace


def test_command_output_handles_missing_failed_and_successful_commands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda command: None)
    assert preflight._command_output(["missing", "--version"]) is None

    monkeypatch.setattr(preflight.shutil, "which", lambda command: f"/bin/{command}")
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 1, "stdout": "ignored"})(),
    )
    assert preflight._command_output(["tool", "--version"]) is None

    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *_args, **_kwargs: type("Result", (), {"returncode": 0, "stdout": " ok \n"})(),
    )
    assert preflight._command_output(["tool", "--version"]) == "ok"


def test_r_version_handles_absence_and_reads_version(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda _command: None)
    assert preflight._r_version() is None

    monkeypatch.setattr(preflight.shutil, "which", lambda _command: "/usr/bin/R")
    captured: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        captured["command"] = command
        captured.update(kwargs)
        return type("Result", (), {"stdout": "4.5.0\n"})()

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    assert preflight._r_version() == "4.5.0"
    assert captured["command"][-1] == "cat(as.character(getRversion()))"
    assert captured["check"] is True


def test_build_preflight_reports_all_satisfied_requirements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _valid_environment(tmp_path, monkeypatch)

    receipt = preflight.build_preflight(
        require_r=True,
        require_pandoc=True,
        strict=True,
        workspace=workspace,
    )

    assert receipt["status"] == "valid"
    assert all(receipt["checks"].values())
    assert receipt["requirements"] == {"r": True, "pandoc": True}
    assert receipt["availability"] == {
        "r": True,
        "pandoc": True,
        "dejavu_sans": True,
    }
    assert receipt["pandoc"] == "pandoc 3.7.0"


def test_optional_r_and_pandoc_do_not_fail_but_availability_is_recorded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _valid_environment(tmp_path, monkeypatch, pandoc=False)
    monkeypatch.setattr(preflight, "_r_version", lambda: None)

    receipt = preflight.build_preflight(
        require_r=False,
        require_pandoc=False,
        strict=True,
        workspace=workspace,
    )

    assert receipt["checks"]["r_4_5_0"] is True
    assert receipt["checks"]["pandoc_requirement_satisfied"] is True
    assert receipt["availability"]["r"] is False
    assert receipt["availability"]["pandoc"] is False


def test_preflight_records_failures_and_strict_mode_names_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = _valid_environment(tmp_path, monkeypatch, pandoc=False)
    (workspace / "uv.lock").unlink()
    monkeypatch.setenv("OMP_NUM_THREADS", "2")

    receipt = preflight.build_preflight(
        require_r=True,
        require_pandoc=True,
        strict=False,
        workspace=workspace,
    )
    assert receipt["status"] == "invalid"
    assert receipt["checks"]["blas_threads_fixed"] is False
    assert receipt["checks"]["dependency_locks_present"] is False
    assert receipt["checks"]["pandoc_requirement_satisfied"] is False

    with pytest.raises(SystemExit, match="blas_threads_fixed.*dependency_locks_present"):
        preflight.build_preflight(
            require_r=True,
            require_pandoc=True,
            strict=True,
            workspace=workspace,
        )


def test_preflight_without_workspace_does_not_require_lock_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _valid_environment(tmp_path, monkeypatch)
    receipt = preflight.build_preflight(require_r=True, strict=True, workspace=None)
    assert receipt["checks"]["dependency_locks_present"] is True


def test_preflight_main_writes_plain_atomic_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "nested" / "preflight.json"
    payload = {"schema_version": 1, "status": "valid", "checks": {"ok": True}}
    monkeypatch.setattr(preflight, "build_preflight", lambda **_kwargs: payload)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hfmd.data.preflight", "--output", str(output), "--no-strict"],
    )

    preflight.main()

    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert not list(output.parent.glob("*.tmp"))
    assert json.loads(capsys.readouterr().out) == payload


def test_preflight_main_writes_hash_bound_environment_stage_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    run_root = workspace / ".runs" / RUN_ID / "staging"
    run_root.mkdir(parents=True)
    snapshot = run_root / "config" / "config.snapshot.json"
    write_config_snapshot(load_config(ROOT / "config" / "project.yaml", "ci"), snapshot)
    output = run_root / "receipts" / "environment.json"
    payload = {"schema_version": 1, "status": "valid", "checks": {"ok": True}}
    monkeypatch.setattr(preflight, "build_preflight", lambda **_kwargs: payload)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hfmd.data.preflight",
            "--output",
            str(output),
            "--run-id",
            RUN_ID,
            "--run-root",
            str(run_root),
            "--workspace",
            str(workspace),
            "--config-snapshot",
            str(snapshot),
        ],
    )

    preflight.main()

    receipt = StageReceipt.model_validate_json(output.read_text(encoding="utf-8"))
    assert receipt.stage == "environment"
    assert receipt.metadata["environment_preflight"] == payload


def test_preflight_main_requires_complete_provenance_tuple(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "preflight.json"
    monkeypatch.setattr(
        preflight,
        "build_preflight",
        lambda **_kwargs: {"schema_version": 1, "status": "valid"},
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "hfmd.data.preflight",
            "--output",
            str(output),
            "--run-id",
            RUN_ID,
        ],
    )

    with pytest.raises(SystemExit, match="are all required"):
        preflight.main()
