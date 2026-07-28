"""Write a machine-readable environment preflight receipt."""

from __future__ import annotations

import argparse
import json
import locale
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from hfmd.core.receipts import build_stage_receipt, write_stage_receipt

EXPECTED_PYTHON = (3, 13, 5)
EXPECTED_UV = "0.11.29"


def _r_version() -> str | None:
    executable = shutil.which("R")
    if executable is None:
        return None
    completed = subprocess.run(
        [executable, "--slave", "-e", "cat(as.character(getRversion()))"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _command_output(arguments: list[str]) -> str | None:
    executable = shutil.which(arguments[0])
    if executable is None:
        return None
    completed = subprocess.run(
        [executable, *arguments[1:]],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def build_preflight(
    *,
    require_r: bool,
    strict: bool,
    require_pandoc: bool = False,
    workspace: Path | None = None,
) -> dict[str, object]:
    python_version = tuple(sys.version_info[:3])
    r_version = _r_version()
    uv_output = _command_output(["uv", "--version"])
    uv_version = uv_output.split()[1] if uv_output and len(uv_output.split()) >= 2 else None
    font_match = _command_output(["fc-match", "-f", "%{family}", "DejaVu Sans"])
    pandoc_version = _command_output(["pandoc", "--version"])
    lock_files_present = True
    if workspace is not None:
        lock_files_present = all(
            (workspace / relative).is_file()
            for relative in (Path("uv.lock"), Path("Script_r/renv.lock"))
        )
    checks = {
        "python_3_13_5": python_version == EXPECTED_PYTHON,
        "timezone_utc": os.environ.get("TZ") == "UTC",
        "locale_fixed": os.environ.get("LC_ALL") in {"C", "C.UTF-8"}
        and locale.getlocale(locale.LC_CTYPE) in {("C", "UTF-8"), (None, None)},
        "blas_threads_fixed": all(
            os.environ.get(name) == "1"
            for name in (
                "OMP_NUM_THREADS",
                "OPENBLAS_NUM_THREADS",
                "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS",
                "NUMEXPR_NUM_THREADS",
            )
        ),
        "r_4_5_0": r_version == "4.5.0" if require_r else True,
        "uv_0_11_29": uv_version == EXPECTED_UV,
        "dejavu_sans_available": bool(font_match and "DejaVu Sans" in font_match),
        "pandoc_requirement_satisfied": bool(pandoc_version) if require_pandoc else True,
        "dependency_locks_present": lock_files_present,
    }
    receipt: dict[str, object] = {
        "schema_version": 1,
        "status": "valid" if all(checks.values()) else "invalid",
        "checks": checks,
        "python": platform.python_version(),
        "r": r_version,
        "uv": uv_version,
        "pandoc": pandoc_version.splitlines()[0] if pandoc_version else None,
        "availability": {
            "r": r_version is not None,
            "pandoc": pandoc_version is not None,
            "dejavu_sans": bool(font_match and "DejaVu Sans" in font_match),
        },
        "requirements": {"r": require_r, "pandoc": require_pandoc},
        "font_match": font_match,
        "platform": platform.platform(),
    }
    if strict and receipt["status"] != "valid":
        failed = sorted(name for name, passed in checks.items() if not passed)
        raise SystemExit(f"Environment preflight failed: {', '.join(failed)}")
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-r", action="store_true")
    parser.add_argument("--no-strict", action="store_true")
    parser.add_argument("--require-pandoc", action="store_true")
    parser.add_argument("--run-id")
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--config-snapshot", type=Path)
    args = parser.parse_args()
    receipt = build_preflight(
        require_r=args.require_r,
        strict=not args.no_strict,
        require_pandoc=args.require_pandoc,
        workspace=args.workspace,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    provenance_args = (args.run_id, args.run_root, args.workspace, args.config_snapshot)
    if any(value is not None for value in provenance_args):
        if any(value is None for value in provenance_args):
            raise SystemExit(
                "--run-id, --run-root, --workspace, and --config-snapshot are all required"
            )
        stage_receipt = build_stage_receipt(
            run_root=args.run_root,
            workspace=args.workspace,
            run_id=args.run_id,
            stage="environment",
            config_snapshot=args.config_snapshot,
            output_paths=(),
            metadata={"environment_preflight": receipt},
        )
        write_stage_receipt(stage_receipt, args.output)
    else:
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(args.output)
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
