"""Pure bootstrap planning and Monte Carlo stopping rules."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil


@dataclass(frozen=True)
class BootstrapPlan:
    """Formal conditional and full-state bootstrap allocation."""

    conditional_replicates: int = 2_000
    full_state_replicates: int = 500
    full_state_multistart_fraction: float = 0.10
    increment: int = 250
    maximum_replicates: int = 2_000
    endpoint_change_threshold: float = 0.05

    def __post_init__(self) -> None:
        if self.conditional_replicates < 1 or self.full_state_replicates < 1:
            raise ValueError("bootstrap replicate counts must be positive")
        if not 0 < self.full_state_multistart_fraction <= 1:
            raise ValueError("full_state_multistart_fraction must lie in (0, 1]")
        if self.increment < 1:
            raise ValueError("increment must be positive")
        if self.maximum_replicates < self.full_state_replicates:
            raise ValueError("maximum_replicates cannot be below the initial full-state count")
        if not 0 < self.endpoint_change_threshold < 1:
            raise ValueError("endpoint_change_threshold must lie in (0, 1)")

    @property
    def full_state_multistart_replicates(self) -> int:
        """Number of full-state replicates that receive four optimization starts."""

        return ceil(self.full_state_replicates * self.full_state_multistart_fraction)


@dataclass(frozen=True)
class BootstrapDecision:
    """Decision after comparing endpoints from two successive MC runs."""

    current_replicates: int
    next_replicates: int
    endpoint_change: float
    interval_width: float
    endpoint_change_fraction: float
    threshold: float
    extend: bool
    reached_maximum: bool


def endpoint_change_fraction(
    previous_interval: Sequence[float],
    current_interval: Sequence[float],
) -> float:
    """Return maximum endpoint change divided by current interval width."""

    previous = _interval(previous_interval, "previous_interval")
    current = _interval(current_interval, "current_interval")
    width = current[1] - current[0]
    change = max(abs(current[0] - previous[0]), abs(current[1] - previous[1]))
    if width == 0:
        return 0.0 if change == 0 else float("inf")
    return change / width


def adaptive_bootstrap_decision(
    current_replicates: int,
    previous_interval: Sequence[float],
    current_interval: Sequence[float],
    *,
    increment: int = 250,
    maximum_replicates: int = 2_000,
    threshold: float = 0.05,
) -> BootstrapDecision:
    """Apply the 5%-of-interval endpoint rule and propose the next run size."""

    if current_replicates < 1 or increment < 1 or maximum_replicates < current_replicates:
        raise ValueError("replicate counts and increment are inconsistent")
    if not 0 < threshold < 1:
        raise ValueError("threshold must lie in (0, 1)")
    previous = _interval(previous_interval, "previous_interval")
    current = _interval(current_interval, "current_interval")
    width = current[1] - current[0]
    change = max(abs(current[0] - previous[0]), abs(current[1] - previous[1]))
    fraction = endpoint_change_fraction(previous, current)
    unstable = fraction > threshold
    reached_maximum = current_replicates >= maximum_replicates
    extend = unstable and not reached_maximum
    next_replicates = (
        min(current_replicates + increment, maximum_replicates) if extend else current_replicates
    )
    return BootstrapDecision(
        current_replicates=current_replicates,
        next_replicates=next_replicates,
        endpoint_change=change,
        interval_width=width,
        endpoint_change_fraction=fraction,
        threshold=threshold,
        extend=extend,
        reached_maximum=reached_maximum,
    )


def full_state_replication_schedule(
    plan: BootstrapPlan | None = None,
) -> tuple[int, ...]:
    """Return all allowable adaptive full-state run sizes, including the cap."""

    plan = plan or BootstrapPlan()
    sizes = [plan.full_state_replicates]
    while sizes[-1] < plan.maximum_replicates:
        sizes.append(min(sizes[-1] + plan.increment, plan.maximum_replicates))
    return tuple(sizes)


def _interval(values: Sequence[float], name: str) -> tuple[float, float]:
    try:
        lower, upper = values
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain exactly two endpoints") from exc
    lower = float(lower)
    upper = float(upper)
    if lower > upper:
        raise ValueError(f"{name} lower endpoint exceeds upper endpoint")
    if not (lower == lower and upper == upper):
        raise ValueError(f"{name} endpoints must not be NaN")
    if lower in {float("inf"), float("-inf")} or upper in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} endpoints must be finite")
    return lower, upper
