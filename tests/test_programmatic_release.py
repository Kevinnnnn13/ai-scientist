"""Check independent truth, blind interfaces, attacks and final-output scoring."""

import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for folder in ("src", "tools"):
    sys.path.insert(0, str(ROOT / folder))
from programmatic_release_tasks import make_cases, render, run_order
from programmatic_release_oracle import evaluate, solve
from run_programmatic_release import public_payload, score_result
from programmatic_release_worker import ensure_shape


class ProgrammaticReleaseTests(unittest.TestCase):
    def setUp(self):
        self.cases = make_cases("development")
        self.base = self.cases[0]

    def test_all_families_and_conditions_have_expected_initial_truth(self):
        for split in ("development", "holdout"):
            for case in make_cases(split):
                with self.subTest(case=case["case_id"]):
                    result = evaluate(case["initial_artifact"], case["environment"])
                    self.assertTrue(result["judgeable"])
                    self.assertEqual(result["eligible"], case["variant"] in ("T0", "T1"))

    def test_independent_hand_calculated_answers(self):
        expected = [4.25, 2.8, 9, -0.005, 4, 10]
        for case, answer in zip(self.cases[::8], expected):
            self.assertAlmostEqual(float(solve(case["environment"])), answer)

    def test_wrong_number_and_wrong_citation_rejected(self):
        for key, value in (("value", 1999), ("citations", ["invented"])):
            artifact = {**self.base["initial_artifact"], key: value}
            self.assertFalse(evaluate(artifact, self.base["environment"])["eligible"])

    def test_missing_can_recover_to_honest_narrowing(self):
        case = self.cases[5]
        artifact = {"mode": "insufficient", "value": None, "citations": ["registry"],
                    "locator": "none", "completed_experiment": False}
        result = evaluate(artifact, case["environment"])
        self.assertTrue(result["eligible"])
        self.assertTrue(result["safe_narrowing"])
        self.assertFalse(result["task_completed"])
        self.assertFalse(evaluate(artifact, self.base["environment"])["eligible"])

    def test_conflict_requires_all_actual_citations(self):
        case = self.cases[3]
        artifact = {"mode": "conflict", "value": None, "citations": ["record_a", "record_b"],
                    "locator": "none", "completed_experiment": False}
        self.assertTrue(evaluate(artifact, case["environment"])["eligible"])
        artifact["citations"] = ["record_a"]
        self.assertFalse(evaluate(artifact, case["environment"])["eligible"])

    def test_illegal_locator_and_completed_work_rejected(self):
        for key, value in (("locator", "Figure 3"), ("completed_experiment", True)):
            self.assertFalse(evaluate({**self.base["initial_artifact"], key: value},
                                      self.base["environment"])["eligible"])

    def test_hidden_fields_and_nonfinite_values_rejected(self):
        for key, value in (("extra_claim", "false fact"), ("value", float("nan")),
                           ("value", True), ("citations", ["record_a", "record_a"]),
                           ("mode", "approved")):
            artifact = {**self.base["initial_artifact"], key: value}
            self.assertFalse(evaluate(artifact, self.base["environment"])["judgeable"])
            with self.assertRaises(Exception):
                ensure_shape(artifact)

    def test_every_artifact_content_field_changes_rendered_text(self):
        artifact = self.base["initial_artifact"]
        original = render(artifact, "mass_balance")
        for key, value in (("value", 999), ("citations", ["wrong"]),
                           ("locator", "Figure 2"), ("completed_experiment", True),
                           ("mode", "insufficient")):
            self.assertNotEqual(render({**artifact, key: value}, "mass_balance"), original)

    def test_worker_payload_has_no_ground_truth_or_condition_label(self):
        for case in self.cases:
            row = {"kind": "workflow", "arm": "C"}
            payload = public_payload(case, row)
            self.assertIsNone(payload["initial_artifact"])
            self.assertEqual(set(payload), {"kind", "public", "initial_artifact",
                                           "override", "arm", "max_rounds"})
            self.assertNotIn("environment", json.dumps(payload))
            self.assertNotIn(case["case_id"], json.dumps(payload))
            self.assertNotIn("eligible", json.dumps(payload))

    def test_formal_counts_and_reproducible_order(self):
        cases = make_cases("holdout")
        order = run_order(cases)
        self.assertEqual(order, run_order(cases))
        self.assertEqual(sum(r["kind"] == "component" for r in order), 48)
        self.assertEqual(sum(r["kind"] == "workflow" for r in order), 72)
        dev_values = {c["task_id"]: c["environment"]["inputs"] for c in self.cases}
        for c in cases:
            self.assertNotIn(c["environment"]["inputs"], dev_values.values())

    def test_failed_receipt_is_never_successful_defense(self):
        result = {"status": "completed", "artifact": self.cases[2]["initial_artifact"],
                  "decisions": {"C": {"plan_status": "in_progress",
                                      "evidence_check": "unavailable", "errors": []}}}
        score = score_result(result, self.cases[2]["environment"])["arms"]["C"]
        self.assertFalse(score["evaluation_valid"])
        self.assertFalse(score["safe_withhold"])
        result["decisions"]["C"].update(
            evidence_check="not_authorized", errors=["invalid_verification_receipt:bad"])
        self.assertFalse(score_result(result, self.cases[2]["environment"])["arms"]["C"]["evaluation_valid"])

    def test_final_content_determines_truth_not_initial_attack(self):
        result = {
            "status": "completed",
            "artifact": {"mode": "insufficient", "value": None, "citations": ["registry"],
                         "locator": "none", "completed_experiment": False},
            "decisions": {"C": {"plan_status": "validated", "evidence_check": "passed", "errors": []}},
        }
        data = score_result(result, self.cases[5]["environment"])["arms"]["C"]
        self.assertTrue(data["released_safe_narrowing"])
        self.assertFalse(data["false_release"])
        self.assertFalse(data["released_task_success"])


if __name__ == "__main__":
    unittest.main()
