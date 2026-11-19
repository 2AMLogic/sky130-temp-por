#!/usr/bin/env python3
"""Regression tests for the array-pair signal-vs-sigma check (issue #446).

`run_pnp_mismatch.py`'s `signal_vs_sigma[dr1|dr10]` check used to guard the
`sigma / signal` division in its pass predicate but re-evaluate the same
division unconditionally in its diagnostic f-string, so a measured mean dVBE
of exactly zero crashed the grader with `ZeroDivisionError` before the failure
could be recorded. The runner now computes the ratio once, and a zero
|mean dVBE| marks the check failed with an explicit "undefined ratio" detail.

These tests drive the real `evaluate()` with synthetic samples, stdlib only:
no SPICE, no PDK, no fleet.

Run: python3 -I sim/pnp-mismatch/test_pnp_mismatch.py
"""
from __future__ import annotations

import statistics
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_pnp_mismatch as rpm  # noqa: E402

N_SAMPLES = 2
ZERO_MEAN_SAMPLES = [0.001, -0.001]  # mean exactly zero, sigma nonzero


def _samples(vector_values: dict[str, list[float]]) -> list[dict[str, float]]:
    """Per-vector sample lists -> the list-of-dicts shape `evaluate()` reads."""
    return [
        {v: vector_values[v][i] for v in rpm.ALL_VECTORS}
        for i in range(N_SAMPLES)
    ]


class SignalVsSigmaTest(unittest.TestCase):
    """The signal_vs_sigma check on the array1v8 pairs (dr1, dr10)."""

    def setUp(self):
        self.point = rpm.build_points(N_SAMPLES)[0]
        assert self.point.role == "mismatch", "point 0 must exercise the mismatch path"

    def check(self, result, vector):
        by_name = {c["name"]: c for c in result["checks"]}
        self.assertIn(f"signal_vs_sigma[{vector}]", by_name)
        return by_name[f"signal_vs_sigma[{vector}]"]

    @staticmethod
    def ratio_text(detail: str) -> str:
        """The four-decimal `sigma/|mean dVBE|` value the diagnostic renders."""
        prefix = "sigma/|mean dVBE| = "
        start = detail.index(prefix) + len(prefix)
        return detail[start:].split(" ", 1)[0]

    def test_zero_mean_records_failed_check_not_crash(self):
        """Zero |mean dVBE| -> both array checks and the point fail, readable detail."""
        result = rpm.evaluate(
            self.point, _samples({v: ZERO_MEAN_SAMPLES for v in rpm.ALL_VECTORS})
        )
        for vector in ("dr1", "dr10"):
            check = self.check(result, vector)
            self.assertFalse(check["pass"], f"{vector}: zero mean must fail the check")
            self.assertIn("undefined", check["detail"])
            self.assertIn("zero", check["detail"])
        self.assertFalse(result["pass"], "the point must record the failure, not crash")

    def test_nonzero_mean_failing_ratio_has_four_decimal_text(self):
        """Nonzero mean, ratio above SIGNAL_RATIO_MAX -> failed with ratio text."""
        # mean 8 mV, sigma ~2.828 mV -> ratio ~0.3536 > SIGNAL_RATIO_MAX
        values = {"dr1": [0.010, 0.006], "dr10": [0.010, 0.006]}
        result = rpm.evaluate(
            self.point,
            _samples({v: values.get(v, [0.0, 0.0]) for v in rpm.ALL_VECTORS}),
        )
        for vector in ("dr1", "dr10"):
            check = self.check(result, vector)
            self.assertFalse(check["pass"])
            self.assertRegex(check["detail"], r"sigma/\|mean dVBE\| = \d+\.\d{4} ")
            expected = f"{statistics.stdev(values[vector]) / statistics.mean(values[vector]):.4f}"
            self.assertEqual(self.ratio_text(check["detail"]), expected)

    def test_nonzero_mean_passing_ratio_passes_with_ratio_text(self):
        """Nonzero mean, ratio inside SIGNAL_RATIO_MAX -> passes with the same text."""
        # mean 10.1 mV, sigma ~0.1414 mV -> ratio ~0.0140 <= SIGNAL_RATIO_MAX
        values = {"dr1": [0.010, 0.0102], "dr10": [0.010, 0.0102]}
        result = rpm.evaluate(
            self.point,
            _samples({v: values.get(v, [0.0, 0.0]) for v in rpm.ALL_VECTORS}),
        )
        for vector in ("dr1", "dr10"):
            check = self.check(result, vector)
            self.assertTrue(check["pass"])
            self.assertRegex(check["detail"], r"sigma/\|mean dVBE\| = 0\.0140 ")


if __name__ == "__main__":
    unittest.main()
