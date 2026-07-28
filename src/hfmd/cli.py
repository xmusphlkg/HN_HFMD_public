"""Command-line interface for the auditable HFMD research platform."""

from __future__ import annotations

import json
import shutil
import subprocess
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer

from hfmd.core.config import ProfileName, load_config
from hfmd.core.environment import reproducible_environment, require_clean_worktree
from hfmd.core.hashing import iter_regular_files, sha256_file
from hfmd.core.manifest import RUN_ID, InputRecord, validate_manifest
from hfmd.core.publish import publish_run
from hfmd.core.receipts import StageReceipt, validate_stage_receipt
from hfmd.core.run import RunContext, discover_workspace
from hfmd.reporting.contracts import ModelRegistry, VisualContract
from hfmd.reporting.science import validate_science_gate_configuration


class DataProfile(StrEnum):
    """Profiles that are allowed to build registered analysis data."""

    RESTRICTED = "restricted"
    SYNTHETIC = "synthetic"


class RunTarget(StrEnum):
    """Public scientific workflow targets."""

    ECOLOGICAL = "ecological"
    DYNAMICS = "dynamics"
    FIGURES = "figures"
    MANUSCRIPT = "manuscript"
    ALL = "all"


class Journal(StrEnum):
    """Submission contracts implemented by the platform."""

    EPIDEMICS = "epidemics"


app = typer.Typer(
    name="hfmd",
    help="Run and audit the multiscale Hunan HFMD research platform.",
    no_args_is_help=True,
    add_completion=False,
)
config_app = typer.Typer(help="Validate the single-source project configuration.")
data_app = typer.Typer(help="Build or register analysis-ready data.")
export_app = typer.Typer(help="Create privacy-audited public exports.")
submission_app = typer.Typer(help="Build a journal submission package.")

app.add_typer(config_app, name="config")
app.add_typer(data_app, name="data")
app.add_typer(export_app, name="export")
app.add_typer(submission_app, name="submission")


def _json_output(payload: Any) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str))


def _fail(message: str, *, code: int = 1) -> NoReturn:
    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=code)


def _workspace(value: Path) -> Path:
    try:
        return discover_workspace(value)
    except (FileNotFoundError, OSError) as exc:
        _fail(str(exc), code=2)


def _uv_executable(workspace: Path) -> str:
    executable = shutil.which("uv")
    if executable:
        return executable
    local = workspace / ".venv" / "bin" / "uv"
    if local.is_file():
        return local.as_posix()
    raise FileNotFoundError("uv is required; install it or restore .venv/bin/uv")


def _workflow_command(
    context: RunContext,
    *,
    target: str,
    public_destination: Path | None = None,
) -> list[str]:
    """Build a non-shell Snakemake command with CLI config taking precedence."""

    profile = context.loaded_config.config.runtime.profile.value
    command = [
        _uv_executable(context.workspace),
        "run",
        "--locked",
        "snakemake",
        "--snakefile",
        (context.workspace / "workflow" / "Snakefile").as_posix(),
        "--profile",
        (context.workspace / "workflow" / "profiles" / profile).as_posix(),
        "--config",
        f"profile={profile}",
        f"run_id={context.run_id}",
        f"targets={target}",
    ]
    if public_destination is not None:
        command.append(f"public_export_destination={public_destination.as_posix()}")
    return command


def _execute_workflow(
    *,
    workspace: Path,
    profile: ProfileName | str,
    target: str,
    run_id: str | None = None,
    label: str | None = None,
    public_destination: Path | None = None,
) -> dict[str, Any]:
    """Prepare and execute one isolated candidate without claiming publication.

    A formal profile is checked for a clean worktree both before any run files
    are created and after Snakemake returns.  Publication remains a separate,
    manifest-gated operation, so a development run can never be reported as a
    formal release merely because its workflow completed.
    """

    profile_value = profile.value if isinstance(profile, ProfileName) else str(profile)
    context = RunContext.create(
        workspace=workspace,
        profile=profile_value,
        target=target,  # type: ignore[arg-type]
        run_id=run_id,
        label=label,
    )
    runtime = context.loaded_config.config.runtime
    if runtime.formal:
        require_clean_worktree(context.workspace)
    context.prepare()
    command = _workflow_command(
        context,
        target=target,
        public_destination=public_destination,
    )
    try:
        environment = context.loaded_config.config.environment
        with reproducible_environment(
            threads=environment.blas_threads,
            timezone_name=environment.timezone,
            locale_name=environment.locale,
            seed=runtime.random_seed,
        ):
            subprocess.run(command, cwd=context.workspace, check=True)
            if runtime.formal:
                require_clean_worktree(context.workspace)
            manifest_sha256 = _seal_completed_workflow(context)
            published = False
            publication_path: str | None = None
            if runtime.formal and target == "all":
                publication = publish_run(context)
                published = True
                publication_path = publication.relative_to(context.workspace).as_posix()
    except BaseException as exc:
        context.record_failure(exc)
        raise
    return {
        "status": "published" if published else "candidate_sealed",
        "run_id": context.run_id,
        "profile": runtime.profile.value,
        "target": target,
        "formal_candidate": runtime.formal,
        "published": published,
        "manifest_sha256": manifest_sha256,
        "publication_path": publication_path,
        "run_root": context.run_root.relative_to(context.workspace).as_posix(),
    }


def _seal_completed_workflow(context: RunContext) -> str:
    """Validate every stage receipt, bind external inputs, and seal exact files."""

    staging = context.staging
    if not staging.is_dir() or staging.is_symlink():
        raise RuntimeError("workflow staging directory is missing or unsafe")
    receipt_directory = staging / "receipts"
    if not receipt_directory.is_dir() or receipt_directory.is_symlink():
        raise RuntimeError("workflow produced no stage receipt directory")
    stage_receipts: list[Path] = []
    receipts_by_stage: dict[str, Path] = {}
    external_inputs: dict[str, InputRecord] = {}
    for path in sorted(receipt_directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"invalid workflow receipt {path.name}: {exc}") from exc
        if payload.get("schema_version") != "hfmd-stage-receipt-v1":
            continue
        report = validate_stage_receipt(
            path,
            run_root=staging,
            workspace=context.workspace,
        )
        if not report.ok:
            raise RuntimeError(
                f"stage receipt {path.name} failed validation: " + "; ".join(report.issues)
            )
        receipt = StageReceipt.model_validate(payload)
        if receipt.run_id != context.run_id:
            raise RuntimeError(f"stage receipt {path.name} belongs to another run")
        if receipt.stage in receipts_by_stage:
            raise RuntimeError(f"workflow produced duplicate {receipt.stage} stage receipts")
        receipts_by_stage[receipt.stage] = path
        stage_receipts.append(path)
        for record in receipt.inputs:
            if record.scope != "workspace":
                continue
            if record.classification not in {
                "public",
                "synthetic",
                "restricted",
                "controlled_derived",
            }:
                continue
            key = record.path
            existing = external_inputs.get(key)
            candidate = InputRecord(
                id=f"stage_input_{len(external_inputs):05d}",
                path=record.path,
                sha256=record.sha256,
                size_bytes=record.size_bytes,
                classification=record.classification,  # type: ignore[arg-type]
            )
            if existing is not None and (
                existing.sha256 != candidate.sha256
                or existing.size_bytes != candidate.size_bytes
                or existing.classification != candidate.classification
            ):
                raise RuntimeError(f"conflicting external input records for {record.path}")
            external_inputs[key] = candidate
    if not stage_receipts:
        raise RuntimeError("workflow produced no hash-bound stage receipts")
    required_by_target = {
        "data": {"environment", "data"},
        "ecological": {"environment", "data", "ecological"},
        "dynamics": {"environment", "data", "dynamics"},
        "figures": {"environment", "data", "ecological", "dynamics", "figures"},
        "manuscript": {
            "environment",
            "data",
            "ecological",
            "dynamics",
            "figures",
            "manuscript",
        },
        "submission": {
            "environment",
            "data",
            "ecological",
            "dynamics",
            "figures",
            "manuscript",
            "submission",
        },
        "all": {
            "environment",
            "data",
            "ecological",
            "dynamics",
            "figures",
            "manuscript",
            "submission",
        },
        "public_export": {
            "environment",
            "data",
            "ecological",
            "dynamics",
            "figures",
            "manuscript",
            "submission",
            "public_export",
        },
    }
    required_stages = required_by_target[context.target]
    missing_stages = sorted(required_stages - set(receipts_by_stage))
    unexpected_stages = sorted(set(receipts_by_stage) - required_stages)
    if missing_stages or unexpected_stages:
        raise RuntimeError(
            "workflow stage-receipt set mismatch: "
            f"missing={missing_stages}, unexpected={unexpected_stages}"
        )
    normalized_inputs = tuple(
        record.model_copy(update={"id": f"input_{index:05d}"})
        for index, record in enumerate(
            sorted(external_inputs.values(), key=lambda item: (item.path, item.classification))
        )
    )
    expected_paths = tuple(
        path.relative_to(staging).as_posix() for path in iter_regular_files(staging)
    )
    context.seal(
        expected_paths=expected_paths,
        inputs=normalized_inputs,
        metadata={
            "stage_receipts": [path.relative_to(staging).as_posix() for path in stage_receipts],
            "stage_receipt_count": len(stage_receipts),
        },
    )
    return sha256_file(context.manifest_path)


def _run_or_fail(**kwargs: Any) -> dict[str, Any]:
    try:
        return _execute_workflow(**kwargs)
    except (KeyboardInterrupt, typer.Abort):
        raise
    except subprocess.CalledProcessError as exc:
        _fail(f"workflow failed with exit code {exc.returncode}")
    except Exception as exc:
        _fail(str(exc))


@config_app.command("validate")
def config_validate(
    profile: Annotated[ProfileName, typer.Option("--profile")] = ProfileName.SYNTHETIC,
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
) -> None:
    """Validate and hash the project plus the selected profile."""

    root = _workspace(workspace)
    try:
        loaded = load_config(root / "config" / "project.yaml", profile.value)
        model_registry = ModelRegistry.model_validate(loaded.resources["model_registry"])
        visual_contract = VisualContract.model_validate(loaded.resources["visual_contract"])
        science_gates = validate_science_gate_configuration(loaded.resources["science_gates"])
    except Exception as exc:
        _fail(str(exc), code=2)
    _json_output(
        {
            "status": "valid",
            "profile": loaded.config.runtime.profile.value,
            "formal": loaded.config.runtime.formal,
            "config_sha256": loaded.config_sha256,
            "source_hashes": loaded.source_hashes,
            "model_count": len(model_registry.models),
            "main_figure_count": len(visual_contract.main_figures),
            "supplementary_figure_count": len(visual_contract.supplementary_figures),
            "science_gate_count": len(science_gates.gates),
        }
    )


@data_app.command("build")
def data_build(
    profile: Annotated[DataProfile, typer.Option("--profile")],
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Build synthetic data or register the sealed restricted-data export."""

    result = _run_or_fail(
        workspace=_workspace(workspace),
        profile=profile.value,
        target="data",
        run_id=run_id,
        label="data",
    )
    _json_output(result)


@app.command("run")
def run_analysis(
    target: Annotated[RunTarget, typer.Option("--target")],
    profile: Annotated[ProfileName, typer.Option("--profile")] = ProfileName.SYNTHETIC,
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Run one scientific target or the complete dependency graph."""

    result = _run_or_fail(
        workspace=_workspace(workspace),
        profile=profile,
        target=target.value,
        run_id=run_id,
        label=target.value,
    )
    _json_output(result)


def _manifest_for_run(workspace: Path, run_id: str) -> tuple[Path, Path]:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run_id")
    loaded = load_config(workspace / "config" / "project.yaml", ProfileName.SYNTHETIC.value)
    candidate_root = workspace / loaded.config.paths.runs / run_id / "staging"
    candidate = candidate_root / "manifest.json"
    if candidate.is_file() and not candidate.is_symlink():
        return candidate, candidate_root

    current_root = workspace / loaded.config.paths.current
    current = current_root / "manifest.json"
    if current.is_file() and not current.is_symlink():
        try:
            payload = json.loads(current.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"current manifest cannot be read: {exc}") from exc
        if payload.get("run_id") == run_id:
            return current, current_root
    raise FileNotFoundError(f"no candidate or current manifest found for run {run_id}")


@app.command("validate")
def validate_run(
    run_id: Annotated[str, typer.Option("--run")],
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
) -> None:
    """Validate a run's exact artifact set, hashes, inputs, and parent link."""

    root = _workspace(workspace)
    try:
        manifest, artifact_root = _manifest_for_run(root, run_id)
        report = validate_manifest(manifest, artifact_root=artifact_root, workspace=root)
    except Exception as exc:
        _fail(str(exc), code=2)
    _json_output(report.model_dump(mode="json"))
    if not report.ok:
        raise typer.Exit(code=1)


@export_app.command("public")
def export_public(
    destination: Annotated[Path, typer.Option("--destination", file_okay=False)],
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Build synthetic inputs and export a deny-by-default public repository."""

    root = _workspace(workspace)
    target = destination.expanduser().resolve()
    if target.exists() or target.is_symlink():
        _fail(f"public destination must not already exist: {target}", code=2)
    try:
        target.relative_to(root)
    except ValueError:
        pass
    else:
        _fail("public destination must be outside the private workspace", code=2)
    result = _run_or_fail(
        workspace=root,
        profile=ProfileName.SYNTHETIC,
        target="public_export",
        run_id=run_id,
        label="public-export",
        public_destination=target,
    )
    _json_output(result)


@submission_app.command("build")
def submission_build(
    journal: Annotated[Journal, typer.Option("--journal")],
    profile: Annotated[ProfileName, typer.Option("--profile")] = ProfileName.RESTRICTED,
    workspace: Annotated[Path, typer.Option("--workspace", file_okay=False)] = Path("."),
    run_id: Annotated[str | None, typer.Option("--run-id")] = None,
) -> None:
    """Build a validated journal-specific submission package candidate."""

    result = _run_or_fail(
        workspace=_workspace(workspace),
        profile=profile,
        target="submission",
        run_id=run_id,
        label=f"submission-{journal.value}",
    )
    result["journal"] = journal.value
    _json_output(result)


if __name__ == "__main__":
    app()
