from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hfmd.reporting.claims import (
    ClaimInterval,
    ClaimRecord,
    ClaimsBundle,
    load_claims,
    write_claims,
)
from hfmd.reporting.manuscript import (
    ClaimOccurrence,
    audit_claim_occurrences,
    render_claim_placeholders,
    render_manuscript_files,
)


def make_claim() -> ClaimRecord:
    return ClaimRecord(
        claim_id="release_cases",
        estimand="Additional non-EV-A71 reported-case proxies under factual versus no-vaccine",
        model_id="M2_age_nb_dm",
        estimate=342.7,
        interval=ClaimInterval(kind="bootstrap_percentile", level=0.95, lower=102.1, upper=581.4),
        unit="reported-case proxies",
        run_id="run-20260717T120000Z",
        input_manifest_sha256="b" * 64,
        run_manifest_sha256="a" * 64,
        source_artifacts=("analysis/dynamics/estimands.csv",),
        status="gated",
        precision=1,
    )


def make_bundle() -> ClaimsBundle:
    return ClaimsBundle(
        schema_version="1.0.0",
        run_id="run-20260717T120000Z",
        run_manifest_sha256="a" * 64,
        claims=(make_claim(),),
    )


def test_claims_json_round_trip_is_validated(tmp_path: Path) -> None:
    path = tmp_path / "claims.json"
    write_claims(make_bundle(), path)
    loaded = load_claims(path)
    assert loaded == make_bundle()
    assert path.read_text(encoding="utf-8").endswith("\n")


def test_duplicate_claim_ids_fail_even_when_values_match() -> None:
    claim = make_claim()
    with pytest.raises(ValidationError, match="duplicate claim IDs"):
        ClaimsBundle(
            schema_version="1.0.0",
            run_id=claim.run_id,
            run_manifest_sha256=claim.run_manifest_sha256,
            claims=(claim, claim),
        )


def test_claim_cannot_point_to_a_different_run_manifest() -> None:
    with pytest.raises(ValidationError, match="manifest does not match"):
        ClaimsBundle(
            schema_version="1.0.0",
            run_id="run-20260717T120000Z",
            run_manifest_sha256="c" * 64,
            claims=(make_claim(),),
        )


def test_manuscript_placeholders_render_from_one_claim() -> None:
    source = (
        "The model estimated {{claim:release_cases.estimate}} additional cases "
        "({{claim:release_cases.interval}}). Repeated: "
        "{{claim:release_cases.estimate=342.7}}."
    )
    rendered, occurrences = render_claim_placeholders(source, make_bundle())
    assert "342.7 additional cases" in rendered
    assert "95% bootstrap interval 102.1–581.4" in rendered
    assert len(occurrences) == 3


def test_inline_assertion_with_stale_number_fails() -> None:
    with pytest.raises(ValueError, match="assertion conflict"):
        render_claim_placeholders(
            "{{claim:release_cases.estimate=341.0}}", make_bundle(), document="main.md"
        )


def test_same_claim_with_conflicting_rendered_values_fails() -> None:
    occurrences = [
        ClaimOccurrence(
            document="main.md",
            claim_id="release_cases",
            field="estimate",
            rendered_value="342.7",
        ),
        ClaimOccurrence(
            document="supplement.md",
            claim_id="release_cases",
            field="estimate",
            rendered_value="341.0",
        ),
    ]
    with pytest.raises(ValueError, match="contradictory manuscript claim values"):
        audit_claim_occurrences(occurrences)


def test_rendered_file_tree_has_occurrence_receipt(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source = source_root / "main.md"
    source.write_text("Value: {{claim:release_cases.estimate}}\n", encoding="utf-8")
    output_root = tmp_path / "rendered"
    audit = tmp_path / "audit" / "claims.json"
    occurrences = render_manuscript_files(
        [source],
        make_bundle(),
        source_root=source_root,
        output_root=output_root,
        audit_path=audit,
    )
    assert (output_root / "main.md").read_text(encoding="utf-8") == "Value: 342.7\n"
    assert audit.is_file()
    assert len(occurrences) == 1
