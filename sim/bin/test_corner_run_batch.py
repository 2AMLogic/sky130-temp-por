#!/usr/bin/env python3
"""Batch-backend tests for corner-run.py (issue #219). Stdlib only, no SPICE, no PDK.

`klt` is a stub executable on PATH: it answers `--version` and `sim` the way the
real verb's outputs are shaped, so request construction, report-to-result
mapping, record rendering and the no-local-fallback failure path are all
exercised without a fleet.

Run: python3 -I -m unittest sim/bin/test_corner_run_batch.py
 or: python3 -m pytest sim/bin/
"""
from __future__ import annotations

import argparse
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
EXPERIMENT = REPO / "sim" / "bias-core-smoke"

STUB_KLT = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("klt 9.9.9-stub")
    sys.exit(0)
assert args[0] == "sim" and "--backend" in args and args[args.index("--backend") + 1] == "batch"
open(os.environ["STUB_KLT_LOG"], "a").write(json.dumps(args) + "\\n")
if os.environ.get("STUB_KLT_FAIL"):
    sys.stderr.write("batch_no_capacity: fleet refused the job\\n")
    sys.exit(2)
sys.stdout.write(open(os.environ["STUB_KLT_REPORT"]).read())
"""


def make_pdk() -> "cr.Pdk":
    root = Path("/nonexistent/pdk-root")
    return cr.Pdk(
        pin=PIN,
        root=root,
        variant="sky130A",
        dir=root / "sky130A",
        installed_commit=PINNED,
        lib_file=root / "sky130A" / PIN["ngspice_lib"],
    )


def full_matrix(exp):
    args = argparse.Namespace(quick=False, process=None, temp=None, supply=None)
    matrix, is_subset = cr.build_matrix(exp, args, PIN)
    assert not is_subset
    return matrix


def fake_report(matrix, vref=1.25, fleet_commit=PINNED, drop=None):
    corners = []
    for c in matrix:
        if c.id == drop:
            continue
        corners.append(
            {
                "corner_id": f"{c.process}/{c.supply_v:.3f}V/{c.temp_c:g}C",
                "process": c.process,
                "supply_v": {"v1": c.supply_v},
                "temperature_c": c.temp_c,
                "status": "pass",
                "runtime_s": 1.5,
                "measurements": [
                    {"name": "vref", "value": vref + 0.001 * c.temp_c / 100, "unit": "V"},
                    {"name": "ibias", "value": c.supply_v, "unit": "V"},
                    {"name": "bias_ok", "value": c.supply_v, "unit": "V"},
                    {"name": "isup", "value": 1e-6, "unit": "A"},
                ],
                "diagnostics": [],
            }
        )
    return {
        "status": "pass",
        "corners": corners,
        "environment": {
            "engine": "ngspice",
            "engine_version": "42",
            "models_lib_sha256": "ab" * 32,
            "remote": {
                "job_id": "job-123",
                "runner_klt_version": "0.7.1-runner",
                "worker_environment": {
                    "pdk": {"variant": "sky130A", "stamp_text": f"open_pdks {fleet_commit}"}
                },
            },
        },
        "provenance": {
            "klt_version": "0.7.1-runner",
            "pdk": {"name": "sky130A", "version": f"open_pdks {PINNED}"},  # client side
        },
    }


class RequestConstruction(unittest.TestCase):
    def setUp(self):
        self.exp = cr.load_experiment(EXPERIMENT)
        self.matrix = full_matrix(self.exp)

    def test_request_spans_all_45_corners_as_one_grid(self):
        req = cr.build_batch_request(self.exp, make_pdk(), self.matrix, 300)
        c = req["corners"]
        self.assertEqual(len(self.matrix), 45)
        self.assertEqual(
            len(c["process"]) * len(c["temperature_c"]) * len(c["supply_v"]["v1"]), 45
        )
        self.assertEqual(c["process"], ["tt", "ss", "ff", "sf", "fs"])
        self.assertEqual(req["backend"], "batch")
        self.assertEqual(req["analysis"], {"kind": "op", "args": ""})
        self.assertEqual(req["options"]["timeout_s"], 300)
        self.assertEqual(
            [m["name"] for m in req["measurements"]], [m.name for m in self.exp.measurements]
        )
        self.assertNotIn("spice", req["measurements"][0])  # `expr` form: .meas cannot do op

    def test_explicit_point_list_is_not_a_grid(self):
        subset = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", -40.0, 2.97), cr.Corner("ff", 125.0, 3.63)]
        with self.assertRaises(cr.HarnessError):
            cr.batch_axes(subset)

    def test_batch_netlist_leaves_lib_temp_and_supply_to_klt(self):
        text = cr.build_batch_netlist(self.exp, ["V1 VDD 0 'vsup'", "R1 VDD 0 1k"], self.matrix)
        self.assertIn(".param vsup=3.3", text)
        self.assertIn(".option wnflag=1", text)
        cards = [ln.split()[0].lower() for ln in text.splitlines() if ln and not ln.startswith("*")]
        self.assertNotIn(".lib", cards)
        self.assertNotIn(".temp", cards)
        self.assertTrue(text.rstrip().endswith(".end"))


class ReportMapping(unittest.TestCase):
    def setUp(self):
        self.exp = cr.load_experiment(EXPERIMENT)
        self.matrix = full_matrix(self.exp)
        self.corners_dir = REPO / "sim" / "bias-core-smoke" / "corners" / "TEST"

    def test_results_have_the_local_schema_and_apply_manifest_limits(self):
        report = fake_report(self.matrix)
        results = cr.results_from_report(self.exp, self.matrix, report, self.corners_dir, 300)
        self.assertEqual(len(results), 45)
        self.assertTrue(all(r["pass"] for r in results))
        local_keys = {
            "corner_id", "process", "temperature_c", "supply_v", "ngspice_exit", "timed_out",
            "killed_by_signal", "killed_by_signal_name", "elapsed_s", "timeout_s",
            "measurements", "pass", "log",
        }
        self.assertTrue(local_keys <= set(results[0]))
        out_of_window = fake_report(self.matrix, vref=2.0)
        bad = cr.results_from_report(self.exp, self.matrix, out_of_window, self.corners_dir, 300)
        self.assertFalse(any(r["pass"] for r in bad))
        self.assertIn("above max", bad[0]["measurements"][0]["reason"])

    def test_corner_missing_from_report_fails_not_passes(self):
        missing = self.matrix[7].id
        report = fake_report(self.matrix, drop=missing)
        results = cr.results_from_report(self.exp, self.matrix, report, self.corners_dir, 300)
        failed = [r["corner_id"] for r in results if not r["pass"]]
        self.assertEqual(failed, [missing])

    def test_fleet_pdk_commit_parsing(self):
        self.assertEqual(cr.fleet_pdk_commit(f"open_pdks {PINNED}"), PINNED)
        self.assertEqual(cr.fleet_pdk_commit("something else"), "unknown")


class SubmitWithStubbedKlt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="corner-run-batch-"))
        bindir = self.tmp / "bin"
        bindir.mkdir()
        klt = bindir / "klt"
        klt.write_text(STUB_KLT)
        klt.chmod(klt.stat().st_mode | stat.S_IXUSR)
        self.log = self.tmp / "klt.log"
        self.exp = cr.load_experiment(EXPERIMENT)
        self.matrix = full_matrix(self.exp)
        self.saved_env = dict(os.environ)
        os.environ["PATH"] = f"{bindir}{os.pathsep}{os.environ['PATH']}"
        os.environ["STUB_KLT_LOG"] = str(self.log)
        report = self.tmp / "report.json"
        report.write_text(json.dumps(fake_report(self.matrix)))
        os.environ["STUB_KLT_REPORT"] = str(report)
        os.environ.pop("STUB_KLT_FAIL", None)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved_env)

    def request(self):
        return cr.build_batch_request(self.exp, make_pdk(), self.matrix, 300)

    def test_submit_records_fleet_provenance(self):
        report, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        self.assertEqual(len(report["corners"]), 45)
        self.assertEqual(fleet["pdk"]["installed_commit"], PINNED)
        self.assertEqual(fleet["batch"]["job_id"], "job-123")
        self.assertEqual(fleet["batch"]["klt_client"], "klt 9.9.9-stub")
        self.assertEqual(len(self.log.read_text().splitlines()), 1)  # one grid request, not 45
        self.assertTrue((self.tmp / "run" / "batch" / "request.json").is_file())

    def test_submit_failure_is_reported_verbatim_without_local_fallback(self):
        os.environ["STUB_KLT_FAIL"] = "1"
        with self.assertRaises(cr.HarnessError) as ctx:
            cr.submit_batch(
                self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
            )
        self.assertIn("batch_no_capacity: fleet refused the job", str(ctx.exception))
        self.assertIn("not falling back to a local grid", str(ctx.exception))
        self.assertEqual(len(self.log.read_text().splitlines()), 1)  # no retry via another path

    def test_runner_pdk_stamp_wins_over_client_side_provenance(self):
        report = fake_report(self.matrix, fleet_commit="c" * 40)
        Path(os.environ["STUB_KLT_REPORT"]).write_text(json.dumps(report))
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        self.assertEqual(fleet["pdk"]["installed_commit"], "c" * 40)
        self.assertIn("c" * 40, fleet["batch"]["fleet_pdk_version"])

    def test_runner_without_pdk_stamp_is_unknown_not_pinned(self):
        report = fake_report(self.matrix)
        del report["environment"]["remote"]["worker_environment"]
        Path(os.environ["STUB_KLT_REPORT"]).write_text(json.dumps(report))
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        self.assertEqual(fleet["pdk"]["installed_commit"], "unknown")

    def test_render_record_cites_fleet_backend_and_flags_pdk_mismatch(self):
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        record = self.minimal_record(fleet, fleet_commit="0" * 40)
        text = cr.render_record(record)
        self.assertIn("klt sim --backend batch", text)
        self.assertIn("job-123", text)
        self.assertIn("MISMATCH", text)
        record_ok = self.minimal_record(fleet, fleet_commit=PINNED)
        self.assertIn("matches sim/pdk.json pin", cr.render_record(record_ok))

    def minimal_record(self, fleet, fleet_commit):
        results = cr.results_from_report(
            self.exp, self.matrix, fake_report(self.matrix), EXPERIMENT / "corners" / "TEST", 300
        )
        pdk = {"variant": "sky130A", **fleet["pdk"], "installed_commit": fleet_commit}
        pdk["matches_pin"] = fleet_commit == PINNED
        return {
            "record_id": "TEST",
            "timestamp": "2026-10-23T00:00:00Z",
            "author": "test",
            "supersedes": "",
            "experiment": {
                "slug": "bias-core-smoke", "title": "t", "claim": "c",
                "provenance": "schematic", "provenance_source": "x",
                "statistical_convention": "N/A",
            },
            "pdk": pdk,
            "tools": {"ngspice": fleet["ngspice"], "xschem": "x", "platform": "p", "python": "3"},
            "git": {"sha": "abc", "branch": "b", "dirty": False},
            "matrix": {
                "process": ["tt"], "temperature_c": [27.0], "supply_v": [3.3], "n_points": 1,
                "is_subset": False, "subset_reason": "", "point_ids": ["tt_27c_3.30v"],
            },
            "corners": results[:1],
            "spread_checks": [],
            "overall_pass": True,
            "links": {k: "x" for k in ("testbench", "netlist_snapshot", "corners_dir", "json", "manifest")},
            "backend": "batch",
            "batch": fleet["batch"],
        }


if __name__ == "__main__":
    unittest.main()
