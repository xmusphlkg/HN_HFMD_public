from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from hfmd import cli
from hfmd.core.environment import EnvironmentFailure

RUN_ID = "20260717T120000Z-01234567-test"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _candidate_result(kwargs: dict[str, Any]) -> dict[str, Any]:
    profile = kwargs["profile"]
    profile_value = profile.value if hasattr(profile, "value") else str(profile)
    return {
        "status": "candidate_completed",
        "run_id": RUN_ID,
        "profile": profile_value,
        "target": kwargs["target"],
        "formal_candidate": profile_value == "restricted",
        "published": False,
        "run_root": f".runs/{RUN_ID}",
    }


def test_root_help_exposes_all_six_command_interfaces(runner: CliRunner) -> None:
    result = runner.invoke(cli.app, ["--help"])

    assert result.exit_code == 0
    for command in ("config", "data", "run", "validate", "export", "submission"):
        assert command in result.stdout
    for group, command in (
        ("config", "validate"),
        ("data", "build"),
        ("export", "public"),
        ("submission", "build"),
    ):
        nested = runner.invoke(cli.app, [group, "--help"])
        assert nested.exit_code == 0
        assert command in nested.stdout


def test_config_validate_reports_hash_and_formal_status(runner: CliRunner) -> None:
    workspace = Path(__file__).resolve().parents[2]
    result = runner.invoke(
        cli.app,
        ["config", "validate", "--profile", "synthetic", "--workspace", str(workspace)],
    )

    assert result.exit_code == 0
    assert '"status": "valid"' in result.stdout
    assert '"profile": "synthetic"' in result.stdout
    assert '"formal": false' in result.stdout
    assert '"config_sha256":' in result.stdout


def test_data_build_accepts_only_restricted_or_synthetic(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _candidate_result(kwargs)

    monkeypatch.setattr(cli, "_workspace", lambda _: tmp_path)
    monkeypatch.setattr(cli, "_run_or_fail", fake_run)
    result = runner.invoke(cli.app, ["data", "build", "--profile", "restricted"])

    assert result.exit_code == 0
    assert captured["profile"] == "restricted"
    assert captured["target"] == "data"
    assert '"published": false' in result.stdout

    rejected = runner.invoke(cli.app, ["data", "build", "--profile", "ci"])
    assert rejected.exit_code == 2


@pytest.mark.parametrize("target", ["ecological", "dynamics", "figures", "manuscript", "all"])
def test_run_routes_every_declared_target(
    target: str, runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _candidate_result(kwargs)

    monkeypatch.setattr(cli, "_workspace", lambda _: tmp_path)
    monkeypatch.setattr(cli, "_run_or_fail", fake_run)
    result = runner.invoke(
        cli.app,
        ["run", "--target", target, "--profile", "synthetic", "--run-id", RUN_ID],
    )

    assert result.exit_code == 0
    assert captured["target"] == target
    assert captured["run_id"] == RUN_ID


def test_validate_routes_run_to_exact_manifest_validator(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}\n", encoding="utf-8")
    report = SimpleNamespace(
        ok=True,
        model_dump=lambda **_: {
            "ok": True,
            "manifest_path": str(manifest),
            "manifest_sha256": "a" * 64,
            "issues": [],
        },
    )
    called: dict[str, Any] = {}

    def fake_validate(path: Path, **kwargs: Any) -> Any:
        called["path"] = path
        called.update(kwargs)
        return report

    monkeypatch.setattr(cli, "_workspace", lambda _: tmp_path)
    monkeypatch.setattr(cli, "_manifest_for_run", lambda *_: (manifest, tmp_path))
    monkeypatch.setattr(cli, "validate_manifest", fake_validate)
    result = runner.invoke(cli.app, ["validate", "--run", RUN_ID])

    assert result.exit_code == 0
    assert called["path"] == manifest
    assert called["artifact_root"] == tmp_path
    assert called["workspace"] == tmp_path
    assert '"ok": true' in result.stdout


def test_export_public_requires_external_new_destination(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _candidate_result(kwargs)

    workspace = tmp_path / "private"
    workspace.mkdir()
    destination = tmp_path / "public"
    monkeypatch.setattr(cli, "_workspace", lambda _: workspace)
    monkeypatch.setattr(cli, "_run_or_fail", fake_run)
    result = runner.invoke(cli.app, ["export", "public", "--destination", str(destination)])

    assert result.exit_code == 0
    assert captured["target"] == "public_export"
    assert captured["public_destination"] == destination
    assert captured["profile"].value == "synthetic"

    inside = workspace / "unsafe-public"
    rejected = runner.invoke(cli.app, ["export", "public", "--destination", str(inside)])
    assert rejected.exit_code == 2


def test_submission_build_only_accepts_epidemics(
    runner: CliRunner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Any] = {}

    def fake_run(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return _candidate_result(kwargs)

    monkeypatch.setattr(cli, "_workspace", lambda _: tmp_path)
    monkeypatch.setattr(cli, "_run_or_fail", fake_run)
    result = runner.invoke(
        cli.app,
        ["submission", "build", "--journal", "epidemics", "--profile", "synthetic"],
    )

    assert result.exit_code == 0
    assert captured["target"] == "submission"
    assert '"journal": "epidemics"' in result.stdout

    rejected = runner.invoke(cli.app, ["submission", "build", "--journal", "not-a-journal"])
    assert rejected.exit_code == 2


def _fake_context(tmp_path: Path, *, formal: bool) -> Any:
    profile = "restricted" if formal else "synthetic"
    runtime = SimpleNamespace(
        formal=formal,
        profile=SimpleNamespace(value=profile),
        random_seed=20260717,
    )
    environment = SimpleNamespace(
        blas_threads=1,
        timezone="UTC",
        locale="C.UTF-8",
    )
    state = {"prepared": False, "failed": False}

    def prepare() -> Path:
        state["prepared"] = True
        return tmp_path / ".runs" / RUN_ID / "staging"

    def record_failure(_: BaseException) -> None:
        state["failed"] = True

    return SimpleNamespace(
        workspace=tmp_path,
        loaded_config=SimpleNamespace(
            config=SimpleNamespace(runtime=runtime, environment=environment)
        ),
        run_id=RUN_ID,
        run_root=tmp_path / ".runs" / RUN_ID,
        prepare=prepare,
        record_failure=record_failure,
        state=state,
    )


def test_formal_workflow_refuses_dirty_tree_before_preparing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = _fake_context(tmp_path, formal=True)
    monkeypatch.setattr(cli.RunContext, "create", lambda **_: context)

    def dirty(_: Path) -> None:
        raise EnvironmentFailure("dirty worktree")

    monkeypatch.setattr(cli, "require_clean_worktree", dirty)

    with pytest.raises(EnvironmentFailure, match="dirty worktree"):
        cli._execute_workflow(
            workspace=tmp_path,
            profile="restricted",
            target="all",
        )
    assert context.state["prepared"] is False


def test_development_workflow_uses_locked_snakemake_without_formal_marker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    context = _fake_context(tmp_path, formal=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(cli.RunContext, "create", lambda **_: context)
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/usr/bin/uv")
    monkeypatch.setattr(
        cli,
        "require_clean_worktree",
        lambda _: pytest.fail("development run must not request formal Git validation"),
    )

    def fake_subprocess(command: list[str], **_: Any) -> None:
        calls.append(command)

    monkeypatch.setattr(cli.subprocess, "run", fake_subprocess)
    monkeypatch.setattr(cli, "_seal_completed_workflow", lambda _: "a" * 64)
    result = cli._execute_workflow(
        workspace=tmp_path,
        profile="synthetic",
        target="dynamics",
    )

    assert calls
    assert calls[0][:4] == ["/usr/bin/uv", "run", "--locked", "snakemake"]
    assert result["formal_candidate"] is False
    assert result["published"] is False
    assert result["status"] == "candidate_sealed"
    assert context.state["prepared"] is True
