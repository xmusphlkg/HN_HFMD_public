from __future__ import annotations

from pathlib import Path

from hfmd.reporting.contracts import load_visual_contract
from hfmd.reporting.science import evaluate_science_gate, load_science_gates

ROOT = Path(__file__).resolve().parents[2]


def test_visual_contract_has_five_main_and_ten_supplementary_figures() -> None:
    contract = load_visual_contract(ROOT / "config" / "visual_contract.yaml")
    assert len(contract.main_figures) == 5
    assert len(contract.supplementary_figures) == 10
    assert contract.backend == "R"
    assert contract.font_family == "DejaVu Sans"
    assert contract.palette["orange"] == "#E57C23"
    assert contract.palette["teal"] == "#2A9D8F"
    assert contract.palette["navy"] == "#123B4A"


def test_old_visual_design_sources_are_retained_but_county_figure_is_new() -> None:
    contract = load_visual_contract(ROOT / "config" / "visual_contract.yaml")
    legacy = {figure.figure_id: figure.legacy_design_source for figure in contract.main_figures}
    assert legacy == {
        "figure1": "figure1",
        "figure2": None,
        "figure3": "figure2",
        "figure4": "figure3",
        "figure5": "figure4",
    }
    assert contract.main_figures[1].implementation_status == "required"


def passing_metrics() -> dict:
    return {
        "competition_release": {
            "selection_analyses_direction_consistent": True,
            "rolling_folds": {
                "joint_m2_better_count": 5,
                "total_noninferior_count": 4,
                "typing_noninferior_count": 4,
            },
            "simulations": {
                "null_false_selection_rate": 0.049,
                "positive_mechanism_absolute_relative_bias": 0.19,
                "positive_mechanism_interval_coverage": 0.94,
            },
            "interpreted_pairs": {"all_parameters_away_from_boundaries": True},
        },
        "under_six_concentration": {
            "shares_across_defensible_structures": [0.80, 0.83, 0.91, 0.88]
        },
        "net_benefit": {
            "estimates_across_major_equivalent_models": [1.0, 10.0, 0.1],
            "full_state_interval_lower_bound": 0.01,
        },
    }


def test_science_gates_pass_only_at_prespecified_thresholds() -> None:
    config = load_science_gates(ROOT / "config" / "science_gates.yaml")
    assert (
        evaluate_science_gate("competition_release", passing_metrics(), config).decision == "pass"
    )
    assert (
        evaluate_science_gate("under_six_concentration", passing_metrics(), config).decision
        == "pass"
    )
    assert evaluate_science_gate("net_benefit", passing_metrics(), config).decision == "pass"


def test_competition_gate_downgrades_at_five_percent_false_selection() -> None:
    config = load_science_gates(ROOT / "config" / "science_gates.yaml")
    metrics = passing_metrics()
    metrics["competition_release"]["simulations"]["null_false_selection_rate"] = 0.05
    result = evaluate_science_gate("competition_release", metrics, config)
    assert result.decision == "downgrade"
    assert "null_false_selection_below_five_percent" in result.failed_checks
    assert "hypothesis-generating" in result.publication_language


def test_missing_gate_metric_is_not_treated_as_pass() -> None:
    config = load_science_gates(ROOT / "config" / "science_gates.yaml")
    metrics = passing_metrics()
    del metrics["competition_release"]["rolling_folds"]
    result = evaluate_science_gate("competition_release", metrics, config)
    assert result.decision == "not_evaluated"
    assert result.missing_metrics
