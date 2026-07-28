"""Render claims and build a receipt-bound manuscript candidate.

The executable pipeline in this module deliberately distinguishes a synthetic
workflow validation document from a scientific manuscript.  CI and synthetic
profiles may exercise the complete reporting contract, but every generated
document is prominently labelled and every numerical value comes from the
current run's validated ecological and dynamics receipts.  Restricted runs
fail closed until formal analyses and authored submission metadata exist.
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import shutil
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from hfmd.core.config import ProfileName, read_config_snapshot
from hfmd.core.hashing import atomic_write_bytes, atomic_write_json, sha256_file, sha256_object
from hfmd.core.receipts import (
    StageReceipt,
    build_stage_receipt,
    receipt_file,
    validate_stage_receipt,
    write_stage_receipt,
)
from hfmd.core.run import discover_workspace

from .claims import PLACEHOLDER_PATTERN, ClaimInterval, ClaimRecord, ClaimsBundle

PURPOSE = "synthetic_validation"
SYNTHETIC_BANNER = "SYNTHETIC VALIDATION — NOT FOR SCIENTIFIC INFERENCE"
EXPECTED_ANALYSIS_STAGES = frozenset({"ecological", "dynamics"})


class RestrictedManuscriptBlocked(RuntimeError):
    """Raised instead of creating an uncertified restricted manuscript."""


class ClaimOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document: str
    claim_id: str
    field: str
    rendered_value: str
    asserted_value: str | None = None


def audit_claim_occurrences(
    occurrences: list[ClaimOccurrence] | tuple[ClaimOccurrence, ...],
) -> None:
    """Fail if one claim field is associated with conflicting rendered values."""

    observed: dict[tuple[str, str], set[str]] = defaultdict(set)
    for occurrence in occurrences:
        observed[(occurrence.claim_id, occurrence.field)].add(occurrence.rendered_value.strip())
    conflicts = {key: sorted(values) for key, values in observed.items() if len(values) > 1}
    if conflicts:
        detail = "; ".join(
            f"{claim_id}.{field}: {values}"
            for (claim_id, field), values in sorted(conflicts.items())
        )
        raise ValueError(f"contradictory manuscript claim values: {detail}")


def render_claim_placeholders(
    text: str,
    claims: ClaimsBundle,
    *,
    document: str = "<memory>",
) -> tuple[str, tuple[ClaimOccurrence, ...]]:
    """Render ``{{claim:ID.field}}`` tokens from the canonical claims bundle.

    Authors may add an assertion, for example
    ``{{claim:release_cases.estimate=342.7}}``.  Assertions are never used as
    values; they are checked against the canonical representation and make
    stale copied numbers fail loudly.
    """

    occurrences: list[ClaimOccurrence] = []
    by_id = claims.by_id

    def replace(match: object) -> str:
        # ``re.Match`` is intentionally not parameterized for Python 3.9 typing.
        claim_id = match.group("claim_id")  # type: ignore[attr-defined]
        field = match.group("field") or "full"  # type: ignore[attr-defined]
        assertion = match.group("assertion")  # type: ignore[attr-defined]
        if claim_id not in by_id:
            raise ValueError(f"unknown claim placeholder {claim_id!r} in {document}")
        rendered = by_id[claim_id].render(field)
        if assertion is not None and assertion.strip() != rendered:
            raise ValueError(
                f"claim assertion conflict in {document}: {claim_id}.{field} "
                f"asserts {assertion.strip()!r}, canonical value is {rendered!r}"
            )
        occurrences.append(
            ClaimOccurrence(
                document=document,
                claim_id=claim_id,
                field=field,
                rendered_value=rendered,
                asserted_value=assertion.strip() if assertion is not None else None,
            )
        )
        return rendered

    rendered_text = PLACEHOLDER_PATTERN.sub(replace, text)
    if "{{claim:" in rendered_text:
        raise ValueError(f"unresolved or malformed claim placeholder in {document}")
    audit_claim_occurrences(occurrences)
    return rendered_text, tuple(occurrences)


def render_manuscript_files(
    sources: list[str | Path] | tuple[str | Path, ...],
    claims: ClaimsBundle,
    *,
    source_root: str | Path,
    output_root: str | Path,
    audit_path: str | Path,
) -> tuple[ClaimOccurrence, ...]:
    """Render a manuscript tree and write a machine-auditable occurrence map."""

    source_base = Path(source_root).resolve()
    output_base = Path(output_root).resolve()
    all_occurrences: list[ClaimOccurrence] = []
    for source_value in sources:
        source = Path(source_value).resolve()
        try:
            relative = source.relative_to(source_base)
        except ValueError as error:
            raise ValueError(f"manuscript source escapes source_root: {source}") from error
        destination = output_base / relative
        rendered, occurrences = render_claim_placeholders(
            source.read_text(encoding="utf-8"), claims, document=str(relative)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered, encoding="utf-8")
        all_occurrences.extend(occurrences)

    audit_claim_occurrences(all_occurrences)
    audit_target = Path(audit_path)
    audit_target.parent.mkdir(parents=True, exist_ok=True)
    audit_target.write_text(
        json.dumps(
            [item.model_dump(mode="json") for item in all_occurrences],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return tuple(all_occurrences)


def _load_receipt(path: Path) -> StageReceipt:
    with path.open("r", encoding="utf-8") as handle:
        return StageReceipt.model_validate(json.load(handle))


def _require_path_below(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve(strict=path.exists())
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} escapes the run directory: {resolved}") from error
    return resolved


def _load_valid_evidence_chain(
    figures_receipt: Path,
    *,
    run_root: Path,
    workspace: Path,
    run_id: str,
    profile: ProfileName,
) -> tuple[StageReceipt, dict[str, tuple[Path, StageReceipt]]]:
    """Validate the figures receipt and both analysis receipts it binds."""

    figures_receipt = _require_path_below(
        figures_receipt.resolve(strict=True), run_root, label="figures receipt"
    )
    report = validate_stage_receipt(
        figures_receipt,
        run_root=run_root,
        workspace=workspace,
    )
    if not report.ok:
        raise RuntimeError("figures receipt validation failed: " + "; ".join(report.issues))
    figures = _load_receipt(figures_receipt)
    if figures.stage != "figures":
        raise ValueError(f"expected a figures StageReceipt, found {figures.stage!r}")
    if figures.run_id != run_id:
        raise ValueError("figures receipt belongs to another run_id")
    if figures.profile != profile:
        raise ValueError("figures receipt profile does not match the requested profile")

    parent_stages = [parent.stage for parent in figures.parents]
    if len(parent_stages) != len(EXPECTED_ANALYSIS_STAGES) or set(parent_stages) != set(
        EXPECTED_ANALYSIS_STAGES
    ):
        raise ValueError(
            "figures receipt must bind exactly one ecological and one dynamics receipt"
        )

    parents: dict[str, tuple[Path, StageReceipt]] = {}
    for reference in figures.parents:
        parent_path = run_root / reference.path
        parent_report = validate_stage_receipt(
            parent_path,
            run_root=run_root,
            workspace=workspace,
        )
        if not parent_report.ok:
            raise RuntimeError(
                f"{reference.stage} receipt validation failed: " + "; ".join(parent_report.issues)
            )
        parent = _load_receipt(parent_path)
        if parent.stage != reference.stage:
            raise ValueError(f"parent stage identity mismatch for {reference.path}")
        if parent.run_id != run_id or parent.profile != profile:
            raise ValueError(f"{reference.stage} receipt belongs to another run or profile")
        if parent.config_sha256 != figures.config_sha256:
            raise ValueError(f"{reference.stage} receipt has a different configuration")
        parents[reference.stage] = (parent_path, parent)
    return figures, parents


def _analysis_summary(
    stage: str,
    receipt: StageReceipt,
    *,
    run_root: Path,
    run_id: str,
    profile: ProfileName,
) -> tuple[Path, dict[str, Any]]:
    candidates = [
        record
        for record in receipt.outputs
        if record.scope == "run" and Path(record.path).name == "summary.json"
    ]
    if len(candidates) != 1:
        raise ValueError(f"{stage} receipt must register exactly one summary.json output")
    record = candidates[0]
    if record.classification != "synthetic":
        raise ValueError(f"{stage} synthetic summary has a non-synthetic classification")
    path = run_root / record.path
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{stage} summary is not a JSON object")
    required_identity = {
        "run_id": run_id,
        "profile": profile.value,
        "analysis_line": stage,
        "purpose": PURPOSE,
        "scientific_inference_allowed": False,
        "formal_models_executed": 0,
    }
    for key, expected in required_identity.items():
        if payload.get(key) != expected:
            raise ValueError(
                f"{stage} summary identity mismatch for {key}: "
                f"expected {expected!r}, got {payload.get(key)!r}"
            )
    if not isinstance(payload.get("computed_totals"), dict):
        raise ValueError(f"{stage} summary has no computed_totals object")
    return path, payload


def _nonnegative_integer(payload: dict[str, Any], key: str, *, source: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{source}.{key} must be a non-negative integer")
    return value


def _build_synthetic_claims(
    *,
    run_id: str,
    figures_receipt: Path,
    parents: dict[str, tuple[Path, StageReceipt]],
    ecological_summary_path: Path,
    ecological_summary: dict[str, Any],
    dynamics_summary_path: Path,
    dynamics_summary: dict[str, Any],
    run_root: Path,
) -> ClaimsBundle:
    ecology_totals = ecological_summary["computed_totals"]
    dynamics_totals = dynamics_summary["computed_totals"]
    reported = _nonnegative_integer(
        ecology_totals, "reported_cases", source="ecological.computed_totals"
    )
    typed = _nonnegative_integer(ecology_totals, "typed_cases", source="ecological.computed_totals")
    folds = _nonnegative_integer(
        dynamics_totals, "rolling_origin_folds", source="dynamics.computed_totals"
    )
    dynamics_reported = _nonnegative_integer(
        dynamics_totals, "reported_cases", source="dynamics.computed_totals"
    )
    resolved = _nonnegative_integer(
        dynamics_totals, "resolved_typing_cases", source="dynamics.computed_totals"
    )
    if reported != dynamics_reported:
        raise ValueError("ecological and dynamics synthetic reported-case totals disagree")
    if typed != resolved:
        raise ValueError("ecological typed total and dynamics resolved-typing total disagree")
    if folds != 7:
        raise ValueError("synthetic dynamics validation must contain all seven 2019–2025 folds")

    evidence_manifest_sha256 = sha256_file(figures_receipt)
    input_manifest_sha256 = sha256_object(
        {stage: sha256_file(parent_path) for stage, (parent_path, _) in sorted(parents.items())}
    )
    ecology_source = ecological_summary_path.relative_to(run_root).as_posix()
    dynamics_source = dynamics_summary_path.relative_to(run_root).as_posix()
    notes = (
        "Synthetic workflow-validation metric only. The run_manifest_sha256 field "
        "binds the upstream figures StageReceipt because the terminal RunManifest "
        "is sealed after manuscript construction."
    )
    claims = (
        ClaimRecord(
            claim_id="synthetic_reported_cases",
            estimand="Total reported-case records generated by the synthetic fixture",
            model_id="synthetic_contract_validator",
            estimate=reported,
            interval=ClaimInterval(kind="none"),
            unit="synthetic reported-case records",
            run_id=run_id,
            input_manifest_sha256=input_manifest_sha256,
            run_manifest_sha256=evidence_manifest_sha256,
            source_artifacts=(ecology_source, dynamics_source),
            status="exploratory",
            precision=0,
            notes=notes,
        ),
        ClaimRecord(
            claim_id="synthetic_typed_cases",
            estimand="Resolved pathogen-typing records generated by the synthetic fixture",
            model_id="synthetic_typing_reconciliation_validator",
            estimate=typed,
            interval=ClaimInterval(kind="none"),
            unit="synthetic resolved-typing records",
            run_id=run_id,
            input_manifest_sha256=input_manifest_sha256,
            run_manifest_sha256=evidence_manifest_sha256,
            source_artifacts=(ecology_source, dynamics_source),
            status="exploratory",
            precision=0,
            notes=notes,
        ),
        ClaimRecord(
            claim_id="synthetic_rolling_folds",
            estimand="Prespecified annual rolling-origin folds exercised by the synthetic baseline",
            model_id="synthetic_rolling_origin_validator",
            estimate=folds,
            interval=ClaimInterval(kind="none"),
            unit="synthetic validation folds",
            run_id=run_id,
            input_manifest_sha256=input_manifest_sha256,
            run_manifest_sha256=evidence_manifest_sha256,
            source_artifacts=(dynamics_source,),
            status="exploratory",
            precision=0,
            notes=notes,
        ),
    )
    return ClaimsBundle(
        schema_version="1.0.0",
        run_id=run_id,
        run_manifest_sha256=evidence_manifest_sha256,
        claims=claims,
    )


def _manuscript_template(run_id: str) -> str:
    return f"""# Multiscale ecological effects of EV-A71 vaccination — validation build

> **{SYNTHETIC_BANNER}**

Run ID: `{run_id}`

## Status and permitted use

This automatically generated document tests the reporting pipeline on wholly
synthetic records. It contains no estimate from Hunan surveillance data, runs
no formal ecological or transmission model, and cannot support scientific,
clinical, public-health, policy, mechanistic, or causal inference.

## Receipt-bound validation evidence

The current synthetic fixture reconciled
{{{{claim:synthetic_reported_cases.full}}}} and
{{{{claim:synthetic_typed_cases.full}}}} across the independently registered
ecological and dynamics summaries. The smoke workflow exercised
{{{{claim:synthetic_rolling_folds.full}}}}. These are software-validation
counts, not study results.

## Scientific findings

No scientific findings are reported. Competition release, pathogen
replacement, age concentration, and net public-health benefit remain not
evaluated until the formal restricted-data models, uncertainty procedures,
validation folds, simulations, and prespecified science gates are complete.

## Figures

All figures in this build are synthetic validation artefacts bound to the same
run. They preserve the registered visual design contract but must not be
interpreted as reproducing or estimating the Hunan study results.

## Data and code availability

Only generated synthetic records are used by this validation build. Access to
restricted source data is outside this workflow and remains subject to the
data controller's authorization process.

## Mandatory warning

**{SYNTHETIC_BANNER}. DO NOT SUBMIT THIS DOCUMENT TO A JOURNAL.**
"""


def _supplementary_template(run_id: str) -> str:
    return f"""# Supplementary validation record

> **{SYNTHETIC_BANNER}**

Run ID: `{run_id}`

## Contract checks exercised

| Claim ID | Receipt-derived value | Interpretation |
|---|---:|---|
| reported | {{{{claim:synthetic_reported_cases.full}}}} | Fixture only |
| typed | {{{{claim:synthetic_typed_cases.full}}}} | Reconciliation only |
| folds | {{{{claim:synthetic_rolling_folds.full}}}} | Smoke validation only |

The ecological and dynamics totals were read from their current-run
`summary.json` outputs only after validation of the figures receipt and both
of its hash-linked parent receipts. Every value above is rendered from the
same `claims.json` registry.

## Analyses deliberately not performed

This build does not fit the formal model registry, correct real typing
selection, estimate intervention effects, evaluate competition release,
execute bootstrap uncertainty, or pass any publication science gate.

**{SYNTHETIC_BANNER}.**
"""


def _markdown_plain_lines(markdown: str) -> list[str]:
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = raw.strip()
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^>\s*", "", line)
        line = line.replace("**", "").replace("`", "")
        lines.append(line)
    return lines


def _minimal_docx_bytes(markdown: str) -> bytes:
    """Return a deterministic, editable OOXML document without optional tools."""

    paragraphs = []
    for line in _markdown_plain_lines(markdown):
        escaped = html.escape(line, quote=False)
        paragraphs.append('<w:p><w:r><w:t xml:space="preserve">' + escaped + "</w:t></w:r></w:p>")
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>" + "".join(paragraphs) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/>'
        "</w:sectPr></w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    entries = {
        "[Content_Types].xml": content_types.encode("utf-8"),
        "_rels/.rels": relationships.encode("utf-8"),
        "word/document.xml": document.encode("utf-8"),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in entries.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def _latex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def _latex_document(markdown: str) -> str:
    body: list[str] = []
    for raw in markdown.splitlines():
        stripped = raw.strip()
        if not stripped:
            body.append("")
            continue
        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            command = {1: "section", 2: "section", 3: "subsection"}[level]
            body.append(f"\\{command}*{{{_latex_escape(heading.group(2))}}}")
            continue
        plain = re.sub(r"^>\s*", "", stripped).replace("**", "").replace("`", "")
        body.append(_latex_escape(plain) + r"\par")
    return (
        "\\documentclass[11pt]{article}\n"
        "\\usepackage{fontspec}\n"
        "\\setmainfont{DejaVu Sans}\n"
        "\\usepackage[margin=1in]{geometry}\n"
        "\\begin{document}\n" + "\n".join(body) + "\n\\end{document}\n"
    )


def _write_synthetic_documents(
    staging: Path,
    *,
    run_id: str,
    claims: ClaimsBundle,
) -> tuple[tuple[Path, ...], tuple[ClaimOccurrence, ...]]:
    reporting = staging / "reporting"
    manuscript = staging / "manuscript"
    reporting.mkdir(parents=True)
    manuscript.mkdir(parents=True)

    main_text, main_occurrences = render_claim_placeholders(
        _manuscript_template(run_id), claims, document="manuscript/manuscript.md"
    )
    supplementary_text, supplementary_occurrences = render_claim_placeholders(
        _supplementary_template(run_id),
        claims,
        document="manuscript/supplementary.md",
    )
    occurrences = (*main_occurrences, *supplementary_occurrences)
    audit_claim_occurrences(occurrences)

    claims_path = reporting / "claims.json"
    audit_path = reporting / "claim_occurrences.json"
    atomic_write_json(claims_path, claims, mode=0o600)
    atomic_write_json(
        audit_path,
        [occurrence.model_dump(mode="json") for occurrence in occurrences],
        mode=0o600,
    )
    document_payloads = {
        manuscript / "manuscript.md": main_text.encode("utf-8"),
        manuscript / "manuscript.tex": _latex_document(main_text).encode("utf-8"),
        manuscript / "manuscript.docx": _minimal_docx_bytes(main_text),
        manuscript / "supplementary.md": supplementary_text.encode("utf-8"),
        manuscript / "supplementary.tex": _latex_document(supplementary_text).encode("utf-8"),
        manuscript / "supplementary.docx": _minimal_docx_bytes(supplementary_text),
    }
    for path, payload in document_payloads.items():
        atomic_write_bytes(path, payload, mode=0o600)
    outputs = (claims_path, audit_path, *document_payloads)
    return tuple(outputs), tuple(occurrences)


def run_manuscript_pipeline(
    *,
    run_id: str,
    profile: str,
    run_root: Path,
    figures_receipt: Path,
    receipt_path: Path,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Build synthetic reporting documents or fail closed for restricted data."""

    run_root = run_root.resolve(strict=True)
    workspace = (workspace or discover_workspace(run_root)).resolve(strict=True)
    requested_profile = ProfileName(profile)
    snapshot_path = run_root / "config" / "config.snapshot.json"
    snapshot = read_config_snapshot(snapshot_path)
    if snapshot.config.runtime.profile != requested_profile:
        raise ValueError("requested profile does not match the configuration snapshot")
    receipt_path = _require_path_below(
        receipt_path.absolute(), run_root, label="manuscript receipt"
    )
    if receipt_path.exists() or receipt_path.is_symlink():
        raise FileExistsError(f"refusing to replace manuscript receipt: {receipt_path}")

    figures_receipt = figures_receipt.resolve(strict=True)
    figures, parents = _load_valid_evidence_chain(
        figures_receipt,
        run_root=run_root,
        workspace=workspace,
        run_id=run_id,
        profile=requested_profile,
    )
    if requested_profile == ProfileName.RESTRICTED:
        raise RestrictedManuscriptBlocked(
            "Restricted manuscript construction is blocked until the formal ecological and "
            "dynamics models, uncertainty analyses, science gates, and author-supplied ethics "
            "and data-access metadata are complete. No document or receipt was written."
        )
    if requested_profile not in {ProfileName.CI, ProfileName.SYNTHETIC}:
        raise ValueError(f"unsupported profile: {requested_profile.value}")
    if figures.formal:
        raise ValueError("a public-profile figures receipt cannot be formal")

    ecological_path, ecological_summary = _analysis_summary(
        "ecological",
        parents["ecological"][1],
        run_root=run_root,
        run_id=run_id,
        profile=requested_profile,
    )
    dynamics_path, dynamics_summary = _analysis_summary(
        "dynamics",
        parents["dynamics"][1],
        run_root=run_root,
        run_id=run_id,
        profile=requested_profile,
    )
    claims = _build_synthetic_claims(
        run_id=run_id,
        figures_receipt=figures_receipt,
        parents=parents,
        ecological_summary_path=ecological_path,
        ecological_summary=ecological_summary,
        dynamics_summary_path=dynamics_path,
        dynamics_summary=dynamics_summary,
        run_root=run_root,
    )

    reporting_root = run_root / "reporting"
    manuscript_root = run_root / "manuscript"
    for output_root in (reporting_root, manuscript_root):
        if output_root.exists() or output_root.is_symlink():
            raise FileExistsError(f"refusing to reuse manuscript output root: {output_root}")

    temporary = Path(tempfile.mkdtemp(prefix=".manuscript.staging-", dir=run_root))
    installed: list[Path] = []
    try:
        staged_outputs, occurrences = _write_synthetic_documents(
            temporary,
            run_id=run_id,
            claims=claims,
        )
        (temporary / "reporting").replace(reporting_root)
        installed.append(reporting_root)
        (temporary / "manuscript").replace(manuscript_root)
        installed.append(manuscript_root)
        outputs = tuple(run_root / path.relative_to(temporary) for path in staged_outputs)
        inputs = tuple(
            receipt_file(
                path,
                scope="run",
                run_root=run_root,
                workspace=workspace,
                classification="synthetic",
            )
            for path in (ecological_path, dynamics_path)
        )
        receipt = build_stage_receipt(
            run_root=run_root,
            workspace=workspace,
            run_id=run_id,
            stage="manuscript",
            config_snapshot=snapshot_path,
            output_paths=outputs,
            output_classification="synthetic",
            parent_receipts=(figures_receipt,),
            input_files=inputs,
            exact_output_roots=(reporting_root, manuscript_root),
            metadata={
                "purpose": PURPOSE,
                "scientific_inference_allowed": False,
                "submission_allowed": False,
                "formal_submission_ready": False,
                "synthetic_warning": SYNTHETIC_BANNER,
                "claim_count": len(claims.claims),
                "claim_occurrence_count": len(occurrences),
                "docx_renderer": "deterministic_minimal_ooxml",
                "tex_renderer": "deterministic_native_tex",
                "evidence_manifest_kind": "figures_stage_receipt",
                "evidence_manifest_sha256": sha256_file(figures_receipt),
            },
        )
        write_stage_receipt(receipt, receipt_path)
        report = validate_stage_receipt(
            receipt_path,
            run_root=run_root,
            workspace=workspace,
        )
        if not report.ok:
            raise RuntimeError(
                "manuscript receipt failed self-validation: " + "; ".join(report.issues)
            )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        for output_root in installed:
            shutil.rmtree(output_root, ignore_errors=True)
        receipt_path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    return {
        "status": PURPOSE,
        "run_id": run_id,
        "profile": requested_profile.value,
        "scientific_inference_allowed": False,
        "submission_allowed": False,
        "output_files": len(outputs),
        "claim_count": len(claims.claims),
        "receipt_sha256": report.receipt_sha256,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile", choices=("ci", "synthetic", "restricted"), required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--figures-receipt", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = run_manuscript_pipeline(
        run_id=args.run_id,
        profile=args.profile,
        run_root=args.run_root,
        figures_receipt=args.figures_receipt,
        receipt_path=args.receipt,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
