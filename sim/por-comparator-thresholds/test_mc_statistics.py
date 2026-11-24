#!/usr/bin/env python3
"""Tests for the mismatch Monte Carlo statistics reduction (issues #348, #401).

The `--axis mc` record reports, per corner, the mean and sample sigma (Bessel,
n-1) of VPOR-up, VPOR-down and hysteresis over the VALID samples, plus the
statistical resolution of that sigma as a number.  The defect class this pins:
a statistics layer that quietly mis-measures the very spread it exists to
report.  Ways that happens, each with a test:

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

The #401 diagnostic reduction pins a second defect class: a reduction that
DISCARDS the enable/clamp-path evidence (the netlist saves `v(bias_ok)` and the
comparator-internal nodes; discarding them is exactly why 38 failed-release
realisations could not be attributed), mislabels the mechanism, or quietly
re-baselines a non-reproduction:

  * the trace and per-sample fields keep the diagnostic nodes when the netlist
    saves them, and stay absent (never zero) when it does not;
  * the peak sampling interpolates at tstop/2, the VDD peak;
  * the stuck-class labels follow their stated criteria, and "no data" is
    `None`, never a mechanism;
  * the mechanism statement is computed from the per-sample classes -- one
    mechanism only when every sample carries it, a split when mixed;
  * the seed-for-seed reproduction comparison states a mismatch, never absorbs
    it.

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


# --------------------------------------------------------------------------
# issue #401: the enable/clamp-path diagnostic reduction
# --------------------------------------------------------------------------

import gzip  # noqa: E402
import tempfile  # noqa: E402
import unittest as ut  # noqa: E402

TSTOP = 72.6e-3  # the 100 V/s sweep: 2 x 3.63 V / 100 V/s
TPEAK = TSTOP / 2


def diag_wave():
    """A synthetic MC-sample waveform carrying the four diagnostic nodes + the original four.

    VDD is a triangle peaking at tstop/2; bias_ok rises mid-up-sweep; cmpo rises at the
    (nominal) release; n1 mirrors cmpo inverted; sns follows vdd through a fixed ratio."""
    t = [i * 1e-4 for i in range(int(TSTOP / 1e-4) + 1)]
    vdd = [min(3.63, 100 * x, max(0.0, 2 * 3.63 - 100 * x)) for x in t]
    return {
        "time": t,
        "v(vdd)": vdd,
        "v(por_raw)": [0.0 if x < 0.0271 else 3.0 for x in t],
        "v(vref)": [min(1.25, v) for v in vdd],
        "v(ibias)": [1e-6 if v > 1.0 else 0.0 for v in vdd],
        "v(bias_ok)": [0.0 if x < 0.02 else 3.5 for x in t],
        "v(xdut.cmpo)": [0.0 if x < 0.0271 else 3.4 for x in t],
        "v(xdut.n1)": [3.5 if x < 0.0271 else 0.2 for x in t],
        "v(xdut.sns)": [0.4615 * v for v in vdd],
        # issue #455 OK-detector nodes (healthy realisation: detector asserted)
        "v(xbias.na)": [min(0.630, v) for v in vdd],
        "v(xbias.nbtop)": [min(0.633, v) for v in vdd],
        "v(xbias.pb)": [min(2.26, v) for v in vdd],
        "v(xbias.tok)": [min(1.96, v) for v in vdd],
        "v(xbias.noko)": [0.0 if x < 0.021 else 1.50 for x in t],
        "v(xbias.nokl)": [0.0 if v < 1.0 else 0.75 for v in vdd],
        "v(xbias.nokx)": [vdd[0] if x < 0.021 else 0.002 for x in t],
        "v(xbias.nkg)": [0.0 for _ in t],
    }

class DiagnosticTraceColumns(ut.TestCase):
    def test_trace_keeps_the_diagnostic_nodes_when_saved(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "mc0.trace.csv.gz"
            rows = m.write_trace(p, diag_wave())
            header = gzip.open(p, "rt").readline().strip().split(",")
            self.assertIn("v(bias_ok)", header)
            self.assertIn("v(xdut.cmpo)", header)
            self.assertIn("v(xdut.n1)", header)
            self.assertIn("v(xdut.sns)", header)
            # a diagnostic column's change is itself a keep trigger: the bias_ok step
            # (0 -> 3.5 V at t = 20 ms, between anchors) must appear as its own row
            body = [ln.split(",") for ln in gzip.open(p, "rt").read().strip().splitlines()[1:]]
            self.assertEqual(len(body), rows)
            bias_col = header.index("v(bias_ok)")
            steps = [r for r in body if float(r[bias_col]) > 1.0]
            self.assertGreaterEqual(len(steps), 1)
            self.assertGreater(rows, 3)  # anchors alone would give exactly 3 on this span

    def test_trace_without_the_nodes_is_unchanged(self):
        """A netlist that does not save the diagnostic nodes still writes the original trace."""
        wave = {k: v for k, v in diag_wave().items() if not k.startswith(("v(xdut", "v(xbias")) and k != "v(bias_ok)"}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "mc0.trace.csv.gz"
            m.write_trace(p, wave)
            header = gzip.open(p, "rt").readline().strip().split(",")
            self.assertEqual(header, ["time", "v(vdd)", "v(por_raw)", "v(vref)", "v(ibias)"])


class DiagnosticFields(ut.TestCase):
    def test_sweep_max_and_at_peak_interpolation(self):
        d = m.mc_diag_fields(diag_wave(), TPEAK)
        # max over the sweep
        self.assertAlmostEqual(d["bias_ok_max_v"], 3.5, places=12)
        self.assertAlmostEqual(d["xdut_cmpo_max_v"], 3.4, places=12)
        self.assertAlmostEqual(d["xdut_n1_max_v"], 3.5, places=12)
        # at the sweep peak (t = tstop/2): sns tracks the 0.4615 divider ratio at 3.63 V
        self.assertAlmostEqual(d["vdd_at_peak_v"], 3.63, places=12)
        self.assertAlmostEqual(d["xdut_sns_at_peak_v"], 0.4615 * 3.63, places=3)
        self.assertAlmostEqual(d["bias_ok_at_peak_v"], 3.5, places=12)
        self.assertAlmostEqual(d["xdut_cmpo_at_peak_v"], 3.4, places=12)
        # the max of sns equals its peak value here (the triangle peaks at the same time)
        self.assertAlmostEqual(d["xdut_sns_max_v"], 0.4615 * 3.63, places=3)

    def test_at_peak_interpolates_linearly_inside_a_segment(self):
        """tpeak lands mid-segment: the value is interpolated, not the bracketing sample."""
        w = diag_wave()
        # pick a peak time strictly inside a 1e-4 segment on the sns ramp (up-sweep, linear)
        tpeak = 0.01505  # mid-segment on the rising VDD ramp
        d = m.mc_diag_fields(w, tpeak)
        expect = 0.4615 * 100 * tpeak  # sns = ratio x vdd, vdd = rate*t on the ramp
        self.assertAlmostEqual(d["xdut_sns_at_peak_v"], expect, places=10)
        self.assertNotEqual(d["xdut_sns_at_peak_v"], 0.4615 * 100 * 0.015)

    def test_missing_nodes_are_absent_never_zero(self):
        """A waveform without the diagnostic nodes yields NO diagnostic fields -- never zeros."""
        wave = {k: v for k, v in diag_wave().items() if not k.startswith(("v(xdut", "v(xbias")) and k != "v(bias_ok)"}
        d = m.mc_diag_fields(wave, TPEAK)
        self.assertEqual(d, {"vdd_at_peak_v": 3.63})  # the peak supply itself is still sampled
        # ...and a waveform without a time column at all
        self.assertEqual(m.mc_diag_fields({"v(bias_ok)": [1.0]}, TPEAK), {})

    def test_field_naming_lowercases_and_flattens(self):
        d = m.mc_diag_fields(diag_wave(), TPEAK)
        for node in m.MC_DIAG_NODES:
            key = node[2:-1].replace(".", "_")
            self.assertIn(f"{key}_max_v", d)
            self.assertIn(f"{key}_at_peak_v", d)


def stuck_sample(**diag):
    """A failed-release sample with the given diagnostic fields."""
    s = {"sample": 0, "valid": False, "reason": "NO_RESULT (no_transition on the UP segment)", "stuck_class": None,
         "vdd_at_peak_v": 3.63}
    s.update(diag)
    return s


class StuckClassification(ut.TestCase):
    def test_enable_clamp_when_bias_ok_never_reached_a_rail_swing(self):
        """BIAS_OK sitting well below the peak supply means NOKX still held the pulldown on."""
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": 0.2, "bias_ok_max_v": 0.3,
                                           "xdut_cmpo_max_v": 0.01}), "enable-clamp")

    def test_comparator_stuck_when_bias_ok_asserted_but_cmpo_never_rose(self):
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": 3.6, "bias_ok_max_v": 3.6,
                                           "xdut_cmpo_max_v": 0.02}), "comparator-stuck")

    def test_extractor_miss_when_both_released(self):
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": 3.6, "bias_ok_max_v": 3.6,
                                           "xdut_cmpo_max_v": 3.3}), "extractor-miss")

    def test_criterion_boundaries_are_stated_and_inclusive(self):
        """Exactly at a criterion counts as the released side (>= threshold)."""
        at_frac = m.MC_BIAS_OK_ASSERTED_FRAC * 3.63
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": at_frac, "xdut_cmpo_max_v": m.MC_CMPO_RELEASED_V}), "extractor-miss")
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": at_frac, "xdut_cmpo_max_v": m.MC_CMPO_RELEASED_V - 1e-9}), "comparator-stuck")
        self.assertEqual(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": at_frac - 1e-9, "xdut_cmpo_max_v": 0.0}), "enable-clamp")

    def test_no_data_is_no_mechanism(self):
        self.assertIsNone(m.mc_stuck_class(None))
        self.assertIsNone(m.mc_stuck_class({}))
        self.assertIsNone(m.mc_stuck_class({"bias_ok_max_v": None}))
        # bias evidence without the peak supply to normalise against is unclassifiable too
        self.assertIsNone(m.mc_stuck_class({"bias_ok_at_peak_v": 3.6, "xdut_cmpo_max_v": 0.0}))

    def test_missing_cmpo_with_asserted_bias_ok_is_no_mechanism(self):
        """CMPO absent (node not saved) cannot prove 'CMPO never rose' -- never invented as 0."""
        self.assertIsNone(m.mc_stuck_class({"vdd_at_peak_v": 3.63, "bias_ok_at_peak_v": 3.6, "bias_ok_max_v": 3.6}))


class MechanismStatement(ut.TestCase):
    def test_all_enable_clamp_names_the_mechanism(self):
        stuck = [(None, stuck_sample(stuck_class="enable-clamp")) for _ in range(3)]
        txt = m.mc_mechanism_statement(stuck)
        self.assertIn("Mechanism established", txt)
        self.assertIn("enable/clamp path never released", txt)
        self.assertIn("all 3", txt)

    def test_all_comparator_stuck_refutes_the_enable_path(self):
        stuck = [(None, stuck_sample(stuck_class="comparator-stuck")) for _ in range(2)]
        txt = m.mc_mechanism_statement(stuck)
        self.assertIn("Mechanism established", txt)
        self.assertIn("refuting the enable-path candidate", txt)

    def test_mixed_outcome_is_enumerated_not_absorbed(self):
        stuck = [(None, stuck_sample(stuck_class="enable-clamp")),
                 (None, stuck_sample(stuck_class="comparator-stuck")),
                 (None, stuck_sample(stuck_class=None))]
        txt = m.mc_mechanism_statement(stuck)
        self.assertIn("mixed", txt)
        self.assertIn("enable/clamp path never released", txt)
        self.assertIn("refuting the enable-path candidate", txt)
        self.assertIn("no mechanism is established for them", txt)
        self.assertNotIn("Mechanism established", txt)

    def test_no_data_states_no_mechanism_plainly(self):
        stuck = [(None, stuck_sample(stuck_class=None)) for _ in range(2)]
        txt = m.mc_mechanism_statement(stuck)
        self.assertIn("No mechanism established", txt)

    def test_all_same_statements_are_not_headline_plus_lowercase_fragment(self):
        """The all-same-class statement is one sentence: no lowercase fragment after the bold headline."""
        for cls in ("enable-clamp", "comparator-stuck", "extractor-miss"):
            stuck = [(None, stuck_sample(stuck_class=cls)) for _ in range(2)]
            self.assertNotRegex(m.mc_mechanism_statement(stuck), r"\*\* [a-z]", msg=cls)
        stuck = [(None, stuck_sample(stuck_class=None)) for _ in range(2)]
        self.assertNotRegex(m.mc_mechanism_statement(stuck), r"\*\* [a-z]")

    def test_empty_is_empty(self):
        self.assertEqual(m.mc_mechanism_statement([]), "")


def repro_record(samples_by_corner):
    """A minimal record dict for mc_reproduction: {corner: {sample: fields}}."""
    return {"record_id": "old", "corners": [
        {"process": p, "temperature_c": t, "samples": [dict(sample=i, **fields) for i, fields in ss.items()]}
        for (p, t), ss in samples_by_corner.items()]}


def repro_fields(vup=2.70, valid=True, reason=None, seed=519744602):
    return {"seed": seed, "process_seed": 1, "mismatch_seed": 2, "valid": valid, "reason": reason,
            "vup": vup, "vdn": vup - 0.15, "hys": 0.15, "vref_max_v": 1.25}


class ReproductionCompare(ut.TestCase):
    def old_and_new(self, **override):
        f = repro_fields(**override)
        old = repro_record({("tt", 27): {0: repro_fields(), 1: repro_fields(vup=2.72)}})
        new = repro_record({("tt", 27): {0: dict(repro_fields()), 1: dict(repro_fields(vup=2.72))}})
        return old, new, f

    def test_identical_pattern_is_reproduced(self):
        old, new, _ = self.old_and_new()
        r = m.mc_reproduction(old, new)
        self.assertTrue(r["pattern_reproduced"])
        self.assertTrue(r["seeds_all_match"])
        self.assertTrue(r["values_all_within_tol"])
        self.assertEqual(r["mismatch_count"], 0)
        self.assertEqual(r["samples_compared"], 2)
        self.assertAlmostEqual(r["max_abs_delta_v"], 0.0, places=15)

    def test_pattern_flip_is_stated_not_absorbed(self):
        old, new, _ = self.old_and_new()
        new["corners"][0]["samples"][1]["valid"] = False
        new["corners"][0]["samples"][1]["reason"] = "NO_RESULT (no_transition on the UP segment)"
        r = m.mc_reproduction(old, new)
        self.assertFalse(r["pattern_reproduced"])
        self.assertFalse(r["pattern_all_match"])
        self.assertEqual(r["mismatch_count"], 1)
        self.assertIn("valid", r["mismatches"][0]["fields"])

    def test_seed_drift_is_reported_separately_from_values(self):
        old, new, _ = self.old_and_new()
        new["corners"][0]["samples"][0]["mismatch_seed"] = 99
        r = m.mc_reproduction(old, new)
        self.assertFalse(r["seeds_all_match"])
        self.assertFalse(r["pattern_reproduced"])  # seeds are part of the pattern contract
        self.assertTrue(r["pattern_all_match"])  # but the pass/fail pattern itself still matches
        self.assertEqual(r["mismatch_count"], 1)

    def test_value_drift_beyond_tolerance_is_reported_with_the_delta(self):
        old, new, _ = self.old_and_new()
        new["corners"][0]["samples"][0]["vup"] += 5e-4  # 0.5 mV > the 0.1 mV tolerance
        r = m.mc_reproduction(old, new)
        self.assertFalse(r["values_all_within_tol"])
        self.assertTrue(r["pattern_reproduced"])  # values alone do not flip the pattern verdict...
        self.assertTrue(r["pattern_all_match"])
        self.assertAlmostEqual(r["max_abs_delta_v"], 5e-4, places=15)
        self.assertIn("vup", r["mismatches"][0]["fields"])

    def test_value_drift_within_tolerance_is_not_a_mismatch(self):
        old, new, _ = self.old_and_new()
        new["corners"][0]["samples"][0]["vup"] += 9e-6  # 9 uV < the 0.1 mV tolerance
        r = m.mc_reproduction(old, new)
        self.assertTrue(r["values_all_within_tol"])
        self.assertEqual(r["mismatch_count"], 0)

    def test_samples_missing_on_one_side_are_counted_not_compared(self):
        old, new, _ = self.old_and_new()
        new["corners"][0]["samples"] = new["corners"][0]["samples"][:1]
        r = m.mc_reproduction(old, new)
        self.assertEqual(r["samples_compared"], 1)
        self.assertEqual(r["mismatch_count"], 0)


class OkdetSubclass(unittest.TestCase):
    """issue #455: the OK-detector sub-attribution must separate the stages of the
    enable path from recorded node levels, never invent levels the netlist did not
    save, and never fold an uninstrumented sample into a mechanism class."""

    def sample(self, **over):
        s = {"xbias_tok_at_peak_v": 1.96, "xbias_nkg_at_peak_v": 0.0,
             "xbias_noko_at_peak_v": 1.50, "xbias_nokx_at_peak_v": 0.002}
        s.update(over)
        return s

    def test_noko_low_with_tail_present_is_first_stage(self):
        self.assertEqual(m.mc_okdet_subclass(self.sample(xbias_noko_at_peak_v=0.31)), "first-stage-unbalanced")

    def test_noko_high_with_nokx_high_is_output_stage(self):
        self.assertEqual(m.mc_okdet_subclass(self.sample(xbias_nokx_at_peak_v=2.9)), "output-stage-fight")

    def test_tail_collapsed_and_clamp_on_have_their_own_classes(self):
        self.assertEqual(m.mc_okdet_subclass(self.sample(xbias_tok_at_peak_v=0.42)), "tok-collapsed")
        self.assertEqual(m.mc_okdet_subclass(self.sample(xbias_nkg_at_peak_v=0.8)), "clamp-on")

    def test_missing_xbias_nodes_are_none_never_a_class(self):
        self.assertIsNone(m.mc_okdet_subclass(None))
        self.assertIsNone(m.mc_okdet_subclass({"bias_ok_at_peak_v": 0.0}))

    def test_attribution_counts_classes_and_ranges(self):
        corners = [{"samples": [
            {"valid": True, "reason": None, "xbias_noko_at_peak_v": 1.5, "xbias_na_at_peak_v": 0.630, "xbias_nbtop_at_peak_v": 0.633},
            {"valid": False, "reason": "no_transition", "stuck_class": "enable-clamp", "okdet_class": "first-stage-unbalanced",
             "xbias_noko_at_peak_v": 0.30, "xbias_na_at_peak_v": 0.630, "xbias_nbtop_at_peak_v": 0.631},
            {"valid": False, "reason": "no_transition", "stuck_class": "enable-clamp", "okdet_class": None},  # uninstrumented
            {"valid": False, "reason": "NO_RESULT (up:multiple_transitions, down:no_transition)"},  # not no_transition-only
        ]}]
        att = m.okdet_attribution(corners)
        self.assertEqual(att["n_failed"], 3)
        self.assertEqual(att["sub_counts"], {"first-stage-unbalanced": 1, "uninstrumented": 1, "not-enable-clamp": 1})
        self.assertAlmostEqual(att["failing_settle_signal_v"]["min"], 0.001, places=12)
        self.assertAlmostEqual(att["releasing_settle_signal_v"]["min"], 0.003, places=12)
        self.assertAlmostEqual(att["releasing_noko_at_peak_v"]["min"], 1.5, places=12)
        st = m.mc_okdet_attribution_statement(att)
        self.assertIn("1x `first-stage-unbalanced`", st)
        self.assertIn("1x `uninstrumented`", st)

    def test_attribution_with_no_failures_says_so(self):
        att = m.okdet_attribution([{"samples": [{"valid": True, "reason": None}]}])
        self.assertEqual(att["n_failed"], 0)
        self.assertIn("No failed-release", m.mc_okdet_attribution_statement(att))


class McEffectiveOverrides(unittest.TestCase):
    """issue #455: --mc-process/--mc-seed override the manifest for ONE run and are
    honored by the record; the manifest itself is never mutated, and no overrides
    means byte-identical behaviour to the pre-override path."""

    MAN = {"monte_carlo": {"process": ["tt", "ss"], "temperature_c": [-40, 27, 125], "seed": 20261114,
                           "n_per_corner": 20, "vary": "mismatch", "rate_v_per_s": 100.0,
                           "request_sizing": "x", "statistical_convention": "y", "seed_offsets": "z", "execution": "e"}}

    def test_no_override_is_the_manifest(self):
        self.assertEqual(m.mc_effective(self.MAN), self.MAN["monte_carlo"])
        self.assertEqual(m.mc_units(self.MAN), m.mc_units(self.MAN, m.mc_effective(self.MAN)))

    def test_process_and_seed_overrides_apply_without_mutation(self):
        mc = m.mc_effective(self.MAN, {"process_override": ["tt", "ss", "ff", "sf", "fs"], "seed_override": 20261121})
        self.assertEqual(mc["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(mc["seed"], 20261121)
        self.assertEqual(self.MAN["monte_carlo"]["process"], ["tt", "ss"])  # manifest untouched
        units = m.mc_units(self.MAN, mc)
        self.assertEqual(len(units), 15)
        self.assertEqual(units[0][2], 1)
        self.assertEqual(units[-1][2], 15)
        self.assertEqual(m.mc_request_seed(mc, 15), 20261121 + 15)

    def test_none_overrides_are_ignored(self):
        mc = m.mc_effective(self.MAN, {"process_override": None, "seed_override": None})
        self.assertEqual(mc["process"], ["tt", "ss"])
        self.assertEqual(mc["seed"], 20261114)


class McEffectiveProse(unittest.TestCase):
    """issue #481: record/run prose follows the effective grid; default grid is verbatim."""

    MAN = m.json.load(open(Path(m.__file__).with_name("experiment.json")))

    def prose(self, **ov):
        mc = m.mc_effective(self.MAN, ov or None)
        return mc, m.mc_effective_prose(self.MAN, mc)

    def test_default_grid_is_byte_identical(self):
        d = self.MAN["monte_carlo"]
        for ov in ({}, {"process_override": ["tt", "ss"], "seed_override": 20261114}):
            _, p = self.prose(**ov)
            self.assertEqual(p["claim"], self.MAN["claim"])
            self.assertEqual(p["statistical_convention"], d["statistical_convention"])
            self.assertEqual(p["request_sizing"], d["request_sizing"])
            self.assertEqual(p["seed_offsets"], d["seed_offsets"])
            self.assertEqual(p["absent_coverage"], self.MAN["absent_coverage"])

    def test_full_five_corner_override(self):
        _, p = self.prose(process_override=["tt", "ss", "ff", "sf", "fs"], seed_override=20261121)
        self.assertIn("= 15 requests", p["request_sizing"])
        self.assertNotIn("= 6 requests", p["request_sizing"])
        self.assertIn("k = 1..15", p["seed_offsets"])
        self.assertIn("fs/125C -> 20261136", p["seed_offsets"])
        self.assertNotIn("the six", p["seed_offsets"])
        self.assertNotIn("ff/sf/fs", p["statistical_convention"])
        self.assertIn("on tt/ss/ff/sf/fs (run override);", p["claim"])
        self.assertFalse(any("NOT sampled by it: the ideal-bias variant, the ff/sf/fs" in a for a in p["absent_coverage"]))
        self.assertTrue(any("tt/ss/ff/sf/fs sections" in a for a in p["absent_coverage"]))

    def test_partial_process_override(self):
        _, p = self.prose(process_override=["ff"])
        self.assertIn("= 3 requests", p["request_sizing"])
        self.assertIn("the tt/ss/sf/fs sections, ", p["statistical_convention"])
        self.assertIn("on ff (run override);", p["claim"])

    def test_seed_only_override(self):
        _, p = self.prose(seed_override=1000)
        self.assertIn("tt/-40C -> 1001", p["seed_offsets"])
        self.assertIn("ss/125C -> 1006", p["seed_offsets"])
        self.assertIn("= 6 requests", p["request_sizing"])
        self.assertIn("on tt/ss;", p["claim"])
        self.assertIn("the ff/sf/fs sections, ", p["statistical_convention"])

    def _not_sampled_line(self, rec):
        out = m.render_mc_md(rec)
        lines = [ln for ln in out.splitlines() if ln.startswith("- **Not sampled**:")]
        self.assertEqual(len(lines), 1)
        return lines[0]

    @staticmethod
    def _rec(name):
        import json
        return json.loads((HERE / "records" / name).read_text())

    def test_render_not_sampled_bullet_five_corner(self):
        line = self._not_sampled_line(self._rec("20261121-115035-c591b93b-real-bias-core-mismatch-mc.json"))
        self.assertTrue(line.endswith("and post-layout parasitics."), line)
        self.assertNotIn("ff/sf/fs process sections", line)

    def test_render_not_sampled_bullet_tt_ss(self):
        line = self._not_sampled_line(self._rec("20261121-114636-63e27cba-real-bias-core-mismatch-mc.json"))
        self.assertIn("post-layout parasitics, and the ff/sf/fs process sections.", line)

    def test_render_not_sampled_bullet_partial(self):
        import copy
        rec = copy.deepcopy(self._rec("20261121-114636-63e27cba-real-bias-core-mismatch-mc.json"))
        rec["matrix"]["process"] = ["ff"]
        line = self._not_sampled_line(rec)
        self.assertIn("the tt/ss/sf/fs process sections.", line)


if __name__ == "__main__":
    try:
        import unittest as _u
        r = _u.TextTestRunner(verbosity=1).run(_u.defaultTestLoader.loadTestsFromModule(sys.modules["__main__"]))
        sys.exit(0 if r.wasSuccessful() else 1)
    except SystemExit:
        raise
