from __future__ import annotations

from pathlib import Path

from hfmd.dynamics.registry import (
    dynamics_model_specs,
    dynamics_sensitivity_families,
    load_dynamics_registry,
)
from hfmd.ecological.registry import ECOLOGICAL_GROUPS, ecological_formula, ecological_model_specs

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "model_registry.yaml"


def test_ecological_registry_contains_55_unique_models_in_four_groups() -> None:
    models = ecological_model_specs(path=REGISTRY)
    assert len(models) == 55
    assert len({model.model_id for model in models}) == 55
    assert {model.group for model in models} == ECOLOGICAL_GROUPS
    assert sum(model.primary for model in models) == 6


def test_ecological_registry_preserves_required_model_identities() -> None:
    model_ids = {model.model_id for model in ecological_model_specs(path=REGISTRY)}
    assert {
        "background_nb2_primary",
        "season_outbreak_risk_primary",
        "ignition_cloglog_primary",
        "age_target_composition_primary",
        "pathogen_ev71_typed_primary",
        "event_size_nb2_primary",
        "background_population_offset_coverage_proxy_weather_county_trend_poisson",
    }.issubset(model_ids)


def test_formula_templates_resolve_without_live_source_configuration() -> None:
    formula = ecological_formula("background_nb2_primary", path=REGISTRY)
    assert formula.startswith("reported_cases ~ vax_lag1_log2_within")
    assert "C(county_code)" in formula
    assert "C(calendar_year)" in formula
    county_formula = ecological_formula("season_outbreak_risk_county_fe", path=REGISTRY)
    assert "C(county_code)" in county_formula
    assert "vax_lag1_between_z" not in county_formula


def test_dynamics_registry_declares_existing_and_required_structures() -> None:
    registry = load_dynamics_registry(REGISTRY)
    migrated = {
        model.model_id for model in dynamics_model_specs(path=REGISTRY, include_planned=False)
    }
    assert migrated == {
        "M0_no_vaccine_no_cross",
        "M1_vaccine_no_cross",
        "M2_vaccine_cross",
        "M3_vaccine_cross_no_covid",
        "M4_vaccine_cross_weather",
    }
    required = {
        model.model_id
        for model in dynamics_model_specs(path=REGISTRY)
        if model.implementation_status == "required"
    }
    assert {
        "M1_vaccine_no_cross_secular6",
        "M2_vaccine_cross_secular6",
        "M2_age_nb_dm_ar1",
        "M2_directional_ev71_cva16",
    }.issubset(required)
    assert len(registry.select(line="dynamics")) == 17


def test_dynamics_sensitivity_registry_covers_scientific_upgrade() -> None:
    families = {family.family_id: family for family in dynamics_sensitivity_families(REGISTRY)}
    assert tuple(families["typing_trailing_window"].values) == (4, 8, 13, 26)
    assert tuple(families["typing_dirichlet_prior_mass"].values) == (1, 5, 20)
    assert tuple(families["placebo_rollout"].values) == (2014, 2015, 2016, 2018, 2019, 2020)
    assert tuple(families["rolling_origin_validation"].values) == (
        2019,
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
    )
    assert "full_state_minimum_500" in families["bootstrap_uncertainty"].values
