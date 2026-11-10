# -*- coding: utf-8 -*-
"""Analyze the claim-level expert audit returns.

The audit contract was frozen in
``docs/claim_level_audit_protocol_20260928.md``.  This tool keeps the two
reviewer labels separate, reports agreement, and marks only material
disagreements for adjudication.  It does not invent an adjudicated label.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path


WORKBOOK_FIELDS = [
    "review_id",
    "run_id",
    "question_id",
    "domain",
    "condition_id",
    "system",
    "reviewer_id",
    "claim_id",
    "claim_text",
    "evidence_status",
    "citation_issue",
    "primary_failure_label",
    "secondary_failure_labels",
    "severity",
    "release_decision",
    "confidence",
    "reviewer_notes",
    "adjudicated_evidence_status",
    "adjudicated_failure_label",
    "adjudicated_release_decision",
    "adjudication_notes",
]

AGREEMENT_FIELDS = [
    "evidence_status",
    "primary_failure_label",
    "release_decision",
]

SECONDARY_AGREEMENT_FIELDS = [
    "citation_issue",
    "severity",
    "confidence",
]

ALL_COMPARISON_FIELDS = AGREEMENT_FIELDS + SECONDARY_AGREEMENT_FIELDS

CSV_OUTPUTS = {
    "reviewer_rows": "reviewer_rows_normalized.csv",
    "combined": "claim_audit_combined.csv",
    "disagreements": "claim_audit_disagreements.csv",
    "adjudication": "adjudication_candidates.csv",
    "run_level": "run_level_agreement.csv",
    "rereview": "focused_rereview_queue.csv",
}

INCOMPLETE_PATTERNS = (
    "未逐条读取",
    "未能逐条读取",
    "未读取假设全文",
    "未查看全文",
    "未读全文",
    "全文未读",
    "not read",
    "did not read",
    "didn't read",
)

GENERIC_CLAIM_PATTERNS = (
    "基线json回答",
    "基线系统对",
    "核心假设主张（全文未读）",
    "核心假设级主张（全文未读）",
    "最佳假设中的核心科学主张",
)

POSITIVE_EVIDENCE = {"supported", "partially_supported"}
NEGATIVE_EVIDENCE = {"unsupported", "contradicted"}
CITATION_ISSUE_VALUES = {
    "",
    "none",
    "metadata_insufficient",
    "wrong_attribution",
    "topic_mismatch",
    "quote_unverifiable",
    "likely_fabricated",
}
PRIMARY_FAILURE_VALUES = {
    "",
    "none",
    "false_support",
    "false_rejection",
    "wrong_citation",
    "unsupported_number",
    "missing_uncertainty",
    "statistical_invalidity",
    "method_not_executable",
    "release_unjustified",
}


def _clean(value) -> str:
    """Normalize one CSV or Markdown cell."""
    if value is None:
        return ""
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", text).strip()


def _clean_key(value) -> str:
    return _clean(value).lower()


def normalize_review_row(row: dict) -> dict:
    """Return a cleaned copy of a reviewer row."""
    normalized = {field: _clean(row.get(field, "")) for field in WORKBOOK_FIELDS}
    # The first FIN-R2 return has an omitted reviewer_id in rows 6-24.  The
    # resulting CSV shift is deterministic: C1/C2/... lands in reviewer_id and
    # every following substantive field lands one column early.  Repair only
    # this exact pattern; do not guess at arbitrary malformed rows.
    if (
        re.match(r"^FIN-R2-\d+$", normalized["review_id"])
        and re.match(r"^C\d+$", normalized["reviewer_id"])
        and normalized["system"] == "F2"
    ):
        shifted = {
            "system": "F0",
            "reviewer_id": "R2",
            "claim_id": normalized["reviewer_id"],
            "claim_text": normalized["claim_id"],
            "evidence_status": normalized["claim_text"],
            "citation_issue": normalized["evidence_status"],
            "primary_failure_label": normalized["citation_issue"],
            "secondary_failure_labels": normalized["primary_failure_label"],
            "severity": normalized["secondary_failure_labels"],
            "release_decision": normalized["severity"],
            "confidence": normalized["release_decision"],
            "reviewer_notes": normalized["confidence"],
            "adjudicated_evidence_status": "",
            "adjudicated_failure_label": "",
            "adjudicated_release_decision": "",
            "adjudication_notes": "",
        }
        normalized.update(shifted)
        normalized["_normalization_note"] = (
            "system:F2->F0;reviewer_id:inserted_R2;field_shift:repaired"
        )
        return normalized
    raw_system = normalized["system"]
    if raw_system == "F2":
        normalized["system"] = "F0"
        normalized["_normalization_note"] = "system:F2->F0"
    if not normalized["reviewer_id"]:
        review_id = normalized["review_id"]
        match = re.match(r"^(?:CHEM|FIN|MATH)-(R[12])-", review_id, re.IGNORECASE)
        if match:
            normalized["reviewer_id"] = match.group(1).upper()
    return normalized


def _deduplicate_rows(rows: list[dict], source: str) -> list[dict]:
    by_review_id: dict[str, dict] = {}
    for row in rows:
        review_id = row["review_id"]
        if not review_id:
            raise ValueError(f"{source}: reviewer row is missing review_id")
        previous = by_review_id.get(review_id)
        if previous is None:
            by_review_id[review_id] = row
            continue
        if previous != row:
            raise ValueError(
                f"{source}: duplicate review_id has conflicting content: {review_id}"
            )
    return list(by_review_id.values())


def load_review_csv(path: Path) -> list[dict]:
    """Load one reviewer CSV, accepting UTF-8 BOM and blank trailing columns."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path}: missing CSV header")
        missing = [field for field in WORKBOOK_FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(missing)}")
        rows = [normalize_review_row(row) for row in reader]
    return _deduplicate_rows(rows, str(path))


def load_review_markdown(text: str) -> list[dict]:
    """Extract MATH reviewer rows from the Markdown table in the raw message."""
    rows: list[dict] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or not re.match(r"^MATH-R[12]-\d+$", cells[0]):
            continue
        if len(cells) < len(WORKBOOK_FIELDS):
            raise ValueError(
                f"Markdown row {cells[0]} has {len(cells)} cells; "
                f"expected at least {len(WORKBOOK_FIELDS)}"
            )
        rows.append(
            normalize_review_row(
                dict(zip(WORKBOOK_FIELDS, cells[: len(WORKBOOK_FIELDS)]))
            )
        )
    if not rows:
        raise ValueError("No MATH review rows found in Markdown source")
    return _deduplicate_rows(rows, "Markdown message")


def _extract_largest_user_message(path: Path) -> str:
    """Extract the largest user message containing MATH rows from a JSONL log."""
    candidates: list[str] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if "MATH-R1-001" not in line and "MATH-R2-001" not in line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            payload = event.get("payload", {})
            if event.get("type") != "response_item":
                continue
            if payload.get("type") != "message" or payload.get("role") != "user":
                continue
            for content in payload.get("content", []):
                text = content.get("text", "")
                if "MATH-R1-001" in text or "MATH-R2-001" in text:
                    candidates.append(text)
    if not candidates:
        raise ValueError(f"{path}: no user message containing MATH review rows")
    return max(candidates, key=len)


def load_math_reviews(path: Path) -> list[dict]:
    """Load MATH rows from either a Markdown text file or a session JSONL file."""
    if path.suffix.lower() == ".jsonl":
        text = _extract_largest_user_message(path)
    else:
        text = path.read_text(encoding="utf-8-sig")
    return load_review_markdown(text)


def _validate_review_rows(rows: list[dict]) -> None:
    required = ("run_id", "domain", "condition_id", "reviewer_id", "claim_id")
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        missing = [field for field in required if not row.get(field)]
        if missing:
            raise ValueError(
                f"Reviewer row {row.get('review_id', '<unknown>')} is missing: "
                f"{', '.join(missing)}"
            )
        key = (row["reviewer_id"], row["run_id"], row["claim_id"])
        if key in seen:
            raise ValueError(f"Duplicate reviewer/key row: {key}")
        seen.add(key)


def _pair_key(row: dict) -> tuple[str, str]:
    return row["run_id"], row["claim_id"]


def _similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", "", left).lower()
    right_norm = re.sub(r"\s+", "", right).lower()
    if not left_norm or not right_norm:
        return 0.0
    return round(SequenceMatcher(None, left_norm, right_norm).ratio(), 3)


def _review_quality_flags(row: dict) -> list[str]:
    notes = _clean(row.get("reviewer_notes", "")).lower()
    claim_text = _clean(row.get("claim_text", "")).lower()
    flags: list[str] = []
    if any(pattern in notes for pattern in INCOMPLETE_PATTERNS):
        flags.append("reviewer_incomplete")
    if any(pattern in claim_text for pattern in GENERIC_CLAIM_PATTERNS):
        flags.append("generic_claim_text")
    return flags


def _schema_warnings(row: dict) -> list[str]:
    warnings: list[str] = []
    citation_issue = _clean_key(row.get("citation_issue", ""))
    if citation_issue not in CITATION_ISSUE_VALUES:
        warnings.append(f"invalid_citation_issue:{citation_issue}")
    failure_label = _clean_key(row.get("primary_failure_label", ""))
    if failure_label not in PRIMARY_FAILURE_VALUES:
        warnings.append(f"invalid_primary_failure_label:{failure_label}")
    return warnings


def _parse_severity(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _material_evidence_disagreement(left: str, right: str) -> bool:
    pair = {left, right}
    if pair & POSITIVE_EVIDENCE and pair & NEGATIVE_EVIDENCE:
        return True
    if "cannot_verify" in pair and pair & {"supported", "unsupported", "contradicted"}:
        return True
    return False


def _opposite_release(left: str, right: str) -> bool:
    return {left, right} == {"justified", "unjustified"}


def _adjudication_reasons(left: dict, right: dict) -> list[str]:
    reasons: list[str] = []
    if _material_evidence_disagreement(
        left["evidence_status"], right["evidence_status"]
    ):
        reasons.append("material_evidence_status_disagreement")
    if _opposite_release(left["release_decision"], right["release_decision"]):
        reasons.append("opposite_release_decisions")
    if (
        left["primary_failure_label"]
        and right["primary_failure_label"]
        and left["primary_failure_label"] != right["primary_failure_label"]
    ):
        reasons.append("different_primary_failure_label")
    left_severity = _parse_severity(left["severity"])
    right_severity = _parse_severity(right["severity"])
    if (
        left_severity is not None
        and right_severity is not None
        and left_severity != right_severity
        and max(left_severity, right_severity) >= 3
    ):
        reasons.append("severity_3_4_disagreement")
    return reasons


def _base_meta(left: dict, right: dict) -> dict:
    source = left if left else right
    return {
        "run_id": source["run_id"],
        "question_id": source["question_id"],
        "domain": source["domain"],
        "condition_id": source["condition_id"],
        "system": source["system"],
        "claim_id": source["claim_id"],
    }


def _metadata_conflicts(left: dict, right: dict) -> list[str]:
    conflicts: list[str] = []
    for field in ("run_id", "question_id", "domain", "condition_id", "system"):
        if _clean_key(left.get(field, "")) != _clean_key(right.get(field, "")):
            conflicts.append(field)
    return conflicts


def pair_reviews(rows: list[dict]) -> list[dict]:
    """Pair R1/R2 rows without collapsing either reviewer's labels."""
    _validate_review_rows(rows)
    by_reviewer: dict[str, dict[tuple[str, str], dict]] = {
        "R1": {},
        "R2": {},
    }
    for row in rows:
        reviewer = row["reviewer_id"].upper()
        if reviewer not in by_reviewer:
            raise ValueError(f"Expected reviewer_id R1 or R2, found {reviewer!r}")
        by_reviewer[reviewer][_pair_key(row)] = row

    all_keys = sorted(set(by_reviewer["R1"]) | set(by_reviewer["R2"]))
    paired: list[dict] = []
    for run_id, claim_id in all_keys:
        left = by_reviewer["R1"].get((run_id, claim_id))
        right = by_reviewer["R2"].get((run_id, claim_id))
        if left is None or right is None:
            source = left or right
            mapping_status = "r1_only" if right is None else "r2_only"
            item = _base_meta(left or {}, right or {})
            item.update(
                {
                    "pair_id": f"{run_id}::{claim_id}",
                    "mapping_status": mapping_status,
                    "claim_text_similarity": "",
                    "claim_text_r1": (left or {}).get("claim_text", ""),
                    "claim_text_r2": (right or {}).get("claim_text", ""),
                    "disagreement_fields": "reviewer_rows_unmatched",
                    "adjudication_required": "1",
                    "adjudication_reasons": "reviewer_rows_unmatched",
                    "schema_warnings": "|".join(
                        sorted(set(_schema_warnings(source)))
                    ),
                    "review_quality_flags": "|".join(
                        sorted(set(_review_quality_flags(source)))
                    ),
                    "reviewer_notes_r1": (left or {}).get("reviewer_notes", ""),
                    "reviewer_notes_r2": (right or {}).get("reviewer_notes", ""),
                    "metadata_conflicts": "",
                }
            )
            for field in WORKBOOK_FIELDS:
                if field in {
                    "review_id",
                    "run_id",
                    "question_id",
                    "domain",
                    "condition_id",
                    "system",
                    "reviewer_id",
                    "claim_id",
                    "claim_text",
                    "reviewer_notes",
                }:
                    continue
                item[f"r1_{field}"] = (left or {}).get(field, "")
                item[f"r2_{field}"] = (right or {}).get(field, "")
            paired.append(item)
            continue

        item = _base_meta(left, right)
        similarity = _similarity(left["claim_text"], right["claim_text"])
        quality_flags = set(_review_quality_flags(left)) | set(
            _review_quality_flags(right)
        )
        if similarity < 0.15:
            quality_flags.add("claim_text_similarity_low")
        item.update(
            {
                "pair_id": f"{run_id}::{claim_id}",
                "mapping_status": "matched",
                "claim_text_similarity": similarity,
                "claim_text_r1": left["claim_text"],
                "claim_text_r2": right["claim_text"],
                "schema_warnings": "|".join(
                    sorted(set(_schema_warnings(left)) | set(_schema_warnings(right)))
                ),
                "review_quality_flags": "|".join(sorted(quality_flags)),
                "reviewer_notes_r1": left["reviewer_notes"],
                "reviewer_notes_r2": right["reviewer_notes"],
            }
        )
        for field in WORKBOOK_FIELDS:
            if field in {
                "review_id",
                "run_id",
                "question_id",
                "domain",
                "condition_id",
                "system",
                "reviewer_id",
                "claim_id",
                "claim_text",
                "reviewer_notes",
            }:
                continue
            item[f"r1_{field}"] = left.get(field, "")
            item[f"r2_{field}"] = right.get(field, "")

        for field in AGREEMENT_FIELDS:
            item[f"agree_{field}"] = (
                "1" if _clean_key(left[field]) == _clean_key(right[field]) else "0"
            )

        disagreement_fields = [
            field
            for field in ALL_COMPARISON_FIELDS
            if _clean_key(left[field]) != _clean_key(right[field])
        ]
        item["disagreement_fields"] = "|".join(disagreement_fields)
        item["metadata_conflicts"] = "|".join(_metadata_conflicts(left, right))

        reasons = _adjudication_reasons(left, right)
        if item["metadata_conflicts"]:
            reasons.append("metadata_mismatch")
        item["adjudication_reasons"] = "|".join(reasons)
        item["adjudication_required"] = "1" if reasons else "0"
        paired.append(item)

    return paired


def _ordered_labels(field: str, labels: set[str]) -> list[str]:
    preferred = {
        "evidence_status": [
            "supported",
            "partially_supported",
            "unsupported",
            "contradicted",
            "cannot_verify",
        ],
        "release_decision": [
            "justified",
            "partially_justified",
            "unjustified",
            "cannot_verify",
        ],
        "confidence": ["high", "medium", "low"],
    }.get(field, [])
    ordered = [label for label in preferred if label in labels]
    ordered.extend(sorted(labels - set(ordered)))
    return ordered


def agreement_stats(pairs: list[dict], field: str) -> dict:
    """Compute exact agreement and Cohen's kappa for one paired field."""
    values: list[tuple[str, str]] = []
    for pair in pairs:
        if pair.get("mapping_status") != "matched":
            continue
        left = _clean_key(pair.get(f"r1_{field}", ""))
        right = _clean_key(pair.get(f"r2_{field}", ""))
        if not left or not right:
            continue
        values.append((left, right))

    n = len(values)
    if n == 0:
        return {
            "n": 0,
            "observed_agreement": None,
            "expected_agreement": None,
            "kappa": None,
            "labels": [],
            "matrix": [],
            "disagreement_count": 0,
        }

    confusion: Counter[tuple[str, str]] = Counter(values)
    labels = _ordered_labels(field, {value for pair in values for value in pair})
    matrix = [[confusion[(left, right)] for right in labels] for left in labels]
    diagonal = sum(confusion[(label, label)] for label in labels)
    observed = diagonal / n
    row_totals = {
        label: sum(confusion[(label, other)] for other in labels) for label in labels
    }
    column_totals = {
        label: sum(confusion[(other, label)] for other in labels) for label in labels
    }
    expected = sum(row_totals[label] * column_totals[label] for label in labels) / (n * n)
    if abs(1.0 - expected) < 1e-12:
        kappa = 1.0 if observed == 1.0 else None
    else:
        kappa = (observed - expected) / (1.0 - expected)

    return {
        "n": n,
        "observed_agreement": round(observed, 6),
        "expected_agreement": round(expected, 6),
        "kappa": None if kappa is None else round(kappa, 6),
        "labels": labels,
        "matrix": matrix,
        "disagreement_count": n - diagonal,
    }


def build_metrics(pairs: list[dict]) -> dict:
    metrics: dict[str, dict] = {
        "overall": {
            field: agreement_stats(pairs, field) for field in ALL_COMPARISON_FIELDS
        },
        "by_domain": {},
        "by_condition": {},
    }
    for domain in sorted({pair["domain"] for pair in pairs}):
        subset = [pair for pair in pairs if pair["domain"] == domain]
        metrics["by_domain"][domain] = {
            field: agreement_stats(subset, field) for field in ALL_COMPARISON_FIELDS
        }
    for condition in sorted({pair["condition_id"] for pair in pairs}):
        subset = [pair for pair in pairs if pair["condition_id"] == condition]
        metrics["by_condition"][condition] = {
            field: agreement_stats(subset, field) for field in ALL_COMPARISON_FIELDS
        }
    return metrics


def build_run_level(pairs: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for pair in pairs:
        grouped[pair["run_id"]].append(pair)

    rows: list[dict] = []
    for run_id in sorted(grouped):
        run_pairs = grouped[run_id]
        matched = [pair for pair in run_pairs if pair["mapping_status"] == "matched"]
        flags: set[str] = set()
        for pair in run_pairs:
            flags.update(flag for flag in pair["review_quality_flags"].split("|") if flag)

        def exact_count(field: str) -> int:
            return sum(
                1
                for pair in matched
                if pair.get(f"r1_{field}", "") == pair.get(f"r2_{field}", "")
            )

        rows.append(
            {
                "run_id": run_id,
                "question_id": run_pairs[0]["question_id"],
                "domain": run_pairs[0]["domain"],
                "condition_id": run_pairs[0]["condition_id"],
                "system": run_pairs[0]["system"],
                "paired_claims": len(run_pairs),
                "matched_claims": len(matched),
                "unmatched_claims": len(run_pairs) - len(matched),
                "exact_evidence": exact_count("evidence_status"),
                "exact_failure": exact_count("primary_failure_label"),
                "exact_release": exact_count("release_decision"),
                "adjudication_required": sum(
                    1 for pair in run_pairs if pair["adjudication_required"] == "1"
                ),
                "review_quality_flags": "|".join(sorted(flags)),
                "incomplete_review": "1" if "reviewer_incomplete" in flags else "0",
                "generic_claim_rows": sum(
                    1
                    for pair in run_pairs
                    if "generic_claim_text" in pair["review_quality_flags"]
                ),
            }
        )
    return rows


def build_focused_rereview_queue(run_rows: list[dict]) -> list[dict]:
    """Flag weak/incomplete reviews without treating them as substantive errors."""
    queue: list[dict] = []
    for row in run_rows:
        flags = {flag for flag in row["review_quality_flags"].split("|") if flag}
        is_mathematics = row["domain"] == "mathematics"
        is_baseline = row["condition_id"] == "B1_flat_rag_clean"
        trigger_flags = {
            "reviewer_incomplete",
            "generic_claim_text",
            "claim_text_similarity_low",
        }
        if not (flags & trigger_flags):
            continue
        scopes: list[str] = []
        if is_mathematics:
            scopes.append("mathematics_claim_level_rereview")
        if is_baseline:
            scopes.append("baseline_claim_level_rereview")
        if "claim_text_similarity_low" in flags:
            scopes.append("claim_alignment_check")
        if not scopes:
            scopes.append("focused_claim_level_rereview")
        reasons: list[str] = []
        if flags & {"reviewer_incomplete", "generic_claim_text"}:
            reasons.append(
                "Reviewer did not read the full claim set or used a generic "
                "placeholder claim."
            )
        if "claim_text_similarity_low" in flags:
            reasons.append(
                "Reviewer claim texts are only loosely aligned; confirm they "
                "refer to the same concrete claim."
            )
        queue.append(
            {
                "run_id": row["run_id"],
                "question_id": row["question_id"],
                "domain": row["domain"],
                "condition_id": row["condition_id"],
                "system": row["system"],
                "paired_claims": row["paired_claims"],
                "review_quality_flags": "|".join(sorted(flags)),
                "recommended_focus": "|".join(scopes),
                "reason": " ".join(reasons),
            }
        )
    return queue


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _fmt_rate(value) -> str:
    if value is None:
        return "NA"
    return f"{100.0 * value:.1f}%"


def _fmt_kappa(value) -> str:
    if value is None:
        return "NA"
    return f"{value:.3f}"


def _markdown_agreement_table(metrics: dict) -> list[str]:
    lines = [
        "| Field | n | Agreement | Cohen's kappa | Disagreements |",
        "|---|---:|---:|---:|---:|",
    ]
    for field in ALL_COMPARISON_FIELDS:
        stat = metrics[field]
        lines.append(
            f"| `{field}` | {stat['n']} | {_fmt_rate(stat['observed_agreement'])} | "
            f"{_fmt_kappa(stat['kappa'])} | {stat['disagreement_count']} |"
        )
    return lines


def _markdown_confusion_table(metrics: dict, field: str) -> list[str]:
    stat = metrics[field]
    labels = stat["labels"]
    if not labels:
        return ["No paired labels."]
    lines = [
        "| Reviewer R1 \\ R2 | " + " | ".join(f"`{label}`" for label in labels) + " |",
        "|---|" + "|".join("---:" for _ in labels) + "|",
    ]
    for index, left in enumerate(labels):
        cells = " | ".join(str(value) for value in stat["matrix"][index])
        lines.append(f"| `{left}` | {cells} |")
    return lines


def _write_first_pass_markdown(
    path: Path,
    metrics: dict,
    pairs: list[dict],
    run_rows: list[dict],
    rereview_rows: list[dict],
    source_counts: dict,
    normalization_counts: dict,
) -> None:
    overall = metrics["overall"]
    adjudication_pairs = [pair for pair in pairs if pair["adjudication_required"] == "1"]
    unmatched = [pair for pair in pairs if pair["mapping_status"] != "matched"]
    reasons = Counter()
    for pair in adjudication_pairs:
        for reason in pair["adjudication_reasons"].split("|"):
            if reason:
                reasons[reason] += 1

    lines = [
        "# Claim-level audit: first pass",
        "",
        f"Generated: {datetime.now().isoformat(timespec='seconds')}",
        "",
        "This first pass measures agreement and identifies rows for a third reviewer. "
        "It does not fill the adjudicated labels and does not treat `cannot_verify` "
        "as evidence of fabrication.",
        "",
        "## Scope",
        "",
        f"- Reviewer rows loaded: {source_counts['rows']}",
        f"- Paired claim rows: {len(pairs)}",
        f"- Matched reviewer pairs: {len(pairs) - len(unmatched)}",
        f"- Unmatched reviewer rows: {len(unmatched)}",
        f"- Runs represented: {len(run_rows)}",
        f"- `system=F2` normalized to `F0`: {normalization_counts['f2_to_f0']}"
        + (
            f"\n- FIN-R2 one-column shift repaired: "
            f"{normalization_counts['fin_r2_shift_repaired']}"
            if normalization_counts.get("fin_r2_shift_repaired")
            else ""
        )
        + (
            "\n- Rows with reviewer schema warnings: "
            f"{sum(1 for pair in pairs if pair.get('schema_warnings'))}"
        ),
        "",
        "## Agreement",
        "",
        *_markdown_agreement_table(overall),
        "",
        "The primary agreement fields are `evidence_status`, "
        "`primary_failure_label`, and `release_decision`. Citation issue, "
        "severity, and confidence are reported as secondary checks.",
        "",
        "### Agreement by domain",
        "",
        "| Domain | Field | n | Agreement | Cohen's kappa | Disagreements |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for domain, domain_metrics in metrics["by_domain"].items():
        for field in AGREEMENT_FIELDS:
            stat = domain_metrics[field]
            lines.append(
                f"| `{domain}` | `{field}` | {stat['n']} | "
                f"{_fmt_rate(stat['observed_agreement'])} | "
                f"{_fmt_kappa(stat['kappa'])} | {stat['disagreement_count']} |"
            )

    lines.extend(
        [
            "",
            "### Release confusion matrix",
            "",
            *_markdown_confusion_table(overall, "release_decision"),
            "",
            "### Evidence-status confusion matrix",
            "",
            *_markdown_confusion_table(overall, "evidence_status"),
            "",
            "### Failure-label confusion matrix",
            "",
            *_markdown_confusion_table(overall, "primary_failure_label"),
            "",
            "## Adjudication queue",
            "",
            f"- Material candidates: {len(adjudication_pairs)} / {len(pairs)} paired rows",
            f"- Unmatched rows: {len(unmatched)}",
        ]
    )
    for reason, count in sorted(reasons.items()):
        lines.append(f"- `{reason}`: {count}")
    lines.extend(
        [
            "",
            "Only material disagreements are placed in `adjudication_candidates.csv`; "
            "the original reviewer labels remain in `claim_audit_combined.csv`.",
            "",
            "## Review quality",
            "",
            f"- Runs needing focused re-review: {len(rereview_rows)}",
            f"- Runs with an incomplete-review flag: "
            f"{sum(int(row['incomplete_review']) for row in run_rows)}",
            f"- Rows using a generic placeholder claim: "
            f"{sum(int(row['generic_claim_rows']) for row in run_rows)}",
            "",
            "The focused queue also covers the Flat-RAG baseline runs whose reviewers "
            "did not inspect the full output. The baseline is ungated and cannot be "
            "used as a scientific-correctness comparator.",
            "",
            "## Interpretation boundary",
            "",
            "- Agreement is about reviewer labels, not scientific truth.",
            "- `cannot_verify` is distinct from fabrication and is retained as such.",
            "- Missing metadata is not automatically a false citation.",
            "- Invalid field-value spellings are retained and reported as schema "
            "warnings; they are not silently recoded into substantive labels.",
            "- Third-reviewer adjudication is still pending.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _combined_fieldnames() -> list[str]:
    fields = [
        "pair_id",
        "run_id",
        "question_id",
        "domain",
        "condition_id",
        "system",
        "claim_id",
        "mapping_status",
        "claim_text_similarity",
        "claim_text_r1",
        "claim_text_r2",
    ]
    for field in WORKBOOK_FIELDS:
        if field in {
            "review_id",
            "run_id",
            "question_id",
            "domain",
            "condition_id",
            "system",
            "reviewer_id",
            "claim_id",
            "claim_text",
            "reviewer_notes",
        }:
            continue
        fields.extend([f"r1_{field}", f"r2_{field}"])
    fields.extend(
        [
            "agree_evidence_status",
            "agree_primary_failure_label",
            "agree_release_decision",
            "disagreement_fields",
            "metadata_conflicts",
            "adjudication_required",
            "adjudication_reasons",
            "schema_warnings",
            "review_quality_flags",
            "reviewer_notes_r1",
            "reviewer_notes_r2",
            "adjudicated_evidence_status",
            "adjudicated_failure_label",
            "adjudicated_release_decision",
            "adjudication_notes",
        ]
    )
    return fields


def write_outputs(
    output_dir: Path,
    reviewer_rows: list[dict],
    pairs: list[dict],
    run_rows: list[dict],
    rereview_rows: list[dict],
    metrics: dict,
    source_counts: dict,
    normalization_counts: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    combined_fields = _combined_fieldnames()
    reviewer_fields = WORKBOOK_FIELDS + ["source", "normalization_note"]
    normalized_reviewer_rows = [
        {
            **{field: row.get(field, "") for field in WORKBOOK_FIELDS},
            "source": row.get("_source", ""),
            "normalization_note": row.get("_normalization_note", ""),
        }
        for row in reviewer_rows
    ]
    _write_csv(
        output_dir / CSV_OUTPUTS["reviewer_rows"],
        reviewer_fields,
        normalized_reviewer_rows,
    )
    _write_csv(output_dir / CSV_OUTPUTS["combined"], combined_fields, pairs)

    disagreements = [
        pair for pair in pairs if pair.get("disagreement_fields")
    ]
    _write_csv(
        output_dir / CSV_OUTPUTS["disagreements"],
        combined_fields,
        disagreements,
    )
    adjudication = [
        pair for pair in pairs if pair.get("adjudication_required") == "1"
    ]
    _write_csv(
        output_dir / CSV_OUTPUTS["adjudication"],
        combined_fields,
        adjudication,
    )
    _write_csv(
        output_dir / CSV_OUTPUTS["run_level"],
        list(run_rows[0].keys()) if run_rows else [
            "run_id",
            "question_id",
            "domain",
            "condition_id",
            "system",
            "paired_claims",
            "matched_claims",
            "unmatched_claims",
            "exact_evidence",
            "exact_failure",
            "exact_release",
            "adjudication_required",
            "review_quality_flags",
            "incomplete_review",
            "generic_claim_rows",
        ],
        run_rows,
    )
    _write_csv(
        output_dir / CSV_OUTPUTS["rereview"],
        list(rereview_rows[0].keys()) if rereview_rows else [
            "run_id",
            "question_id",
            "domain",
            "condition_id",
            "system",
            "paired_claims",
            "review_quality_flags",
            "recommended_focus",
            "reason",
        ],
        rereview_rows,
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_counts": source_counts,
        "normalization_counts": normalization_counts,
        "pairing": {
            "paired_rows": len(pairs),
            "matched_rows": sum(
                1 for pair in pairs if pair["mapping_status"] == "matched"
            ),
            "unmatched_rows": sum(
                1 for pair in pairs if pair["mapping_status"] != "matched"
            ),
            "adjudication_candidates": sum(
                1 for pair in pairs if pair["adjudication_required"] == "1"
            ),
        },
        "metrics": metrics,
    }
    (output_dir / "agreement_metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_first_pass_markdown(
        output_dir / "audit_first_pass.md",
        metrics,
        pairs,
        run_rows,
        rereview_rows,
        source_counts,
        normalization_counts,
    )


def analyze(
    review_paths: list[Path],
    math_raw: Path | None,
    output_dir: Path,
    overwrite: bool = False,
) -> dict:
    source_rows: list[dict] = []
    source_counts = Counter()
    for index, path in enumerate(review_paths, start=1):
        rows = load_review_csv(path)
        for row in rows:
            row["_source"] = path.as_posix()
        source_rows.extend(rows)
        source_counts["rows"] += len(rows)
        source_counts[f"review_csv_{index}"] = len(rows)
    if math_raw is not None:
        rows = load_math_reviews(math_raw)
        for row in rows:
            row["_source"] = math_raw.as_posix()
        source_rows.extend(rows)
        source_counts["rows"] += len(rows)
        source_counts["math_markdown"] = len(rows)

    _validate_review_rows(source_rows)
    normalization_counts = Counter()
    for row in source_rows:
        note = row.get("_normalization_note", "")
        if "system:F2->F0" in note:
            normalization_counts["f2_to_f0"] += 1
        if "field_shift:repaired" in note:
            normalization_counts["fin_r2_shift_repaired"] += 1
    pairs = pair_reviews(source_rows)
    run_rows = build_run_level(pairs)
    rereview_rows = build_focused_rereview_queue(run_rows)
    metrics = build_metrics(pairs)

    existing = [
        output_dir / name
        for name in (
            *CSV_OUTPUTS.values(),
            "agreement_metrics.json",
            "audit_first_pass.md",
        )
        if (output_dir / name).exists()
    ]
    if existing and not overwrite:
        raise RuntimeError(
            f"Output files already exist in {output_dir}; pass --overwrite to replace them."
        )
    write_outputs(
        output_dir,
        source_rows,
        pairs,
        run_rows,
        rereview_rows,
        metrics,
        dict(source_counts),
        dict(normalization_counts),
    )
    return {
        "pairs": len(pairs),
        "matched_pairs": sum(
            1 for pair in pairs if pair["mapping_status"] == "matched"
        ),
        "adjudication_candidates": sum(
            1 for pair in pairs if pair["adjudication_required"] == "1"
        ),
        "focused_rereview_runs": len(rereview_rows),
        "output_dir": str(output_dir),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--review",
        action="append",
        required=True,
        type=Path,
        help="Reviewer CSV. Repeat for each returned file.",
    )
    parser.add_argument(
        "--math-raw",
        type=Path,
        help="Raw Markdown text or session JSONL containing the MATH tables.",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    result = analyze(
        [path.resolve() for path in args.review],
        args.math_raw.resolve() if args.math_raw else None,
        args.out.resolve(),
        overwrite=args.overwrite,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
