# -*- coding: utf-8 -*-
"""Regression tests for validated vs exploratory plan release semantics."""

import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import langgraph_agent


class PlanReleaseTests(unittest.TestCase):
    def _dims(self):
        return {
            "testability": 96,
            "evidence": 88,
            "feasibility": 92,
            "novelty": 88,
        }

    def test_low_data_cannot_be_released_as_validated(self):
        state = {
            "quality_target": 90,
            "hypothesis_score": 92,
            "data_score": 3,
            "dimensions": self._dims(),
            "gap_confirmed_latched": True,
            "total_data_rounds": 3,
        }
        self.assertFalse(langgraph_agent.pass_check(state))
        self.assertTrue(langgraph_agent.exploratory_check(state))
        plan_status, evidence_status, _ = langgraph_agent.assess_plan_release(state)
        self.assertEqual(plan_status, "exploratory")
        self.assertEqual(evidence_status, "insufficient_evidence")

    def test_verified_evidence_can_be_released_as_validated(self):
        state = {
            "quality_target": 90,
            "hypothesis_score": 92,
            "data_score": 72,
            "dimensions": self._dims(),
        }
        plan_status, evidence_status, _ = langgraph_agent.assess_plan_release(state)
        self.assertEqual(plan_status, "validated")
        self.assertEqual(evidence_status, "verified")

    def test_exploratory_requires_resolved_evidence_search(self):
        state = {
            "quality_target": 90,
            "hypothesis_score": 92,
            "data_score": 3,
            "dimensions": self._dims(),
        }
        self.assertFalse(langgraph_agent.exploratory_check(state))
        plan_status, evidence_status, _ = langgraph_agent.assess_plan_release(state)
        self.assertEqual(plan_status, "in_progress")
        self.assertEqual(evidence_status, "searching")

    def test_exploratory_delivery_marks_unverified(self):
        state = {
            "question": "如何提高高镍三元正极锂离子电池的循环稳定性？",
            "plan_status": "exploratory",
            "evidence_status": "insufficient_evidence",
            "release_reason": "检索预算已耗尽，证据覆盖不足。",
            "best_score": 91,
            "best_data_score": 19,
            "best_hypothesis": "通过界面包覆降低高镍正极的副反应。",
            "knowledge_gaps": ["缺少循环后 Ni 溶出的直接定量证据"],
            "verification": {
                "summary": "本方案为探索性方案，证据覆盖不足，不能视为已验证。",
                "claims": [{"claim": "界面包覆会降低副反应", "verdict": "可验证"}],
            },
        }
        text = langgraph_agent.build_final_delivery(state)
        self.assertIn("探索性完成", text)
        self.assertIn("不能视为已验证", text)
        self.assertIn("91 / 100", text)
        self.assertIn("19 / 100", text)
        self.assertIn("缺少循环后", text)

    def test_save_run_log_writes_final_delivery(self):
        state = {
            "question": "测试问题",
            "plan_status": "exploratory",
            "evidence_status": "insufficient_evidence",
            "release_reason": "证据覆盖不足。",
            "best_score": 91,
            "best_data_score": 19,
            "best_hypothesis": "测试假设",
            "score_history": [],
            "knowledge_gaps": [],
            "verification": {"summary": "探索性方案，未验证。", "claims": [], "results_preview": ""},
        }
        with tempfile.TemporaryDirectory() as folder:
            state["run_folder"] = folder
            state["run_no"] = 1
            langgraph_agent.save_run_log(state, "测试问题", 90)
            final_path = os.path.join(folder, "05_最终交付.md")
            self.assertTrue(os.path.isfile(final_path))
            with open(final_path, encoding="utf-8") as f:
                text = f.read()
            self.assertIn("不能视为已验证", text)
            anchor_path = os.path.join(folder, "06_锚点与预实验核查报告.md")
            self.assertTrue(os.path.isfile(anchor_path))


if __name__ == "__main__":
    unittest.main()
