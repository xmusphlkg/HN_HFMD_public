#!/usr/bin/env python3
"""Reproduce every committed public result using only the Python standard library."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
HUNAN_DATA = ROOT / "data" / "hunan_aggregate"
SYNTHETIC_DATA = ROOT / "data" / "synthetic"
DEFAULT_RESULTS = ROOT / "results"
PATHOGENS = ("ev_a71", "cv_a16", "other_enterovirus")
PATHOGEN_LABELS = {
    "ev_a71": "EV-A71",
    "cv_a16": "CV-A16",
    "other_enterovirus": "Other enterovirus",
}
PATHOGEN_COLOURS = {
    "ev_a71": "#3B6FB6",
    "cv_a16": "#E69F00",
    "other_enterovirus": "#5AAE61",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: format(value, ".12g") if isinstance(value, float) else value
                    for key, value in row.items()
                }
            )


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def validate_manifest(directory: Path) -> list[dict[str, str]]:
    manifest_path = directory / "manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = payload.get("files")
    if not isinstance(records, list) or not records:
        raise ValueError(f"{manifest_path.relative_to(ROOT)} has no file records")
    validated: list[dict[str, str]] = []
    for record in records:
        relative = record["path"]
        expected = record["sha256"]
        source = directory / relative
        if not source.is_file():
            raise FileNotFoundError(f"missing registered input: {source.relative_to(ROOT)}")
        observed = sha256_file(source)
        if observed != expected:
            raise ValueError(
                f"input digest mismatch for {source.relative_to(ROOT)}: "
                f"expected {expected}, observed {observed}"
            )
        validated.append(
            {
                "path": source.relative_to(ROOT).as_posix(),
                "sha256": observed,
            }
        )
    return validated


def parse_number(value: str) -> float:
    cleaned = value.strip().replace(",", "").replace("%", "")
    if not cleaned:
        raise ValueError("cannot parse an empty numeric value")
    return float(cleaned)


def svg_text(
    x: float,
    y: float,
    value: str,
    *,
    size: int = 14,
    anchor: str = "start",
    weight: str = "normal",
    fill: str = "#263238",
) -> str:
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" text-anchor="{anchor}" '
        f'font-family="Arial, Helvetica, sans-serif" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}">{escape(value)}</text>'
    )


def svg_document(width: int, height: int, title: str, body: Sequence[str]) -> str:
    content = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" role="img" aria-labelledby="title">'
        ),
        f'<title id="title">{escape(title)}</title>',
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
        *body,
        "</svg>",
        "",
    ]
    return "\n".join(content)


def stacked_composition_svg(
    categories: Sequence[str],
    values: Sequence[Mapping[str, float]],
    *,
    title: str,
    subtitle: str,
) -> str:
    width, height = 1000, 600
    left, right, top, bottom = 105, 40, 105, 120
    plot_width = width - left - right
    plot_height = height - top - bottom
    bar_width = min(95.0, plot_width / max(len(categories), 1) * 0.58)
    gap = plot_width / max(len(categories), 1)
    body = [
        svg_text(left, 42, title, size=24, weight="bold"),
        svg_text(left, 70, subtitle, size=14, fill="#546E7A"),
    ]
    for tick in range(0, 101, 20):
        y = top + plot_height * (1 - tick / 100)
        body.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
            'stroke="#E6EAED" stroke-width="1"/>'
        )
        body.append(svg_text(left - 12, y + 5, f"{tick}%", anchor="end", size=12))
    for index, (category, row) in enumerate(zip(categories, values, strict=True)):
        x = left + gap * (index + 0.5) - bar_width / 2
        cumulative = 0.0
        for pathogen in PATHOGENS:
            value = row[pathogen]
            rect_height = plot_height * value / 100
            y = top + plot_height - plot_height * (cumulative + value) / 100
            body.append(
                f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_width:.2f}" '
                f'height="{rect_height:.2f}" fill="{PATHOGEN_COLOURS[pathogen]}"/>'
            )
            if value >= 8:
                body.append(
                    svg_text(
                        x + bar_width / 2,
                        y + rect_height / 2 + 5,
                        f"{value:.1f}%",
                        anchor="middle",
                        size=12,
                        weight="bold",
                        fill="#FFFFFF",
                    )
                )
            cumulative += value
        label_x = x + bar_width / 2
        words = category.replace(" post-", " post-\n").split("\n")
        for line_index, line in enumerate(words):
            body.append(
                svg_text(
                    label_x,
                    top + plot_height + 28 + line_index * 17,
                    line,
                    anchor="middle",
                    size=12,
                )
            )
    legend_x = left
    legend_y = height - 25
    for pathogen in PATHOGENS:
        body.append(
            f'<rect x="{legend_x}" y="{legend_y-12}" width="14" height="14" '
            f'fill="{PATHOGEN_COLOURS[pathogen]}"/>'
        )
        body.append(svg_text(legend_x + 21, legend_y, PATHOGEN_LABELS[pathogen], size=12))
        legend_x += 185
    return svg_document(width, height, title, body)


def annual_validation_svg(rows: Sequence[Mapping[str, str]]) -> str:
    width, height = 1000, 560
    left, right, top, bottom = 100, 40, 95, 85
    plot_width = width - left - right
    plot_height = height - top - bottom
    values = [parse_number(row["Composite-index difference"]) for row in rows]
    maximum = max(80.0, math.ceil(max(abs(value) for value in values) / 20) * 20)
    x_step = plot_width / len(rows)

    def y_position(value: float) -> float:
        return top + plot_height * (maximum - value) / (2 * maximum)

    body = [
        svg_text(left, 40, "Annual out-of-period model comparison", size=24, weight="bold"),
        svg_text(
            left,
            68,
            "Positive composite-index differences favour M2; negative values favour M1.",
            size=14,
            fill="#546E7A",
        ),
    ]
    for tick in range(int(-maximum), int(maximum) + 1, 20):
        y = y_position(float(tick))
        stroke = "#455A64" if tick == 0 else "#E6EAED"
        body.append(
            f'<line x1="{left}" y1="{y:.2f}" x2="{width-right}" y2="{y:.2f}" '
            f'stroke="{stroke}" stroke-width="{"2" if tick == 0 else "1"}"/>'
        )
        body.append(svg_text(left - 12, y + 5, str(tick), anchor="end", size=12))
    zero = y_position(0.0)
    for index, (row, value) in enumerate(zip(rows, values, strict=True)):
        center = left + x_step * (index + 0.5)
        y = y_position(value)
        bar_y = min(y, zero)
        bar_height = abs(zero - y)
        colour = "#3B6FB6" if value >= 0 else "#D95F5F"
        body.append(
            f'<rect x="{center-25:.2f}" y="{bar_y:.2f}" width="50" '
            f'height="{bar_height:.2f}" fill="{colour}"/>'
        )
        body.append(
            svg_text(
                center,
                y - 9 if value >= 0 else y + 20,
                f"{value:.1f}",
                anchor="middle",
                size=12,
                weight="bold",
                fill=colour,
            )
        )
        body.append(
            svg_text(center, top + plot_height + 27, row["Test year"], anchor="middle", size=12)
        )
    return svg_document(width, height, "Annual out-of-period model comparison", body)


def burden_contrasts_svg(rows: Sequence[Mapping[str, str]]) -> str:
    selected: dict[str, list[Mapping[str, str]]] = {"case": [], "severe": []}
    for row in rows:
        if (
            row["family"] == "compensation"
            and row["analysis_role"] == "primary"
            and row["metric"] in {"ev_change_post_minus_pre", "non_ev_change"}
        ):
            selected[row["outcome"]].append(row)
    width, height = 1060, 510
    panel_width = 450
    panel_lefts = (80, 590)
    labels = {
        "ev_change_post_minus_pre": "EV-A71",
        "non_ev_change": "Non-EV-A71",
    }
    body = [
        svg_text(60, 40, "Reported-case and recorded-severe burden contrasts", size=24, weight="bold"),
        svg_text(
            60,
            68,
            "Points are estimates; lines are hierarchical moving-block 95% intervals.",
            size=14,
            fill="#546E7A",
        ),
    ]
    for outcome, panel_left in zip(("case", "severe"), panel_lefts, strict=True):
        panel_rows = sorted(selected[outcome], key=lambda row: row["display_order"])
        bounds = [
            parse_number(row[field])
            for row in panel_rows
            for field in ("lower_95", "upper_95")
        ]
        limit = max(abs(min(bounds)), abs(max(bounds)))
        limit = math.ceil(limit / (10000 if outcome == "case" else 200)) * (
            10000 if outcome == "case" else 200
        )

        def x_position(value: float) -> float:
            return panel_left + panel_width * (value + limit) / (2 * limit)

        panel_title = "Reported cases per year" if outcome == "case" else "Recorded severe cases per year"
        body.append(svg_text(panel_left, 112, panel_title, size=16, weight="bold"))
        for tick_index in range(5):
            value = -limit + tick_index * limit / 2
            x = x_position(value)
            body.append(
                f'<line x1="{x:.2f}" y1="140" x2="{x:.2f}" y2="390" '
                f'stroke="{"#455A64" if value == 0 else "#E6EAED"}" '
                f'stroke-width="{"2" if value == 0 else "1"}"/>'
            )
            body.append(
                svg_text(x, 420, f"{value:,.0f}", anchor="middle", size=11)
            )
        for row_index, row in enumerate(panel_rows):
            y = 210 + row_index * 110
            estimate = parse_number(row["point_estimate"])
            lower = parse_number(row["lower_95"])
            upper = parse_number(row["upper_95"])
            colour = "#3B6FB6" if row["metric"] == "ev_change_post_minus_pre" else "#E69F00"
            body.append(svg_text(panel_left, y - 28, labels[row["metric"]], size=13, weight="bold"))
            body.append(
                f'<line x1="{x_position(lower):.2f}" y1="{y}" '
                f'x2="{x_position(upper):.2f}" y2="{y}" stroke="{colour}" '
                'stroke-width="5" stroke-linecap="round"/>'
            )
            body.append(
                f'<circle cx="{x_position(estimate):.2f}" cy="{y}" r="8" '
                f'fill="{colour}" stroke="#FFFFFF" stroke-width="2"/>'
            )
            body.append(
                svg_text(
                    panel_left,
                    y + 28,
                    f"{estimate:,.0f} ({lower:,.0f} to {upper:,.0f})",
                    size=12,
                    fill="#546E7A",
                )
            )
    return svg_document(width, height, "Reported-case and recorded-severe burden contrasts", body)


def reproduce_hunan(destination: Path) -> None:
    observation = read_csv(HUNAN_DATA / "observation_adjustment_summary.csv")
    composition = read_csv(HUNAN_DATA / "pathogen_composition_by_period.csv")
    balance = read_csv(HUNAN_DATA / "model_conditional_balance.csv")
    validation = read_csv(HUNAN_DATA / "annual_model_validation.csv")
    burden = read_csv(HUNAN_DATA / "case_severity_burden_summary.csv")

    observation_by_metric = {row["metric"]: row for row in observation}
    composition_by_period = {row["Epidemiological period"]: row for row in composition}
    balance_by_estimand = {row["Public-health estimand"]: row for row in balance}
    burden_by_metric = {
        (row["outcome"], row["metric"]): row
        for row in burden
        if row["family"] == "compensation" and row["analysis_role"] == "primary"
    }
    findings = [
        {
            "finding": "complete_week_reported_cases",
            "value": observation_by_metric["complete_week_reported_cases"]["value"],
            "unit": "reports",
            "source": "observation_adjustment_summary.csv",
        },
        {
            "finding": "reports_with_resolvable_final_pathogen_label",
            "value": observation_by_metric["reports_with_resolvable_final_pathogen_label"]["value"],
            "unit": "reports",
            "source": "observation_adjustment_summary.csv",
        },
        {
            "finding": "overall_resolvable_label_fraction",
            "value": observation_by_metric["overall_resolvable_label_fraction"]["value"],
            "unit": "percent",
            "source": "observation_adjustment_summary.csv",
        },
        {
            "finding": "pre_vaccine_ev_a71_share",
            "value": composition_by_period["Pre-vaccine"]["EV-A71 share"].rstrip("%"),
            "unit": "percent",
            "source": "pathogen_composition_by_period.csv",
        },
        {
            "finding": "early_post_vaccine_ev_a71_share",
            "value": composition_by_period["Early post-vaccine"]["EV-A71 share"].rstrip("%"),
            "unit": "percent",
            "source": "pathogen_composition_by_period.csv",
        },
        {
            "finding": "early_post_vaccine_other_enterovirus_share",
            "value": composition_by_period["Early post-vaccine"]["Other-enterovirus share"].rstrip("%"),
            "unit": "percent",
            "source": "pathogen_composition_by_period.csv",
        },
        {
            "finding": "model_conditional_net_reduction",
            "value": balance_by_estimand[
                "Net all-pathogen reported-case-proxy reduction"
            ]["Point estimate"].replace(",", ""),
            "unit": "reported-case proxies",
            "source": "model_conditional_balance.csv",
        },
        {
            "finding": "annual_validation_years_favouring_m2",
            "value": str(sum(row["Composite-index winner"] == "M2" for row in validation)),
            "unit": f"of {len(validation)} years",
            "source": "annual_model_validation.csv",
        },
    ]
    for outcome, metric, finding, unit in (
        ("case", "ev_change_post_minus_pre", "ev_a71_reported_case_change", "reports/year"),
        ("case", "non_ev_change", "non_ev_a71_reported_case_change", "reports/year"),
        ("severe", "ev_change_post_minus_pre", "ev_a71_recorded_severe_change", "reports/year"),
        ("severe", "non_ev_change", "non_ev_a71_recorded_severe_change", "reports/year"),
    ):
        findings.append(
            {
                "finding": finding,
                "value": format(parse_number(burden_by_metric[(outcome, metric)]["point_estimate"]), ".12g"),
                "unit": unit,
                "source": "case_severity_burden_summary.csv",
            }
        )
    write_csv(
        destination / "key_findings.csv",
        ("finding", "value", "unit", "source"),
        findings,
    )
    categories = [row["Epidemiological period"] for row in composition]
    values = [
        {
            "ev_a71": parse_number(row["EV-A71 share"]),
            "cv_a16": parse_number(row["CV-A16 share"]),
            "other_enterovirus": parse_number(row["Other-enterovirus share"]),
        }
        for row in composition
    ]
    write_text(
        destination / "pathogen_composition.svg",
        stacked_composition_svg(
            categories,
            values,
            title="Observation-adjusted pathogen composition",
            subtitle="Disclosure-approved aggregate Hunan results by epidemiological period.",
        ),
    )
    write_text(destination / "annual_model_validation.svg", annual_validation_svg(validation))
    write_text(destination / "case_severity_contrasts.svg", burden_contrasts_svg(burden))


def reproduce_synthetic(destination: Path) -> None:
    annual: dict[tuple[int, str], dict[str, float]] = defaultdict(
        lambda: {"reported": 0.0, "typed": 0.0, "vaccine_sum": 0.0, "rows": 0.0}
    )
    annual_total: dict[int, int] = defaultdict(int)
    weekly_typed: dict[tuple[int, str], int] = defaultdict(int)
    with (SYNTHETIC_DATA / "weekly_surveillance.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            year = int(row["year"])
            pathogen = row["pathogen_group"]
            if pathogen not in PATHOGENS:
                raise ValueError(f"unexpected synthetic pathogen: {pathogen}")
            cases = int(row["cases"])
            typed = int(row["typed_cases"])
            values = annual[(year, pathogen)]
            values["reported"] += cases
            values["typed"] += typed
            values["vaccine_sum"] += float(row["ev_a71_vaccine_proxy"])
            values["rows"] += 1
            annual_total[year] += cases
            weekly_typed[(year, pathogen)] += typed

    selection_total: dict[int, int] = defaultdict(int)
    selection_resolved: dict[tuple[int, str], int] = defaultdict(int)
    with (SYNTHETIC_DATA / "typing_selection.csv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        for row in csv.DictReader(handle):
            year = int(row["year"])
            count = int(row["reported_cases"])
            selection_total[year] += count
            if row["testing_stage"] == "resolved_pathogen":
                pathogen = row["pathogen_group"]
                if pathogen not in PATHOGENS:
                    raise ValueError(f"unexpected resolved synthetic pathogen: {pathogen}")
                selection_resolved[(year, pathogen)] += count
            elif row["testing_stage"] != "not_tested":
                raise ValueError(f"unexpected testing stage: {row['testing_stage']}")

    if dict(annual_total) != dict(selection_total):
        raise ValueError("weekly surveillance and typing-selection annual totals differ")
    if dict(weekly_typed) != dict(selection_resolved):
        raise ValueError("weekly typed counts and resolved typing-selection counts differ")

    reported_totals = {
        year: sum(annual[(year, pathogen)]["reported"] for pathogen in PATHOGENS)
        for year in sorted(annual_total)
    }
    typed_totals = {
        year: sum(annual[(year, pathogen)]["typed"] for pathogen in PATHOGENS)
        for year in sorted(annual_total)
    }
    pathogen_rows: list[dict[str, object]] = []
    for year in sorted(annual_total):
        for pathogen in PATHOGENS:
            values = annual[(year, pathogen)]
            pathogen_rows.append(
                {
                    "year": year,
                    "pathogen_group": pathogen,
                    "reported_cases": int(values["reported"]),
                    "typed_cases": int(values["typed"]),
                    "reported_case_fraction": values["reported"] / reported_totals[year],
                    "typed_case_fraction": values["typed"] / typed_totals[year],
                    "mean_vaccine_proxy": values["vaccine_sum"] / values["rows"],
                }
            )
    write_csv(
        destination / "annual_pathogen_summary.csv",
        (
            "year",
            "pathogen_group",
            "reported_cases",
            "typed_cases",
            "reported_case_fraction",
            "typed_case_fraction",
            "mean_vaccine_proxy",
        ),
        pathogen_rows,
    )
    total_rows = [
        {
            "year": year,
            "reported_cases": reported_totals[year],
            "typed_cases": typed_totals[year],
            "typed_fraction": typed_totals[year] / reported_totals[year],
        }
        for year in sorted(annual_total)
    ]
    write_csv(
        destination / "annual_totals.csv",
        ("year", "reported_cases", "typed_cases", "typed_fraction"),
        total_rows,
    )
    rolling_rows: list[dict[str, object]] = []
    years = sorted(annual_total)
    for test_year in range(2019, 2026):
        training = [year for year in years if year < test_year]
        observed = reported_totals[test_year]
        predicted = sum(reported_totals[year] for year in training) / len(training)
        pooled_typed = {
            pathogen: sum(weekly_typed[(year, pathogen)] for year in training)
            for pathogen in PATHOGENS
        }
        pooled_total = sum(pooled_typed.values())
        test_total = typed_totals[test_year]
        composition_l1 = sum(
            abs(
                weekly_typed[(test_year, pathogen)] / test_total
                - pooled_typed[pathogen] / pooled_total
            )
            for pathogen in PATHOGENS
        )
        rolling_rows.append(
            {
                "test_year": test_year,
                "training_start_year": min(training),
                "training_end_year": max(training),
                "observed_total_cases": observed,
                "predicted_total_cases": predicted,
                "absolute_percent_error": abs(observed - predicted) / observed * 100,
                "typed_composition_l1_distance": composition_l1,
            }
        )
    write_csv(
        destination / "rolling_origin_validation.csv",
        (
            "test_year",
            "training_start_year",
            "training_end_year",
            "observed_total_cases",
            "predicted_total_cases",
            "absolute_percent_error",
            "typed_composition_l1_distance",
        ),
        rolling_rows,
    )
    categories = [str(year) for year in years]
    values = [
        {
            pathogen: annual[(year, pathogen)]["typed"] / typed_totals[year] * 100
            for pathogen in PATHOGENS
        }
        for year in years
    ]
    write_text(
        destination / "annual_pathogen_composition.svg",
        stacked_composition_svg(
            categories,
            values,
            title="Synthetic annual pathogen composition",
            subtitle="End-to-end validation using fictional deterministic records; not a Hunan estimate.",
        ),
    )


def result_readme() -> str:
    return """# Reproduced results

Everything in this directory is generated by:

```bash
python3 scripts/reproduce.py
```

- `hunan_aggregate/` contains a key-finding table and three SVGs reproduced
  from the disclosure-approved aggregate Hunan tables.
- `synthetic/` contains annual summaries, rolling-origin validation and one SVG
  generated from fictional deterministic records.
- `manifest.json` records the input and output SHA-256 digests.

The Hunan outputs support public result-level verification and re-plotting.
They do not re-estimate the restricted record-level analysis. Synthetic
outputs demonstrate end-to-end computation but are not scientific estimates.
"""


def build_results(destination: Path) -> None:
    inputs = validate_manifest(HUNAN_DATA) + validate_manifest(SYNTHETIC_DATA)
    destination = destination.resolve()
    if destination == ROOT:
        raise ValueError("refusing to replace the repository root")
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        reproduce_hunan(staging / "hunan_aggregate")
        reproduce_synthetic(staging / "synthetic")
        write_text(staging / "README.md", result_readme())
        outputs = [
            {
                "path": path.relative_to(staging).as_posix(),
                "sha256": sha256_file(path),
            }
            for path in sorted(staging.rglob("*"))
            if path.is_file()
        ]
        manifest = {
            "command": "python3 scripts/reproduce.py",
            "inputs": sorted(inputs, key=lambda item: item["path"]),
            "outputs": outputs,
            "schema_version": 1,
        }
        write_text(
            staging / "manifest.json",
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        )
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def directory_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def check_results() -> None:
    if not DEFAULT_RESULTS.is_dir():
        raise FileNotFoundError("results/ is missing; run the reproduction command first")
    with tempfile.TemporaryDirectory(prefix="hfmd-reproduce-") as temporary:
        candidate = Path(temporary) / "results"
        build_results(candidate)
        expected = directory_hashes(DEFAULT_RESULTS)
        observed = directory_hashes(candidate)
    if expected != observed:
        missing = sorted(expected.keys() - observed.keys())
        unexpected = sorted(observed.keys() - expected.keys())
        changed = sorted(
            path for path in expected.keys() & observed.keys() if expected[path] != observed[path]
        )
        detail = []
        if missing:
            detail.append("missing: " + ", ".join(missing))
        if unexpected:
            detail.append("unexpected: " + ", ".join(unexpected))
        if changed:
            detail.append("changed: " + ", ".join(changed))
        raise RuntimeError("committed results are not reproducible (" + "; ".join(detail) + ")")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_RESULTS,
        help="result directory to replace (default: repository results/)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in a temporary directory and compare with committed results",
    )
    args = parser.parse_args()
    if args.check:
        check_results()
        print("OK: committed results match a clean reproduction.")
    else:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        build_results(output)
        print(f"Reproduced results in {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
