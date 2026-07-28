from __future__ import annotations

import math

import pytest

from hfmd.dynamics.validation import (
    FORMAL_TEST_YEARS,
    FoldLogScore,
    evaluate_rolling_score_gate,
    rolling_origin_folds,
)


def _scores(
    total_differences: tuple[float, ...] | None = None,
    typing_differences: tuple[float, ...] | None = None,
) -> tuple[list[FoldLogScore], list[FoldLogScore]]:
    total_differences = total_differences or (0.0,) * len(FORMAL_TEST_YEARS)
    typing_differences = typing_differences or (0.0,) * len(FORMAL_TEST_YEARS)
    reference = [FoldLogScore(year, -100, -50) for year in FORMAL_TEST_YEARS]
    candidate = [
        FoldLogScore(year, -100 + total_delta, -50 + typing_delta)
        for year, total_delta, typing_delta in zip(
            FORMAL_TEST_YEARS,
            total_differences,
            typing_differences,
            strict=True,
        )
    ]
    return candidate, reference


def test_builds_seven_expanding_rolling_folds_from_unsorted_duplicate_years() -> None:
    available = [*range(2010, 2026), 2015, 2010]

    folds = rolling_origin_folds(reversed(available), minimum_training_years=5)

    assert tuple(fold.test_year for fold in folds) == FORMAL_TEST_YEARS
    assert tuple(fold.fold_id for fold in folds) == tuple(
        f"rolling-{year}" for year in FORMAL_TEST_YEARS
    )
    assert folds[0].train_years == tuple(range(2010, 2019))
    assert folds[-1].train_years == tuple(range(2010, 2025))
    assert all(fold.test_year not in fold.train_years for fold in folds)


@pytest.mark.parametrize(
    ("available", "kwargs", "message"),
    [
        (range(2010, 2025), {}, "omit formal test years: 2025"),
        (range(2010, 2026), {"test_years": range(2018, 2025)}, "must use test years"),
        (range(2010, 2026), {"minimum_training_years": 0}, "must be positive"),
        (
            range(2019, 2026),
            {"minimum_training_years": 1},
            "test year 2019 has only 0 training years",
        ),
    ],
)
def test_rolling_origin_folds_rejects_incomplete_or_nonformal_designs(
    available: object, kwargs: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        rolling_origin_folds(available, **kwargs)  # type: ignore[arg-type]


def test_score_gate_enforces_joint_and_component_thresholds() -> None:
    # Joint wins in five folds; totals non-inferior in five; typing in six.
    candidate, reference = _scores(
        total_differences=(1, 1, 1, 1, 1, -1, -1),
        typing_differences=(1, 1, 1, 1, 1, 1, -1),
    )

    gate = evaluate_rolling_score_gate(candidate, reference)

    assert gate.passed
    assert gate.joint_wins == 5
    assert gate.total_noninferior == 5
    assert gate.typing_noninferior == 6
    assert gate.required_joint_wins == 5
    assert gate.required_component_noninferior == 4
    assert gate.years == FORMAL_TEST_YEARS
    assert gate.joint_differences == (2, 2, 2, 2, 2, 0, -2)
    assert gate.total_differences == (1, 1, 1, 1, 1, -1, -1)
    assert gate.typing_differences == (1, 1, 1, 1, 1, 1, -1)


def test_score_gate_fails_when_either_component_lacks_four_noninferior_folds() -> None:
    candidate, reference = _scores(
        total_differences=(2, 2, 2, -1, -1, -1, -1),
        typing_differences=(2, 2, 2, 2, 2, 2, 2),
    )

    gate = evaluate_rolling_score_gate(candidate, reference)

    assert gate.joint_wins == 7
    assert gate.total_noninferior == 3
    assert gate.typing_noninferior == 7
    assert not gate.passed


def test_score_gate_tolerance_is_strict_for_wins_and_symmetric_for_noninferiority() -> None:
    candidate, reference = _scores(
        total_differences=(-0.125, -0.125, -0.125, -0.125, 0, 0, 0),
        typing_differences=(0.25, 0.25, 0.25, 0.25, 0.125, 0.125, 0.125),
    )

    gate = evaluate_rolling_score_gate(
        candidate,
        reference,
        joint_wins_required=4,
        component_noninferior_required=4,
        tolerance=0.125,
    )

    # First four joint differences are exactly tolerance and therefore not wins.
    assert gate.joint_wins == 0
    assert gate.total_noninferior == 7
    assert gate.typing_noninferior == 7
    assert not gate.passed


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"tolerance": -0.1}, "tolerance must be non-negative"),
        ({"joint_wins_required": 0}, "joint_wins_required is outside"),
        ({"joint_wins_required": 8}, "joint_wins_required is outside"),
        ({"component_noninferior_required": 0}, "component_noninferior_required is outside"),
        ({"component_noninferior_required": 8}, "component_noninferior_required is outside"),
    ],
)
def test_score_gate_rejects_invalid_thresholds(
    kwargs: dict[str, float | int], message: str
) -> None:
    candidate, reference = _scores()
    with pytest.raises(ValueError, match=message):
        evaluate_rolling_score_gate(candidate, reference, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("which", "mutation", "message"),
    [
        ("candidate", "missing", "candidate scores must contain exactly"),
        ("reference", "extra", "reference scores must contain exactly"),
        ("candidate", "duplicate", "candidate has duplicate score for 2019"),
        ("reference", "nonfinite_total", "reference contains a non-finite log score"),
        ("candidate", "nonfinite_typing", "candidate contains a non-finite log score"),
    ],
)
def test_score_gate_rejects_invalid_fold_sets(which: str, mutation: str, message: str) -> None:
    candidate, reference = _scores()
    target = candidate if which == "candidate" else reference
    if mutation == "missing":
        target.pop()
    elif mutation == "extra":
        target.append(FoldLogScore(2026, -1, -1))
    elif mutation == "duplicate":
        target.append(target[0])
    elif mutation == "nonfinite_total":
        target[0] = FoldLogScore(target[0].test_year, math.inf, target[0].typing)
    elif mutation == "nonfinite_typing":
        target[0] = FoldLogScore(target[0].test_year, target[0].total_cases, math.nan)
    else:  # pragma: no cover - protects the test table itself
        raise AssertionError(mutation)

    with pytest.raises(ValueError, match=message):
        evaluate_rolling_score_gate(candidate, reference)


def test_fold_joint_score_is_exact_sum() -> None:
    score = FoldLogScore(2020, total_cases=-2.5, typing=-1.25)
    assert score.joint == pytest.approx(-3.75)
