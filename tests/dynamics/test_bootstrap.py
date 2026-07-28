from __future__ import annotations

import math

import pytest

from hfmd.dynamics.bootstrap import (
    BootstrapPlan,
    adaptive_bootstrap_decision,
    endpoint_change_fraction,
    full_state_replication_schedule,
)


def test_default_plan_matches_formal_allocation() -> None:
    plan = BootstrapPlan()

    assert plan.conditional_replicates == 2_000
    assert plan.full_state_replicates == 500
    assert plan.full_state_multistart_replicates == 50
    assert full_state_replication_schedule(plan) == (500, 750, 1_000, 1_250, 1_500, 1_750, 2_000)


def test_multistart_allocation_rounds_up_and_schedule_stops_exactly_at_cap() -> None:
    plan = BootstrapPlan(
        full_state_replicates=503,
        full_state_multistart_fraction=0.1,
        increment=250,
        maximum_replicates=1_000,
    )

    assert plan.full_state_multistart_replicates == 51
    assert full_state_replication_schedule(plan) == (503, 753, 1_000)
    assert full_state_replication_schedule(
        BootstrapPlan(full_state_replicates=500, maximum_replicates=500)
    ) == (500,)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"conditional_replicates": 0}, "replicate counts must be positive"),
        ({"full_state_replicates": 0}, "replicate counts must be positive"),
        ({"full_state_multistart_fraction": 0}, "must lie in"),
        ({"full_state_multistart_fraction": 1.01}, "must lie in"),
        ({"increment": 0}, "increment must be positive"),
        (
            {"full_state_replicates": 501, "maximum_replicates": 500},
            "cannot be below",
        ),
        ({"endpoint_change_threshold": 0}, "must lie in"),
        ({"endpoint_change_threshold": 1}, "must lie in"),
    ],
)
def test_bootstrap_plan_rejects_invalid_allocations(
    overrides: dict[str, float | int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        BootstrapPlan(**overrides)  # type: ignore[arg-type]


def test_endpoint_change_above_threshold_extends_by_declared_increment() -> None:
    # Current width is 2.0 and the lower endpoint moves 0.2 => 10%.
    decision = adaptive_bootstrap_decision(
        500,
        [0.8, 3.0],
        [1.0, 3.0],
        increment=300,
        threshold=0.05,
    )

    assert decision.endpoint_change_fraction == pytest.approx(0.1)
    assert decision.endpoint_change == pytest.approx(0.2)
    assert decision.interval_width == pytest.approx(2.0)
    assert decision.threshold == pytest.approx(0.05)
    assert decision.extend
    assert not decision.reached_maximum
    assert decision.next_replicates == 800


def test_stable_threshold_equal_or_capped_run_does_not_extend() -> None:
    stable = adaptive_bootstrap_decision(750, [1.04, 3.0], [1.0, 3.0])
    exactly_at_threshold = adaptive_bootstrap_decision(
        750,
        [0.9, 3.0],
        [1.0, 3.0],
        threshold=0.05,
    )
    capped = adaptive_bootstrap_decision(2_000, [0.5, 3.0], [1.0, 3.0])

    assert not stable.extend
    assert not exactly_at_threshold.extend
    assert exactly_at_threshold.endpoint_change_fraction == pytest.approx(0.05)
    assert not capped.extend
    assert capped.reached_maximum
    assert capped.next_replicates == 2_000


def test_adaptive_increment_is_clipped_at_maximum() -> None:
    decision = adaptive_bootstrap_decision(
        1_900,
        [0.5, 3.0],
        [1.0, 3.0],
        increment=250,
        maximum_replicates=2_000,
    )

    assert decision.extend
    assert decision.next_replicates == 2_000


def test_zero_width_interval_has_defined_stability_behavior() -> None:
    assert endpoint_change_fraction([1, 1], [1, 1]) == 0
    assert math.isinf(endpoint_change_fraction([0, 0], [1, 1]))
    decision = adaptive_bootstrap_decision(500, [0, 0], [1, 1])
    assert decision.extend
    assert math.isinf(decision.endpoint_change_fraction)


@pytest.mark.parametrize(
    ("previous", "current", "message"),
    [
        ([1], [1, 2], "exactly two endpoints"),
        ([1, 2, 3], [1, 2], "exactly two endpoints"),
        (None, [1, 2], "exactly two endpoints"),
        ([2, 1], [1, 2], "lower endpoint exceeds"),
        ([1, 2], [2, 1], "lower endpoint exceeds"),
        ([float("nan"), 2], [1, 2], "must not be NaN"),
        ([1, 2], [1, float("inf")], "must be finite"),
    ],
)
def test_endpoint_change_rejects_invalid_intervals(
    previous: object, current: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        endpoint_change_fraction(previous, current)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"current_replicates": 0}, "counts and increment are inconsistent"),
        ({"current_replicates": 500, "increment": 0}, "counts and increment are inconsistent"),
        (
            {"current_replicates": 501, "maximum_replicates": 500},
            "counts and increment are inconsistent",
        ),
        ({"current_replicates": 500, "threshold": 0}, "threshold must lie"),
        ({"current_replicates": 500, "threshold": 1}, "threshold must lie"),
    ],
)
def test_adaptive_decision_rejects_invalid_control_parameters(
    kwargs: dict[str, float | int], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        adaptive_bootstrap_decision(
            previous_interval=[0, 1],
            current_interval=[0, 1],
            **kwargs,  # type: ignore[arg-type]
        )
