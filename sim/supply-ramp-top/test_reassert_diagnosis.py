#!/usr/bin/env python3
"""Matrix + verdict-rule tests for run_reassert_diagnosis.py (issue #142). Stdlib only, no SPICE.

Run: python3 -I sim/supply-ramp-top/test_reassert_diagnosis.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_reassert_diagnosis as rd  # noqa: E402


def run(i, role, physical=True, resolved=True, n_rel=1, n_re=0, t_rel=3.0e-3, usable=True):
    chk = None
    if usable:
        chk = {"physical": {"ok": physical}, "resolution_ok": resolved, "ramp_ok": True,
               "resetn": {"n_reassert": n_re, "n_release": n_rel, "n_runt": 0, "t_release_s": t_rel}}
    return {"id": i, "role": role, "check": chk}


class MatrixTest(unittest.TestCase):
    def test_exact_points_and_controls_present_once(self):
        man = rd.sim_common.load_manifest(rd.MANIFEST)
        cases = rd.build_matrix(man)
        ids = [c["id"] for c in cases]
        self.assertEqual(len(ids), len(set(ids)))
        for rate, pt in ((5e5, "A_ss_m40c_3p63v_500kVs"), (5e3, "B_fs_27c_2p97v_5kVs")):
            base = [c for c in cases if c["point"] == pt and c["variant"] == "base" and c["rate"] == rate]
            self.assertEqual(len(base), 1)
            self.assertGreaterEqual(len([c for c in cases if c["point"] == pt and c["role"] == "solver"]), 1)
            self.assertGreaterEqual(len({c["rate"] for c in cases if c["point"] == pt and c["role"] == "adjacent-rate"}), 1)

    def test_netlist_keeps_dut_and_adds_only_saves_and_options(self):
        man = rd.sim_common.load_manifest(rd.MANIFEST)
        case = next(c for c in rd.build_matrix(man) if c["variant"] == "trap")
        text = rd.netlist_for("XDUT VDD 0 PTAT CTAT RESETn temp_por_top\n", man, case)
        self.assertIn(".options method=trap trtol=7", text)
        self.assertIn("v(xdut.xpor.trip)", text)
        self.assertIn(rd.camp.DUT_NETLIST.read_text().split("\n", 1)[1].split(".end")[0][:200], text)


class VerdictTest(unittest.TestCase):
    def test_artifact(self):
        runs = [run("b", "exact", physical=False, n_re=1), run("t7", "solver", t_rel=3.0e-3), run("rt", "solver", t_rel=3.05e-3),
                run("adj", "adjacent-rate")]
        self.assertEqual(rd.verdict_for_point(runs)[0], "solver/nonphysical artifact")

    def test_design_level(self):
        runs = [run("b", "exact", physical=False, n_re=1), run("t7", "solver", n_re=1)]
        self.assertEqual(rd.verdict_for_point(runs)[0], "physical design-level re-assertion")

    def test_adjacent_rate_reassert_on_physical_is_design(self):
        runs = [run("b", "exact", physical=False, n_re=1), run("t7", "solver"), run("rt", "solver"), run("adj", "adjacent-rate", n_re=1)]
        self.assertEqual(rd.verdict_for_point(runs)[0], "physical design-level re-assertion")

    def test_unresolved_when_not_reproduced(self):
        runs = [run("b", "exact"), run("t7", "solver")]
        self.assertEqual(rd.verdict_for_point(runs)[0], "unresolved")

    def test_unresolved_when_physical_unstable_or_scarce(self):
        self.assertEqual(rd.verdict_for_point([run("b", "exact", physical=False, n_re=1), run("t7", "solver")])[0], "unresolved")
        runs = [run("b", "exact", physical=False, n_re=1), run("t7", "solver", t_rel=3e-3), run("rt", "solver", t_rel=4e-3)]
        self.assertEqual(rd.verdict_for_point(runs)[0], "unresolved")

    def test_unresolved_with_missing_runs(self):
        runs = [run("b", "exact", usable=False), run("t7", "solver", usable=False)]
        self.assertEqual(rd.verdict_for_point(runs)[0], "unresolved")

    def test_unresolved_grid_never_counts_as_physical(self):
        runs = [run("b", "exact", physical=False, n_re=1), run("t7", "solver", resolved=False), run("rt", "solver", resolved=False)]
        self.assertEqual(rd.verdict_for_point(runs)[0], "unresolved")


if __name__ == "__main__":
    unittest.main()
