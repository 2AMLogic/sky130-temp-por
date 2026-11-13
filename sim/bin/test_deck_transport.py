#!/usr/bin/env python3
"""Deck-transport tests for the two fleet-submitting bespoke runners (issue #319).

Stdlib only, no SPICE, no PDK, no fleet: `klt` is a stub executable on PATH that
answers `--version` and `sim` the way the real verb's outputs are shaped, so request
construction, the shipped-`.spiceinit` path, report-to-result mapping and the
no-local-fallback failure path are all exercised without a batch job.

Modelled on sim/bin/test_corner_run_batch.py.

Run: python3 -I sim/bin/test_deck_transport.py
 or: python3 -m pytest sim/bin/
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent
REPO = BIN.parent.parent
sys.path.insert(0, str(BIN))

import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
PIN = cr.load_pin()
PINNED = PIN["open_pdks_commit"]

# The stub writes its argv to STUB_KLT_LOG and replays a canned report, so a test can
# assert BOTH what was submitted (one request, never one per point) and what came back.
STUB_KLT = """#!/usr/bin/env python3
import json, os, shutil, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("klt 9.9.9-stub")
    sys.exit(0)
assert args[0] == "sim"
open(os.environ["STUB_KLT_LOG"], "a").write(json.dumps(args) + "\\n")
if os.environ.get("STUB_KLT_FAIL"):
    sys.stderr.write('{"error": {"code": "batch_no_capacity", "message": "fleet refused the job"}}\\n')
    sys.exit(2)
req = json.loads(open(args[1]).read())
outdir = args[args.index("-o") + 1]
units = []
for deck in req["decks"]:
    d = os.path.join(outdir, deck["id"])
    os.makedirs(d, exist_ok=True)
    # Replay the deck and its shipped .spiceinit into the unit's stdout, so a test can
    # assert the engine saw what the request declared.
    init = ""
    for inp in deck.get("inputs", []):
        src = os.path.join(os.path.dirname(args[1]), inp["path"])
        if os.path.isfile(src):
            init = open(src).read()
    solver = "SPARSE 1.3" if "\\n* option klu" in init else "KLU"
    body = os.environ.get("STUB_KLT_STDOUT", "").replace("@SOLVER@", solver)
    open(os.path.join(d, "stdout.bin"), "w").write(body)
    open(os.path.join(d, "stderr.bin"), "w").write("")
    units.append({"id": deck["id"], "status": "pass", "exit_code": 0, "timed_out": False,
                  "stdout": deck["id"] + "/stdout.bin", "stderr": deck["id"] + "/stderr.bin",
                  "engine_version": "47", "diagnostics": []})
json.dump({"schema_version": 3, "mode": "decks", "status": "pass", "unit_count": len(units),
           "passed": len(units), "errored": 0, "timed_out": 0, "units": units,
           "outdir": os.path.abspath(outdir),
           "environment": {"engine": "ngspice", "engine_version": "47", "klt_version": "9.9.9-stub",
                           "engine_host": "worker",
                           "remote": {"provider": "aws-batch-fleet", "job_id": "job-deck-1",
                                      "region": "us-east-1", "instance_type": "c7i.8xlarge",
                                      "state": "done", "runner_klt_version": "0.9.0-runner",
                                      "runner_request_features": {"required": ["decks"],
                                                                  "missing": [], "status": "supported"}}}},
          sys.stdout)
"""


def load(path: Path, name: str):
    """Import a `run_*.py` whose filename is not an identifier-friendly module name."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


OP = load(REPO / "sim" / "bias-core-op-branch" / "run_op_branch.py", "run_op_branch_mod")
PNP = load(REPO / "sim" / "pnp-mismatch" / "run_pnp_mismatch.py", "run_pnp_mismatch_mod")


def make_pdk() -> "cr.Pdk":
    root = Path("/nonexistent/pdk-root")
    return cr.Pdk(pin=PIN, root=root, variant="sky130A", dir=root / "sky130A",
                  installed_commit=PINNED, lib_file=root / "sky130A" / PIN["ngspice_lib"])


def op_args(**kw) -> argparse.Namespace:
    return argparse.Namespace(timeout=600, max_workers=8, wait_for_capacity=600, **kw)


# ---------------------------------------------------------------------------
# request construction
# ---------------------------------------------------------------------------


class DeckRequestShape(unittest.TestCase):
    def test_deck_request_declares_no_corner_fields(self):
        req = sim_common.deck_request([{"id": "u", "deck": "u/deck.spice"}], "batch", timeout_s=42,
                                      capacity_wait_s=600, max_workers=8)
        # klt rejects a document declaring both shapes by name, so the two must not mix.
        for forbidden in ("netlist", "corners", "analysis", "measurements", "monte_carlo"):
            self.assertNotIn(forbidden, req)
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["models"], {"pdk": "sky130A"})
        self.assertEqual(req["options"], {"timeout_s": 42, "max_workers": 8})
        self.assertEqual(req["batch"], {"runner_version_check": "warn", "capacity_wait_s": 600})

    def test_local_backend_carries_no_batch_block(self):
        req = sim_common.deck_request([{"id": "u", "deck": "u/deck.spice"}], "local", timeout_s=42)
        self.assertNotIn("batch", req)

    def test_model_lib_is_spelled_for_the_runner_not_this_host(self):
        # A shipped deck is never rewritten: an absolute path under the SUBMITTING host's
        # own PDK root is refused by klt rather than retargeted at the runner's.
        self.assertEqual(sim_common.runner_lib_ref(),
                         "$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice")


class OpBranchRequest(unittest.TestCase):
    def setUp(self):
        self.points = OP.build_points(quick=True)
        self.body = ["* body", "R1 VDD 0 1k"]
        self.req, self.files = OP.build_request(self.points, self.body, make_pdk(), "batch", op_args())

    def test_one_request_covers_every_point(self):
        self.assertEqual(len(self.req["decks"]), len(self.points))
        self.assertEqual([u["id"] for u in self.req["decks"]], [p.point_id for p in self.points])

    def test_every_unit_ships_its_own_spiceinit_as_an_input(self):
        for unit in self.req["decks"]:
            self.assertEqual(unit["inputs"], [{"path": f"units/{unit['id']}/spiceinit",
                                               "name": ".spiceinit"}])
            self.assertIn(unit["inputs"][0]["path"], self.files)
            self.assertIn(unit["deck"], self.files)

    def test_sparse_variant_disables_klu_in_its_shipped_spiceinit(self):
        # The one setting that cannot travel any other way: the fleet runner ignores
        # options.ngspice_init, and `klu` is not in klt's ngspice_options allow-list.
        sparse = self.files["units/sweep-sparse_tt_27c_2.97v/spiceinit"]
        klu = self.files["units/sweep-klu_tt_27c_2.97v/spiceinit"]
        self.assertIn("* option klu", sparse)
        self.assertIn("DISABLED by", sparse)
        self.assertNotIn("\n* option klu", klu)
        self.assertIn("option klu", klu)

    def test_variant_options_and_nodeset_reach_the_deck(self):
        srcstep = self.files["units/variant-srcstep_tt_27c_2.97v/deck.spice"]
        nodeset = self.files["units/variant-nodeset_tt_27c_2.97v/deck.spice"]
        self.assertIn(".option gminsteps=0", srcstep)
        self.assertIn(".nodeset v(vref)=1.25", nodeset)
        self.assertNotIn(".nodeset", srcstep)

    def test_deck_names_the_runner_resolved_library(self):
        deck = self.files["units/sweep-klu_tt_27c_2.97v/deck.spice"]
        self.assertIn('.lib "$PDK_ROOT/sky130A/libs.tech/combined/sky130.lib.spice" tt', deck)
        self.assertNotIn("/nonexistent/pdk-root", deck)

    def test_the_three_determinism_repeats_are_byte_identical_decks(self):
        # A corner grid cannot express "run this identical point three times"; the deck
        # list can, and the control check depends on the decks really being identical.
        decks = {self.files[f"units/control-repeat{i}_tt_27c_2.97v/deck.spice"] for i in (1, 2, 3)}
        self.assertEqual(len(decks), 3)  # they differ only in the `* point:` comment
        bodies = {"\n".join(ln for ln in d.splitlines() if not ln.startswith("* point:"))
                  for d in decks}
        self.assertEqual(len(bodies), 1)


class PnpRequest(unittest.TestCase):
    def setUp(self):
        self.points = PNP.build_points(20)
        args = argparse.Namespace(timeout=3600, max_workers=6, wait_for_capacity=600)
        self.req, self.files = PNP.build_request(self.points, make_pdk(), "batch", args)

    def test_one_request_covers_all_six_points(self):
        self.assertEqual(len(self.req["decks"]), 6)
        self.assertEqual([u["id"] for u in self.req["decks"]], [p.corner_id for p in self.points])

    def test_testbench_is_shipped_byte_for_byte(self):
        # Method preservation (issue #319 risk item 2): the in-deck `.control` Monte
        # Carlo loop is the sampling method the existing record was minted by, so the
        # deck must cross to the fleet unmodified rather than become a monte_carlo block.
        shipped = self.files["units/tt_mm_27c_nosupply/tb_pnp_mismatch.spice"]
        self.assertEqual(shipped, PNP.DECK.read_text())
        self.assertIn("dowhile run < nruns", shipped)
        self.assertNotIn("monte_carlo", json.dumps(self.req))

    def test_seed_and_sample_count_ride_in_the_shipped_spiceinit(self):
        a = self.files["units/tt_mm_27c_nosupply/spiceinit"]
        b = self.files["units/tt_mm_27c_nosupply_seed-b/spiceinit"]
        self.assertIn("set mc_seed=20260825", a)
        self.assertIn("set mc_runs=20", a)
        self.assertIn("set mc_seed=20260826", b)
        # ...and the deck reads exactly those two variable names.
        self.assertIn("$?mc_seed", PNP.DECK.read_text())
        self.assertIn("$?mc_runs", PNP.DECK.read_text())

    def test_each_section_gets_its_own_corner_shim(self):
        sections = {u: self.files[f"units/{u}/corner.spice"] for u in
                    ("tt_mm_27c_nosupply", "tt_27c_nosupply_mm-off", "mc_27c_nosupply")}
        self.assertIn('" tt_mm\n', sections["tt_mm_27c_nosupply"])
        self.assertIn('" tt\n', sections["tt_27c_nosupply_mm-off"])
        self.assertIn('" mc\n', sections["mc_27c_nosupply"])
        for text in sections.values():
            self.assertIn("$PDK_ROOT/sky130A/", text)
            self.assertNotIn("/nonexistent/pdk-root", text)


# ---------------------------------------------------------------------------
# report mapping
# ---------------------------------------------------------------------------


class ReportMapping(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-report-"))
        (self.tmp / "u1").mkdir()
        (self.tmp / "u1" / "stdout.bin").write_bytes(b"vref = 1.25\n\xff bad utf8\nngspice-47 done\n")
        (self.tmp / "u1" / "stderr.bin").write_bytes(b"warn\n")
        self.report = {"outdir": str(self.tmp), "units": [
            {"id": "u1", "status": "pass", "exit_code": 0, "timed_out": False,
             "stdout": "u1/stdout.bin", "stderr": "u1/stderr.bin"}]}

    def test_streams_are_concatenated_and_decoded_leniently(self):
        unit = sim_common.deck_units(self.report)["u1"]
        raw = sim_common.deck_streams(self.report, unit)
        self.assertIn("vref = 1.25", raw)
        self.assertTrue(raw.endswith("warn\n"))  # stdout then stderr, as the local path read them
        self.assertEqual(sim_common.fleet_ngspice(raw), "ngspice-47")

    def test_deck_units_is_empty_for_a_non_deck_report(self):
        self.assertEqual(sim_common.deck_units({"corners": []}), {})
        self.assertEqual(sim_common.deck_units(None), {})

    def test_missing_unit_fails_the_point_instead_of_dropping_it(self):
        point = OP.build_points(quick=True)[0]
        res = OP.result_from_unit(point, "* deck", self.report, None)
        self.assertEqual(res["rc"], -1)
        self.assertIn("no unit in the klt deck report", res["raw"])
        self.assertFalse(OP.evaluate(res)["pass"])

    def test_log_solver_reads_the_engine_banner(self):
        self.assertEqual(sim_common.log_solver("Using KLU as Direct Linear Solver"), "KLU")
        self.assertEqual(sim_common.log_solver("Using SPARSE 1.3 as Direct Linear Solver"), "SPARSE 1.3")
        self.assertIsNone(sim_common.log_solver("no banner here"))


class SolverCrossCheck(unittest.TestCase):
    """`solver_variant_reached[...]` is what makes a silently-dropped `.spiceinit`
    setting fail the record instead of being recorded as a variant nobody ran."""

    def results(self, klu_solver, sparse_solver):
        out = []
        for variant, solver in (("klu", klu_solver), ("sparse", sparse_solver)):
            for supply in (2.97, 3.63):
                out.append({"point_id": f"sweep-{variant}_tt_27c_{supply:.2f}v", "role": "sweep",
                            "variant": variant, "supply_v": supply, "temperature_c": 27.0,
                            "branch": "good", "vref": 1.25, "isup": 1e-6, "solver": solver,
                            "checks": [], "pass": True})
        return out

    def check(self, results, name):
        return next(c for c in OP.cross_checks(results) if c["name"] == name)

    def test_passes_when_each_variant_ran_under_its_declared_solver(self):
        good = self.results("KLU", "SPARSE 1.3")
        self.assertTrue(self.check(good, "solver_variant_reached[klu]")["pass"])
        self.assertTrue(self.check(good, "solver_variant_reached[sparse]")["pass"])

    def test_fails_when_the_sparse_variant_silently_ran_under_klu(self):
        # i.e. the shipped .spiceinit was dropped: both variants are then the SAME run,
        # and `solver_dependence` below would be comparing a variant against itself.
        bad = self.results("KLU", "KLU")
        self.assertFalse(self.check(bad, "solver_variant_reached[sparse]")["pass"])
        self.assertTrue(self.check(bad, "solver_variant_reached[klu]")["pass"])

    def test_fails_when_no_solver_was_announced_at_all(self):
        self.assertFalse(self.check(self.results(None, None), "solver_variant_reached[klu]")["pass"])


# ---------------------------------------------------------------------------
# submit, with a stubbed klt
# ---------------------------------------------------------------------------


class SubmitWithStubbedKlt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-submit-"))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        klt = bindir / "klt"
        klt.write_text(STUB_KLT)
        klt.chmod(klt.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "klt.log"
        self.saved_env = dict(os.environ)
        os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        os.environ["STUB_KLT_LOG"] = str(self.log)
        os.environ["STUB_KLT_STDOUT"] = (
            "Using @SOLVER@ as Direct Linear Solver\nvref = 1.25\n-i(v1) = 1e-06\nngspice-47 done\n"
        )
        os.environ.pop("STUB_KLT_FAIL", None)
        self.points = OP.build_points(quick=True)
        self.req, self.files = OP.build_request(self.points, ["* body"], make_pdk(), "batch", op_args())

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def submit(self):
        d = self.tmp / "run" / "batch"
        return d, sim_common.submit_prepared(
            d, None, self.req, "msg", "label", files=self.files)

    def test_one_submit_for_the_whole_grid_not_one_per_point(self):
        d, outcome = self.submit()
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        self.assertEqual(outcome["exit"], 0)
        self.assertFalse((d / "netlist.spice").exists())  # a deck request has no netlist
        self.assertTrue((d / "request.json").is_file())
        for unit in self.req["decks"]:
            self.assertTrue((d / unit["deck"]).is_file())
            self.assertTrue((d / unit["inputs"][0]["path"]).is_file())

    def test_shipped_spiceinit_reaches_the_engine_per_variant(self):
        # The stub reports the solver its unit's own .spiceinit selected, so this asserts
        # the end-to-end path the real fleet run demonstrates: request -> staged input ->
        # engine -> log -> record check.
        d, _ = self.submit()
        report = json.loads((d / "report.json").read_text())
        units = sim_common.deck_units(report)
        results = [OP.evaluate(OP.result_from_unit(p, "", report, units.get(p.point_id)))
                   for p in self.points]
        by_variant = {}
        for r in results:
            by_variant.setdefault(r["variant"], set()).add(r["solver"])
        self.assertEqual(by_variant["klu"], {"KLU"})
        self.assertEqual(by_variant["sparse"], {"SPARSE 1.3"})
        for name in ("solver_variant_reached[klu]", "solver_variant_reached[sparse]"):
            self.assertTrue(next(c for c in OP.cross_checks(results) if c["name"] == name)["pass"])

    def test_refusal_is_recorded_verbatim_and_never_retried_locally(self):
        os.environ["STUB_KLT_FAIL"] = "1"
        d, outcome = self.submit()
        self.assertNotEqual(outcome["exit"], 0)
        self.assertEqual(sim_common.deck_units(json.loads((d / "report.json").read_text() or "{}")), {})
        self.assertIn("batch_no_capacity", (d / "klt.stderr").read_text())
        self.assertEqual(len(self.log.read_text().splitlines()), 1)  # no second path tried

    def test_pnp_submit_is_also_one_request(self):
        points = PNP.build_points(5)
        args = argparse.Namespace(timeout=3600, max_workers=6, wait_for_capacity=600)
        req, files = PNP.build_request(points, make_pdk(), "batch", args)
        d = self.tmp / "pnp" / "batch"
        sim_common.submit_prepared(d, None, req, "msg", "label", files=files)
        self.assertEqual(len(self.log.read_text().splitlines()), 1)
        report = json.loads((d / "report.json").read_text())
        self.assertEqual(len(sim_common.deck_units(report)), 6)


if __name__ == "__main__":
    unittest.main()
