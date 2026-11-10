# -*- coding: utf-8 -*-
"""Regression tests for DeepSeek off-peak cost protection."""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import llm_client


class DeepSeekPricingGuardTests(unittest.TestCase):
    def test_weekday_peak_and_off_peak_boundaries(self):
        cases = {
            (0, 59): True,
            (1, 0): False,
            (3, 59): False,
            (4, 0): True,
            (5, 59): True,
            (6, 0): False,
            (9, 59): False,
            (10, 0): True,
        }
        for (hour, minute), expected in cases.items():
            with self.subTest(hour=hour, minute=minute):
                now = datetime(2026, 9, 28, hour, minute, tzinfo=timezone.utc)
                self.assertEqual(llm_client.is_deepseek_off_peak(now), expected)

    def test_weekends_are_off_peak_all_day(self):
        now = datetime(2026, 10, 3, 2, 0, tzinfo=timezone.utc)
        self.assertEqual(now.weekday(), 5)
        self.assertTrue(llm_client.is_deepseek_off_peak(now))

    def test_explicit_holiday_override_uses_china_date(self):
        now = datetime(2026, 10, 1, 2, 0, tzinfo=timezone.utc)
        with mock.patch.dict(
            os.environ,
            {"DEEPSEEK_OFF_PEAK_EXTRA_DATES": "2026-10-01"},
            clear=False,
        ):
            self.assertTrue(llm_client.is_deepseek_off_peak(now))

    def test_guard_rejects_peak_and_accepts_off_peak(self):
        peak = datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc)
        off_peak = datetime(2026, 9, 28, 5, 0, tzinfo=timezone.utc)
        with mock.patch.dict(
            os.environ,
            {"DEEPSEEK_OFF_PEAK_ONLY": "1"},
            clear=False,
        ):
            with self.assertRaises(llm_client.DeepSeekOffPeakError):
                llm_client.require_deepseek_off_peak(peak)
            llm_client.require_deepseek_off_peak(off_peak)

    def test_explicit_override_disables_guard(self):
        peak = datetime(2026, 9, 28, 2, 0, tzinfo=timezone.utc)
        with mock.patch.dict(
            os.environ,
            {"DEEPSEEK_OFF_PEAK_ONLY": "0"},
            clear=False,
        ):
            llm_client.require_deepseek_off_peak(peak)


if __name__ == "__main__":
    unittest.main()
