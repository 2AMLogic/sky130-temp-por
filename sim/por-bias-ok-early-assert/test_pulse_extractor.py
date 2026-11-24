#!/usr/bin/env python3
"""Synthetic-waveform pins for pulse_extractor.py (issue #495). Run: python3 sim/por-bias-ok-early-assert/test_pulse_extractor.py"""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pulse_extractor as pe  # noqa: E402
import run_early_assert as rea  # noqa: E402


def wave(bok_at, por_windows, rst_windows=(), peak=3.6, rate=100.0, step=0.002):
    """VDD ramps up then down; each signal is high (=VDD) inside its (lo, hi) VDD windows on the UP leg."""
    n = int(peak / step)
    vdd = [i * step for i in range(n + 1)] + [peak - (i + 1) * step for i in range(n)]
    cols = {k: [] for k in ("t", "vdd", "por_raw", "bias_ok", "resetn", "na")}
    for i, v in enumerate(vdd):
        up = i <= n
        hi = lambda wins: v if (up and any(a <= v < b for a, b in wins)) else 0.0  # noqa: E731
        cols["t"].append(i * step / rate)
        cols["vdd"].append(v)
        cols["bias_ok"].append(v if up and v >= bok_at else 0.0)
        cols["por_raw"].append(hi(por_windows))
        cols["resetn"].append(hi(rst_windows))
        cols["na"].append(0.7)
    return cols


class Extractor(unittest.TestCase):
    def test_clean(self):
        r = pe.extract(wave(1.7, [(2.7, 9)]))
        self.assertEqual(pe.verdict_class(r), "clean")
        self.assertAlmostEqual(r["bias_ok_up_v"], 1.7, delta=0.003)
        self.assertAlmostEqual(r["por_up_v"], 2.7, delta=0.003)

    def test_pulse_absorbed(self):
        r = pe.extract(wave(1.6, [(1.65, 1.72), (2.7, 9)]))
        self.assertEqual(pe.verdict_class(r), "pulse_absorbed")
        self.assertEqual(r["pulse_count"], 1)
        self.assertAlmostEqual(r["pulses"][0]["width_v"], 0.07, delta=0.004)
        self.assertAlmostEqual(r["pulses"][0]["width_s"], 0.0007, delta=4e-5)

    def test_pulse_propagates(self):
        r = pe.extract(wave(1.6, [(1.65, 1.72), (2.7, 9)], rst_windows=[(1.66, 1.9), (2.9, 9)]))
        self.assertEqual(pe.verdict_class(r), "pulse_propagates")

    def test_early_release(self):
        r = pe.extract(wave(1.6, [(1.62, 9)]))
        self.assertEqual(pe.verdict_class(r), "early_release")

    def test_no_release(self):
        r = pe.extract(wave(99, []))
        self.assertEqual(pe.verdict_class(r), "no_release")

    def test_no_data(self):
        self.assertEqual(pe.verdict_class(pe.extract(pe.load_wrdata(""))), "no_data")


class ProbeTable(unittest.TestCase):
    def setUp(self):
        self.man = json.loads(rea.MANIFEST.read_text())

    def test_every_grid_point_is_probeable(self):
        table = rea.probe_table(self.man)
        for grid in self.man["grids"]:
            ids = {p.point_id for p in rea.build_points(grid, self.man)}
            self.assertTrue(ids, f"grid {grid!r} built no points")
            for pid in ids:
                self.assertIn(pid, table, f"{pid} ({grid}) missing from the --probe lookup table")

    def test_pilot_extended_only_point_is_probeable(self):
        table = rea.probe_table(self.man)
        self.assertIn("ss_m40c_r100_default_xmoka_offm120", table)
        other = {p.point_id for g in ("pilot", "full") for p in rea.build_points(g, self.man)}
        self.assertNotIn("ss_m40c_r100_default_xmoka_offm120", other)

    def test_docstring_probe_example_resolves(self):
        m = re.search(r"run_early_assert\.py --probe (\S+)", rea.__doc__)
        self.assertIsNotNone(m, "docstring has no --probe example")
        self.assertIn(m.group(1), rea.probe_table(self.man))

    def test_settle_s_default_and_override(self):
        self.assertEqual(rea.settle_seconds({}), 2e-3)
        self.assertEqual(rea.settle_seconds({"settle_s": 5e-3}), 5e-3)

    def test_manifest_prose_matches_grids(self):
        swept = {d for g in self.man["grids"].values() for d in g["offset_mv"]}
        self.assertEqual(swept, {"XMOL2", "XMOKA"})
        prose = self.man["claim"] + self.man["provenance_source"] + self.man["absent_coverage"][0]
        for d in sorted(swept):
            self.assertIn(d, prose, f"swept device {d} not named in the manifest prose")
        self.assertNotIn("XMOL2 only", self.man["claim"])
        self.assertNotIn("XMOL2 only", self.man["absent_coverage"][0])


if __name__ == "__main__":
    unittest.main()
