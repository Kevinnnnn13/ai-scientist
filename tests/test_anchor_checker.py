# -*- coding: utf-8 -*-
"""Regression tests for deterministic figure/table/experiment anchor checks."""

import os
import sys
import unittest
import contextlib
import io
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import anchor_checker
import langgraph_agent
import consumer


class AnchorCheckerTests(unittest.TestCase):
    def _passing_state(self):
        return {
            "quality_target": 90,
            "hypothesis_score": 92,
            "data_score": 72,
            "dimensions": {
                "testability": 96,
                "evidence": 88,
                "feasibility": 92,
                "novelty": 88,
            },
        }

    def test_specific_figure_locator_is_blocked(self):
        issues = anchor_checker.check_hypothesis(
            "文献[1]图4显示，界面包覆可以降低副反应。",
            {"literature": [{"标题": "A paper title"}]},
        )
        self.assertTrue(any(i["type"] == "specific_locator" for i in issues))

    def test_chemical_silicon_is_not_treated_as_supplementary_information(self):
        issues = anchor_checker.check_hypothesis(
            "采用 Si 片作为离子注入标准样品，并用 Si 片标定浓度。",
            {},
        )
        self.assertFalse(issues)

    def test_explicit_supplementary_information_locator_is_blocked(self):
        issues = anchor_checker.check_hypothesis(
            "具体参数见 SI Table 2，实验流程见 SI。",
            {},
        )
        self.assertTrue(any(i["type"] == "specific_locator" for i in issues))

    def test_completed_preexperiment_claim_is_blocked(self):
        issues = anchor_checker.check_hypothesis(
            "预实验 n=3 证实，界面包覆后阻抗显著下降。",
            {},
        )
        self.assertTrue(any(i["type"] == "unverified_experiment_claim" for i in issues))

    def test_future_preexperiment_plan_is_not_blocked(self):
        issues = anchor_checker.check_hypothesis(
            "计划开展预实验验证界面包覆对阻抗的影响。",
            {},
        )
        self.assertFalse(issues)

    def test_conditional_preexperiment_result_is_not_blocked(self):
        issues = anchor_checker.check_hypothesis(
            "若预实验显示阻抗未下降，则排除该批次样品。",
            {},
        )
        self.assertFalse(issues)

    def test_anchor_block_is_a_hard_release_gate(self):
        state = self._passing_state()
        state["anchor_blocked"] = True
        self.assertFalse(langgraph_agent.pass_check(state))
        self.assertFalse(langgraph_agent.exploratory_check(state))
        plan_status, _, reason = langgraph_agent.assess_plan_release(state)
        self.assertEqual(plan_status, "in_progress")
        self.assertIn("未经核验", reason)

    def test_round_limit_cannot_override_anchor_release_status(self):
        state = self._passing_state()
        state.update({"anchor_blocked": True, "rounds": langgraph_agent.MAX_ROUNDS})
        plan_status, _, _ = langgraph_agent.assess_plan_release(state)
        self.assertEqual(plan_status, "in_progress")
        self.assertEqual(langgraph_agent.route_review(state), langgraph_agent.END)

    def test_review_node_blocks_and_routes_back(self):
        state = {
            "question": "如何提高高镍三元正极锂离子电池的循环稳定性？",
            "gap": "界面退化机制仍需验证。",
            "hypothesis": "文献[1]图4显示，界面包覆可以降低副反应。",
            "hypothesis_history": [],
            "revision_notes": "",
            "literature": [{"标题": "A paper title", "期刊": "Test", "年份": 2025}],
            "knowledge_tree": None,
            "score_history": [],
            "review": [],
            "points": [],
            "quality_target": 90,
            "rounds": 0,
            "data_score": 72,
            "hypothesis_score": 0,
            "last_feedback_ts": 0,
            "adj_cache": None,
            "run_no": None,
            "run_folder": None,
            "search_exhausted": False,
            "soft_search_rounds": 0,
            "total_soft_searches": 0,
            "consecutive_data_rounds": 0,
            "total_data_rounds": 0,
            "last_new_relevant": 0,
            "tree_version": 0,
            "probe_count": 0,
            "points_healthcheck_round": 0,
            "filtered_out": [],
            "search_keywords": [],
            "search_requested": False,
        }
        review_json = {
            "mode": "hypothesis",
            "data_score": 72,
            "hypothesis_score": 92,
            "dimensions": {
                "testability": 96,
                "evidence": 88,
                "feasibility": 92,
                "novelty": 88,
            },
            "bottleneck": "evidence",
            "reasons": [
                {
                    "dimension": "testability",
                    "location": "验证方法",
                    "issue": "需要明确验证条件。",
                    "suggestion": "补充判定标准。",
                    "expected_gain": 1,
                }
            ],
            "points": [],
        }
        with contextlib.redirect_stdout(io.StringIO()):
            with mock.patch.object(langgraph_agent, "_write_progress"), \
                 mock.patch.object(langgraph_agent, "_adjudicate_feedback", return_value=({}, "", False)), \
                 mock.patch.object(consumer, "consumer_test", return_value=("consumable", [], [])), \
                 mock.patch.object(langgraph_agent, "json_chat", return_value=review_json):
                result = langgraph_agent.review_hypothesis(state)

        self.assertTrue(result["anchor_blocked"])
        self.assertEqual(result["plan_status"], "in_progress")
        self.assertIn("确定性锚点核查未通过", result["feedback"])
        self.assertIn("文献[1]图4", result["review"][-1])
        self.assertEqual(langgraph_agent.route_review(result), "hypothesis")


if __name__ == "__main__":
    unittest.main()
