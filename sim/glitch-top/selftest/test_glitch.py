#!/usr/bin/env python3
"""Targeted tests for sim/glitch-top (issue #117).  No simulation, standard library only.

    python3 -I sim/glitch-top/selftest/test_glitch.py
"""

from __future__ import annotations

import datetime as _dt
import gzip
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import glitch_checker as gc  # noqa: E402
import run_glitch_campaign as rg  # noqa: E402

MAN = json.loads((HERE.parent / "experiment.json").read_text())
A, B = gc.CLASS_A, gc.CLASS_B

# cmd_record resolves the host PDK only to stamp provenance; CI runners have no PDK, so the record
# tests substitute a fixed stand-in (a plain object: the record JSON serialises these fields).
FAKE_PDK = SimpleNamespace(variant="sky130A", installed_commit="0" * 40, matches_pin=True)


def _no_host_pdk():
    return mock.patch.object(rg.cr, "resolve_pdk", return_value=FAKE_PDK)


class CheckerCases(unittest.TestCase):
    def test_every_synthetic_case(self):
        for r in gc.run_selftest():
            with self.subTest(r["case"]):
                self.assertTrue(r["ok"], r)

    def test_case_coverage_matches_issue_test_plan(self):
        names = {r["case"] for r in gc.run_selftest()}
        for need in ("A_rejected_pulse", "A_required_assertion_recovers", "A_missed_assertion", "A_unwanted_assertion", "A_premature_release",
                     "A_multiple_releases_chatter", "A_sparse_samples", "A_unsettled_baseline", "A_nonphysical_node", "A_missing_current_channel",
                     "A_control_ok", "B_required_assertion_recovers", "B_missed_assertion", "B_premature_release", "B_multiple_releases_chatter",
                     "B_sparse_samples", "B_unsettled_baseline", "B_rail_collapse_nonphysical", "B_missing_waveform_channel", "B_control_ok"):
            self.assertIn(need, names)

    def test_committed_fixtures_regrade_from_disk(self):
        for name, cls, want in (("A_required_assertion_recovers", A, "PASS"), ("A_missed_assertion", A, "FAIL"), ("B_required_assertion_recovers", B, "PASS")):
            with gzip.open(HERE / f"{name}.wave.json.gz", "rt") as fh:
                doc = json.load(fh)
            cols = {v["name"]: [row[i] for row in doc["points"]] for i, v in enumerate(doc["variables"])}
            for n in gc.PHYS_NODES:
                cols.setdefault(n, [0.5] * len(cols["time"]))
            for s in gc.I_SINKS:
                cols.setdefault(s, [1e-6] * len(cols["time"]))
            self.assertEqual(gc.analyze(cls, cols, 3.3, doc["stimulus"], gc.T_OBS_REF)["verdict"], want, name)

    def test_no_waveform_is_error_and_nonphysical_cannot_pass(self):
        self.assertEqual(gc.analyze(A, None, 3.3, gc.REF_A, gc.T_OBS_REF)["verdict"], "ERROR")
        self.assertEqual(gc.analyze(B, None, 3.3, gc.REF_B, gc.T_OBS_REF)["verdict"], "ERROR")
        w, st = gc.synth_a(bad_node=("v(xdut.xtemp.nb)", -50.0))
        self.assertEqual(gc.analyze(A, w, 3.3, st, gc.T_OBS_REF)["verdict"], "NONPHYSICAL")

    def test_wrong_bias_sign_is_nonphysical_in_both_classes(self):
        w, st = gc.synth_a()
        w[gc.I_DELIVERED] = [-x for x in w[gc.I_DELIVERED]]
        self.assertEqual(gc.analyze(A, w, 3.3, st, gc.T_OBS_REF)["verdict"], "NONPHYSICAL")
        w, st = gc.synth_b()
        w[gc.I_DELIVERED] = [-x for x in w[gc.I_DELIVERED]]
        self.assertEqual(gc.analyze(B, w, 3.3, st, gc.T_OBS_REF)["verdict"], "NONPHYSICAL")

    def test_rejected_vs_required_expectations_are_distinct(self):
        self.assertEqual(gc.expectation_a(10e-6, False), "rejection")
        self.assertEqual(gc.expectation_a(300e-6, False), "assertion_optional")
        self.assertEqual(gc.expectation_a(2e-3, False), "assertion_required")
        self.assertEqual(gc.expectation_a(0.0, True), "no_glitch")

    def test_class_a_pass_requires_bias_current_and_injection_channels(self):
        w, st = gc.synth_a(st=dict(gc.REF_A, tw=2e-3))
        res = gc.analyze(A, w, 3.3, st, gc.T_OBS_REF)
        self.assertEqual(res["verdict"], "PASS")
        self.assertGreater(res["delivered_bias"]["baseline_a"], 0)
        self.assertGreater(res["injection"]["peak_injected_current_a"], 0)
        self.assertTrue(res["injection"]["exercised"])

    def test_stimulus_drive_mismatch_is_unresolved(self):
        w, st = gc.synth_a(st=dict(gc.REF_A, tw=2e-3))
        w[gc.V_GINJ] = [0.0] * len(w["time"])  # the sampled drive does not match the declared trapezoid
        self.assertEqual(gc.analyze(A, w, 3.3, st, gc.T_OBS_REF)["verdict"], "UNRESOLVED")


class StimulusConstruction(unittest.TestCase):
    st = dict(rup=1e5, t0=8e-3, te=20e-6, tw=200e-6, rinj=1e3, gen=1)

    def test_trapezoid_flat_width_and_edges(self):
        s, t0, te, tw = self.st, self.st["t0"], self.st["te"], self.st["tw"]
        self.assertEqual(gc.g_expected(t0 - 1e-6, s), 0.0)
        self.assertAlmostEqual(gc.g_expected(t0 + te / 2, s), 0.5)
        self.assertAlmostEqual(gc.g_expected(t0 + te + tw / 2, s), 1.0)
        self.assertAlmostEqual(gc.g_expected(t0 + te + tw + te / 2, s), 0.5)
        self.assertEqual(gc.g_expected(t0 + 2 * te + tw + 1e-6, s), 0.0)
        tl = gc.timeline_a(s)
        self.assertAlmostEqual(tl["t_end"] - t0, tw + 2 * te)
        self.assertAlmostEqual(tl["fwhm"], tw + te)

    def test_width_and_edge_are_independent_axes(self):
        a = gc.timeline_a(self.st)
        b = gc.timeline_a(dict(self.st, tw=2e-3))
        c = gc.timeline_a(dict(self.st, te=200e-6))
        self.assertEqual(a["t_rise_end"], b["t_rise_end"])
        self.assertNotEqual(a["t_fall_start"], b["t_fall_start"])
        self.assertAlmostEqual(a["t_fall_start"] - a["t_rise_end"], self.st["tw"], places=12)
        self.assertAlmostEqual(c["t_fall_start"] - c["t_rise_end"], self.st["tw"], places=12)
        self.assertNotEqual(a["t_rise_end"], c["t_rise_end"])

    def test_control_has_zero_drive(self):
        s = dict(self.st, gen=0)
        self.assertTrue(gc.timeline_a(s)["control"])
        self.assertTrue(all(gc.g_expected(x * 1e-4, s) == 0.0 for x in range(0, 200)))

    def test_vdd_glitch_edges_are_symmetric_and_derived(self):
        st = dict(gc.REF_B)
        for vf in (2.97, 3.3, 3.63):
            s = gc.b_stim(st)
            tl = gc.bc.timeline(vf, s)
            self.assertAlmostEqual(tl["t_fall"], tl["t_rec"])
            self.assertAlmostEqual(tl["t_fall"] * st["sf"], vf - st["vlow"])


class Matrix(unittest.TestCase):
    def test_declared_counts_per_class(self):
        self.assertEqual(rg.declared_counts(MAN, A), {"requests": 9, "points_per_request": 45, "points": 405})
        self.assertEqual(rg.declared_counts(MAN, B), {"requests": 9, "points_per_request": 45, "points": 405})
        self.assertEqual(rg.declared_counts(MAN)["points"], 810)
        reqs = rg.plan_requests(MAN)
        self.assertEqual(len({r["tag"] for r in reqs}), len(reqs))
        for cls in (A, B):
            rs = [r for r in reqs if r["cls"] == cls]
            self.assertEqual(sum(1 for r in rs if r["kind"] == "control"), 1)

    def test_class_a_grid_axes(self):
        cube = [r for r in rg.plan_requests(MAN, A) if r["kind"] == "cube"]
        g = MAN["grid"]["por_raw_inject"]
        self.assertEqual({r["rinj"] for r in cube}, set(g["rinj_ohm"]))
        self.assertEqual({r["tw"] for r in cube}, set(g["flat_widths_s"]))
        self.assertEqual(len({(r["rinj"], r["tw"]) for r in cube}), len(cube))
        ctl = next(r for r in rg.plan_requests(MAN, A) if r["kind"] == "control")
        self.assertEqual(ctl["gen"], 0)

    def test_class_b_grid_axes(self):
        cube = [r for r in rg.plan_requests(MAN, B) if r["kind"] == "cube"]
        g = MAN["grid"]["vdd_level"]
        self.assertEqual({r["vlow"] for r in cube}, set(g["floors_v"]))
        self.assertEqual({r["th"] for r in cube}, set(g["holds_s"]))
        ctl = next(r for r in rg.plan_requests(MAN, B) if r["kind"] == "control")
        self.assertGreater(ctl["vlow"], 10)

    def test_request_axes_and_step_bound_resolves_requested_width(self):
        for r in rg.plan_requests(MAN):
            req = rg.build_request(r, MAN, "batch")
            self.assertEqual(req["backend"], "batch")
            self.assertEqual(len(req["corners"]["process"]) * len(req["corners"]["supply_v"]["vset"]) * len(req["corners"]["temperature_c"]), 45)
            self.assertLessEqual(rg.tmax_of(r, MAN), 10e-6)
            if r["kind"] == "control":
                continue
            if r["cls"] == A:
                self.assertLessEqual(rg.tmax_of(r, MAN), r["tw"] / 8 + 1e-15)
                self.assertLessEqual(rg.tmax_of(r, MAN), r["te"] / 8 + 1e-15)
                self.assertLess(rg.tmax_of(r, MAN), gc.required_max_dt_a(rg.stim_of(r)) + 1e-15)
            else:
                for vf in MAN["corners"]["supply_v"]:
                    self.assertLess(rg.tmax_of(r, MAN), gc.required_max_dt_b(vf, rg.stim_of(r)) + 1e-15)

    def test_observation_window_covers_recovery(self):
        for r in rg.plan_requests(MAN):
            if r["cls"] == A:
                self.assertAlmostEqual(rg.tstop_of(r, MAN) - gc.timeline_a(rg.stim_of(r))["t_end"], MAN["stimulus"]["observation_after_recovery_s"])


class Netlists(unittest.TestCase):
    def deck(self, req):
        return rg.build_netlist("* head\n", req)

    def test_class_b_dut_is_byte_identical(self):
        r = next(r for r in rg.plan_requests(MAN, B) if r["kind"] == "cube")
        text = self.deck(r)
        dut = "\n".join(ln for ln in rg.DUT_NETLIST.read_text().splitlines() if ln.strip().lower() != ".end") + "\n"
        self.assertIn(dut, text)
        self.assertNotIn("RINJ", text)
        self.assertNotIn("BINJ", text)
        self.assertNotIn(".global", text)

    def test_class_a_differs_from_committed_dut_by_exactly_the_instrument_lines(self):
        r = next(r for r in rg.plan_requests(MAN, A) if r["kind"] == "cube")
        committed = rg.DUT_NETLIST.read_text().splitlines()
        committed = [ln for ln in committed if ln.strip().lower() != ".end"]
        spliced = rg.splice_injection("\n".join(committed) + "\n", r["rinj"]).splitlines()
        added = [ln for ln in spliced if ln not in committed]
        self.assertEqual(added, [rg.INJ_MARK, rg.INJ_B, rg.INJ_R.format(rinj=r["rinj"])])
        self.assertEqual([ln for ln in spliced if ln in committed], committed)
        # the comparator and the output chain are still connected: nothing was removed
        self.assertTrue(any(ln.startswith("xcmp ") for ln in spliced) and any(ln.startswith("xpor ") for ln in spliced))
        self.assertIn("XMN1 PDN IBIAS VSS VSS sky130_fd_pr__nfet_g5v0d10v5 L=20 W=0.42", "\n".join(spliced))
        text = self.deck(r)
        self.assertIn(".global GINJ", text)
        self.assertIn(rg.INJ_SAVE, text)

    def test_control_keeps_instrument_topology_with_zero_drive(self):
        ctl = next(r for r in rg.plan_requests(MAN, A) if r["kind"] == "control")
        text = self.deck(ctl)
        self.assertIn(rg.INJ_B, text)
        self.assertIn("gen=0", text)

    def test_param_line_carries_every_axis(self):
        r = next(r for r in rg.plan_requests(MAN, A) if r["kind"] == "edge")
        text = self.deck(r)
        for k in ("rinj", "tw", "te", "t0", "rup", "gen"):
            self.assertIn(f"{k}={r[k]:g}", text)


class DeckAttribution(unittest.TestCase):
    def test_correct_decks_are_attributable(self):
        for r in rg.plan_requests(MAN):
            self.assertEqual(rg.deck_attribution(rg.build_netlist("* head\n", r), r), [], r["tag"])

    def test_wrong_class_deck_is_rejected(self):
        a = next(r for r in rg.plan_requests(MAN, A) if r["kind"] == "cube")
        b = next(r for r in rg.plan_requests(MAN, B) if r["kind"] == "cube")
        self.assertTrue(rg.deck_attribution(rg.build_netlist("* head\n", b), a))  # class B deck credited to a class A point
        self.assertTrue(rg.deck_attribution(rg.build_netlist("* head\n", a), b))  # injected deck credited to the unmodified class

    def test_diagnostic_or_wrong_xmn1_deck_is_rejected(self):
        r = rg.plan_requests(MAN, B)[0]
        deck = rg.build_netlist("* head\n", r)
        self.assertTrue(rg.deck_attribution(deck + "\n* diag-mn1-l20\n", r))
        self.assertTrue(rg.deck_attribution(deck.replace("L=20 W=0.42", "L=2 W=0.42"), r))
        self.assertTrue(rg.deck_attribution(deck.replace(r["tag"], "other_request"), r))


class Accounting(unittest.TestCase):
    def test_unsubmitted_points_are_not_covered_never_pass(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            for r in (rg.plan_requests(MAN, A)[0], rg.plan_requests(MAN, B)[0]):
                res = rg.analyze_request(r, run_dir, MAN, run_dir / "corners", write=False)
                self.assertEqual(len(res["points"]), 45)
                self.assertTrue(all(p["outcome"] == "NOT_COVERED" for p in res["points"]))
                summ = rg.summarize(res["points"])
                self.assertEqual(summ["total"]["NOT_COVERED"], 45)
                self.assertEqual(summ["total"]["PASS"], 0)
                self.assertEqual(len(summ["by_corner"]), 45)

    def test_refused_report_without_corners_is_not_covered(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            r = rg.plan_requests(MAN, A)[0]
            (run_dir / r["tag"]).mkdir()
            (run_dir / r["tag"] / "report.json").write_text(json.dumps({"status": "error", "error": {"message": "fleet capacity refused"}}))
            res = rg.analyze_request(r, run_dir, MAN, run_dir / "corners", write=False)
            self.assertEqual({p["outcome"] for p in res["points"]}, {"NOT_COVERED"})
            self.assertIn("capacity", res["info"]["outcome"])

    def test_record_writes_one_record_per_class_and_refuses_overwrite(self):
        fixed = _dt.datetime(2030, 1, 2, 3, 4, 5, tzinfo=_dt.timezone.utc)

        class FixedDT(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build, here = td / "build", td / "here"
            (build / "run1").mkdir(parents=True)
            here.mkdir()
            (build / "run1" / "run.json").write_text(json.dumps({"klt_client": "test", "source": {"dirty": False}}))
            gi = {"sha": "abc1234", "sha_full": "abc1234" + "0" * 33, "branch": "t", "dirty": False, "pushed_to_remote": True, "remote_branches": []}
            ns = mock.Mock(run_id="run1", notes_file=None, author="t", supersedes=None, allow_dirty=False, allow_deck_drift=False)
            with mock.patch.object(rg, "BUILD", build), mock.patch.object(rg, "HERE", here), mock.patch.object(rg, "datetime", FixedDT), mock.patch.object(rg, "source_state", return_value=gi), \
                    _no_host_pdk():
                self.assertEqual(rg.cmd_record(ns), 0)
                recs = sorted((here / "records").glob("*.json"))
                self.assertEqual([json.loads(p.read_text())["class"] for p in recs], [A, B])
                for p in recs:
                    rec = json.loads(p.read_text())
                    self.assertEqual(rec["matrix"]["n_points_graded"], 0)
                    self.assertEqual(rec["matrix"]["n_points_not_covered"], 405)
                    self.assertEqual(rec["summary"]["total"]["PASS"], 0)
                    self.assertTrue(all(q["class"] == rec["class"] for q in rec["points"]))
                    self.assertEqual(rec["injection"] is not None, rec["class"] == A)
                    md = p.with_suffix(".md").read_text()
                    self.assertIn("NOT_COVERED", md)
                    self.assertIn("covers ONLY this class", md)
                before = {p: p.read_text() for p in (here / "records").glob("*")}
                with self.assertRaises(SystemExit):
                    rg.cmd_record(ns)
                self.assertEqual(before, {p: p.read_text() for p in (here / "records").glob("*")})

    def test_record_refuses_dirty_tree_and_deck_drift(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            build, here = td / "build", td / "here"
            (build / "run1").mkdir(parents=True)
            here.mkdir()
            (build / "run1" / "run.json").write_text(json.dumps({"klt_client": "t", "source": {"dirty": False, "sha_full": "a" * 40}}))
            ns = mock.Mock(run_id="run1", notes_file=None, author="t", supersedes=None, allow_dirty=False, allow_deck_drift=False)
            gi = {"sha": "abc1234", "sha_full": "b" * 40, "branch": "t", "dirty": True, "pushed_to_remote": True, "remote_branches": []}
            with mock.patch.object(rg, "BUILD", build), mock.patch.object(rg, "HERE", here), mock.patch.object(rg, "source_state", return_value=gi), _no_host_pdk():
                with self.assertRaises(SystemExit):
                    rg.cmd_record(ns)
            gi["dirty"] = False
            with mock.patch.object(rg, "BUILD", build), mock.patch.object(rg, "HERE", here), mock.patch.object(rg, "source_state", return_value=gi), \
                    mock.patch.object(rg, "deck_drift", return_value=["design/netlist/temp_por_top.spice"]), _no_host_pdk():
                with self.assertRaises(SystemExit):
                    rg.cmd_record(ns)
            self.assertFalse((here / "records").exists())


if __name__ == "__main__":
    unittest.main(verbosity=1)
