# -*- coding: utf-8 -*-
"""Offline regression tests for the research-quality audit modules."""

import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import data_source_checker
import citation_checker
import plan_quality_checker


class PlanQualityCheckerTests(unittest.TestCase):
    def test_false_precision_needs_source_label(self):
        unsupported = "预期 Jaccard = 87.3 ± 2.1%。"
        supported = "预期 Jaccard = 87.3 ± 2.1%（[待标定估计]）。"
        self.assertTrue(plan_quality_checker.check_false_precision("H1", unsupported))
        self.assertFalse(plan_quality_checker.check_false_precision("H1", supported))

    def test_threshold_gap_is_detected(self):
        text = "支持：R² ≥ 0.93；推翻：R² < 0.91。"
        issues = plan_quality_checker.check_threshold_gap("H1", text)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["type"], "statistical_inconsistency")

    def test_threshold_gap_does_not_cross_metrics(self):
        text = "支持：WVT下降 ≥ 2.0数量级，且R² ≥ 0.93；推翻：WVT < 1.8数量级，或R² < 0.91。"
        issues = plan_quality_checker.check_threshold_gap("H1", text)
        self.assertEqual(len(issues), 1)
        self.assertIn("r2", issues[0]["quote"])

    def test_predictive_question_requires_out_of_sample_test(self):
        question = "Can systemic risk be predicted?"
        missing = plan_quality_checker.check_question_alignment(
            question,
            "使用 Cox 模型估计风险比，并报告 p 值。",
        )
        present = plan_quality_checker.check_question_alignment(
            question,
            "按时间划分训练集与测试集，报告样本外 AUC 和校准误差。",
        )
        self.assertEqual(len(missing), 1)
        self.assertFalse(present)


class DataSourceCheckerTests(unittest.TestCase):
    def test_extract_sources_ignores_statistical_method(self):
        state = {
            "best_hypothesis": (
                "假设 1\n"
                "① 背景依据：测试。\n"
                "② 明确主张：测试。\n"
                "③ 预期结果：测试。\n"
                "④ 验证方法：WVT使用MOCON PERMATRAN-W 3/31测试，n=15；"
                "统计采用双侧t检验，n=15。\n"
                "⑤ 判定标准：测试。"
            )
        }
        snippets = data_source_checker.extract_source_snippets(state)
        self.assertTrue(any("MOCON" in item for item in snippets))
        self.assertFalse(any("统计采用" in item for item in snippets))

    def test_judge_sources_accepts_chinese_keys_fallback(self):
        class FakeError(Exception):
            last_content = (
                '[{"kind":"external_dataset","数据源":"BIS CBS","是否公开":"unverified",'
                '"获取方式":"未说明","粒度":"未说明","时间覆盖":"2004-2010",'
                '"是否支持当前分析":"unverified","风险说明":"缺机构间连边"}]'
            )

        state = {"question": "test", "best_hypothesis": "test"}
        with mock.patch.object(data_source_checker, "json_chat", side_effect=FakeError()):
            items = data_source_checker.judge_sources(state, ["BIS CBS"])
        self.assertEqual(items[0]["source"], "BIS CBS")
        self.assertEqual(items[0]["coverage"], "2004-2010")


class CitationCheckerTests(unittest.TestCase):
    def test_origin_check_uses_verification_text(self):
        state = {
            "best_hypothesis": (
                "假设 1\n"
                "① 背景依据：已有文献提出相关风险指标。\n"
                "② 明确主张：测试。\n"
                "③ 预期结果：测试。\n"
                "④ 验证方法：DebtRank按 Bardoscia et al. (2017) 算法实现。\n"
                "⑤ 判定标准：测试。"
            )
        }
        premises = citation_checker.extract_premises(state)
        self.assertEqual(len(premises), 1)
        self.assertIn("Bardoscia", premises[0]["origin_text"])


if __name__ == "__main__":
    unittest.main()
