#!/usr/bin/env python3
"""Targeted tests for sim/brownout-top (issue #116).  No simulation, standard library only.

    python3 sim/brownout-top/selftest/test_brownout.py
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import brownout_checker as bc  # noqa: E402
import run_brownout_campaign as rb  # noqa: E402

MAN = json.loads((HERE.parent / "experiment.json").read_text())


class CheckerCases(unittest.TestCase):
    def test_every_synthetic_case(self):
        for r in bc.run_selftest():
            with self.subTest(r["case"]):
                self.assertTrue(r["ok"], r)

    def test_case_coverage_matches_issue_test_plan(self):
        names = {r["case"] for r in bc.run_selftest()}
        for need in ("recovery_ok", "missed_assertion", "premature_release", "truncated_observation", "sparse_samples", "nonphysical_node",
                     "missing_current_channel", "nodip_control_ok", "unready_baseline"):
            self.assertIn(need, names)

    def test_committed_fixtures_regrade_from_disk(self):
        import gzip
        for name, want in (("recovery_ok", "PASS"), ("missed_assertion", "FAIL")):
            with gzip.open(HERE / f"{name}.wave.json.gz", "rt") as fh:
                doc = json.load(fh)
            cols = {v["name"]: [row[i] for row in doc["points"]] for i, v in enumerate(doc["variables"])}
            for n in bc.PHYS_NODES:
                cols.setdefault(n, [0.5] * len(cols["time"]))
            self.assertEqual(bc.analyze(cols, 3.3, doc["stimulus"], bc.T_OBS_REF)["verdict"], want)

    def test_no_waveform_is_error_and_nonphysical_cannot_pass(self):
        self.assertEqual(bc.analyze(None, 3.3, bc.REF_ST, bc.T_OBS_REF)["verdict"], "ERROR")
        w, st = bc.synth(bad_node=("v(xdut.xtemp.nb)", -50.0))
        res = bc.analyze(w, 3.3, st, bc.T_OBS_REF)
        self.assertEqual(res["verdict"], "NONPHYSICAL")

    def test_wrong_bias_sign_is_nonphysical(self):
        w, st = bc.synth()
        w[bc.I_DELIVERED] = [-x for x in w[bc.I_DELIVERED]]  # negative delivered current = sign-convention violation
        self.assertEqual(bc.analyze(w, 3.3, st, bc.T_OBS_REF)["verdict"], "NONPHYSICAL")

    def test_unready_baseline_is_unresolved_not_fail(self):
        w, st = bc.synth(behavior="no_baseline")
        res = bc.analyze(w, 3.3, st, bc.T_OBS_REF)
        self.assertEqual(res["verdict"], "UNRESOLVED")
        self.assertFalse(res["baseline"]["ok"])
        self.assertEqual(res["fail_codes"], [])


class StimulusAxes(unittest.TestCase):
    base = dict(bc.REF_ST)

    def tl(self, vf=3.3, **kw):
        return bc.timeline(vf, {**self.base, **kw})

    def test_edges_derive_from_excursion_over_slew(self):
        t = self.tl()
        self.assertAlmostEqual(t["t_fall"] * self.base["sf"], 3.3 - self.base["vlow"])
        self.assertAlmostEqual(t["t_rec"] * self.base["sr"], 3.3 - self.base["vlow"])

    def test_axes_are_independent(self):
        ref = self.tl()
        hold = self.tl(th=1e-3)
        self.assertEqual((hold["t_fall"], hold["t_rec"]), (ref["t_fall"], ref["t_rec"]))
        self.assertAlmostEqual(hold["t_rec_start"] - ref["t_rec_start"], 1e-3 - self.base["th"])
        sr = self.tl(sr=1e3)
        self.assertEqual((sr["t_fall"], sr["t_rec_start"]), (ref["t_fall"], ref["t_rec_start"]))
        self.assertNotEqual(sr["t_rec"], ref["t_rec"])
        sf = self.tl(sf=1e3)
        self.assertEqual(sf["t_rec"], ref["t_rec"])
        self.assertNotEqual(sf["t_fall"], ref["t_fall"])

    def test_starting_supply_does_not_couple_into_slew(self):
        st = dict(self.base)
        for vf in (2.97, 3.3, 3.63):
            t0, dt = st["t0"], 1e-7
            slope_fall = (bc.vdd_expected(t0 + 2 * dt, vf, st) - bc.vdd_expected(t0 + dt, vf, st)) / dt
            self.assertAlmostEqual(slope_fall / -st["sf"], 1.0, places=6)
            tr = bc.timeline(vf, st)["t_rec_start"]
            slope_rec = (bc.vdd_expected(tr + 2 * dt, vf, st) - bc.vdd_expected(tr + dt, vf, st)) / dt
            self.assertAlmostEqual(slope_rec / st["sr"], 1.0, places=6)
            tl = bc.timeline(vf, st)
            self.assertAlmostEqual(bc.vdd_expected(tl["t_fall_end"] + st["th"] / 2, vf, st), st["vlow"], places=9)
            self.assertAlmostEqual(bc.vdd_expected(tl["t_rec_end"] + 1e-3, vf, st), vf, places=9)

    def test_control_has_no_dip(self):
        st = {**self.base, "vlow": 99.0}
        self.assertTrue(bc.timeline(3.3, st)["control"])
        for x in (0.0, 0.019, 0.0205, 0.03):
            self.assertAlmostEqual(bc.vdd_expected(x, 3.3, st), min(3.3, st["rup"] * x), places=12)


class Matrix(unittest.TestCase):
    def test_declared_counts(self):
        reqs = rb.plan_requests(MAN)
        g = MAN["grid"]
        cube = len(g["floors_v"]) * len(g["holds_s"]) * len(g["fall_slews_v_per_s"])
        self.assertEqual(len(reqs), cube + len(g["recovery_variants_v_per_s"]) + 1)
        self.assertEqual(rb.declared_counts(MAN), {"requests": 30, "points_per_request": 45, "points": 1350})
        self.assertEqual(len(rb.corners_of(MAN)), 45)
        self.assertEqual(sum(1 for r in reqs if r["kind"] == "control"), 1)
        self.assertEqual(len({r["tag"] for r in reqs}), len(reqs))

    def test_each_axis_level_present_and_independent(self):
        cube = [r for r in rb.plan_requests(MAN) if r["kind"] == "cube"]
        g = MAN["grid"]
        self.assertEqual({r["vlow"] for r in cube}, set(g["floors_v"]))
        self.assertEqual({r["th"] for r in cube}, set(g["holds_s"]))
        self.assertEqual({r["sf"] for r in cube}, set(g["fall_slews_v_per_s"]))
        self.assertEqual(len({(r["vlow"], r["th"], r["sf"]) for r in cube}), len(cube))

    def test_request_axes_and_tmax(self):
        for r in rb.plan_requests(MAN):
            req = rb.build_request(r, MAN, "batch")
            self.assertEqual(req["backend"], "batch")
            self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["supply_v"]["vset"]) * len(req["corners"]["temperature_c"]), 45)
            self.assertLessEqual(rb.tmax_of(r, MAN), 5e-6)
            if r["kind"] != "control":
                self.assertLessEqual(rb.tmax_of(r, MAN), r["th"] / 10 + 1e-15)
                # the simulator step bound must satisfy the checker's sample-gap requirement at every supply
                for vf in MAN["corners"]["supply_v"]:
                    self.assertLess(rb.tmax_of(r, MAN), bc.required_max_dt(vf, rb.stim_of(r)) + 1e-15)

    def test_netlist_carries_only_params_no_design_edits(self):
        r = rb.plan_requests(MAN)[0]
        text = rb.build_netlist("* head\n", r)
        self.assertIn(rb.DUT_NETLIST.read_text().splitlines()[3], text)
        self.assertIn("XMN1 PDN IBIAS VSS VSS sky130_fd_pr__nfet_g5v0d10v5 L=20 W=0.42", text)
        self.assertIn(f"vlow={r['vlow']:g}", text)


class Accounting(unittest.TestCase):
    def test_unsubmitted_points_are_not_covered_never_pass(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            r = rb.plan_requests(MAN)[0]
            res = rb.analyze_request(r, run_dir, MAN, run_dir / "corners", write=False)
            self.assertEqual(len(res["points"]), 45)
            self.assertTrue(all(p["outcome"] == "NOT_COVERED" for p in res["points"]))
            summ = rb.summarize(res["points"])
            self.assertEqual(summ["total"]["NOT_COVERED"], 45)
            self.assertEqual(summ["total"]["PASS"], 0)

    def test_refused_report_without_corners_is_not_covered(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            r = rb.plan_requests(MAN)[0]
            (run_dir / r["tag"]).mkdir()
            (run_dir / r["tag"] / "report.json").write_text(json.dumps({"status": "error", "error": {"message": "fleet capacity refused"}}))
            res = rb.analyze_request(r, run_dir, MAN, run_dir / "corners", write=False)
            self.assertEqual({p["outcome"] for p in res["points"]}, {"NOT_COVERED"})
            self.assertIn("capacity", res["info"]["outcome"])

    def test_record_id_collision_refuses_overwrite(self):
        fixed = _dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)

        class FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build, here = td / "build", td / "here"
            (build / "run1").mkdir(parents=True)
            (here).mkdir()
            (build / "run1" / "run.json").write_text(json.dumps({"klt_client": "test", "source": {"dirty": False}}))
            gi = {"sha": "abc1234", "sha_full": "abc1234" + "0" * 33, "branch": "t", "dirty": False, "pushed_to_remote": True, "remote_branches": []}
            ns = mock.Mock(run_id="run1", notes_file=None, author="t", supersedes=None)
            with mock.patch.object(rb, "BUILD", build), mock.patch.object(rb, "HERE", here), mock.patch.object(rb, "datetime", FixedDT), mock.patch.object(rb, "source_state", return_value=gi):
                self.assertEqual(rb.cmd_record(ns), 0)
                rec = json.loads(next((here / "records").glob("*.json")).read_text())
                self.assertEqual(rec["matrix"]["n_points_graded"], 0)
                self.assertEqual(rec["matrix"]["n_points_not_covered"], 1350)
                self.assertEqual(rec["summary"]["total"]["PASS"], 0)
                before = {p: p.read_text() for p in (here / "records").glob("*")}
                with self.assertRaises(SystemExit):
                    rb.cmd_record(ns)
                self.assertEqual(before, {p: p.read_text() for p in (here / "records").glob("*")})


if __name__ == "__main__":
    unittest.main(verbosity=1)
