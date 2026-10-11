#!/usr/bin/env python3
"""Targeted tests for sim/brownout-top (issue #116).  No simulation, standard library only.

    python3 sim/brownout-top/selftest/test_brownout.py
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
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
        self.assertEqual(rb.declared_counts(MAN), {"requests": 21, "points_per_request": 45, "points": 945})
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
            self.assertLessEqual(rb.tmax_of(r, MAN), 10e-6)
            if r["kind"] != "control":
                self.assertLessEqual(rb.tmax_of(r, MAN), r["th"] / 6 + 1e-15)
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
            ns = mock.Mock(run_id="run1", variant=None, compare_source=None, notes_file=None, author="t", supersedes=None, allow_dirty=False, allow_deck_drift=False)
            with mock.patch.object(rb, "BUILD", build), mock.patch.object(rb, "HERE", here), mock.patch.object(rb, "datetime", FixedDT), mock.patch.object(rb, "source_state", return_value=gi):
                self.assertEqual(rb.cmd_record(ns), 0)
                rec = json.loads(next((here / "records").glob("*.json")).read_text())
                self.assertEqual(rec["matrix"]["n_points_graded"], 0)
                self.assertEqual(rec["matrix"]["n_points_not_covered"], 945)
                self.assertEqual(rec["summary"]["total"]["PASS"], 0)
                before = {p: p.read_text() for p in (here / "records").glob("*")}
                with self.assertRaises(SystemExit):
                    rb.cmd_record(ns)
                self.assertEqual(before, {p: p.read_text() for p in (here / "records").glob("*")})

    def _record_env(self, td, gi):
        build, here = td / "build", td / "here"
        (build / "run1").mkdir(parents=True)
        here.mkdir()
        (build / "run1" / "run.json").write_text(json.dumps({"klt_client": "test", "source": {"dirty": False, "sha_full": "a" * 40}}))
        return build, here

    def test_record_refuses_dirty_tree(self):
        with tempfile.TemporaryDirectory() as td:
            gi = {"sha": "abc1234", "sha_full": "b" * 40, "branch": "t", "dirty": True, "pushed_to_remote": True, "remote_branches": []}
            build, here = self._record_env(Path(td), gi)
            ns = mock.Mock(run_id="run1", variant=None, compare_source=None, notes_file=None, author="t", supersedes=None, allow_dirty=False, allow_deck_drift=False)
            with mock.patch.object(rb, "BUILD", build), mock.patch.object(rb, "HERE", here), mock.patch.object(rb, "source_state", return_value=gi):
                with self.assertRaises(SystemExit):
                    rb.cmd_record(ns)
            self.assertFalse((here / "records").exists())

    def test_record_refuses_deck_drift_between_submit_and_grading(self):
        with tempfile.TemporaryDirectory() as td:
            gi = {"sha": "abc1234", "sha_full": "b" * 40, "branch": "t", "dirty": False, "pushed_to_remote": True, "remote_branches": []}
            build, here = self._record_env(Path(td), gi)
            ns = mock.Mock(run_id="run1", variant=None, compare_source=None, notes_file=None, author="t", supersedes=None, allow_dirty=False, allow_deck_drift=False)
            with mock.patch.object(rb, "BUILD", build), mock.patch.object(rb, "HERE", here), mock.patch.object(rb, "source_state", return_value=gi), \
                    mock.patch.object(rb, "deck_drift", return_value=["design/netlist/temp_por_top.spice"]):
                with self.assertRaises(SystemExit):
                    rb.cmd_record(ns)
            self.assertFalse((here / "records").exists())

    def test_deck_drift_is_empty_for_identical_commits(self):
        head = subprocess.run(["git", "-C", str(rb.REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(rb.deck_drift(head, head), [])
        self.assertIsNone(rb.deck_drift(None, head))


class SolverVariantDeck(unittest.TestCase):
    """The tightened-deck variant (issue #153): only the declared .options line and the banner may differ."""

    head = "* head\n.options method=gear trtol=50\n.save v(vdd)\n"

    def test_default_variant_leaves_deck_identical(self):
        r = rb.plan_requests(MAN)[0]
        self.assertNotIn("reltol", rb.build_netlist(self.head, r))
        self.assertEqual(rb.build_netlist(self.head, r), rb.build_netlist(self.head, r, MAN, "default"))
        self.assertEqual(rb.build_netlist(self.head, r), rb.build_netlist(self.head, r, MAN, None))

    def test_variant_changes_only_options_line_and_banner(self):
        r = rb.plan_requests(MAN)[0]
        a = rb.build_netlist(self.head, r)
        b = rb.build_netlist(self.head, r, MAN, "reltol2e-4")
        self.assertIn(".options method=gear trtol=50 reltol=2e-4", b)
        added = [ln for ln in b.splitlines() if ln not in a.splitlines()]
        self.assertTrue(all(ln.startswith("*") or ln.startswith(".options") for ln in added), added)
        self.assertIn(f".param rup={r['rup']:g} t0={r['t0']:g} vlow={r['vlow']:g} th={r['th']:g} sf={r['sf']:g} sr={r['sr']:g}", b)
        a_code = [ln for ln in a.splitlines() if not ln.startswith("*")]
        b_code = [ln for ln in b.splitlines() if not ln.startswith("*")]
        self.assertEqual(len(a_code), len(b_code))
        for la, lb in zip(a_code, b_code):
            if la.startswith(".options"):
                self.assertEqual(lb, la + " reltol=2e-4")
            else:
                self.assertEqual(la, lb)

    def test_variant_keeps_method_and_trtol(self):
        r = rb.plan_requests(MAN)[0]
        b = rb.build_netlist(self.head, r, MAN, "reltol2e-4")
        self.assertIn("method=gear trtol=50", b)

    def test_undeclared_variant_refuses(self):
        with self.assertRaises(SystemExit):
            rb.variant_of(MAN, "trtol7")
        with self.assertRaises(SystemExit):
            rb.build_netlist(self.head, rb.plan_requests(MAN)[0], MAN, "trtol7")

    def test_head_without_declared_options_line_refuses(self):
        with self.assertRaises(SystemExit):
            rb.build_netlist("* head\n", rb.plan_requests(MAN)[0], MAN, "reltol2e-4")

    def test_fleet_request_is_variant_independent(self):
        r = rb.plan_requests(MAN)[0]
        self.assertEqual(rb.build_request(r, MAN, "batch"), rb.build_request(r, MAN, "batch"))

    def test_run_subparser_accepts_variant(self):
        with mock.patch.object(rb, "cmd_run") as run:
            run.return_value = 0
            self.assertEqual(rb.main(["run", "--variant", "reltol2e-4", "--run-id", "x"]), 0)
        self.assertEqual(run.call_args[0][0].variant, "reltol2e-4")


class TightenedRerunDeclared(unittest.TestCase):
    """The predeclared #153 rerun set must be tied to the committed source record."""

    SRC = HERE.parent / "records" / "20261010-222529-41bde9f.json"

    def test_manifest_declares_variant_and_rerun(self):
        self.assertEqual(MAN["solver_variants"]["default"]["options_extra"], [])
        v = MAN["solver_variants"]["reltol2e-4"]
        self.assertEqual(v["options_extra"], ["reltol=2e-4"])
        rr = MAN["tightened_rerun"]
        self.assertEqual(rr["variant"], "reltol2e-4")
        self.assertIn("20261010-222529-41bde9f", rr["source_record"])
        self.assertIn("UNCHANGED", rr["physicality_bounds"])
        self.assertIn("STAYS NONPHYSICAL", rr["physicality_bounds"])

    @unittest.skipUnless(SRC.is_file(), "source record not on disk")
    def test_rerun_set_covers_every_source_nonphysical_point(self):
        src = json.loads(self.SRC.read_text())
        self.assertEqual(len(src["points"]), 945)
        nonphys: dict = {}
        for p in src["points"]:
            if p["outcome"] == "NONPHYSICAL":
                nonphys[p["tag"]] = nonphys.get(p["tag"], 0) + 1
        tags = {r["tag"] for r in rb.plan_requests(MAN)}
        self.assertEqual(sum(nonphys.values()), 673)
        self.assertEqual(set(nonphys), tags)  # every request holds >= 1 target, so whole-request reruns cover the set


def _cpt(tag, cid, outcome, runtime=None, phys=None, codes=()):
    pt = {"tag": tag, "id": cid, "process": "tt", "temperature_c": 27, "supply_v": 3.3, "outcome": outcome, "runtime_s": runtime}
    if outcome == "NOT_COVERED":
        pt["reason"] = "fleet refused"
    else:
        pt["check"] = {"physical": {} if phys is None else {"ok": phys}, "fail_codes": list(codes), "unresolved_reasons": []}
    return pt


class Comparison(unittest.TestCase):
    SRC_1 = {"record_id": "src-1", "points": [_cpt("a", "p1", "NONPHYSICAL", 10.0), _cpt("a", "p2", "PASS", 12.0)]}

    def test_every_point_joined_exactly_once(self):
        rerun = [_cpt("a", "p1", "PASS", 20.0, phys=True), _cpt("a", "p2", "NONPHYSICAL", 24.0, phys=False)]
        cmp = rb.build_comparison(self.SRC_1, rerun)
        self.assertEqual(cmp["points_compared"], 2)
        self.assertEqual(cmp["source_record"], "src-1")
        self.assertEqual(cmp["transition_matrix"]["NONPHYSICAL"]["PASS"], 1)
        self.assertEqual(cmp["transition_matrix"]["PASS"]["NONPHYSICAL"], 1)
        self.assertEqual(cmp["targets"]["n"], 1)
        self.assertEqual(cmp["targets"]["transitions"], {"PASS": 1})
        self.assertEqual(cmp["controls"]["n"], 1)
        self.assertEqual(cmp["controls"]["n_changed"], 1)
        self.assertEqual(cmp["runtime_ratio"]["median_ratio"], 2.0)
        self.assertTrue(rb.render_comparison_md(cmp))

    def test_broken_joins_refuse(self):
        with self.assertRaises(SystemExit):  # rerun point absent from source
            rb.build_comparison({"record_id": "s", "points": []}, [_cpt("a", "p1", "PASS")])
        with self.assertRaises(SystemExit):  # source point with no rerun row
            rb.build_comparison({"record_id": "s", "points": [_cpt("a", "p1", "PASS")]}, [])
        with self.assertRaises(SystemExit):  # duplicate source rows
            rb.build_comparison({"record_id": "s", "points": [_cpt("a", "p1", "PASS"), _cpt("a", "p1", "FAIL")]}, [_cpt("a", "p1", "PASS")])

    def test_not_covered_and_error_kept_not_dropped(self):
        rerun = [{"tag": "a", "id": "p1", "process": "tt", "temperature_c": 27, "supply_v": 3.3, "outcome": "NOT_COVERED", "reason": "fleet refused", "runtime_s": None}]
        cmp = rb.build_comparison({"record_id": "s", "points": [_cpt("a", "p1", "NONPHYSICAL", 10.0)]}, rerun)
        self.assertEqual(cmp["transition_matrix"]["NONPHYSICAL"]["NOT_COVERED"], 1)
        self.assertIsNone(cmp["rows"][0]["tightened_physical"])
        self.assertIn("refused", cmp["rows"][0]["tightened_note"])
        rerun2 = [_cpt("a", "p1", "ERROR", runtime=None)]
        cmp2 = rb.build_comparison({"record_id": "s", "points": [_cpt("a", "p1", "NONPHYSICAL", 10.0)]}, rerun2)
        self.assertEqual(cmp2["transition_matrix"]["NONPHYSICAL"]["ERROR"], 1)
        self.assertIsNone(cmp2["rows"][0]["tightened_physical"])

    def test_fail_codes_surfaced_in_note(self):
        rerun = [_cpt("a", "p1", "FAIL", 20.0, phys=True, codes=("reassert_chatter",))]
        cmp = rb.build_comparison({"record_id": "s", "points": [_cpt("a", "p1", "NONPHYSICAL", 10.0)]}, rerun)
        self.assertEqual(cmp["rows"][0]["tightened_note"], "reassert_chatter")


if __name__ == "__main__":
    unittest.main(verbosity=1)
