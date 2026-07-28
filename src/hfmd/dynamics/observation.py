"""Observation-model log scores used by transmission-model comparisons."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
from scipy.special import gammaln  # type: ignore[import-untyped]


def age_specific_nb2_loglik(
    observed: Sequence[float] | np.ndarray,
    mean: Sequence[float] | np.ndarray,
    dispersion: float | Sequence[float] | Mapping[object, float] | np.ndarray,
    *,
    age: Sequence[object] | np.ndarray | None = None,
    reduce: bool = True,
) -> float | np.ndarray:
    """Return NB2 log likelihood with age-specific overdispersion.

    ``dispersion`` is the NB2 ``alpha`` in ``Var(Y)=mu+alpha*mu**2``.  It can be
    scalar, one value per observation, or a mapping keyed by the supplied age
    labels.  Setting ``reduce=False`` returns observation-level contributions.
    """

    y = _count_array(observed, "observed")
    mu = np.asarray(mean, dtype=float)
    if mu.shape != y.shape or not np.all(np.isfinite(mu)) or np.any(mu <= 0):
        raise ValueError("mean must be finite, positive, and match observed")
    alpha = _resolve_dispersion(dispersion, y.shape, age)
    size = 1.0 / alpha
    probability = size / (size + mu)
    terms = (
        gammaln(y + size)
        - gammaln(size)
        - gammaln(y + 1.0)
        + size * np.log(probability)
        + y * np.log1p(-probability)
    )
    return float(np.sum(terms)) if reduce else terms


def dirichlet_multinomial_loglik(
    counts: Sequence[Sequence[float]] | np.ndarray,
    concentration: Sequence[float] | Sequence[Sequence[float]] | np.ndarray,
    *,
    reduce: bool = True,
) -> float | np.ndarray:
    """Return Dirichlet-multinomial log likelihood for one or more count rows."""

    y = _count_array(counts, "counts")
    if y.ndim == 1:
        y = y[np.newaxis, :]
    if y.ndim != 2 or y.shape[1] < 2:
        raise ValueError("counts must have shape (observations, categories>=2)")
    alpha = np.asarray(concentration, dtype=float)
    if alpha.ndim == 1:
        if alpha.shape[0] != y.shape[1]:
            raise ValueError("concentration width must match the number of categories")
        alpha = np.broadcast_to(alpha, y.shape)
    if alpha.shape != y.shape or not np.all(np.isfinite(alpha)) or np.any(alpha <= 0):
        raise ValueError("concentration must be finite, positive, and conformable")

    totals = np.sum(y, axis=1)
    alpha_total = np.sum(alpha, axis=1)
    terms = (
        gammaln(totals + 1.0)
        - np.sum(gammaln(y + 1.0), axis=1)
        + gammaln(alpha_total)
        - gammaln(totals + alpha_total)
        + np.sum(gammaln(y + alpha) - gammaln(alpha), axis=1)
    )
    return float(np.sum(terms)) if reduce else terms


def dirichlet_concentration(
    shares: Sequence[float] | Sequence[Sequence[float]] | np.ndarray,
    precision: float | Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Convert simplex shares and a positive precision into concentration."""

    p = np.asarray(shares, dtype=float)
    if p.ndim not in {1, 2} or not np.all(np.isfinite(p)) or np.any(p <= 0):
        raise ValueError("shares must be a finite, strictly positive vector or matrix")
    if not np.allclose(np.sum(p, axis=-1), 1.0, rtol=1e-8, atol=1e-10):
        raise ValueError("shares must sum to one")
    phi = np.asarray(precision, dtype=float)
    if not np.all(np.isfinite(phi)) or np.any(phi <= 0):
        raise ValueError("precision must be finite and positive")
    if p.ndim == 1:
        if phi.ndim > 0 and phi.size != 1:
            raise ValueError("vector shares require scalar precision")
        return p * float(phi.reshape(-1)[0] if phi.ndim else phi)
    if phi.ndim == 0:
        return p * float(phi)
    if phi.ndim != 1 or phi.shape[0] != p.shape[0]:
        raise ValueError("matrix shares require scalar or row-specific precision")
    return np.asarray(p * phi[:, np.newaxis], dtype=float)


def ar1_residual_score(
    residuals: Sequence[float] | Sequence[Sequence[float]] | np.ndarray,
    rho: float,
    innovation_sd: float,
    *,
    reduce: bool = True,
) -> float | np.ndarray:
    """Score residual series under a stationary zero-mean Gaussian AR(1).

    A 2-D input is interpreted as one independent series per row.  The first
    residual in each row uses the stationary variance; later residuals use the
    innovation variance.
    """

    values = np.asarray(residuals, dtype=float)
    if values.ndim == 1:
        values = values[np.newaxis, :]
    if values.ndim != 2 or values.shape[1] == 0 or not np.all(np.isfinite(values)):
        raise ValueError("residuals must contain one or more finite series")
    if not np.isfinite(rho) or abs(rho) >= 1:
        raise ValueError("rho must be finite and satisfy abs(rho) < 1")
    if not np.isfinite(innovation_sd) or innovation_sd <= 0:
        raise ValueError("innovation_sd must be finite and positive")

    variance = innovation_sd * innovation_sd
    stationary_variance = variance / (1.0 - rho * rho)
    initial = -0.5 * (
        np.log(2.0 * np.pi * stationary_variance)
        + values[:, 0] * values[:, 0] / stationary_variance
    )
    if values.shape[1] == 1:
        scores = initial
    else:
        innovations = values[:, 1:] - rho * values[:, :-1]
        conditional = -0.5 * (np.log(2.0 * np.pi * variance) + innovations * innovations / variance)
        scores = initial + np.sum(conditional, axis=1)
    return float(np.sum(scores)) if reduce else scores


def _count_array(values: object, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.size == 0 or not np.all(np.isfinite(result)) or np.any(result < 0):
        raise ValueError(f"{name} must contain finite non-negative counts")
    if not np.allclose(result, np.round(result)):
        raise ValueError(f"{name} must be integer-valued")
    return result


def _resolve_dispersion(
    dispersion: float | Sequence[float] | Mapping[object, float] | np.ndarray,
    shape: tuple[int, ...],
    age: Sequence[object] | np.ndarray | None,
) -> np.ndarray:
    if isinstance(dispersion, Mapping):
        if age is None:
            raise ValueError("age labels are required for mapped dispersion")
        labels = np.asarray(age, dtype=object)
        if labels.shape != shape:
            raise ValueError("age labels must match observed")
        try:
            result = np.asarray([dispersion[label] for label in labels.flat], dtype=float).reshape(
                shape
            )
        except KeyError as exc:
            raise ValueError(f"dispersion is missing age label {exc.args[0]!r}") from exc
    else:
        result = np.asarray(dispersion, dtype=float)
        if result.ndim == 0:
            result = np.full(shape, float(result))
        elif result.shape != shape:
            if age is None or result.ndim != 1:
                raise ValueError("dispersion must be scalar or match observed")
            labels = np.asarray(age)
            if labels.shape != shape or not np.issubdtype(labels.dtype, np.integer):
                raise ValueError("indexed dispersion requires integer age indices")
            if np.any(labels < 0) or np.any(labels >= result.size):
                raise ValueError("age index is outside the dispersion vector")
            result = result[labels]
    if not np.all(np.isfinite(result)) or np.any(result <= 0):
        raise ValueError("dispersion must be finite and positive")
    return result
