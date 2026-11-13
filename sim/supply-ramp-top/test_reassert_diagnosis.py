#!/usr/bin/env python3
"""Matrix + verdict-rule tests for run_reassert_diagnosis.py (issue #142). Stdlib only, no SPICE.

Run: python3 -I sim/supply-ramp-top/test_reassert_diagnosis.py
"""
from __future__ import annotations

import json
import sys
import tempfile
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


class FleetNgspiceTest(unittest.TestCase):
    """`load_case()` must read the fleet's ngspice version out of the case's own klt log.

    Until issue #297 this driver was the one fleet runner that did not, and its record
    stated a constant (`ngspice-46 (per fleet log)`) that had gone stale by two releases.
    """

    def _case(self, tmp, log_body):
        """A klt report for one case whose corner carries `log_body` as its log and no
        waveform (so `load_case` returns right after reading the provenance)."""
        man = rd.sim_common.load_manifest(rd.MANIFEST)
        case = rd.build_matrix(man)[0]
        d = Path(tmp) / case["id"]
        d.mkdir(parents=True)
        log = d / "corner.log"
        if log_body is not None:
            log.write_text(log_body)
        (d / "report.json").write_text(json.dumps({
            "status": "ok", "environment": {"remote": {"job_id": "j1", "runner_klt_version": "0.9.0"}},
            "corners": [{"artifacts": {"log": str(log)} if log_body is not None else {}}],
        }))
        return rd.load_case(case, Path(tmp), man, Path(tmp) / "corners", False)

    def test_version_comes_from_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._case(tmp, "Note: Compatibility modes selected\nngspice-47 done\n")
        self.assertEqual(rec["ngspice"], "ngspice-47")
        self.assertEqual(rec["runner_klt_version"], "0.9.0")

    def test_log_without_a_banner_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._case(tmp, "no version banner here\n")
        self.assertIsNone(rec["ngspice"])

    def test_missing_log_is_none_not_a_literal(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self._case(tmp, None)
        self.assertIsNone(rec["ngspice"])

    def test_record_block_reports_unknown_when_nothing_was_observed(self):
        """A case set with no ngspice banner anywhere must say so, not name a version."""
        _, tools = rd.sim_common.record_pdk_tools(
            _Pdk(), {"open_pdks_commit": "a" * 40}, {"klt_client": "klt 0.9.0"},
            [{"ngspice": None}], [{"runner_klt_version": None}],
            lib_file=None, root=None, host_tools=False, fleet_note=None, xschem_note=None,
        )
        self.assertEqual(tools["fleet_ngspice"], "unknown")
        self.assertEqual(tools["fleet_runner_klt"], "unknown")


class _Pdk:
    variant = "sky130A"
    installed_commit = "a" * 40
    matches_pin = True


if __name__ == "__main__":
    unittest.main()
