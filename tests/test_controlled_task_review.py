"""Check the declared scope of the shared controlled-task review adapter."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from programmatic_release_tasks import REVIEW_SCHEMA, REVIEW_SYSTEM, make_cases, render
from selective_release import ReleasePolicy, plan_units, PLANNED_RE


class ControlledTaskReviewTests(unittest.TestCase):
    def test_neutral_novelty_is_explicit_and_enforced(self):
        import jsonschema
        review = {
            "hypothesis_score": 95, "data_score": 95,
            "dimensions": {"testability": 95, "evidence": 95, "feasibility": 95, "novelty": 75},
            "feedback": "No deficiency within the task contract.",
        }
        jsonschema.validate(review, REVIEW_SCHEMA)
        review["dimensions"]["novelty"] = 95
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(review, REVIEW_SCHEMA)
        self.assertIn("NOT ASSESSED", REVIEW_SYSTEM)
        self.assertIn("BOTH controller arms", REVIEW_SYSTEM)

    def test_quality_thresholds_are_unchanged(self):
        policy = ReleasePolicy()
        self.assertEqual((policy.target, policy.evidence_floor, policy.dimension_floor,
                          policy.novelty_floor), (90, 60, 75, 50))

    def test_fixed_proposal_is_conditional_and_visible_to_verifier(self):
        for case in make_cases("development"):
            units = plan_units(render(case["initial_artifact"], case["public"]["operation"]))
            self.assertIn("if the required inputs are available", units[-1]["text"])
            self.assertTrue(PLANNED_RE.search(units[-1]["text"]))

    def test_rubric_is_common_and_contains_no_condition_or_gold_fields(self):
        self.assertNotIn("T5", REVIEW_SYSTEM)
        self.assertNotIn("T0", REVIEW_SYSTEM)
        self.assertNotIn("eligible", REVIEW_SCHEMA["properties"])
        self.assertNotIn("approved", REVIEW_SCHEMA["properties"])
        self.assertIn("insufficient-evidence statement", REVIEW_SYSTEM)


if __name__ == "__main__":
    unittest.main()
