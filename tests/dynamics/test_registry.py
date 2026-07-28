from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from hfmd.dynamics.registry import (
    REQUIRED_DYNAMICS_GROUPS,
    dynamics_model_specs,
    dynamics_sensitivity_families,
    load_dynamics_registry,
)

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "config" / "model_registry.yaml"


def _canonical_payload() -> dict[str, Any]:
    payload = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def _write_registry(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "model_registry.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


def _dynamics_models(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return [model for model in payload["models"] if model["line"] == "dynamics"]


def test_canonical_dynamics_registry_has_all_groups_and_unique_models() -> None:
    registry = load_dynamics_registry(REGISTRY)
    models = dynamics_model_specs(path=REGISTRY)

    assert len(models) == 17
    assert len({model.model_id for model in models}) == len(models)
    assert {model.group for model in models} == REQUIRED_DYNAMICS_GROUPS
    assert registry.expected_counts["dynamics"] == 17


def test_model_selection_filters_group_and_migration_status() -> None:
    migrated = dynamics_model_specs(path=REGISTRY, include_planned=False)
    observation_models = dynamics_model_specs(group="observation_models", path=REGISTRY)

    assert {model.model_id for model in migrated} == {
        "M0_no_vaccine_no_cross",
        "M1_vaccine_no_cross",
        "M2_vaccine_cross",
        "M3_vaccine_cross_no_covid",
        "M4_vaccine_cross_weather",
    }
    assert {model.model_id for model in observation_models} == {
        "M2_age_nb_dm",
        "M2_age_nb_dm_ar1",
    }
    assert dynamics_model_specs(group="unknown", path=REGISTRY) == ()


def test_sensitivity_accessor_preserves_declared_formal_values() -> None:
    families = {item.family_id: item for item in dynamics_sensitivity_families(REGISTRY)}

    assert tuple(families["typing_trailing_window"].values) == (4, 8, 13, 26)
    assert tuple(families["typing_dirichlet_prior_mass"].values) == (1, 5, 20)
    assert tuple(families["rolling_origin_validation"].values) == tuple(range(2019, 2026))


def test_registry_rejects_empty_dynamics_line(tmp_path: Path) -> None:
    payload = _canonical_payload()
    payload["models"] = [model for model in payload["models"] if model["line"] != "dynamics"]
    payload["expected_counts"]["dynamics"] = 0
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValueError, match="dynamics registry is empty"):
        load_dynamics_registry(path)


@pytest.mark.parametrize("missing_group", sorted(REQUIRED_DYNAMICS_GROUPS))
def test_registry_rejects_each_missing_required_group(tmp_path: Path, missing_group: str) -> None:
    payload = _canonical_payload()
    payload["models"] = [
        model
        for model in payload["models"]
        if not (model["line"] == "dynamics" and model["group"] == missing_group)
    ]
    payload["expected_counts"]["dynamics"] = len(_dynamics_models(payload))
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValueError, match=rf"missing dynamics model groups: .*{missing_group}"):
        load_dynamics_registry(path)


def test_registry_rejects_missing_sensitivity_families(tmp_path: Path) -> None:
    payload = _canonical_payload()
    payload["sensitivity_families"] = []
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValueError, match="sensitivity-family registry is empty"):
        load_dynamics_registry(path)


def test_registry_rejects_duplicate_model_ids_before_scientific_selection(tmp_path: Path) -> None:
    payload = _canonical_payload()
    payload["models"].append(copy.deepcopy(_dynamics_models(payload)[0]))
    payload["expected_counts"]["dynamics"] += 1
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValidationError, match="duplicate model_id values"):
        load_dynamics_registry(path)


def test_registry_rejects_declared_count_mismatch(tmp_path: Path) -> None:
    payload = _canonical_payload()
    payload["expected_counts"]["dynamics"] = 99
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValidationError, match="contains 17 dynamics models; expected 99"):
        load_dynamics_registry(path)


def test_registry_rejects_duplicate_sensitivity_family_ids(tmp_path: Path) -> None:
    payload = _canonical_payload()
    payload["sensitivity_families"].append(copy.deepcopy(payload["sensitivity_families"][0]))
    path = _write_registry(tmp_path, payload)

    with pytest.raises(ValidationError, match="duplicate sensitivity family values"):
        load_dynamics_registry(path)


def test_registry_loader_rejects_non_mapping_and_missing_file(tmp_path: Path) -> None:
    path = _write_registry(tmp_path, ["not", "a", "mapping"])
    with pytest.raises(ValueError, match="model registry must be a mapping"):
        load_dynamics_registry(path)
    with pytest.raises(FileNotFoundError):
        load_dynamics_registry(tmp_path / "missing.yaml")
