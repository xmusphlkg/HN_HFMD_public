from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from hfmd.core.config import load_config, write_config_snapshot
from hfmd.core.hashing import iter_regular_files
from hfmd.core.receipts import build_stage_receipt, write_stage_receipt
from hfmd.data.synthetic import generate_synthetic_directory

RUN_ID = "20260717T120000Z-01234567-analysis-test"


@dataclass(frozen=True)
class StagedRun:
    workspace: Path
    run_root: Path
    data_receipt: Path
    analysis_receipt: Path
    profile: str


@pytest.fixture
def staged_run_factory(tmp_path: Path) -> Callable[..., StagedRun]:
    workspace = Path(__file__).resolve().parents[2]

    def factory(*, profile: str, line: str) -> StagedRun:
        run_root = tmp_path / profile / line / ".runs" / RUN_ID / "staging"
        (run_root / "config").mkdir(parents=True)
        (run_root / "receipts").mkdir()
        loaded = load_config(workspace / "config" / "project.yaml", profile)
        snapshot = run_root / "config" / "config.snapshot.json"
        write_config_snapshot(loaded, snapshot)
        data_receipt = run_root / "receipts" / "data.json"
        if profile in {"ci", "synthetic"}:
            data_root = run_root / "data" / "synthetic"
            generate_synthetic_directory(
                data_root,
                profile=profile,
                seed=loaded.config.runtime.random_seed,
            )
            outputs = tuple(iter_regular_files(data_root))
            receipt = build_stage_receipt(
                run_root=run_root,
                workspace=workspace,
                run_id=RUN_ID,
                stage="data",
                config_snapshot=snapshot,
                output_paths=outputs,
                output_classification="synthetic",
                exact_output_roots=(data_root,),
                metadata={"data_kind": "fully_synthetic"},
            )
        else:
            receipt = build_stage_receipt(
                run_root=run_root,
                workspace=workspace,
                run_id=RUN_ID,
                stage="data",
                config_snapshot=snapshot,
                output_paths=(),
                metadata={"data_kind": "sealed_controlled_derived"},
            )
        write_stage_receipt(receipt, data_receipt)
        return StagedRun(
            workspace=workspace,
            run_root=run_root,
            data_receipt=data_receipt,
            analysis_receipt=run_root / "receipts" / f"{line}.json",
            profile=profile,
        )

    return factory
