# -*- coding: utf-8 -*-
"""Offline tests for claim-level audit agreement analysis."""

import csv
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import analyze_claim_audit as audit


def _row(**overrides):
    row = {field: "" for field in audit.WORKBOOK_FIELDS}
    row.update(
        {
            "review_id": "REV-001",
            "run_id": "run-001",
            "question_id": "q01",
            "domain": "mathematics",
            "condition_id": "F0_clean",
            "system": "F0",
            "reviewer_id": "R1",
            "claim_id": "C1",
            "claim_text": "A concrete claim",
            "evidence_status": "supported",
            "citation_issue": "none",
            "primary_failure_label": "none",
            "secondary_failure_labels": "none",
            "severity": "1",
            "release_decision": "justified",
            "confidence": "high",
            "reviewer_notes": "",
        }
    )
    row.update(overrides)
    return row


class ClaimAuditParsingTests(unittest.TestCase):
    def test_csv_loader_normalizes_f2_and_deduplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "review.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=audit.WORKBOOK_FIELDS)
                writer.writeheader()
                writer.writerow(_row(system="F2", domain="finance"))
                writer.writerow(_row(system="F2", domain="finance"))
            rows = audit.load_review_csv(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["system"], "F0")
        self.assertEqual(rows[0]["_normalization_note"], "system:F2->F0")

    def test_fin_r2_shift_is_repaired(self):
        shifted = _row(
            review_id="FIN-R2-006",
            run_id="run-fin",
            question_id="fin01",
            domain="finance",
            condition_id="F0_judge_override",
            system="F2",
            reviewer_id="C1",
            claim_id="claim text",
            claim_text="supported",
            evidence_status="none",
            citation_issue="none",
            primary_failure_label="none",
            secondary_failure_labels="3",
            severity="unjustified",
            release_decision="high",
            confidence="review note",
            reviewer_notes="",
        )
        row = audit.normalize_review_row(shifted)
        self.assertEqual(row["system"], "F0")
        self.assertEqual(row["reviewer_id"], "R2")
        self.assertEqual(row["claim_id"], "C1")
        self.assertEqual(row["claim_text"], "claim text")
        self.assertEqual(row["evidence_status"], "supported")
        self.assertEqual(row["release_decision"], "unjustified")
        self.assertEqual(row["reviewer_notes"], "review note")
        self.assertIn("field_shift:repaired", row["_normalization_note"])

    def test_schema_warnings_do_not_recod_label(self):
        row = _row(citation_issue="wrong_citation")
        warnings = audit._schema_warnings(row)
        self.assertEqual(warnings, ["invalid_citation_issue:wrong_citation"])
        self.assertEqual(
            audit.normalize_review_row(row)["citation_issue"],
            "wrong_citation",
        )

    def test_markdown_loader_extracts_math_rows(self):
        header = "| " + " | ".join(audit.WORKBOOK_FIELDS) + " |"
        separator = "|" + "|".join("---" for _ in audit.WORKBOOK_FIELDS) + "|"
        values = [
            "MATH-R1-001",
            "run-001",
            "math01",
            "mathematics",
            "F0_clean",
            "F0",
            "R1",
            "C1",
            "核心假设主张（全文未读）",
            "cannot_verify",
            "none",
            "none",
            "none",
            "2",
            "justified",
            "low",
            "未逐条读取交付全文",
            "",
            "",
            "",
            "",
        ]
        text = "\n".join([header, separator, "| " + " | ".join(values) + " |"])
        rows = audit.load_review_markdown(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reviewer_id"], "R1")
        self.assertEqual(rows[0]["claim_text"], "核心假设主张（全文未读）")

    def test_pairing_keeps_both_labels(self):
        left = _row()
        right = _row(
            review_id="REV-002",
            reviewer_id="R2",
            evidence_status="unsupported",
            primary_failure_label="false_support",
            release_decision="unjustified",
            severity="4",
            reviewer_notes="independent review",
        )
        pairs = audit.pair_reviews([left, right])
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["r1_evidence_status"], "supported")
        self.assertEqual(pairs[0]["r2_evidence_status"], "unsupported")
        self.assertEqual(pairs[0]["adjudication_required"], "1")
        self.assertIn(
            "material_evidence_status_disagreement",
            pairs[0]["adjudication_reasons"],
        )


class ClaimAuditMetricsTests(unittest.TestCase):
    def test_perfect_agreement_has_kappa_one(self):
        pairs = audit.pair_reviews([_row(), _row(review_id="REV-002", reviewer_id="R2")])
        stats = audit.agreement_stats(pairs, "release_decision")
        self.assertEqual(stats["n"], 1)
        self.assertEqual(stats["observed_agreement"], 1.0)
        self.assertEqual(stats["kappa"], 1.0)

    def test_agreement_stats_keep_confusion_matrix(self):
        pairs = []
        for index, (left, right) in enumerate(
            [
                ("supported", "supported"),
                ("supported", "unsupported"),
                ("unsupported", "unsupported"),
                ("unsupported", "supported"),
            ]
        ):
            pairs.append(
                audit.pair_reviews(
                    [
                        _row(
                            review_id=f"R1-{index}",
                            claim_id=f"C{index}",
                            evidence_status=left,
                            release_decision="justified",
                        ),
                        _row(
                            review_id=f"R2-{index}",
                            reviewer_id="R2",
                            claim_id=f"C{index}",
                            evidence_status=right,
                            release_decision="justified",
                        ),
                    ]
                )[0]
            )
        stats = audit.agreement_stats(pairs, "evidence_status")
        self.assertEqual(stats["n"], 4)
        self.assertEqual(stats["disagreement_count"], 2)
        self.assertEqual(stats["matrix"], [[1, 1], [1, 1]])

    def test_incomplete_and_generic_review_flags(self):
        rows = [
            _row(
                claim_text="核心假设主张（全文未读）",
                reviewer_notes="未逐条读取交付全文",
            ),
            _row(review_id="REV-002", reviewer_id="R2", claim_text="具体数字主张", reviewer_notes=""),
        ]
        pairs = audit.pair_reviews(rows)
        flags = set(pairs[0]["review_quality_flags"].split("|"))
        self.assertIn("reviewer_incomplete", flags)
        self.assertIn("generic_claim_text", flags)

    def test_low_claim_similarity_is_a_review_flag(self):
        rows = [
            _row(claim_text="specific claim with numbers"),
            _row(
                review_id="REV-002",
                reviewer_id="R2",
                claim_text="zzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
            ),
        ]
        pair = audit.pair_reviews(rows)[0]
        self.assertIn("claim_text_similarity_low", pair["review_quality_flags"])

    def test_output_bundle_is_written(self):
        pairs = audit.pair_reviews(
            [
                _row(),
                _row(review_id="REV-002", reviewer_id="R2"),
                _row(
                    review_id="REV-003",
                    claim_id="C2",
                    reviewer_notes="未逐条读取交付全文",
                    claim_text="核心假设主张（全文未读）",
                ),
                _row(
                    review_id="REV-004",
                    reviewer_id="R2",
                    claim_id="C2",
                    reviewer_notes="未逐条读取交付全文",
                    claim_text="核心假设主张（全文未读）",
                ),
            ]
        )
        run_rows = audit.build_run_level(pairs)
        rereview = audit.build_focused_rereview_queue(run_rows)
        metrics = audit.build_metrics(pairs)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "out"
            audit.write_outputs(
                output,
                [],
                pairs,
                run_rows,
                rereview,
                metrics,
                {"rows": 4},
                {"f2_to_f0": 0},
            )
            self.assertTrue((output / "claim_audit_combined.csv").exists())
            self.assertTrue((output / "reviewer_rows_normalized.csv").exists())
            self.assertTrue((output / "agreement_metrics.json").exists())
            self.assertTrue((output / "audit_first_pass.md").exists())
            self.assertTrue((output / "focused_rereview_queue.csv").exists())


if __name__ == "__main__":
    unittest.main()
