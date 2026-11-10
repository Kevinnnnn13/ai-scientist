"""Offline checks for preserved attempts and valid resumption of frozen data."""

from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from continue_controlled_study import choose_attempt, result_path
from run_programmatic_release import digest, write_new


class ControlledResumeTests(unittest.TestCase):
    def test_new_unit_uses_original_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            target, interrupted = choose_attempt(study, "u0001", False)
            self.assertEqual(target, study / "runs/u0001")
            self.assertEqual(interrupted, [])

    def test_interrupted_attempt_remains_intact(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            old = study / "runs/u0001"
            write_new(old / "raw.json", {"status": "interrupted"})
            original = digest(old / "raw.json")
            with self.assertRaisesRegex(RuntimeError, "explicit resume"):
                choose_attempt(study, "u0001", False)
            target, interrupted = choose_attempt(study, "u0001", True)
            self.assertEqual(target, study / "attempts/u0001/attempt_002")
            self.assertEqual(interrupted, ["runs/u0001"])
            self.assertEqual(digest(old / "raw.json"), original)

    def test_finished_failure_is_never_retried_to_select_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            old = study / "runs/u0001"
            write_new(old / "result.json", {"status": "worker_error"})
            target, interrupted = choose_attempt(study, "u0001", True)
            self.assertEqual(target, old)
            self.assertFalse(interrupted)

    def test_finished_second_attempt_is_reused_after_launcher_interruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            (study / "runs/u0001").mkdir(parents=True)
            new = study / "attempts/u0001/attempt_002"
            write_new(new / "result.json", {"status": "completed"})
            self.assertEqual(choose_attempt(study, "u0001", True)[0], new)

    def test_modified_and_outside_results_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary) / "study"
            path = study / "runs/u0001/result.json"
            write_new(path, {"status": "completed"})
            row = {"unit_id": "u0001", "result_sha256": digest(path)}
            self.assertEqual(result_path(study, row), path)
            row["result_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "checksum"):
                result_path(study, row)
            row["result_path"] = "../outside.json"
            with self.assertRaisesRegex(ValueError, "escapes"):
                result_path(study, row)


if __name__ == "__main__":
    unittest.main()
