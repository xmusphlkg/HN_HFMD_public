from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.special import gammaln
from scipy.stats import nbinom

from hfmd.dynamics.observation import (
    age_specific_nb2_loglik,
    ar1_residual_score,
    dirichlet_concentration,
    dirichlet_multinomial_loglik,
)


def test_age_specific_nb2_matches_scipy_for_mapped_dispersion() -> None:
    observed = np.array([2, 7, 3])
    mean = np.array([2.5, 5.0, 4.5])
    age = np.array(["young", "older", "young"])
    dispersion = {"young": 0.2, "older": 0.5}

    actual = age_specific_nb2_loglik(observed, mean, dispersion, age=age, reduce=False)
    alpha = np.array([0.2, 0.5, 0.2])
    size = 1 / alpha
    expected = nbinom.logpmf(observed, size, size / (size + mean))

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    assert age_specific_nb2_loglik(observed, mean, dispersion, age=age) == pytest.approx(
        expected.sum()
    )


def test_age_specific_nb2_supports_scalar_per_observation_and_indexed_dispersion() -> None:
    observed = np.array([0, 1, 4, 2])
    mean = np.array([0.5, 1.5, 3.0, 2.5])

    scalar = age_specific_nb2_loglik(observed, mean, 0.25, reduce=False)
    per_observation = age_specific_nb2_loglik(
        observed,
        mean,
        np.full(observed.shape, 0.25),
        reduce=False,
    )
    indexed = age_specific_nb2_loglik(
        observed,
        mean,
        [0.25, 0.5],
        age=[0, 0, 1, 0],
        reduce=False,
    )

    np.testing.assert_allclose(scalar, per_observation)
    assert indexed.shape == observed.shape
    assert np.all(np.isfinite(indexed))


@pytest.mark.parametrize(
    ("observed", "mean", "message"),
    [
        ([], [], "observed must contain"),
        ([1, -1], [1, 1], "observed must contain"),
        ([1, np.nan], [1, 1], "observed must contain"),
        ([1, 1.5], [1, 1], "integer-valued"),
        ([1, 2], [1], "mean must be"),
        ([1, 2], [1, 0], "mean must be"),
        ([1, 2], [1, np.inf], "mean must be"),
    ],
)
def test_age_specific_nb2_rejects_invalid_counts_and_means(
    observed: list[float], mean: list[float], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        age_specific_nb2_loglik(observed, mean, 0.2)


@pytest.mark.parametrize(
    ("dispersion", "age", "message"),
    [
        ({"young": 0.2}, None, "age labels are required"),
        ({"young": 0.2}, ["young"], "age labels must match"),
        ({"young": 0.2}, ["young", "older", "young"], "missing age label"),
        ({"young": 0.0}, ["young", "young", "young"], "finite and positive"),
        ([0.2], None, "scalar or match observed"),
        ([0.2, 0.5], ["young", "older", "young"], "integer age indices"),
        ([0.2, 0.5], [0, 2, 1], "outside the dispersion vector"),
        ([0.2, np.nan, 0.3], None, "finite and positive"),
        (0.0, None, "finite and positive"),
    ],
)
def test_age_specific_nb2_rejects_invalid_dispersion_contracts(
    dispersion: object, age: list[object] | None, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        age_specific_nb2_loglik(
            [1, 2, 3],
            [1.0, 2.0, 3.0],
            dispersion,  # type: ignore[arg-type]
            age=age,
        )


def test_dirichlet_multinomial_matches_manual_formula_and_reduces_rows() -> None:
    counts = np.array([[2, 1, 3], [0, 4, 2]])
    alpha = np.array([[1.5, 2.0, 2.5], [2.0, 1.0, 3.0]])

    actual = dirichlet_multinomial_loglik(counts, alpha, reduce=False)
    expected = []
    for row, row_alpha in zip(counts, alpha, strict=True):
        total = row.sum()
        expected.append(
            gammaln(total + 1)
            - gammaln(row + 1).sum()
            + gammaln(row_alpha.sum())
            - gammaln(total + row_alpha.sum())
            + (gammaln(row + row_alpha) - gammaln(row_alpha)).sum()
        )

    np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
    assert dirichlet_multinomial_loglik(counts, alpha) == pytest.approx(sum(expected))


def test_dirichlet_multinomial_broadcasts_concentration_and_accepts_one_row() -> None:
    counts = [2, 1, 3]
    alpha = [1.5, 2.0, 2.5]

    row_scores = dirichlet_multinomial_loglik(counts, alpha, reduce=False)

    assert row_scores.shape == (1,)
    assert dirichlet_multinomial_loglik([counts, counts], alpha) == pytest.approx(2 * row_scores[0])


@pytest.mark.parametrize(
    ("counts", "concentration", "message"),
    [
        ([], [1, 1], "counts must contain"),
        ([1, -1], [1, 1], "counts must contain"),
        ([1, 0.5], [1, 1], "integer-valued"),
        ([[1], [2]], [1], "categories>=2"),
        ([[1, 2], [3, 4]], [1, 1, 1], "width must match"),
        ([[1, 2], [3, 4]], [[1, 1]], "finite, positive, and conformable"),
        ([[1, 2]], [1, 0], "finite, positive, and conformable"),
        ([[1, 2]], [1, np.inf], "finite, positive, and conformable"),
    ],
)
def test_dirichlet_multinomial_rejects_invalid_contracts(
    counts: object, concentration: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        dirichlet_multinomial_loglik(counts, concentration)  # type: ignore[arg-type]


def test_dirichlet_concentration_supports_vector_and_row_specific_precision() -> None:
    np.testing.assert_allclose(
        dirichlet_concentration([0.2, 0.3, 0.5], np.array([10.0])),
        [2, 3, 5],
    )
    shares = np.array([[0.2, 0.3, 0.5], [0.1, 0.2, 0.7]])
    np.testing.assert_allclose(
        dirichlet_concentration(shares, [10, 20]),
        [[2, 3, 5], [2, 4, 14]],
    )
    np.testing.assert_allclose(
        dirichlet_concentration(shares, 5),
        shares * 5,
    )


@pytest.mark.parametrize(
    ("shares", "precision", "message"),
    [
        (1.0, 1, "vector or matrix"),
        ([[[0.5, 0.5]]], 1, "vector or matrix"),
        ([0.0, 1.0], 1, "strictly positive"),
        ([0.5, np.nan], 1, "strictly positive"),
        ([0.2, 0.2], 1, "sum to one"),
        ([0.5, 0.5], 0, "precision must be"),
        ([0.5, 0.5], np.nan, "precision must be"),
        ([0.5, 0.5], [1, 2], "vector shares require scalar"),
        ([[0.5, 0.5], [0.4, 0.6]], [1], "row-specific precision"),
        ([[0.5, 0.5], [0.4, 0.6]], [[1], [2]], "row-specific precision"),
    ],
)
def test_dirichlet_concentration_rejects_invalid_inputs(
    shares: object, precision: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        dirichlet_concentration(shares, precision)  # type: ignore[arg-type]


def test_ar1_score_uses_stationary_initial_density() -> None:
    residuals = np.array([0.5, -0.1, 0.2])
    rho = 0.4
    sd = 0.7
    stationary_variance = sd**2 / (1 - rho**2)
    expected = -0.5 * (
        math.log(2 * math.pi * stationary_variance) + residuals[0] ** 2 / stationary_variance
    )
    innovations = residuals[1:] - rho * residuals[:-1]
    expected += np.sum(-0.5 * (np.log(2 * np.pi * sd**2) + innovations**2 / sd**2))

    assert ar1_residual_score(residuals, rho, sd) == pytest.approx(expected)


def test_ar1_returns_one_score_per_independent_series_and_handles_singletons() -> None:
    residuals = np.array([[0.2, 0.1, -0.1], [1.0, 0.4, 0.2]])

    row_scores = ar1_residual_score(residuals, 0.3, 0.5, reduce=False)
    singleton = ar1_residual_score([[0.2], [1.0]], 0.3, 0.5, reduce=False)

    assert row_scores.shape == (2,)
    assert ar1_residual_score(residuals, 0.3, 0.5) == pytest.approx(row_scores.sum())
    assert singleton.shape == (2,)
    assert np.all(np.isfinite(singleton))


@pytest.mark.parametrize(
    ("residuals", "rho", "innovation_sd", "message"),
    [
        ([], 0.1, 1, "one or more finite series"),
        ([[[]]], 0.1, 1, "one or more finite series"),
        ([0, np.nan], 0.1, 1, "one or more finite series"),
        ([0], 1.0, 1, r"abs\(rho\) < 1"),
        ([0], -1.0, 1, r"abs\(rho\) < 1"),
        ([0], np.nan, 1, r"abs\(rho\) < 1"),
        ([0], 0.1, 0, "finite and positive"),
        ([0], 0.1, np.inf, "finite and positive"),
    ],
)
def test_ar1_rejects_invalid_series_and_parameters(
    residuals: object, rho: float, innovation_sd: float, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        ar1_residual_score(residuals, rho, innovation_sd)  # type: ignore[arg-type]
