from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from hfmd.reporting.submission import (
    Author,
    ControlledDataAccess,
    EpidemicsSubmissionMetadata,
    EthicsMetadata,
    SubmissionFiles,
    validate_submission_files,
)


def valid_payload() -> dict:
    return {
        "title": "Multiscale ecological effects of EV-A71 vaccination in Hunan, China",
        "abstract": "We evaluated multiscale ecological changes in long-term HFMD surveillance.",
        "keywords": ("HFMD", "EV-A71 vaccine", "pathogen replacement"),
        "highlights": (
            "County models and transmission dynamics retain distinct estimands",
            "Typing selection is evaluated with a prespecified two-stage model",
            "Mechanism claims require rolling validation and recovery simulation",
        ),
        "authors": (
            Author(
                name="An Authored Name",
                affiliations=("An Authored Institution",),
                email="author@example.org",
                corresponding=True,
            ),
        ),
        "ethics": EthicsMetadata(
            review_status="approved",
            committee="An Authored Ethics Committee",
            approval_number="AUTHORED-2026-001",
        ),
        "controlled_data_access": ControlledDataAccess(
            data_controller="An Authored Data Controller",
            request_route="Apply through the controller's documented review route",
            access_conditions="Approval and a data-use agreement are required",
        ),
        "funding_statement": "The authors supplied the funding statement.",
        "competing_interests_statement": "The authors supplied this declaration.",
        "data_availability_statement": "Restricted data are available by controlled request.",
        "code_availability_statement": "Public code and synthetic data will be archived.",
        "ai_disclosure": "The authors supplied the required AI-use disclosure.",
        "files": SubmissionFiles(
            manuscript="manuscript.docx",
            supplementary_material="supplement.docx",
            title_page="title-page.docx",
            cover_letter="cover-letter.docx",
            graphical_abstract="graphical-abstract.svg",
            record_checklist="RECORD.docx",
            strobe_checklist="STROBE.docx",
            credit_statement="CRediT.docx",
        ),
    }


def test_valid_epidemics_metadata() -> None:
    metadata = EpidemicsSubmissionMetadata.model_validate(valid_payload())
    assert metadata.journal == "Epidemics"
    assert len(metadata.highlights) == 3


def test_abstract_over_250_words_fails() -> None:
    payload = valid_payload()
    payload["abstract"] = "word " * 251
    with pytest.raises(ValidationError, match="maximum is 250"):
        EpidemicsSubmissionMetadata.model_validate(payload)


def test_eight_keywords_fail() -> None:
    payload = valid_payload()
    payload["keywords"] = tuple(f"keyword{i}" for i in range(8))
    with pytest.raises(ValidationError):
        EpidemicsSubmissionMetadata.model_validate(payload)


def test_highlight_over_85_characters_fails() -> None:
    payload = valid_payload()
    payload["highlights"] = ("x" * 86,) + payload["highlights"][1:]
    with pytest.raises(ValidationError, match="at most 85"):
        EpidemicsSubmissionMetadata.model_validate(payload)


def test_missing_ethics_number_fails_and_is_not_inferred() -> None:
    with pytest.raises(ValidationError, match="approval number"):
        EthicsMetadata(review_status="approved", committee="An Authored Ethics Committee")


def test_placeholder_author_metadata_fails() -> None:
    with pytest.raises(ValidationError, match="placeholder"):
        Author(name="TBD", affiliations=("Institution",))


def test_submission_files_are_hashed_and_missing_file_fails(tmp_path: Path) -> None:
    metadata = EpidemicsSubmissionMetadata.model_validate(valid_payload())
    for relative in metadata.files.model_dump().values():
        path = tmp_path / relative
        path.write_text(f"content for {relative}\n", encoding="utf-8")
    receipt = validate_submission_files(metadata, tmp_path)
    assert set(receipt) == set(metadata.files.model_dump())
    assert all(len(item["sha256"]) == 64 for item in receipt.values())
    (tmp_path / metadata.files.cover_letter).unlink()
    with pytest.raises(ValueError, match="missing required submission file"):
        validate_submission_files(metadata, tmp_path)
