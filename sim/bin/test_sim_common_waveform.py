#!/usr/bin/env python3
"""Parity tests for the shared waveform primitives (issue #170). Stdlib only, no SPICE.

The ``_ref_*`` functions are frozen copies of the pre-consolidation checker
implementations (ramp: t > 0 / LOW-initial; brown-out: t_from / init_high).

Run: python3 -I sim/bin/test_sim_common_waveform.py
"""
from __future__ import annotations

import gzip
import random
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_common as sc  # noqa: E402


def _ref_cross(t0, y0, t1, y1, level):
    if y1 == y0:
        return t1
    return t0 + (level - y0) * (t1 - t0) / (y1 - y0)


def _ref_crossings(t, y, level, direction, t_from=0.0):
    out = []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if direction == "rise" and a < level <= b:
            out.append(_ref_cross(t[i - 1], a, t[i], b, level))
        elif direction == "fall" and a > level >= b:
            out.append(_ref_cross(t[i - 1], a, t[i], b, level))
    return out


def _ref_schmitt(t, y, lo, hi, init_high, t_from):
    state = init_high
    rises, falls = [], []
    for i in range(1, len(t)):
        if t[i] <= t_from:
            continue
        a, b = y[i - 1], y[i]
        if not state and b >= hi:
            rises.append(_ref_cross(t[i - 1], a, t[i], b, hi) if a < hi else t[i])
            state = True
        elif state and b <= lo:
            falls.append(_ref_cross(t[i - 1], a, t[i], b, lo) if a > lo else t[i])
            state = False
    return rises, falls


def _ref_interp_at(t, y, when):
    if when <= t[0]:
        return y[0]
    if when >= t[-1]:
        return y[-1]
    for k in range(len(t) - 1):
        if t[k] <= when < t[k + 1]:
            lo, hi = k, k + 1
            break
    return y[lo] + (when - t[lo]) * (y[hi] - y[lo]) / (t[hi] - t[lo]) if t[hi] != t[lo] else y[hi]


T = [-1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
Y = [0.0, 0.0, 1.0, 2.0, 2.0, 2.0, 0.5, 0.0]  # flat head, ramp, flat plateau, fall


class CrossingsTest(unittest.TestCase):
    def test_known_values(self):
        self.assertEqual(sc.crossings(T, Y, 1.5, "rise"), [1.5])
        self.assertEqual(sc.crossings(T, Y, 1.0, "fall"), [4.0 + (1.0 - 2.0) / (0.5 - 2.0)])

    def test_default_excludes_t_le_zero(self):
        # the sample at t == 0 is skipped; the rise happens later so crossing at 1.5 only
        self.assertEqual(sc.crossings([0.0, 0.0, 1.0], [0.0, 1.0, 1.0], 0.5, "rise"), [])
        self.assertEqual(sc.crossings([-1.0, 1.0], [0.0, 1.0], 0.5, "rise"), [0.0])

    def test_nonzero_t_from_boundary_strict(self):
        # segment ending exactly at t_from is skipped; next segment kept
        self.assertEqual(sc.crossings(T, Y, 1.5, "rise", 3.0), [])
        self.assertEqual(sc.crossings(T, Y, 1.5, "rise", 1.0), [1.5])
        self.assertEqual(sc.crossings(T, Y, 1.5, "rise", 2.0), [])

    def test_level_on_sample_and_flat(self):
        self.assertEqual(sc.crossings(T, Y, 2.0, "rise"), [2.0])  # b == level, a < level
        self.assertEqual(sc.crossings(T, Y, 2.0, "fall"), [])  # a > level required
        self.assertEqual(sc.interp_cross(0.0, 1.0, 2.0, 1.0, 1.0), 2.0)  # flat -> t1

    def test_parity_random(self):
        rng = random.Random(170)
        for _ in range(300):
            n = rng.randint(2, 12)
            t = sorted(rng.choice([-1.0, 0.0, 0.5, 1.0, 2.0, 3.0, 4.0]) + k * 1e-3 * rng.randint(0, 1) for k in range(n))
            y = [rng.choice([0.0, 0.5, 1.0, 1.5, 2.0]) for _ in range(n)]
            for lvl in (0.5, 1.0, 1.5):
                for d in ("rise", "fall"):
                    for tf in (0.0, 0.5, 1.0, 2.5):
                        self.assertEqual(sc.crossings(t, y, lvl, d, tf), _ref_crossings(t, y, lvl, d, tf))
                    self.assertEqual(sc.crossings(t, y, lvl, d), _ref_crossings(t, y, lvl, d, 0.0))


class InterpAtTest(unittest.TestCase):
    def test_boundaries_and_flat(self):
        self.assertEqual(sc.interp_at(T, Y, -5.0), Y[0])
        self.assertEqual(sc.interp_at(T, Y, T[0]), Y[0])
        self.assertEqual(sc.interp_at(T, Y, T[-1]), Y[-1])
        self.assertEqual(sc.interp_at(T, Y, 99.0), Y[-1])
        self.assertEqual(sc.interp_at(T, Y, 3.5), 2.0)  # flat segment
        self.assertEqual(sc.interp_at(T, Y, 1.5), 1.5)
        self.assertEqual(sc.interp_at(T, Y, 2.0), 2.0)  # exactly on an interior sample

    def test_duplicate_time_step(self):
        t, y = [0.0, 1.0, 1.0, 2.0], [0.0, 0.0, 5.0, 5.0]
        for w in (0.5, 1.0, 1.5):
            self.assertEqual(sc.interp_at(t, y, w), _ref_interp_at(t, y, w) if w != 1.0 else sc.interp_at(t, y, w))
        self.assertEqual(sc.interp_at(t, y, 1.0), 5.0)

    def test_parity_grid(self):
        for k in range(-20, 80):
            w = k * 0.1
            self.assertEqual(sc.interp_at(T, Y, w), _ref_interp_at(T, Y, w))


class SchmittTest(unittest.TestCase):
    def test_default_is_low_initial_t_gt_zero(self):
        self.assertEqual(sc.schmitt(T, Y, 0.4, 1.6), _ref_schmitt(T, Y, 0.4, 1.6, False, 0.0))
        r, f = sc.schmitt(T, Y, 0.4, 1.6)
        self.assertEqual(r, [1.6])
        self.assertAlmostEqual(f[0], 5.2)  # 0.5 -> 0.0 crosses 0.4 at 5.2
        self.assertEqual(len(f), 1)

    def test_init_high_first_event_is_fall(self):
        r, f = sc.schmitt(T, Y, 0.4, 1.6, True, 0.0)
        self.assertEqual(r, [])
        self.assertEqual(len(f), 1)

    def test_init_low_vs_high_differ_on_high_start(self):
        t, y = [0.0, 1.0, 2.0, 3.0], [2.0, 2.0, 0.0, 2.0]
        self.assertEqual(sc.schmitt(t, y, 0.5, 1.5, False, 0.0)[0], [1.0, 2.75])  # a >= hi -> t[i]; re-arms after fall
        r, f = sc.schmitt(t, y, 0.5, 1.5, True, 0.0)
        self.assertEqual((len(r), len(f)), (1, 1))

    def test_nonzero_t_from(self):
        r, f = sc.schmitt(T, Y, 0.4, 1.6, True, 4.0)
        self.assertEqual((r, len(f)), ([], 1))
        self.assertEqual(sc.schmitt(T, Y, 0.4, 1.6, False, 5.0), ([], []))

    def test_parity_random(self):
        rng = random.Random(171)
        for _ in range(400):
            n = rng.randint(2, 14)
            t = sorted(rng.choice([-1.0, 0.0, 0.5, 1.0, 2.0, 3.0, 4.0, 5.0]) for _ in range(n))
            y = [rng.choice([0.0, 0.3, 1.0, 1.7, 2.0]) for _ in range(n)]
            for ih in (False, True):
                for tf in (0.0, 0.5, 2.0, 3.5):
                    self.assertEqual(sc.schmitt(t, y, 0.4, 1.6, ih, tf), _ref_schmitt(t, y, 0.4, 1.6, ih, tf))
            self.assertEqual(sc.schmitt(t, y, 0.4, 1.6), _ref_schmitt(t, y, 0.4, 1.6, False, 0.0))


class WriteGzRowsTest(unittest.TestCase):
    def test_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "x.csv.gz"
            sc.write_gz_rows(p, "# h", [[0.0, 1.23456789], [1e-3, 2.0]])
            with gzip.open(p, "rt") as fh:
                self.assertEqual(fh.read(), "# h\n0,1.23457\n0.001,2\n")


if __name__ == "__main__":
    unittest.main()
