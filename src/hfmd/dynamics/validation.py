"""Rolling-origin validation contracts and scientific score gates."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from math import isfinite

FORMAL_TEST_YEARS = tuple(range(2019, 2026))


@dataclass(frozen=True)
class RollingOriginFold:
    """A one-calendar-year test fold trained only on earlier years."""

    fold_id: str
    test_year: int
    train_years: tuple[int, ...]


@dataclass(frozen=True)
class FoldLogScore:
    """Held-out score decomposition for one fitted model and test year."""

    test_year: int
    total_cases: float
    typing: float

    @property
    def joint(self) -> float:
        return self.total_cases + self.typing


@dataclass(frozen=True)
class RollingScoreGate:
    """Result of the predeclared M2-versus-M1 held-out score gate."""

    passed: bool
    joint_wins: int
    total_noninferior: int
    typing_noninferior: int
    required_joint_wins: int
    required_component_noninferior: int
    years: tuple[int, ...]
    joint_differences: tuple[float, ...]
    total_differences: tuple[float, ...]
    typing_differences: tuple[float, ...]


def rolling_origin_folds(
    available_years: Iterable[int],
    *,
    test_years: Sequence[int] = FORMAL_TEST_YEARS,
    minimum_training_years: int = 1,
) -> tuple[RollingOriginFold, ...]:
    """Build formal 2019--2025 expanding-window, one-year-ahead folds."""

    years = tuple(sorted({int(year) for year in available_years}))
    tests = tuple(int(year) for year in test_years)
    if tests != FORMAL_TEST_YEARS:
        raise ValueError("formal rolling validation must use test years 2019 through 2025")
    missing = [year for year in tests if year not in years]
    if missing:
        raise ValueError("available data omit formal test years: " + ", ".join(map(str, missing)))
    if minimum_training_years < 1:
        raise ValueError("minimum_training_years must be positive")

    folds: list[RollingOriginFold] = []
    for test_year in tests:
        train = tuple(year for year in years if year < test_year)
        if len(train) < minimum_training_years:
            raise ValueError(f"test year {test_year} has only {len(train)} training years")
        folds.append(
            RollingOriginFold(
                fold_id=f"rolling-{test_year}",
                test_year=test_year,
                train_years=train,
            )
        )
    return tuple(folds)


def evaluate_rolling_score_gate(
    candidate: Sequence[FoldLogScore],
    reference: Sequence[FoldLogScore],
    *,
    joint_wins_required: int = 5,
    component_noninferior_required: int = 4,
    tolerance: float = 0.0,
) -> RollingScoreGate:
    """Evaluate the predeclared held-out score gate for candidate M2 vs M1.

    Higher log score is better.  Candidate joint score must be strictly higher
    in at least five folds; each score component must be no worse (within the
    declared tolerance) in at least four folds.
    """

    if tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if not 1 <= joint_wins_required <= len(FORMAL_TEST_YEARS):
        raise ValueError("joint_wins_required is outside the formal fold count")
    if not 1 <= component_noninferior_required <= len(FORMAL_TEST_YEARS):
        raise ValueError("component_noninferior_required is outside the formal fold count")

    candidate_by_year = _formal_score_map(candidate, "candidate")
    reference_by_year = _formal_score_map(reference, "reference")
    total_differences = tuple(
        candidate_by_year[year].total_cases - reference_by_year[year].total_cases
        for year in FORMAL_TEST_YEARS
    )
    typing_differences = tuple(
        candidate_by_year[year].typing - reference_by_year[year].typing
        for year in FORMAL_TEST_YEARS
    )
    joint_differences = tuple(
        total + typing for total, typing in zip(total_differences, typing_differences, strict=True)
    )
    joint_wins = sum(value > tolerance for value in joint_differences)
    total_noninferior = sum(value >= -tolerance for value in total_differences)
    typing_noninferior = sum(value >= -tolerance for value in typing_differences)
    passed = (
        joint_wins >= joint_wins_required
        and total_noninferior >= component_noninferior_required
        and typing_noninferior >= component_noninferior_required
    )
    return RollingScoreGate(
        passed=passed,
        joint_wins=joint_wins,
        total_noninferior=total_noninferior,
        typing_noninferior=typing_noninferior,
        required_joint_wins=joint_wins_required,
        required_component_noninferior=component_noninferior_required,
        years=FORMAL_TEST_YEARS,
        joint_differences=joint_differences,
        total_differences=total_differences,
        typing_differences=typing_differences,
    )


def _formal_score_map(scores: Sequence[FoldLogScore], name: str) -> dict[int, FoldLogScore]:
    result: dict[int, FoldLogScore] = {}
    for score in scores:
        if not isfinite(score.total_cases) or not isfinite(score.typing):
            raise ValueError(f"{name} contains a non-finite log score")
        if score.test_year in result:
            raise ValueError(f"{name} has duplicate score for {score.test_year}")
        result[score.test_year] = score
    years = tuple(sorted(result))
    if years != FORMAL_TEST_YEARS:
        raise ValueError(f"{name} scores must contain exactly 2019 through 2025")
    return result
