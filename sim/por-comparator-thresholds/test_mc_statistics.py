#!/usr/bin/env python3
"""Tests for the mismatch Monte Carlo statistics reduction (issue #348).

The `--axis mc` record reports, per corner, the mean and sample sigma (Bessel,
n-1) of VPOR-up, VPOR-down and hysteresis over the VALID samples, plus the
statistical resolution of that sigma as a number.  The defect class this pins:
a statistics layer that quietly mis-measures the very spread it exists to
report.  Four ways that happens, each with a test:

  * a population (n) divisor instead of Bessel (n-1) -- understates sigma;
  * hysteresis sigma combined from the two MARGINAL sigmas instead of computed
    per sample -- comparator offset moves both edges of one realisation in the
    same direction, so the marginal combination overstates the spread, in the
    correlated limit to a value that is pure artifact (per-sample spread 0);
  * N counted from run samples instead of valid samples -- exclusions shrink N
    and must shrink the reported N and the resolution figure with it;
  * an all-invalid corner rendered as sigma = 0 -- "nothing was measured" must
    stay a three-state NO-RESULT, never a measurement of zero spread;
  * the resolution figure itself: 1/sqrt(2(N-1)), exact.

Stdlib only: no SPICE, no PDK, no fleet, no records written.

Run: python3 -I sim/por-comparator-thresholds/test_mc_statistics.py
"""
from __future__ import annotations

import math
import statistics
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_thresholds_campaign as m  # noqa: E402


def vsample(i, vup, vdn):
    """One valid sample the way mc_samples() emits it (per-sample hysteresis inside)."""
    return {"sample": i, "valid": True, "reason": None, "vup": vup, "vdn": vdn, "hys": vup - vdn}


def isample(i, reason):
    """One excluded sample with the reason recorded verbatim."""
    return {"sample": i, "valid": False, "reason": reason, "vup": None, "vdn": None, "hys": None}


V = 2.7  # any positive base; the statistics under test are shift-invariant


class BesselDivisor(unittest.TestCase):
    def test_two_samples_sigma_is_half_the_gap(self):
        """n-1: two samples a, b must give sigma = |a-b|/sqrt(2), not |a-b|/2."""
        st = m.corner_mc_stats([vsample(1, V, V - 0.16), vsample(2, V + 0.004, V - 0.16 + 0.004)])
        up = st["stats"]["vpor_up_v"]
        self.assertAlmostEqual(up["sigma_v"], abs(0.004) / math.sqrt(2), places=12)
        self.assertNotAlmostEqual(up["sigma_v"], abs(0.004) / 2, places=12)

    def test_matches_statistics_stdev_on_a_wider_fixture(self):
        xs = [V + 0.001 * k for k in (0, 1, -2, 4, -1, 3)]
        st = m.corner_mc_stats([vsample(i + 1, x, x - 0.15) for i, x in enumerate(xs)])
        self.assertAlmostEqual(st["stats"]["vpor_up_v"]["sigma_v"], statistics.stdev(xs), places=15)
        # and the population (n) divisor is measurably smaller on this fixture
        self.assertAlmostEqual(statistics.stdev(xs), statistics.pstdev(xs) * math.sqrt(len(xs) / (len(xs) - 1)), places=15)
        self.assertGreater(st["stats"]["vpor_up_v"]["sigma_v"], statistics.pstdev(xs))


class PerSampleHysteresis(unittest.TestCase):
    def test_correlated_fixture_per_sample_not_marginal(self):
        """Comparator offset shifts both edges of ONE realisation together.

        Fixture: down tracks up with a fixed 160 mV offset plus a common per-sample
        shift, so the per-sample hysteresis is CONSTANT (sigma 0) while both marginal
        sigmas are large.  The marginal combination sqrt(sigma_up^2 + sigma_dn^2) would
        report a spread that is pure artifact."""
        shifts = (0.0, 3.0, -2.0, 5.0, -4.0, 1.0)
        samples = [vsample(i + 1, V + d, V + d - 0.160) for i, d in enumerate(shifts)]
        st = m.corner_mc_stats(samples)["stats"]
        self.assertAlmostEqual(st["hysteresis_v"]["sigma_v"], 0.0, places=12)
        self.assertGreater(st["vpor_up_v"]["sigma_v"], 1e-3)
        naive = math.sqrt(st["vpor_up_v"]["sigma_v"] ** 2 + st["vpor_down_v"]["sigma_v"] ** 2)
        self.assertGreater(naive, 100 * max(st["hysteresis_v"]["sigma_v"], 1e-12))
        # the hysteresis MEAN is the per-sample mean, not the difference of marginal means of
        # DIFFERENT sample sets either -- equal here, and pinned to stay computed per sample
        self.assertAlmostEqual(st["hysteresis_v"]["mean_v"], 0.160, places=12)

    def test_partially_correlated_fixture_stays_below_the_marginal_combination(self):
        """A realistic fixture: common offset + small independent edge noise.

        Per-sample hysteresis sigma must be the SMALLER number (the common part drops
        out); the marginal combination must not be what the code reports."""
        shifts = (0.0, 2.0, -1.0, 4.0, -3.0, 1.5, -0.5, 3.0)
        noise = (0.1, -0.1, 0.2, -0.2, 0.05, -0.05, 0.15, -0.15)  # mV-scale independent part, in V
        samples = [vsample(i + 1, V + d + n, V + d - 0.160 - n) for i, (d, n) in enumerate(zip(shifts, noise))]
        st = m.corner_mc_stats(samples)["stats"]
        hys = st["hysteresis_v"]["sigma_v"]
        naive = math.sqrt(st["vpor_up_v"]["sigma_v"] ** 2 + st["vpor_down_v"]["sigma_v"] ** 2)
        self.assertGreater(hys, 0.0)
        self.assertLess(hys, naive / 2)
        self.assertAlmostEqual(st["hysteresis_v"]["sigma_v"], statistics.stdev([2 * n for n in noise]), places=15)


class ResolutionFigure(unittest.TestCase):
    def test_exact_values(self):
        self.assertAlmostEqual(m.sigma_resolution(20), 1 / math.sqrt(2 * 19), places=15)
        self.assertAlmostEqual(m.sigma_resolution(20), 0.1622214211, places=8)
        self.assertAlmostEqual(m.sigma_resolution(2), 1 / math.sqrt(2), places=15)
        self.assertAlmostEqual(m.sigma_resolution(24), 1 / math.sqrt(2 * 23), places=15)

    def test_undefined_below_two_valid_samples(self):
        self.assertIsNone(m.sigma_resolution(1))
        self.assertIsNone(m.sigma_resolution(0))

    def test_record_resolution_follows_valid_n_not_run_n(self):
        """The resolution quoted for a corner with exclusions is the VALID n's figure."""
        samples = [vsample(1, V, V - 0.15), vsample(2, V + 0.01, V - 0.15), isample(3, "no_transition (state high)")]
        st = m.corner_mc_stats(samples)
        self.assertEqual(st["n_valid"], 2)
        self.assertAlmostEqual(st["sigma_resolution"], m.sigma_resolution(2), places=15)
        self.assertNotAlmostEqual(st["sigma_resolution"], m.sigma_resolution(3), places=12)


class ValidSampleCounting(unittest.TestCase):
    def test_n_counts_valid_samples_only(self):
        samples = [vsample(1, 2.690, 2.540), isample(2, "multiple_transitions"), vsample(3, 2.700, 2.550),
                   isample(4, "unresolved (bracket 14 mV)"), vsample(5, 2.710, 2.560)]
        st = m.corner_mc_stats(samples)
        self.assertEqual(st["n_samples"], 5)
        self.assertEqual(st["n_valid"], 3)
        self.assertAlmostEqual(st["stats"]["vpor_up_v"]["mean_v"], statistics.fmean([2.690, 2.700, 2.710]), places=15)
        # the invalid samples' values (here None) never enter a mean
        self.assertAlmostEqual(st["stats"]["vpor_down_v"]["mean_v"], statistics.fmean([2.540, 2.550, 2.560]), places=15)

    def test_exclusions_are_listed_with_reasons_not_dropped(self):
        reason = "no_transition (state high)"
        st = m.corner_mc_stats([vsample(1, V, V - 0.15), isample(2, reason)])
        self.assertEqual(len(st["excluded"]), 1)
        self.assertEqual(st["excluded"][0], {"sample": 2, "reason": reason})

    def test_wrong_direction_extract_is_invalid_with_its_verdict(self):
        verdict = "NO_RESULT (wrong_direction on the UP segment)"
        ok, why = m.classify_mc_sample({"verdict": "NO_RESULT (wrong_direction on the UP segment)", "hysteresis_v": None})
        self.assertFalse(ok)
        self.assertEqual(why, verdict)
        ok, why = m.classify_mc_sample({"verdict": "OK", "hysteresis_v": 0.15})
        self.assertTrue(ok)
        self.assertIsNone(why)
        ok, why = m.classify_mc_sample(None)
        self.assertFalse(ok)
        self.assertEqual(why, "no waveform retrieved")


class AllInvalidCorner(unittest.TestCase):
    def test_all_invalid_is_no_result_never_zero_sigma(self):
        samples = [isample(1, "no_transition (state high)"), isample(2, "no_transition (state high)")]
        st = m.corner_mc_stats(samples)
        self.assertTrue(st["result"].startswith("NO-RESULT"))
        self.assertIsNone(st["stats"])
        self.assertEqual(st["n_valid"], 0)
        self.assertIsNone(st["sigma_resolution"])
        dumped = str(st)
        self.assertNotIn("'sigma_v': 0", dumped)
        self.assertNotIn('"sigma_v": 0', dumped)

    def test_single_valid_sample_reports_mean_without_sigma(self):
        """n = 1: the mean exists, the Bessel sigma does not -- neither is invented."""
        st = m.corner_mc_stats([vsample(1, 2.70, 2.54)])
        self.assertEqual(st["result"], "OK")
        self.assertIsNone(st["stats"]["vpor_up_v"]["sigma_v"])
        self.assertAlmostEqual(st["stats"]["vpor_up_v"]["mean_v"], 2.70, places=15)
        self.assertIsNone(st["sigma_resolution"])


if __name__ == "__main__":
    try:
        import unittest as _u
        r = _u.TextTestRunner(verbosity=1).run(_u.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
        sys.exit(0 if r.wasSuccessful() else 1)
    except SystemExit:
        raise
