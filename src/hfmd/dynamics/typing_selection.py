"""Two-stage typing-selection utilities for aggregated restricted data.

The functions in this module operate on *cell counts*, not person-level rows.
They model (1) entry into pathogen testing and (2) resolution of a pathogen
result conditional on testing.  Keeping the two stages explicit makes the
selection estimand and its positivity diagnostics auditable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd  # type: ignore[import-untyped]

DEFAULT_COUNT_COLUMNS = ("eligible_count", "tested_count", "resolved_count")


@dataclass(frozen=True)
class TwoStageCounts:
    """Aggregated binomial counts for the two typing-selection stages."""

    testing: pd.DataFrame
    resolution: pd.DataFrame
    strata: tuple[str, ...]


@dataclass(frozen=True)
class WeightAudit:
    """Positivity and effective-sample-size diagnostics for IP weights."""

    n_cells: int
    represented_units: float
    probability_min: float
    probability_p01: float
    probability_p05: float
    probability_median: float
    probability_max: float
    fraction_probability_below_001: float
    fraction_probability_below_005: float
    raw_weight_min: float
    raw_weight_max: float
    truncated_weight_min: float
    truncated_weight_max: float
    truncation_lower: float
    truncation_upper: float
    fraction_truncated: float
    effective_sample_size: float
    effective_sample_fraction: float


@dataclass(frozen=True)
class IPWResult:
    """Raw and truncated inverse-probability weights plus their audit."""

    combined_probability: np.ndarray
    raw_weights: np.ndarray
    weights: np.ndarray
    audit: WeightAudit


def load_restricted_aggregate(
    path: str | Path,
    *,
    required_columns: Sequence[str] = DEFAULT_COUNT_COLUMNS,
) -> pd.DataFrame:
    """Load a restricted aggregate table and validate its count contract.

    Only CSV and Parquet inputs are accepted.  This function deliberately does
    not infer person-level schemas: callers must provide already aggregated
    count columns where ``resolved <= tested <= eligible``.
    """

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(source)
    suffixes = tuple(suffix.lower() for suffix in source.suffixes)
    if suffixes[-1:] == (".csv",) or suffixes[-2:] == (".csv", ".gz"):
        frame = pd.read_csv(source)
    elif suffixes[-1:] in {(".parquet",), (".pq",)}:
        frame = pd.read_parquet(source)
    else:
        raise ValueError("restricted aggregate must be CSV or Parquet")
    _validate_count_columns(frame, required_columns)
    return frame


def build_two_stage_counts(
    frame: pd.DataFrame,
    *,
    strata: Sequence[str],
    eligible_col: str = "eligible_count",
    tested_col: str = "tested_count",
    resolved_col: str = "resolved_count",
) -> TwoStageCounts:
    """Aggregate a joint table into testing and conditional-resolution counts."""

    strata_tuple = tuple(strata)
    if not strata_tuple:
        raise ValueError("at least one stratum column is required")
    required = (*strata_tuple, eligible_col, tested_col, resolved_col)
    _validate_count_columns(frame, required)
    _validate_nonnegative_integer_columns(frame, (eligible_col, tested_col, resolved_col))

    grouped = (
        frame.loc[:, list(required)]
        .groupby(list(strata_tuple), dropna=False, observed=True, as_index=False)[
            [eligible_col, tested_col, resolved_col]
        ]
        .sum()
    )
    _validate_nested_counts(grouped, eligible_col, tested_col, resolved_col)

    testing = grouped.loc[:, list(strata_tuple)].copy()
    testing["successes"] = grouped[tested_col].astype(float)
    testing["trials"] = grouped[eligible_col].astype(float)
    testing["failures"] = testing["trials"] - testing["successes"]
    testing["stage"] = "testing"

    resolution = grouped.loc[:, list(strata_tuple)].copy()
    resolution["successes"] = grouped[resolved_col].astype(float)
    resolution["trials"] = grouped[tested_col].astype(float)
    resolution["failures"] = resolution["trials"] - resolution["successes"]
    resolution["stage"] = "resolution_given_test"
    return TwoStageCounts(testing=testing, resolution=resolution, strata=strata_tuple)


def fit_aggregated_binomial_glm(
    successes: Sequence[float] | np.ndarray,
    trials: Sequence[float] | np.ndarray,
    design: Sequence[Sequence[float]] | np.ndarray,
    *,
    column_names: Sequence[str] | None = None,
    maxiter: int = 200,
) -> Any:
    """Fit a statsmodels Binomial GLM to aggregated successes/trials.

    The returned object is the standard ``GLMResults`` instance.  The response
    is a cell proportion and ``freq_weights`` is the number of trials, which is
    the statsmodels representation of aggregated binomial data.
    """

    try:
        import statsmodels.api as sm  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - exercised by environment QA
        raise RuntimeError("statsmodels is required for selection GLMs") from exc

    y = _as_finite_vector(successes, "successes")
    n = _as_finite_vector(trials, "trials")
    x = np.asarray(design, dtype=float)
    if x.ndim != 2 or x.shape[0] != y.size:
        raise ValueError("design must be a finite 2-D matrix with one row per cell")
    if not np.all(np.isfinite(x)):
        raise ValueError("design contains non-finite values")
    if np.any(n <= 0) or np.any(y < 0) or np.any(y > n):
        raise ValueError("aggregated binomial counts require 0 <= successes <= trials")
    if column_names is not None:
        if len(column_names) != x.shape[1]:
            raise ValueError("column_names length must equal the design width")
        x = pd.DataFrame(x, columns=list(column_names))
    model = sm.GLM(
        y / n,
        x,
        family=sm.families.Binomial(),
        freq_weights=n,
    )
    return model.fit(maxiter=maxiter, disp=False)


def combined_selection_probability(
    testing_probability: Sequence[float] | np.ndarray,
    resolution_probability: Sequence[float] | np.ndarray,
) -> np.ndarray:
    """Return P(testing) * P(resolution | testing) for each aggregate cell."""

    p_test = _as_probability_vector(testing_probability, "testing_probability")
    p_resolve = _as_probability_vector(resolution_probability, "resolution_probability")
    if p_test.shape != p_resolve.shape:
        raise ValueError("the two probability vectors must have the same shape")
    return np.asarray(p_test * p_resolve, dtype=float)


def truncated_ipw(
    testing_probability: Sequence[float] | np.ndarray,
    resolution_probability: Sequence[float] | np.ndarray,
    *,
    frequency: Sequence[float] | np.ndarray | None = None,
    lower_quantile: float = 0.01,
    upper_quantile: float = 0.99,
    stabilized_numerator: float | Sequence[float] | np.ndarray = 1.0,
) -> IPWResult:
    """Construct two-stage IP weights, truncate them, and audit positivity.

    Quantiles are computed with represented-unit frequencies when ``frequency``
    is supplied.  ESS likewise treats each row as an aggregate cell containing
    ``frequency`` exchangeable represented units.
    """

    if not 0 <= lower_quantile < upper_quantile <= 1:
        raise ValueError("truncation quantiles must satisfy 0 <= lower < upper <= 1")
    probability = combined_selection_probability(testing_probability, resolution_probability)
    if np.any(probability <= 0):
        raise ValueError("selection probabilities must be strictly positive")

    numerator = np.asarray(stabilized_numerator, dtype=float)
    if numerator.ndim == 0:
        numerator = np.full(probability.shape, float(numerator))
    if numerator.shape != probability.shape or not np.all(np.isfinite(numerator)):
        raise ValueError("stabilized_numerator must be finite and conformable")
    if np.any(numerator <= 0):
        raise ValueError("stabilized_numerator must be strictly positive")

    freq = (
        np.ones(probability.size, dtype=float)
        if frequency is None
        else _as_finite_vector(frequency, "frequency")
    )
    if freq.shape != probability.shape or np.any(freq <= 0):
        raise ValueError("frequency must be positive and conformable")

    raw = numerator / probability
    lower = _weighted_quantile(raw, lower_quantile, freq)
    upper = _weighted_quantile(raw, upper_quantile, freq)
    weights = np.clip(raw, lower, upper)
    changed = ~np.isclose(raw, weights, rtol=0.0, atol=1e-12)

    weighted_sum = float(np.sum(freq * weights))
    weighted_square_sum = float(np.sum(freq * weights * weights))
    ess = weighted_sum * weighted_sum / weighted_square_sum
    represented = float(np.sum(freq))
    probability_quantiles = np.asarray(
        [_weighted_quantile(probability, quantile, freq) for quantile in (0.01, 0.05, 0.5)],
        dtype=float,
    )
    audit = WeightAudit(
        n_cells=int(probability.size),
        represented_units=represented,
        probability_min=float(np.min(probability)),
        probability_p01=float(probability_quantiles[0]),
        probability_p05=float(probability_quantiles[1]),
        probability_median=float(probability_quantiles[2]),
        probability_max=float(np.max(probability)),
        fraction_probability_below_001=float(np.sum(freq * (probability < 0.01)) / represented),
        fraction_probability_below_005=float(np.sum(freq * (probability < 0.05)) / represented),
        raw_weight_min=float(np.min(raw)),
        raw_weight_max=float(np.max(raw)),
        truncated_weight_min=float(np.min(weights)),
        truncated_weight_max=float(np.max(weights)),
        truncation_lower=float(lower),
        truncation_upper=float(upper),
        fraction_truncated=float(np.sum(freq * changed) / represented),
        effective_sample_size=float(ess),
        effective_sample_fraction=float(ess / represented),
    )
    return IPWResult(
        combined_probability=probability,
        raw_weights=raw,
        weights=weights,
        audit=audit,
    )


def standardize_probability(
    probability: Sequence[float] | np.ndarray,
    target_frequency: Sequence[float] | np.ndarray,
) -> float:
    """Standardize predicted cell probabilities to a declared target mix."""

    p = _as_probability_vector(probability, "probability", allow_zero=True)
    frequency = _as_finite_vector(target_frequency, "target_frequency")
    if p.shape != frequency.shape or np.any(frequency < 0):
        raise ValueError("target_frequency must be non-negative and conformable")
    total = float(np.sum(frequency))
    if total <= 0:
        raise ValueError("target_frequency must have positive total mass")
    return float(np.sum(p * frequency) / total)


def _validate_count_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError("missing required aggregate columns: " + ", ".join(missing))
    count_columns = [column for column in DEFAULT_COUNT_COLUMNS if column in columns]
    _validate_nonnegative_integer_columns(frame, count_columns)
    if all(column in frame.columns for column in DEFAULT_COUNT_COLUMNS):
        _validate_nested_counts(frame, *DEFAULT_COUNT_COLUMNS)


def _validate_nonnegative_integer_columns(frame: pd.DataFrame, columns: Sequence[str]) -> None:
    for column in columns:
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or (values < 0).any():
            raise ValueError(f"{column} must contain finite non-negative counts")
        if not np.allclose(values, np.round(values)):
            raise ValueError(f"{column} must contain integer-valued counts")


def _validate_nested_counts(
    frame: pd.DataFrame,
    eligible_col: str,
    tested_col: str,
    resolved_col: str,
) -> None:
    eligible = pd.to_numeric(frame[eligible_col], errors="coerce").to_numpy(float)
    tested = pd.to_numeric(frame[tested_col], errors="coerce").to_numpy(float)
    resolved = pd.to_numeric(frame[resolved_col], errors="coerce").to_numpy(float)
    if not (
        np.all(np.isfinite(eligible))
        and np.all(np.isfinite(tested))
        and np.all(np.isfinite(resolved))
    ):
        raise ValueError("selection counts must be finite")
    if np.any(resolved > tested) or np.any(tested > eligible):
        raise ValueError("selection counts must satisfy resolved <= tested <= eligible")


def _as_finite_vector(values: Sequence[float] | np.ndarray, name: str) -> np.ndarray:
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or result.size == 0 or not np.all(np.isfinite(result)):
        raise ValueError(f"{name} must be a non-empty finite vector")
    return result


def _as_probability_vector(
    values: Sequence[float] | np.ndarray,
    name: str,
    *,
    allow_zero: bool = False,
) -> np.ndarray:
    result = _as_finite_vector(values, name)
    lower_invalid = result < 0 if allow_zero else result <= 0
    if np.any(lower_invalid) or np.any(result > 1):
        interval = "[0, 1]" if allow_zero else "(0, 1]"
        raise ValueError(f"{name} must lie in {interval}")
    return result


def _weighted_quantile(values: np.ndarray, quantile: float, weights: np.ndarray) -> float:
    order = np.argsort(values, kind="mergesort")
    ordered_values = values[order]
    ordered_weights = weights[order]
    cumulative = np.cumsum(ordered_weights) - 0.5 * ordered_weights
    cumulative /= np.sum(ordered_weights)
    return float(
        np.interp(
            quantile,
            cumulative,
            ordered_values,
            left=ordered_values[0],
            right=ordered_values[-1],
        )
    )
