"""Scientific core utilities for the HFMD transmission-dynamics analysis."""

from hfmd.dynamics.bootstrap import (
    BootstrapDecision,
    BootstrapPlan,
    adaptive_bootstrap_decision,
    endpoint_change_fraction,
    full_state_replication_schedule,
)
from hfmd.dynamics.observation import (
    age_specific_nb2_loglik,
    ar1_residual_score,
    dirichlet_concentration,
    dirichlet_multinomial_loglik,
)
from hfmd.dynamics.typing_selection import (
    IPWResult,
    TwoStageCounts,
    WeightAudit,
    build_two_stage_counts,
    combined_selection_probability,
    fit_aggregated_binomial_glm,
    load_restricted_aggregate,
    standardize_probability,
    truncated_ipw,
)
from hfmd.dynamics.validation import (
    FORMAL_TEST_YEARS,
    FoldLogScore,
    RollingOriginFold,
    RollingScoreGate,
    evaluate_rolling_score_gate,
    rolling_origin_folds,
)

__all__ = [
    "BootstrapDecision",
    "BootstrapPlan",
    "FORMAL_TEST_YEARS",
    "FoldLogScore",
    "IPWResult",
    "RollingOriginFold",
    "RollingScoreGate",
    "TwoStageCounts",
    "WeightAudit",
    "adaptive_bootstrap_decision",
    "age_specific_nb2_loglik",
    "ar1_residual_score",
    "build_two_stage_counts",
    "combined_selection_probability",
    "dirichlet_concentration",
    "dirichlet_multinomial_loglik",
    "endpoint_change_fraction",
    "evaluate_rolling_score_gate",
    "fit_aggregated_binomial_glm",
    "full_state_replication_schedule",
    "load_restricted_aggregate",
    "rolling_origin_folds",
    "standardize_probability",
    "truncated_ipw",
]
