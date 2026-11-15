#!/usr/bin/env python3
"""Batch-backend tests for corner-run.py (issue #219). Stdlib only, no SPICE, no PDK.

`klt` is a stub executable on PATH: it answers `--version` and `sim` the way the
real verb's outputs are shaped, so request construction, report-to-result
mapping, record rendering and the no-local-fallback failure path are all
exercised without a fleet.

Run: python3 -I sim/bin/test_corner_run_batch.py
 or: python3 -m pytest sim/bin/
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parent
REPO = BIN.parent.parent
sys.path.insert(0, str(BIN))

import sim_common  # noqa: E402
import evidence_store  # noqa: E402

cr = sim_common.load_corner_run()

PIN = cr.load_pin()
PINNED = PIN["open_pdks_commit"]
LOCAL_COMMIT = "e" * 40          # this host's own install, parked on a batch record
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


class FixedDatetime(datetime):
    """`datetime` whose `now()` is frozen, so `main()`'s record id is deterministic."""

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


# Child interpreter for the end-to-end collision check: fakes the PDK away,
# freezes the clock and the git state, then lets `main()` hit the guard with
# SystemExit uncaught so the process exit status is the real one.
COLLISION_CHILD = """\
import sys
from datetime import datetime, timezone
from pathlib import Path

BIN = Path(sys.argv[1])
sys.path.insert(0, str(BIN))
import sim_common

cr = sim_common.load_corner_run()
pin = cr.load_pin()
fake_root = Path("/nonexistent/pdk-root")
cr.resolve_pdk = lambda p: cr.Pdk(
    pin=p, root=fake_root, variant=pin["variant"], dir=fake_root / pin["variant"],
    installed_commit=pin["open_pdks_commit"],
    lib_file=fake_root / pin["variant"] / pin["ngspice_lib"],
)

class FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

cr.datetime = FixedDatetime
cr.git_state = lambda: {"sha": "deadbee", "branch": "test", "dirty": False}
cr.main([sys.argv[2]])
"""


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

    # ------------------------------------------------------------------
    # issue #333: an UNSTAMPED fleet run is not a mismatch
    # ------------------------------------------------------------------
    #
    # `fleet_pdk_commit()` returns the string `"unknown"` when the runner's stamp carries
    # no 40-hex commit, and this path used to compare that against the pin with `!=`.  So
    # a fleet run that simply never said what it ran was recorded as
    # `**MISMATCH vs sim/pdk.json pin**` and reported as one on stderr.  These assert the
    # three states are distinguishable in BOTH the JSON field and the rendered text.

    def test_an_unreported_runner_commit_is_not_reported_not_a_mismatch(self):
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        record = self.minimal_record(fleet, fleet_commit="unknown")
        self.assertEqual(record["pdk"]["fleet_matches_pin"], "not-reported")
        self.assertIs(record["pdk"]["matches_pin"], False)  # still not a pass
        text = cr.render_record(record)
        self.assertNotIn("MISMATCH", text)
        self.assertNotIn("matches sim/pdk.json pin", text)
        self.assertIn(sim_common.fleet_pin_state("not-reported"), text)

    def test_the_three_batch_pin_states_are_distinct_in_field_and_text(self):
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        want = {PINNED: "match", "0" * 40: "mismatch", "unknown": "not-reported"}
        rendered = {}
        for commit, verdict in want.items():
            rec = self.minimal_record(fleet, fleet_commit=commit)
            self.assertEqual(rec["pdk"]["fleet_matches_pin"], verdict, commit)
            # the host's own install is kept, never overwritten by the fleet's
            self.assertEqual(rec["pdk"]["local_installed_commit"], LOCAL_COMMIT)
            rendered[verdict] = cr.render_record(rec).splitlines()
        pdk_lines = {v: next(l for l in ls if l.startswith("- **PDK**")) for v, ls in rendered.items()}
        self.assertEqual(len(set(pdk_lines.values())), 3, pdk_lines)
        self.assertIn("MISMATCH", pdk_lines["mismatch"])
        for v in ("match", "not-reported"):
            self.assertNotIn("MISMATCH", pdk_lines[v], v)

    def test_a_batch_record_states_what_an_equal_commit_does_not_establish(self):
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        limit = self.minimal_record(fleet, fleet_commit=PINNED)["pdk"]["fleet_pin_limit"]
        self.assertEqual(limit, sim_common.PIN_COMMIT_LIMIT)
        self.assertIn("not proof", limit)

    def test_an_unstamped_report_flows_into_the_not_reported_verdict(self):
        """Not a hand-set `"unknown"`: the whole path from a report with no
        `worker_environment` through to the verdict."""
        report = fake_report(self.matrix)
        del report["environment"]["remote"]["worker_environment"]
        Path(os.environ["STUB_KLT_REPORT"]).write_text(json.dumps(report))
        _, fleet = cr.submit_batch(
            self.exp, self.matrix, "* netlist\n.end\n", self.request(), self.tmp / "run"
        )
        self.assertEqual(fleet["pdk"]["installed_commit"], "unknown")
        block = cr.fleet_pdk_block(fleet["pdk"]["installed_commit"], LOCAL_COMMIT, PIN)
        self.assertEqual(block["fleet_matches_pin"], "not-reported")

    def minimal_record(self, fleet, fleet_commit):
        results = cr.results_from_report(
            self.exp, self.matrix, fake_report(self.matrix), EXPERIMENT / "corners" / "TEST", 300
        )
        pdk = {"variant": "sky130A", **fleet["pdk"], "installed_commit": fleet_commit}
        pdk.update(cr.fleet_pdk_block(fleet_commit, LOCAL_COMMIT, PIN))
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
            "links": {k: "x" for k in ("testbench", "netlist_snapshot", "corners_dir", "json", "manifest", "artifact_manifest", "artifact_summary")},
            "backend": "batch",
            "batch": fleet["batch"],
        }


class RefuseExistingHelper(unittest.TestCase):
    """Net-new coverage for `sim_common.refuse_existing` (issue #369): the helper
    is the append-only refusal for sim/ evidence at 13 call sites and had none."""

    def test_a_collision_aborts_naming_that_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing = Path(tmp) / "rec.md"
            existing.write_text("prior evidence\n")
            with self.assertRaises(SystemExit) as ctx:
                sim_common.refuse_existing((existing, Path(tmp) / "rec.json"))
            self.assertEqual(str(ctx.exception), f"{existing} exists -- sim/ is append-only")

    def test_no_collision_returns_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = (Path(tmp) / "rec.md", Path(tmp) / "rec.json")
            self.assertIsNone(sim_common.refuse_existing(paths))


class WriteSelftestRecordCollision(unittest.TestCase):
    """`write_selftest_record` used to raise a pathless `record exists --
    append-only`, so an operator could not tell whether the `.md` or the `.json`
    was in the way (issue #369). The refusal must name the colliding path and
    write nothing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="selftest-record-")
        self.addCleanup(self.tmp.cleanup)
        self.rec_dir = Path(self.tmp.name) / "records"
        self.rec_dir.mkdir()

    def test_existing_md_names_the_md_and_writes_nothing(self):
        existing = self.rec_dir / "REC.md"
        existing.write_text("prior record\n")
        with self.assertRaises(SystemExit) as ctx:
            sim_common.write_selftest_record(self.rec_dir, "REC", {"record_id": "REC"}, ["- line"])
        self.assertEqual(str(ctx.exception), f"{existing} exists -- sim/ is append-only")
        self.assertFalse((self.rec_dir / "REC.json").exists())

    def test_json_only_collision_names_the_json_the_old_message_could_not(self):
        existing = self.rec_dir / "REC.json"
        existing.write_text("{}\n")
        with self.assertRaises(SystemExit) as ctx:
            sim_common.write_selftest_record(self.rec_dir, "REC", {"record_id": "REC"}, ["- line"])
        self.assertEqual(str(ctx.exception), f"{existing} exists -- sim/ is append-only")
        self.assertFalse((self.rec_dir / "REC.md").exists())

    def test_a_clean_record_still_writes_both_files(self):
        sim_common.write_selftest_record(
            self.rec_dir, "REC", {"record_id": "REC"}, ["# REC", "- line"]
        )
        self.assertEqual(json.loads((self.rec_dir / "REC.json").read_text()), {"record_id": "REC"})
        self.assertEqual((self.rec_dir / "REC.md").read_text(), "# REC\n- line")


class MainRecordCollision(unittest.TestCase):
    """`main()`'s five-path append-only guard now routes through
    `sim_common.refuse_existing` (issue #369): a collision aborts with
    SystemExit naming the path -- not a HarnessError with the old wording --
    before anything is written under sim/.

    The experiment lives in a tmp dir (a copy of bias-core-smoke's manifest with
    an absolute schematic path), and the evidence-store roots are repointed
    there too, so no repo path is ever created.
    """

    REC_ID = "20260101-120000-deadbee"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="corner-run-collision-")
        self.addCleanup(self.tmp.cleanup)
        self.exp_dir = Path(self.tmp.name) / "experiment"
        self.exp_dir.mkdir()
        manifest = json.loads((EXPERIMENT / "experiment.json").read_text())
        manifest["schematic"] = str(EXPERIMENT / manifest["schematic"])
        (self.exp_dir / "experiment.json").write_text(json.dumps(manifest))
        # Deterministic record id: frozen clock, frozen git sha, fake PDK pinned
        # to the pin (matches_pin -> True, no --allow-pdk-mismatch needed).
        for patch in (
            mock.patch.object(cr, "datetime", FixedDatetime),
            mock.patch.object(cr, "git_state",
                              lambda: {"sha": "deadbee", "branch": "test", "dirty": False}),
            mock.patch.object(cr, "resolve_pdk", lambda pin: make_pdk()),
            mock.patch.object(evidence_store, "STAGE_ROOT", self.exp_dir / ".stage"),
            mock.patch.object(evidence_store, "MANIFEST_DIR", self.exp_dir / ".manifests"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def guarded_paths(self):
        exp = cr.load_experiment(self.exp_dir)
        return {
            "record_md": exp.dir / "records" / f"{self.REC_ID}.md",
            "record_json": exp.dir / "records" / f"{self.REC_ID}.json",
            "snapshot": exp.dir / "netlist-snapshots" / f"{self.REC_ID}.spice",
            "stage_dir": evidence_store.stage_dir_for(exp.slug, self.REC_ID),
            "artifact_manifest": evidence_store.manifest_path(exp.slug, self.REC_ID),
        }

    def place(self, colliding, as_dir=False):
        colliding.parent.mkdir(parents=True, exist_ok=True)
        if as_dir:
            colliding.mkdir()
            (colliding / "staged-bytes").write_text("raw log\n")
        else:
            colliding.write_text("prior evidence\n")

    def assert_refusal(self, colliding):
        self.place(colliding)
        with self.assertRaises(SystemExit) as ctx:
            cr.main([str(self.exp_dir)])
        self.assertEqual(str(ctx.exception), f"{colliding} exists -- sim/ is append-only")

    def test_existing_record_md_refuses_and_names_the_md(self):
        self.assert_refusal(self.guarded_paths()["record_md"])

    def test_existing_record_json_without_md_refuses_and_names_the_json(self):
        self.assert_refusal(self.guarded_paths()["record_json"])

    def test_existing_netlist_snapshot_refuses_and_names_the_snapshot(self):
        self.assert_refusal(self.guarded_paths()["snapshot"])

    def test_existing_stage_dir_refuses_and_names_the_dir(self):
        self.assert_refusal(self.guarded_paths()["stage_dir"])

    def test_existing_artifact_manifest_refuses_and_names_the_manifest(self):
        self.assert_refusal(self.guarded_paths()["artifact_manifest"])

    def test_collision_exits_status_1_from_a_real_process(self):
        # End-to-end: the guard's SystemExit carries a string code, which the
        # interpreter turns into exit status 1 with the message on stderr.
        # Assert that real exit status from a child interpreter rather than
        # assuming it from the exception type.
        existing = self.guarded_paths()["record_md"]
        self.place(existing)
        proc = subprocess.run(
            [sys.executable, "-I", "-c", COLLISION_CHILD, str(BIN), str(self.exp_dir)],
            capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(proc.returncode, 1, proc.stderr)
        self.assertIn(f"{existing} exists -- sim/ is append-only", proc.stderr)


if __name__ == "__main__":
    unittest.main()
