# -*- coding: utf-8 -*-
"""Offline tests for the claim-level audit sampling logic."""

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

import build_claim_audit_packet as packet


class ClaimAuditSamplingTests(unittest.TestCase):
    def _rows(self):
        questions = [
            ("chem01", "chemistry"),
            ("chem02", "chemistry"),
            ("fin01", "finance"),
            ("fin02", "finance"),
            ("math01", "mathematics"),
            ("math02", "mathematics"),
        ]
        conditions = [
            "F0_clean",
            "B1_flat_rag_clean",
            "F0_missing_evidence",
            "F0_corrupted_citation",
            "F0_conflicting_evidence",
            "F0_indirect_prompt_injection",
            "F0_retrieval_unavailable",
            "F0_retrieval_empty",
            "F0_json_invalid",
            "F0_judge_override",
            "F0_failing_judge_plus_injection",
            "A1_no_anchor_gate_plus_injection",
        ]
        rows = []
        for question_id, domain in questions:
            for condition in conditions:
                run_id = f"pilot__{question_id}__{condition}__r01"
                rows.append({
                    "run_id": run_id,
                    "question_id": question_id,
                    "domain": domain,
                    "condition_id": condition,
                    "system": "F0",
                    "is_stress": "0" if condition in {"F0_clean", "B1_flat_rag_clean"} else "1",
                    "plan_status": "validated",
                    "validated": "1" if condition in {
                        "F0_judge_override",
                        "F0_failing_judge_plus_injection",
                    } else "0",
                    "silent_fail_open": "0",
                    "injection_canary_leak": "0",
                })
        rows[0]["validated"] = "0"
        rows[2]["validated"] = "1"
        rows[5]["injection_canary_leak"] = "1"
        rows[4]["silent_fail_open"] = "1"
        return rows

    def test_selection_is_fixed_size_and_includes_required_cases(self):
        rows = self._rows()
        _, selected, _ = packet._select_double_review(rows)
        self.assertEqual(len(selected), packet.TARGET_DOUBLE_REVIEW)

        required = {
            row["run_id"]
            for row in rows
            if (row["is_stress"] == "1" and row["validated"] == "1")
            or row["silent_fail_open"] == "1"
            or row["injection_canary_leak"] == "1"
        }
        self.assertTrue(required.issubset(selected))

        for domain in ("chemistry", "finance", "mathematics"):
            for condition in ("F0_clean", "B1_flat_rag_clean"):
                control = next(
                    row["run_id"]
                    for row in rows
                    if row["domain"] == domain and row["condition_id"] == condition
                )
                self.assertIn(control, selected)


if __name__ == "__main__":
    unittest.main()
