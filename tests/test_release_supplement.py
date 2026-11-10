import copy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from programmatic_release_tasks import make_cases
from release_supplement_worker import run
from run_release_supplement import semantic_only
from release_fairness_check import ENGLISH_COMPLETED


class SupplementTests(unittest.TestCase):
    def payload(self):
        case = make_cases("development")[0]
        return {"public": case["public"], "initial_artifact": case["initial_artifact"],
                "override": False, "arm": "D"}

    def test_private_labels_rejected_before_call(self):
        payload = self.payload()
        payload["gold"] = True
        with self.assertRaises(ValueError):
            run(payload, lambda *a, **k: self.fail("model must not be called"))

    def test_d_does_not_let_override_bypass_negative_second_review(self):
        payload = self.payload()
        payload["override"] = True
        seen = []
        def model(prompt, **kwargs):
            seen.append((prompt, kwargs))
            return {"verdict": "unsupported", "reason": "missing evidence"}
        result = run(payload, model)
        self.assertEqual(result["decisions"]["D"]["plan_status"], "in_progress")
        self.assertEqual(len(seen), 1)
        self.assertNotIn("environment", seen[0][0])
        self.assertNotIn("case_id", seen[0][0])

    def test_d_support_releases_and_invalid_enum_faults(self):
        result = run(self.payload(), lambda *a, **k: {"verdict": "supported", "reason": "supported"})
        self.assertEqual(result["decisions"]["D"]["plan_status"], "validated")
        import jsonschema
        with self.assertRaises(jsonschema.ValidationError):
            run(self.payload(), lambda *a, **k: {"verdict": "approve", "reason": "ok"})

    def test_english_addition_distinguishes_future_fixture(self):
        self.assertIsNotNone(ENGLISH_COMPLETED.search(
            "We completed the experiments and observed this result in our own measurements."))
        self.assertIsNone(ENGLISH_COMPLETED.search(
            "We propose an independent arithmetic check; this is a future verification step."))

    def test_semantic_ablation_keeps_negative_verdicts(self):
        receipt = {"units": [{"kind": "factual", "verdict": "supported"},
                             {"kind": "planned", "verdict": "not_applicable"}]}
        self.assertTrue(semantic_only(receipt))
        negative = copy.deepcopy(receipt)
        negative["units"][0]["verdict"] = "unsupported"
        self.assertFalse(semantic_only(negative))
        self.assertFalse(semantic_only({"units": [{"kind": "planned", "verdict": "not_applicable"}]}))


if __name__ == "__main__":
    unittest.main()
