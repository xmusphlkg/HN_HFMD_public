"""Audit a proposed public tree for disclosure and licensing risks.

This module intentionally errs on refusal.  A finding is never silently
downgraded because the exporter is the last automated boundary before a new
public repository is created.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import stat
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml  # type: ignore[import-untyped]

ALLOWED_LICENSES = frozenset({"BSD-3-Clause", "CC0-1.0", "CC-BY-4.0"})
ALLOWED_CLASSIFICATIONS = frozenset(
    {
        "aggregate_result_data",
        "code",
        "configuration",
        "documentation",
        "synthetic",
        "visual_template",
    }
)
CLASS_LICENSES = {
    "aggregate_result_data": frozenset({"CC-BY-4.0"}),
    "code": frozenset({"BSD-3-Clause"}),
    "configuration": frozenset({"BSD-3-Clause"}),
    "documentation": frozenset({"CC-BY-4.0", "BSD-3-Clause"}),
    "synthetic": frozenset({"CC0-1.0"}),
    "visual_template": frozenset({"BSD-3-Clause"}),
}


@dataclass(frozen=True, slots=True)
class FileMetadata:
    classification: str
    license: str
    source: str | None = None


@dataclass(frozen=True, slots=True)
class AuditFinding:
    code: str
    path: str
    detail: str
    row: int | None = None
    column: str | None = None


@dataclass(frozen=True, slots=True)
class AuditResult:
    status: str
    files_scanned: int
    bytes_scanned: int
    findings: tuple[AuditFinding, ...]
    file_hashes: Mapping[str, str]

    @property
    def passed(self) -> bool:
        return self.status == "passed"

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "status": self.status,
            "files_scanned": self.files_scanned,
            "bytes_scanned": self.bytes_scanned,
            "findings": [asdict(item) for item in self.findings],
            "file_hashes": dict(sorted(self.file_hashes.items())),
        }


@dataclass(frozen=True, slots=True)
class PrivacyPolicy:
    minimum_public_cell: int = 10
    maximum_text_bytes: int = 25 * 1024 * 1024
    allowed_suffixes: frozenset[str] = frozenset(
        {
            "",
            ".cff",
            ".csv",
            ".json",
            ".lock",
            ".md",
            ".py",
            ".r",
            ".R",
            ".rst",
            ".smk",
            ".svg",
            ".toml",
            ".tsv",
            ".txt",
            ".yaml",
            ".yml",
        }
    )


_DIRECT_IDENTIFIER_COLUMNS = frozenset(
    {
        "address",
        "email",
        "full_name",
        "id_card",
        "medical_record_number",
        "mrn",
        "name",
        "national_id",
        "patient_id",
        "patient_name",
        "phone",
        "telephone",
        "wechat",
        "wechat_id",
    }
)
_STRONG_DIRECT_IDENTIFIER_COLUMNS = frozenset(
    {
        "full_name",
        "id_card",
        "medical_record_number",
        "mrn",
        "national_id",
        "passport_number",
        "patient_email",
        "patient_name",
        "patient_phone",
        "social_security_number",
        "subject_name",
    }
)
_EVENT_IDENTIFIER_COLUMNS = frozenset(
    {
        "case_id",
        "event_id",
        "individual_id",
        "person_id",
        "record_id",
        "report_card_id",
    }
)
_GEOGRAPHIC_QUASI_COLUMNS = frozenset(
    {
        "admin_code",
        "admin_id",
        "admin_label",
        "admin_name",
        "administrative_code",
        "administrative_id",
        "administrative_label",
        "administrative_name",
        "address_code",
        "county",
        "county_code",
        "county_id",
        "county_label",
        "county_name",
        "district",
        "district_code",
        "district_id",
        "district_label",
        "district_name",
        "geocode",
        "latitude",
        "longitude",
        "street",
        "township",
        "village",
    }
)
_EXACT_TIME_COLUMNS = frozenset(
    {
        "admission_date",
        "date",
        "datetime",
        "diagnosis_date",
        "onset_date",
        "report_date",
        "timestamp",
    }
)
_COUNT_COLUMNS = frozenset(
    {
        "case_count",
        "cases",
        "count",
        "event_count",
        "events",
        "n",
        "sample_size",
        "total_cases",
        "typed_cases",
        "n_case",
        "n_cases",
        "n_event",
        "n_events",
        "n_positive",
        "n_positives",
        "n_sample",
        "n_samples",
        "n_tested",
        "positive",
        "positive_cases",
        "positive_count",
        "positives",
    }
)
_FORBIDDEN_BASENAMES = frozenset(
    {
        ".env",
        ".netrc",
        "credentials",
        "credentials.json",
        "id_rsa",
        "id_ed25519",
        "secrets.json",
    }
)
_ISO_DATE = re.compile(r"(?:^|[^0-9])(?:19|20)\d{2}-[01]\d-[0-3]\d(?:$|[^0-9])")
_CHINESE_NATIONAL_ID = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
_CHINESE_MOBILE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_TEXT_ASSIGNMENT = re.compile(
    r"(?im)(?:^|[,{;\s])['\"]?(?P<key>[A-Za-z][A-Za-z0-9_.-]{1,63})['\"]?"
    r"\s*[:=]\s*(?P<value>['\"](?:\\.|[^'\"])*['\"]|[^,;}\n\r<]{1,160})"
)
_PLACEHOLDER_VALUES = frozenset(
    {
        "",
        "anonymous",
        "example",
        "fake",
        "fictional",
        "none",
        "null",
        "placeholder",
        "redacted",
        "synthetic",
        "unknown",
        "x",
        "xxx",
    }
)
_CODE_OR_PROSE_SUFFIXES = frozenset({".md", ".py", ".r", ".rst", ".smk"})
_SECRET_PATTERNS = (
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,255}\b")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    (
        "private_key",
        re.compile("-" * 5 + r"BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY" + "-" * 5),
    ),
    (
        "assigned_secret",
        re.compile(
            r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|secret[_-]?key)\b"
            r"\s*[:=]\s*['\"](?!example|placeholder|changeme|redacted)[^'\"\s]{8,}['\"]"
        ),
    ),
)


def _normalized_column(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def _semantic_name(value: str) -> str:
    """Normalize a field name while preserving privacy-bearing suffixes.

    HTML/SVG custom attributes commonly prepend ``data-`` and nested JSON
    paths may prepend container names.  Removing only those non-semantic
    wrappers lets ``data-county-label`` and ``records.n_cases`` reach the same
    policy checks as CSV headers without treating every occurrence of the word
    ``county`` in source code as a data field.
    """

    normalized = _normalized_column(value)
    while normalized.startswith(("data_", "attr_", "field_")):
        normalized = normalized.split("_", 1)[1]
    return normalized


def _is_geographic_quasi(name: str) -> bool:
    normalized = _semantic_name(name)
    if normalized in _GEOGRAPHIC_QUASI_COLUMNS:
        return True
    components = normalized.split("_")
    geographic = {"admin", "administrative", "county", "district", "township", "village"}
    qualifier = {"code", "id", "label", "name"}
    return bool(geographic.intersection(components) and qualifier.intersection(components))


def _is_exact_time(name: str, *, strict: bool) -> bool:
    normalized = _semantic_name(name)
    strong = {
        "admission_date",
        "diagnosis_date",
        "onset_date",
        "report_date",
        "specimen_date",
    }
    if normalized in strong:
        return True
    if strict and normalized in _EXACT_TIME_COLUMNS:
        return True
    if strict and (normalized.endswith("_date") or normalized.endswith("_datetime")):
        return normalized not in {"publication_year", "year"}
    return False


def _is_count(name: str) -> bool:
    normalized = _semantic_name(name)
    if normalized in _COUNT_COLUMNS:
        return True
    return bool(
        re.fullmatch(
            r"(?:n_)?(?:case|cases|event|events|positive|positives|sample|samples|tested)",
            normalized,
        )
    )


def _is_direct_identifier(name: str, *, strict: bool) -> bool:
    normalized = _semantic_name(name)
    if normalized in _STRONG_DIRECT_IDENTIFIER_COLUMNS:
        return True
    return strict and normalized in _DIRECT_IDENTIFIER_COLUMNS


def _is_event_identifier(name: str) -> bool:
    normalized = _semantic_name(name)
    if normalized in _EVENT_IDENTIFIER_COLUMNS:
        return True
    return bool(
        re.fullmatch(
            r"(?:case|event|individual|patient|person|record|report_card|subject)_(?:id|identifier)",
            normalized,
        )
    )


def _display_column(path: tuple[str, ...]) -> str | None:
    return ".".join(path) if path else None


def _is_placeholder(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    cleaned = value.strip().strip("'\"").lower()
    if cleaned in _PLACEHOLDER_VALUES:
        return True
    return any(
        token in cleaned
        for token in (
            "example.com",
            "example.org",
            "invalid.example",
            "<redacted>",
            "${",
            "{{",
        )
    )


def _small_cell(value: object, threshold: int) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if not isinstance(value, (int, float, str)):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0 < number < threshold


def _embedded_identifier_findings(
    value: str,
    relative: str,
    *,
    column: str | None,
) -> list[AuditFinding]:
    """Detect direct identifiers in data-bearing free text without echoing them."""

    findings: list[AuditFinding] = []
    if _CHINESE_NATIONAL_ID.search(value):
        findings.append(
            AuditFinding(
                "embedded_direct_identifier",
                relative,
                "Found a national-identity-number pattern in data-bearing text",
                column=column,
            )
        )
    if _CHINESE_MOBILE.search(value):
        findings.append(
            AuditFinding(
                "embedded_direct_identifier",
                relative,
                "Found a mobile-phone-number pattern in data-bearing text",
                column=column,
            )
        )
    for match in _EMAIL.finditer(value):
        if not _is_placeholder(match.group(0)):
            findings.append(
                AuditFinding(
                    "embedded_direct_identifier",
                    relative,
                    "Found an email-address pattern in data-bearing text",
                    column=column,
                )
            )
            break
    return findings


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _metadata(value: FileMetadata | Mapping[str, str]) -> FileMetadata:
    if isinstance(value, FileMetadata):
        return value
    return FileMetadata(
        classification=str(value.get("classification", "")),
        license=str(value.get("license", "")),
        source=value.get("source"),
    )


def _audit_table(
    path: Path,
    relative: str,
    *,
    delimiter: str,
    policy: PrivacyPolicy,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        if reader.fieldnames is None:
            return [AuditFinding("missing_header", relative, "Tabular file has no header")]
        columns = {_semantic_name(value): value for value in reader.fieldnames}
        if len(columns) != len(reader.fieldnames):
            findings.append(
                AuditFinding(
                    "ambiguous_header",
                    relative,
                    "Two or more headers normalize to the same privacy field name",
                )
            )
        for normalized, original in columns.items():
            if _is_direct_identifier(normalized, strict=True):
                findings.append(
                    AuditFinding(
                        "direct_identifier_column",
                        relative,
                        "Direct identifier columns are never public-exportable",
                        column=original,
                    )
                )
            if _is_event_identifier(normalized):
                findings.append(
                    AuditFinding(
                        "event_level_identifier",
                        relative,
                        "Event- or person-level identifiers imply forbidden granularity",
                        column=original,
                    )
                )
            if _is_geographic_quasi(normalized):
                findings.append(
                    AuditFinding(
                        "geographic_quasi_identifier",
                        relative,
                        "County or finer geographic quasi-identifiers are forbidden",
                        column=original,
                    )
                )
            if _is_exact_time(normalized, strict=True):
                findings.append(
                    AuditFinding(
                        "exact_time_column",
                        relative,
                        "Exact dates or timestamps are forbidden in public tables",
                        column=original,
                    )
                )

        count_columns = {
            original for normalized, original in columns.items() if _is_count(normalized)
        }
        date_scan_columns = {
            original
            for normalized, original in columns.items()
            if normalized not in {"year", "iso_week", "week", "month"}
        }
        for row_number, row in enumerate(reader, start=2):
            for column in count_columns:
                raw = (row.get(column) or "").strip()
                if not raw:
                    continue
                try:
                    number = float(raw)
                except ValueError:
                    findings.append(
                        AuditFinding(
                            "invalid_count",
                            relative,
                            "Count-like value is not numeric",
                            row=row_number,
                            column=column,
                        )
                    )
                    continue
                if 0 < number < policy.minimum_public_cell:
                    findings.append(
                        AuditFinding(
                            "small_cell",
                            relative,
                            f"Positive count is below {policy.minimum_public_cell}",
                            row=row_number,
                            column=column,
                        )
                    )
            for column in date_scan_columns:
                value = row.get(column) or ""
                if _ISO_DATE.search(value):
                    findings.append(
                        AuditFinding(
                            "exact_date_value",
                            relative,
                            "ISO-like exact date found in a public table",
                            row=row_number,
                            column=column,
                        )
                    )
                findings.extend(_embedded_identifier_findings(value, relative, column=column))
            if len(findings) >= 250:
                findings.append(
                    AuditFinding(
                        "finding_limit",
                        relative,
                        "Audit stopped table scanning after 250 findings",
                    )
                )
                break
    return findings


def _semantic_scalar_findings(
    key: str,
    value: object,
    relative: str,
    *,
    path: tuple[str, ...],
    strict: bool,
    policy: PrivacyPolicy,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    column = _display_column(path)
    placeholder = _is_placeholder(value)
    if _is_direct_identifier(key, strict=strict) and (strict or not placeholder):
        findings.append(
            AuditFinding(
                "direct_identifier_field",
                relative,
                "Structured content contains a direct-identifier field",
                column=column,
            )
        )
    if _is_event_identifier(key) and (strict or not placeholder):
        findings.append(
            AuditFinding(
                "event_level_identifier",
                relative,
                "Structured content contains an event- or person-level identifier",
                column=column,
            )
        )
    if _is_geographic_quasi(key) and (strict or not placeholder):
        findings.append(
            AuditFinding(
                "geographic_quasi_identifier",
                relative,
                "Structured content contains county or finer administrative geography",
                column=column,
            )
        )
    time_field = _is_exact_time(key, strict=strict)
    if time_field and (strict or not placeholder):
        findings.append(
            AuditFinding(
                "exact_time_field",
                relative,
                "Structured content contains an exact date or timestamp field",
                column=column,
            )
        )
    if _is_count(key) and _small_cell(value, policy.minimum_public_cell):
        findings.append(
            AuditFinding(
                "small_cell",
                relative,
                f"Positive count is below {policy.minimum_public_cell}",
                column=column,
            )
        )
    if isinstance(value, str):
        if (strict or time_field) and _ISO_DATE.search(value):
            findings.append(
                AuditFinding(
                    "exact_date_value",
                    relative,
                    "ISO-like exact date found in structured content",
                    column=column,
                )
            )
        if strict or _is_direct_identifier(key, strict=False) or _is_event_identifier(key):
            findings.extend(_embedded_identifier_findings(value, relative, column=column))
    return findings


def _audit_structure(
    value: object,
    relative: str,
    *,
    strict: bool,
    policy: PrivacyPolicy,
    path: tuple[str, ...] = (),
    inherited_key: str | None = None,
    depth: int = 0,
) -> list[AuditFinding]:
    if depth > 40:
        return [
            AuditFinding(
                "structure_too_deep",
                relative,
                "Structured content exceeds the maximum audit nesting depth",
                column=_display_column(path),
            )
        ]
    findings: list[AuditFinding] = []
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = (*path, key)
            if isinstance(child, (Mapping, list, tuple)):
                findings.extend(
                    _audit_structure(
                        child,
                        relative,
                        strict=strict,
                        policy=policy,
                        path=child_path,
                        inherited_key=key,
                        depth=depth + 1,
                    )
                )
            else:
                findings.extend(
                    _semantic_scalar_findings(
                        key,
                        child,
                        relative,
                        path=child_path,
                        strict=strict,
                        policy=policy,
                    )
                )
                if strict and isinstance(child, str):
                    stripped = child.strip()
                    if stripped.startswith(("{", "[")):
                        try:
                            embedded = json.loads(stripped)
                        except (json.JSONDecodeError, TypeError):
                            pass
                        else:
                            findings.extend(
                                _audit_structure(
                                    embedded,
                                    relative,
                                    strict=True,
                                    policy=policy,
                                    path=(*child_path, "embedded"),
                                    depth=depth + 1,
                                )
                            )
            if len(findings) >= 250:
                break
        return findings
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            child_path = (*path, f"[{index}]")
            if isinstance(child, (Mapping, list, tuple)):
                findings.extend(
                    _audit_structure(
                        child,
                        relative,
                        strict=strict,
                        policy=policy,
                        path=child_path,
                        inherited_key=inherited_key,
                        depth=depth + 1,
                    )
                )
            elif inherited_key is not None:
                findings.extend(
                    _semantic_scalar_findings(
                        inherited_key,
                        child,
                        relative,
                        path=child_path,
                        strict=strict,
                        policy=policy,
                    )
                )
            if len(findings) >= 250:
                break
        return findings
    if inherited_key is not None:
        findings.extend(
            _semantic_scalar_findings(
                inherited_key,
                value,
                relative,
                path=path,
                strict=strict,
                policy=policy,
            )
        )
    return findings


def _audit_assignments(
    content: str,
    relative: str,
    *,
    strict: bool,
    scan_exact_dates: bool,
    policy: PrivacyPolicy,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for match in _TEXT_ASSIGNMENT.finditer(content):
        key = match.group("key")
        raw_value = match.group("value").strip().strip("'\"")
        value: object = raw_value
        with suppress(ValueError):
            value = float(raw_value)
        findings.extend(
            _semantic_scalar_findings(
                key,
                value,
                relative,
                path=(key,),
                strict=strict,
                policy=policy,
            )
        )
        if len(findings) >= 250:
            break
    if scan_exact_dates and _ISO_DATE.search(content):
        findings.append(
            AuditFinding(
                "exact_date_value",
                relative,
                "ISO-like exact date found in data-bearing text",
            )
        )
    if strict:
        findings.extend(_embedded_identifier_findings(content, relative, column=None))
    return findings


def _audit_svg(
    content: str,
    relative: str,
    *,
    strict: bool,
    policy: PrivacyPolicy,
) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return [AuditFinding("invalid_svg", relative, "SVG is not well-formed XML")]
    for element_index, element in enumerate(root.iter()):
        for raw_key, value in element.attrib.items():
            key = raw_key.rsplit("}", 1)[-1]
            findings.extend(
                _semantic_scalar_findings(
                    key,
                    value,
                    relative,
                    path=(f"element[{element_index}]", key),
                    strict=strict,
                    policy=policy,
                )
            )
        if element.text:
            findings.extend(
                _audit_assignments(
                    element.text,
                    relative,
                    strict=strict,
                    scan_exact_dates=True,
                    policy=policy,
                )
            )
        if len(findings) >= 250:
            break
    return findings


def _audit_text(
    path: Path,
    relative: str,
    policy: PrivacyPolicy,
    metadata: FileMetadata,
) -> list[AuditFinding]:
    if path.stat().st_size > policy.maximum_text_bytes:
        return [
            AuditFinding(
                "file_too_large",
                relative,
                f"Text file exceeds {policy.maximum_text_bytes} bytes",
            )
        ]
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [AuditFinding("invalid_utf8", relative, "Public text must be UTF-8")]
    findings: list[AuditFinding] = []
    for label, pattern in _SECRET_PATTERNS:
        if pattern.search(content):
            findings.append(
                AuditFinding("secret_pattern", relative, f"Matched secret pattern: {label}")
            )
    suffix = path.suffix.lower()
    strict = metadata.classification == "synthetic"
    structured: object | None = None
    if suffix == ".json" or (suffix == ".lock" and content.lstrip().startswith("{")):
        try:
            structured = json.loads(content)
        except json.JSONDecodeError:
            findings.append(
                AuditFinding("invalid_structured_text", relative, "JSON content is invalid")
            )
    elif suffix in {".yaml", ".yml", ".cff"}:
        try:
            structured = yaml.safe_load(content)
        except yaml.YAMLError:
            findings.append(
                AuditFinding("invalid_structured_text", relative, "YAML content is invalid")
            )
    if structured is not None:
        findings.extend(
            _audit_structure(
                structured,
                relative,
                strict=strict,
                policy=policy,
            )
        )
    if suffix == ".svg":
        findings.extend(_audit_svg(content, relative, strict=strict, policy=policy))
    elif strict and suffix not in {".csv", ".tsv"}:
        # Synthetic JSON/YAML may contain embedded strings; plain synthetic
        # text also reaches this path.  Source code and prose examples are not
        # treated as records merely because they name a forbidden field.
        findings.extend(
            _audit_assignments(
                content,
                relative,
                strict=True,
                scan_exact_dates=True,
                policy=policy,
            )
        )
    elif suffix == ".txt" and suffix not in _CODE_OR_PROSE_SUFFIXES:
        findings.extend(
            _audit_assignments(
                content,
                relative,
                strict=False,
                scan_exact_dates=False,
                policy=policy,
            )
        )
    return findings


def audit_tree(
    root: Path | str,
    metadata_by_path: Mapping[str, FileMetadata | Mapping[str, str]],
    *,
    policy: PrivacyPolicy | None = None,
) -> AuditResult:
    """Audit every non-``.git`` file; missing metadata is itself a failure."""

    policy = policy or PrivacyPolicy()
    base = Path(root)
    findings: list[AuditFinding] = []
    hashes: dict[str, str] = {}
    bytes_scanned = 0
    files_scanned = 0
    if base.is_symlink() or not base.is_dir():
        finding = AuditFinding("unsafe_root", str(base), "Audit root must be a regular directory")
        return AuditResult("failed", 0, 0, (finding,), {})

    observed: set[str] = set()
    for path in sorted(base.rglob("*")):
        relative_path = path.relative_to(base)
        if relative_path.parts and relative_path.parts[0] == ".git":
            continue
        relative = relative_path.as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            findings.append(AuditFinding("symbolic_link", relative, "Symbolic links are forbidden"))
            continue
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            findings.append(
                AuditFinding("special_file", relative, "Only regular files are allowed")
            )
            continue
        observed.add(relative)
        files_scanned += 1
        bytes_scanned += path.stat().st_size
        hashes[relative] = _sha256(path)
        meta_value = metadata_by_path.get(relative)
        if meta_value is None:
            findings.append(
                AuditFinding(
                    "unclassified_file",
                    relative,
                    "Every public file requires explicit classification and license",
                )
            )
            continue
        meta = _metadata(meta_value)
        if meta.classification not in ALLOWED_CLASSIFICATIONS:
            findings.append(
                AuditFinding(
                    "forbidden_classification",
                    relative,
                    f"Classification is not public-exportable: {meta.classification!r}",
                )
            )
        if meta.license not in ALLOWED_LICENSES:
            findings.append(
                AuditFinding(
                    "unknown_license",
                    relative,
                    f"License is not on the approved list: {meta.license!r}",
                )
            )
        elif (
            meta.classification in CLASS_LICENSES
            and meta.license not in CLASS_LICENSES[meta.classification]
        ):
            findings.append(
                AuditFinding(
                    "license_class_mismatch",
                    relative,
                    f"{meta.license} is not valid for {meta.classification}",
                )
            )
        if path.name.lower() in _FORBIDDEN_BASENAMES or path.name.lower().startswith(".env"):
            findings.append(
                AuditFinding("forbidden_filename", relative, "Credential filename is forbidden")
            )
        if path.suffix not in policy.allowed_suffixes:
            findings.append(
                AuditFinding(
                    "forbidden_file_type",
                    relative,
                    f"File suffix is not approved: {path.suffix!r}",
                )
            )
            continue
        findings.extend(_audit_text(path, relative, policy, meta))
        if path.suffix.lower() in {".csv", ".tsv"}:
            findings.extend(
                _audit_table(
                    path,
                    relative,
                    delimiter="\t" if path.suffix.lower() == ".tsv" else ",",
                    policy=policy,
                )
            )

    for declared in sorted(set(metadata_by_path) - observed):
        findings.append(
            AuditFinding(
                "declared_file_missing",
                declared,
                "Audit metadata refers to a missing public file",
            )
        )
    ordered = tuple(
        sorted(findings, key=lambda item: (item.path, item.code, item.row or 0, item.column or ""))
    )
    return AuditResult(
        "passed" if not ordered else "failed",
        files_scanned,
        bytes_scanned,
        ordered,
        hashes,
    )


def _uniform_metadata(
    root: Path, classification: str, license_name: str
) -> dict[str, FileMetadata]:
    result: dict[str, FileMetadata] = {}
    for path in root.rglob("*"):
        if path.is_file() and ".git" not in path.relative_to(root).parts:
            result[path.relative_to(root).as_posix()] = FileMetadata(classification, license_name)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--classification", choices=sorted(ALLOWED_CLASSIFICATIONS))
    parser.add_argument("--license", dest="license_name", choices=sorted(ALLOWED_LICENSES))
    parser.add_argument("--minimum-cell", type=int, default=10)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.metadata:
        raw = json.loads(args.metadata.read_text(encoding="utf-8"))
        metadata = {path: _metadata(item) for path, item in raw.items()}
    elif args.classification and args.license_name:
        metadata = _uniform_metadata(args.root, args.classification, args.license_name)
    else:
        parser.error("provide --metadata or both --classification and --license")
    result = audit_tree(
        args.root,
        metadata,
        policy=PrivacyPolicy(minimum_public_cell=args.minimum_cell),
    )
    payload = json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(json.dumps(result.as_dict(), ensure_ascii=False, sort_keys=True))
    if not result.passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
