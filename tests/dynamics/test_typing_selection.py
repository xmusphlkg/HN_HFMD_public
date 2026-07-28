from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from hfmd.dynamics.typing_selection import (
    build_two_stage_counts,
    combined_selection_probability,
    fit_aggregated_binomial_glm,
    load_restricted_aggregate,
    standardize_probability,
    truncated_ipw,
)


def _aggregate_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "age_group": ["0-2", "0-2", "3-5"],
            "severe": [0, 0, 1],
            "eligible_count": [40, 60, 30],
            "tested_count": [10, 20, 24],
            "resolved_count": [8, 17, 22],
        }
    )


@pytest.mark.parametrize(("suffix", "compression"), [(".csv", None), (".csv.gz", "gzip")])
def test_loads_csv_aggregate_without_person_level_inference(
    tmp_path: Path, suffix: str, compression: str | None
) -> None:
    source = _aggregate_frame()
    path = tmp_path / f"synthetic{suffix}"
    source.to_csv(path, index=False, compression=compression)

    loaded = load_restricted_aggregate(path)

    pd.testing.assert_frame_equal(source, loaded)


@pytest.mark.parametrize("suffix", [".parquet", ".pq"])
def test_loads_supported_parquet_suffixes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    source = _aggregate_frame()
    path = tmp_path / f"aggregate{suffix}"
    path.touch()
    seen: list[Path] = []

    def fake_read_parquet(received: Path) -> pd.DataFrame:
        seen.append(received)
        return source.copy()

    monkeypatch.setattr(pd, "read_parquet", fake_read_parquet)

    loaded = load_restricted_aggregate(path)

    pd.testing.assert_frame_equal(source, loaded)
    assert seen == [path]


def test_load_restricted_aggregate_rejects_missing_unsupported_and_malformed_files(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_restricted_aggregate(tmp_path / "missing.csv")

    unsupported = tmp_path / "aggregate.xlsx"
    unsupported.touch()
    with pytest.raises(ValueError, match="must be CSV or Parquet"):
        load_restricted_aggregate(unsupported)

    missing_column = tmp_path / "missing_column.csv"
    pd.DataFrame({"eligible_count": [10], "tested_count": [5]}).to_csv(missing_column, index=False)
    with pytest.raises(ValueError, match="missing required aggregate columns: resolved_count"):
        load_restricted_aggregate(missing_column)

    impossible = tmp_path / "impossible.csv"
    pd.DataFrame({"eligible_count": [10], "tested_count": [8], "resolved_count": [9]}).to_csv(
        impossible, index=False
    )
    with pytest.raises(ValueError, match="resolved <= tested <= eligible"):
        load_restricted_aggregate(impossible)


def test_load_restricted_aggregate_nested_check_rejects_nonfinite_counts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nonfinite.csv"
    pd.DataFrame({"eligible_count": [np.inf], "tested_count": [1], "resolved_count": [1]}).to_csv(
        path, index=False
    )

    # An explicitly empty required set still performs the cross-column nesting check
    # whenever all three canonical count columns are present.
    with pytest.raises(ValueError, match="selection counts must be finite"):
        load_restricted_aggregate(path, required_columns=())


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("eligible_count", -1, "finite non-negative counts"),
        ("tested_count", 1.5, "integer-valued counts"),
        ("resolved_count", np.nan, "finite non-negative counts"),
    ],
)
def test_load_restricted_aggregate_rejects_invalid_count_cells(
    tmp_path: Path, column: str, value: float, message: str
) -> None:
    source = pd.DataFrame({"eligible_count": [10], "tested_count": [6], "resolved_count": [5]})
    source[column] = pd.Series([value], dtype=float)
    path = tmp_path / "invalid.csv"
    source.to_csv(path, index=False)

    with pytest.raises(ValueError, match=message):
        load_restricted_aggregate(path)


def test_builds_nested_stage_counts_and_preserves_missing_strata() -> None:
    source = _aggregate_frame()
    source.loc[len(source)] = [None, 0, 5, 2, 1]

    stages = build_two_stage_counts(source, strata=["age_group", "severe"])

    first = stages.testing.loc[stages.testing["age_group"] == "0-2"].iloc[0]
    assert first["trials"] == 100
    assert first["successes"] == 30
    assert first["failures"] == 70
    assert first["stage"] == "testing"
    resolved = stages.resolution.loc[stages.resolution["age_group"] == "0-2"].iloc[0]
    assert resolved["trials"] == 30
    assert resolved["successes"] == 25
    assert resolved["failures"] == 5
    assert resolved["stage"] == "resolution_given_test"
    assert stages.testing["age_group"].isna().sum() == 1
    assert stages.resolution["age_group"].isna().sum() == 1
    assert stages.strata == ("age_group", "severe")


def test_build_two_stage_counts_supports_custom_count_column_names() -> None:
    source = pd.DataFrame(
        {
            "county": ["A", "A", "B"],
            "eligible": [10, 20, 30],
            "tested": [5, 10, 15],
            "resolved": [4, 7, 12],
        }
    )

    stages = build_two_stage_counts(
        source,
        strata=["county"],
        eligible_col="eligible",
        tested_col="tested",
        resolved_col="resolved",
    )

    county_a = stages.testing.loc[stages.testing["county"] == "A"].iloc[0]
    assert county_a["trials"] == 30
    assert county_a["successes"] == 15


def test_build_two_stage_counts_rejects_missing_or_empty_strata() -> None:
    source = _aggregate_frame()
    with pytest.raises(ValueError, match="at least one stratum"):
        build_two_stage_counts(source, strata=[])
    with pytest.raises(ValueError, match="missing required aggregate columns: county"):
        build_two_stage_counts(source, strata=["county"])


@pytest.mark.parametrize(
    ("eligible", "tested", "resolved", "message"),
    [
        (10, 8, 9, "resolved <= tested <= eligible"),
        (10, 11, 9, "resolved <= tested <= eligible"),
        (10.5, 8, 7, "integer-valued counts"),
        (10, -1, 0, "finite non-negative counts"),
    ],
)
def test_build_two_stage_counts_rejects_invalid_nested_counts(
    eligible: float, tested: float, resolved: float, message: str
) -> None:
    source = pd.DataFrame(
        {
            "age_group": ["0-2"],
            "eligible_count": [eligible],
            "tested_count": [tested],
            "resolved_count": [resolved],
        }
    )

    with pytest.raises(ValueError, match=message):
        build_two_stage_counts(source, strata=["age_group"])


def test_aggregated_glm_recovers_positive_covariate_effect_with_named_columns() -> None:
    x_binary = np.tile([0.0, 1.0], 6)
    design = np.column_stack([np.ones(x_binary.size), x_binary])
    trials = np.full(x_binary.size, 100.0)
    # Small cell-to-cell variation avoids a degenerate two-pattern fit.
    successes = np.array([18, 63, 22, 67, 20, 65, 24, 69, 19, 64, 23, 68])

    result = fit_aggregated_binomial_glm(
        successes,
        trials,
        design,
        column_names=["intercept", "severe"],
    )

    assert result.params["severe"] > 1.5
    predicted = result.predict(pd.DataFrame({"intercept": [1, 1], "severe": [0, 1]}))
    assert predicted.iloc[0] < predicted.iloc[1]


def test_aggregated_glm_accepts_unnamed_design_matrix() -> None:
    successes = np.array([10, 30, 20, 40], dtype=float)
    trials = np.full(4, 50.0)
    design = np.column_stack([np.ones(4), [0, 0, 1, 1]])

    result = fit_aggregated_binomial_glm(successes, trials, design)

    assert result.params.shape == (2,)
    assert np.all(np.isfinite(result.params))


@pytest.mark.parametrize(
    ("successes", "trials", "design", "column_names", "message"),
    [
        ([], [], [], None, "successes must be a non-empty finite vector"),
        ([[1]], [2], [[1]], None, "successes must be a non-empty finite vector"),
        ([1], [np.nan], [[1]], None, "trials must be a non-empty finite vector"),
        ([1, 2], [2, 3], [1, 1], None, "design must be a finite 2-D matrix"),
        ([1, 2], [2, 3], [[1]], None, "design must be a finite 2-D matrix"),
        ([1], [2], [[np.inf]], None, "design contains non-finite"),
        ([1], [0], [[1]], None, "0 <= successes <= trials"),
        ([-1], [2], [[1]], None, "0 <= successes <= trials"),
        ([3], [2], [[1]], None, "0 <= successes <= trials"),
        ([1], [2], [[1, 0]], ["intercept"], "column_names length"),
    ],
)
def test_aggregated_glm_rejects_invalid_contracts(
    successes: object,
    trials: object,
    design: object,
    column_names: list[str] | None,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        fit_aggregated_binomial_glm(
            successes,  # type: ignore[arg-type]
            trials,  # type: ignore[arg-type]
            design,  # type: ignore[arg-type]
            column_names=column_names,
        )


def test_combined_selection_probability_multiplies_stages() -> None:
    np.testing.assert_allclose(
        combined_selection_probability([0.5, 0.25], [0.8, 0.4]),
        [0.4, 0.1],
    )


@pytest.mark.parametrize(
    ("testing", "resolution", "message"),
    [
        ([0.5], [0.5, 0.5], "same shape"),
        ([0], [0.5], r"testing_probability must lie in \(0, 1\]"),
        ([1.1], [0.5], r"testing_probability must lie in \(0, 1\]"),
        ([0.5], [np.nan], "non-empty finite vector"),
        ([[0.5]], [0.5], "non-empty finite vector"),
    ],
)
def test_combined_selection_probability_rejects_invalid_vectors(
    testing: object, resolution: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        combined_selection_probability(testing, resolution)  # type: ignore[arg-type]


def test_truncated_ipw_reports_frequency_weighted_positivity_and_ess() -> None:
    result = truncated_ipw(
        [0.5, 0.4, 0.2, 0.01],
        [0.8, 0.5, 0.5, 0.5],
        frequency=[20, 20, 10, 1],
        lower_quantile=0.05,
        upper_quantile=0.95,
    )

    assert np.all(result.weights <= result.audit.truncation_upper)
    assert np.all(result.weights >= result.audit.truncation_lower)
    assert result.audit.n_cells == 4
    assert result.audit.represented_units == 51
    assert result.audit.fraction_truncated > 0
    assert result.audit.effective_sample_size <= result.audit.represented_units
    assert result.audit.effective_sample_fraction == pytest.approx(
        result.audit.effective_sample_size / result.audit.represented_units
    )
    assert result.audit.probability_min == pytest.approx(0.005)
    assert result.audit.probability_max == pytest.approx(0.4)
    assert result.audit.fraction_probability_below_001 == pytest.approx(1 / 51)


def test_ipw_probability_quantiles_respect_represented_unit_frequency() -> None:
    result = truncated_ipw(
        [0.1, 0.2, 0.9],
        [1.0, 1.0, 1.0],
        frequency=[100, 1, 1],
        lower_quantile=0,
        upper_quantile=1,
    )

    # The high-frequency 0.1 cell must dominate the represented-unit median.
    assert result.audit.probability_median < 0.15


def test_truncated_ipw_supports_vector_stabilization_and_no_truncation() -> None:
    result = truncated_ipw(
        [0.5, 0.25],
        [1.0, 0.5],
        lower_quantile=0,
        upper_quantile=1,
        stabilized_numerator=[0.5, 0.25],
    )

    np.testing.assert_allclose(result.combined_probability, [0.5, 0.125])
    np.testing.assert_allclose(result.raw_weights, [1, 2])
    np.testing.assert_allclose(result.weights, result.raw_weights)
    assert result.audit.fraction_truncated == 0
    assert result.audit.raw_weight_min == 1
    assert result.audit.raw_weight_max == 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"lower_quantile": -0.1}, "truncation quantiles"),
        ({"lower_quantile": 0.5, "upper_quantile": 0.5}, "truncation quantiles"),
        ({"upper_quantile": 1.1}, "truncation quantiles"),
        ({"stabilized_numerator": [1]}, "finite and conformable"),
        ({"stabilized_numerator": [1, np.nan]}, "finite and conformable"),
        ({"stabilized_numerator": [1, 0]}, "strictly positive"),
        ({"frequency": [1]}, "positive and conformable"),
        ({"frequency": [1, 0]}, "positive and conformable"),
        ({"frequency": [1, np.nan]}, "frequency must be a non-empty finite vector"),
    ],
)
def test_truncated_ipw_rejects_invalid_controls(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        truncated_ipw([0.5, 0.25], [0.5, 0.5], **kwargs)  # type: ignore[arg-type]


def test_truncated_ipw_rejects_probability_product_underflow() -> None:
    with pytest.raises(ValueError, match="selection probabilities must be strictly positive"):
        truncated_ipw([1e-300], [1e-300])


def test_standardize_probability_computes_target_mix_and_allows_zero_probability() -> None:
    assert standardize_probability([0.2, 0.6], [3, 1]) == pytest.approx(0.3)
    assert standardize_probability([0.0, 1.0], [1, 3]) == pytest.approx(0.75)


@pytest.mark.parametrize(
    ("probability", "frequency", "message"),
    [
        ([-0.1, 0.5], [1, 1], r"must lie in \[0, 1\]"),
        ([0.1, 1.1], [1, 1], r"must lie in \[0, 1\]"),
        ([0.1], [1, 1], "non-negative and conformable"),
        ([0.1, 0.2], [1, -1], "non-negative and conformable"),
        ([0.1, 0.2], [0, 0], "positive total mass"),
        ([0.1, 0.2], [1, np.nan], "non-empty finite vector"),
    ],
)
def test_standardize_probability_rejects_invalid_target_contract(
    probability: object, frequency: object, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        standardize_probability(probability, frequency)  # type: ignore[arg-type]
