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
capfail = os.environ.get("STUB_KLT_CAPFAIL")
if capfail:
    n = int(open(capfail).read().strip() or "0")
    if n < int(os.environ.get("STUB_KLT_CAPFAIL_TIMES", "1")):
        open(capfail, "w").write(str(n + 1))
        sys.stderr.write(json.dumps({"error": {"message": "launch refused: BATCH_MAX_CONCURRENT_INSTANCES cap reached"}}) + "\\n")
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
            [m["name"] for m in req["measurements"]],
            [cr.MEAS_PREFIX + m.name for m in self.exp.measurements],
        )
        self.assertNotIn("spice", req["measurements"][0])  # `expr` form: .meas cannot do op

    def test_explicit_point_list_is_not_a_grid(self):
        subset = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", -40.0, 2.97), cr.Corner("ff", 125.0, 3.63)]
        with self.assertRaises(cr.HarnessError) as raised:
            cr.batch_axes(subset)
        msg = str(raised.exception)
        # the diagnostic names the required cross product (3 x 3 x 3 = 27)...
        self.assertIn("3 process", msg)
        self.assertIn("3 temperature", msg)
        self.assertIn("3 supply", msg)
        self.assertIn("27 corners", msg)
        # ...and no longer advises `--backend local`, which a grid refuses
        self.assertNotIn("--backend local", msg)

    def test_batch_netlist_leaves_lib_temp_and_supply_to_klt(self):
        text = cr.build_batch_netlist(self.exp, ["V1 VDD 0 'vsup'", "R1 VDD 0 1k"], self.matrix)
        self.assertIn(".param vsup=3.3", text)
        self.assertIn(".option wnflag=1", text)
        cards = [ln.split()[0].lower() for ln in text.splitlines() if ln and not ln.startswith("*")]
        self.assertNotIn(".lib", cards)
        self.assertNotIn(".temp", cards)
        self.assertTrue(text.rstrip().endswith(".end"))
        # neither klt backend honors options.ngspice_init and neither stages
        # sim/spiceinit, so the netlist itself carries a `set ng_nomodcheck`
        # control block or native-device decks abort on the BSIM parameter check
        self.assertIn("set ng_nomodcheck", text)


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

    def test_request_carries_capacity_wait_and_zero_disables_it(self):
        req = cr.build_batch_request(self.exp, make_pdk(), self.matrix, 300, capacity_wait_s=600)
        self.assertEqual(req["batch"]["capacity_wait_s"], 600)
        req0 = cr.build_batch_request(self.exp, make_pdk(), self.matrix, 300)
        self.assertNotIn("capacity_wait_s", req0["batch"])

    def test_default_wait_for_capacity_is_600(self):
        self.assertEqual(cr.parse_args([]).wait_for_capacity, 600.0)

    def test_concurrency_cap_refusal_is_a_single_klt_run(self):
        counter = self.tmp / "capfail-noretry.count"
        counter.write_text("0")
        os.environ["STUB_KLT_CAPFAIL"] = str(counter)
        with self.assertRaises(cr.HarnessError):
            cr.submit_batch(
                self.exp, self.matrix, "* netlist\n.end\n",
                self.request(), self.tmp / "run-noretry",
            )
        self.assertEqual(len(self.log.read_text().splitlines()), 1)  # one refusal, no retry

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

    # ------------------------------------------------------------------
    # a multi-sweep experiment submits one fleet job per sweep (issue #327)
    # ------------------------------------------------------------------

    def two_sweep_fleet(self, commit1, commit2):
        """Submit twice through the real `submit_batch`, each report stamped by its own
        runner, and fold them the way `main()` does."""
        subs = []
        for i, commit in enumerate((commit1, commit2), start=1):
            rep = fake_report(self.matrix, fleet_commit=commit)
            rep["environment"]["remote"]["job_id"] = f"job-{i}"
            rep["environment"]["engine_version"] = f"4{i}"
            Path(os.environ["STUB_KLT_REPORT"]).write_text(json.dumps(rep))
            _, info = cr.submit_batch(
                self.exp, self.matrix, "* netlist\n.end\n", self.request(),
                self.tmp / "run", subdir=f"batch-sweep{i}",
            )
            subs.append((f"batch-sweep{i}", info))
        return cr.merge_fleet(subs)

    def multi_record(self, fleet):
        rec = self.minimal_record(fleet, fleet_commit=PINNED)
        pdk = {"variant": "sky130A", **fleet["pdk"]}
        pdk.update(cr.fleet_pdk_block(fleet["pdk_commits"], LOCAL_COMMIT, PIN))
        rec["pdk"] = pdk
        rec["tools"]["ngspice"] = fleet["ngspice"]
        return rec

    def test_an_off_pin_second_sweep_makes_the_record_a_mismatch(self):
        fleet = self.two_sweep_fleet(PINNED, "0" * 40)
        rec = self.multi_record(fleet)
        self.assertEqual(rec["pdk"]["fleet_matches_pin"], "mismatch")
        self.assertIs(rec["pdk"]["matches_pin"], False)
        self.assertIn("0" * 40, rec["pdk"]["installed_commit"])
        self.assertIn(PINNED, rec["pdk"]["installed_commit"])
        self.assertIn("MISMATCH", cr.render_record(rec))

    def test_an_unstamped_first_sweep_does_not_hide_an_off_pin_second(self):
        fleet = self.two_sweep_fleet("unknown", "0" * 40)
        self.assertEqual(
            cr.fleet_pdk_block(fleet["pdk_commits"], LOCAL_COMMIT, PIN)["fleet_matches_pin"],
            "mismatch",
        )

    def test_both_sweeps_on_pin_keep_every_submissions_provenance(self):
        fleet = self.two_sweep_fleet(PINNED, PINNED)
        rec = self.multi_record(fleet)
        self.assertEqual(rec["pdk"]["fleet_matches_pin"], "match")
        self.assertEqual(rec["pdk"]["installed_commit"], PINNED)
        subs = rec["batch"]["submissions"]
        self.assertEqual([x["job_id"] for x in subs], ["job-1", "job-2"])
        for x in subs:
            self.assertEqual(x["installed_commit"], PINNED)
            self.assertEqual(x["models_lib_sha256"], "ab" * 32)
            self.assertEqual(x["remote"]["runner_klt_version"], "0.7.1-runner")
        self.assertEqual(rec["tools"]["ngspice"], "ngspice 41 (fleet) / ngspice 42 (fleet)")
        text = cr.render_record(rec)
        self.assertIn("Fleet submissions (one per sweep)", text)
        self.assertIn("job-1", text)
        self.assertIn("job-2", text)
        self.assertIn(f"open_pdks {PINNED}", text.split("Fleet submissions")[1])

    def test_fleet_pdk_block_takes_one_commit_or_many(self):
        self.assertEqual(cr.fleet_pdk_block(PINNED, LOCAL_COMMIT, PIN)["fleet_matches_pin"], "match")
        self.assertEqual(
            cr.fleet_pdk_block([PINNED, "0" * 40], LOCAL_COMMIT, PIN)["fleet_matches_pin"], "mismatch"
        )

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


ALL_EXPERIMENTS = [
    "bias-core-smoke", "bias-core-startup", "temp-core-startup",
    "temp-core-startup-en-delayed", "native-device-characterization",
    "por-output-chain-deglitch",
]


def unit_report(exp, unit, matrix, supply_key="va", param=None, drop=None, decoys=()):
    """A klt report for one sweep unit: every owned measurement mid-window, so a
    value that lands in the wrong place or goes missing changes the grade."""
    corners = []
    for c in matrix:
        if c.id == drop:
            continue
        ms = []
        for m in unit.measurements:
            lo = m.min if m.min is not None else 0.0
            hi = m.max if m.max is not None else lo + 1.0
            ms.append({"name": cr.MEAS_PREFIX + m.name, "value": (lo + hi) / 2, "unit": m.unit})
        ms += [{"name": cr.MEAS_PREFIX + n, "value": v, "unit": ""} for n, v in decoys]
        row = {
            "process": c.process, "temperature_c": c.temp_c, "status": "pass",
            "runtime_s": 1.0, "measurements": ms, "diagnostics": [],
        }
        if param:
            row["params"] = {param: c.supply_v}
        else:
            row["supply_v"] = {supply_key: c.supply_v}
        corners.append(row)
    return {"status": "pass", "corners": corners}


class AllManifestsBuildRequests(unittest.TestCase):
    """Issue #327: every corner-runner manifest becomes a runnable klt request."""

    def test_every_manifest_builds_a_request_for_its_full_matrix(self):
        for slug in ALL_EXPERIMENTS:
            exp = cr.load_experiment(REPO / "sim" / slug)
            matrix = full_matrix(exp)
            units = cr.sweep_units(exp)
            self.assertTrue(units, slug)
            for unit in units:
                req = cr.build_batch_request(exp, make_pdk(), matrix, 300, unit=unit)
                self.assertEqual(req["backend"], "batch", slug)
                self.assertEqual(req["analysis"]["kind"], unit.analysis.split()[0], slug)
                for m in req["measurements"]:
                    self.assertTrue(m["name"].startswith(cr.MEAS_PREFIX), (slug, m["name"]))
                    self.assertNotRegex(m["expr"], r"\bnlast\b|\bdc\d+\.", (slug, m["expr"]))

    def test_local_request_is_the_same_request_without_the_batch_block(self):
        exp = cr.load_experiment(REPO / "sim" / "temp-core-startup")
        point = [cr.Corner("tt", 27.0, 3.3)]
        fleet = cr.build_batch_request(exp, make_pdk(), point, 300, 600)
        local = cr.build_batch_request(exp, make_pdk(), point, 300, 600, backend="local")
        self.assertEqual(local["backend"], "local")
        self.assertNotIn("batch", local)
        fleet.pop("batch"), fleet.pop("backend"), local.pop("backend")
        self.assertEqual(fleet, local)

    def test_measurement_names_cannot_shadow_circuit_nodes(self):
        # klt runs `let <name> = <expr>` in the node-vector plot; an unprefixed
        # `ptat` would replace v(ptat) with a scalar and zero every later guard.
        exp = cr.load_experiment(REPO / "sim" / "temp-core-startup")
        req = cr.build_batch_request(exp, make_pdk(), full_matrix(exp), 300)
        names = {m["name"] for m in req["measurements"]}
        self.assertIn("meas_ptat", names)
        self.assertNotIn("ptat", names)

    def test_startup_helper_is_inlined_at_every_use(self):
        exp = cr.load_experiment(REPO / "sim" / "temp-core-startup")
        req = cr.build_batch_request(exp, make_pdk(), full_matrix(exp), 300)
        by = {m["name"]: m["expr"] for m in req["measurements"]}
        self.assertEqual(by["meas_ptat"], "v(ptat)[(length(v(ptat))-1)]")
        self.assertEqual(
            by["meas_ptat_settled"],
            "abs(v(ptat)[(length(v(ptat))-1)] - v(ptat)[(length(v(ptat))-1)-100])",
        )

    def test_helper_substitution_keeps_multiplication_grouping(self):
        # a helper used multiplicatively must stay grouped when inlined:
        # `nlast*2` is `(length(v(x))-1)*2`, not `length(v(x))-1*2` (= length-2)
        self.assertEqual(
            cr.request_expr("nlast*2", {"nlast": "length(v(x))-1"}),
            "(length(v(x))-1)*2",
        )
        # an index helper in brackets keeps working with the grouping too
        self.assertEqual(
            cr.request_expr("v(x)[nlast-100]", {"nlast": "length(v(x))-1"}),
            "v(x)[(length(v(x))-1)-100]",
        )

    def test_startup_supply_is_a_parameter_axis_at_both_ends_of_the_range(self):
        for slug in ("bias-core-startup", "temp-core-startup", "temp-core-startup-en-delayed"):
            exp = cr.load_experiment(REPO / "sim" / slug)
            req = cr.build_batch_request(exp, make_pdk(), full_matrix(exp), 300)
            self.assertEqual(req["corners"]["params"], {"vsup": [2.97, 3.3, 3.63]}, slug)
            self.assertNotIn("supply_v", req["corners"], slug)  # an alter cannot move a PWL source
            for end in (2.97, 3.63):
                one = cr.build_batch_request(exp, make_pdk(), [cr.Corner("tt", 27.0, end)], 300)
                self.assertEqual(one["corners"]["params"], {"vsup": [end]}, slug)
            text = cr.build_batch_netlist(
                exp, ["V1 VDD 0 PWL(0 0 'tramp' 'vsup' 'tstop' 'vsup')"], full_matrix(exp)
            )
            self.assertIn(".param vsup=3.3", text)  # the param the axis re-points


class NativeTwoSweeps(unittest.TestCase):
    def setUp(self):
        self.exp = cr.load_experiment(REPO / "sim" / "native-device-characterization")
        self.matrix = full_matrix(self.exp)
        self.units = cr.sweep_units(self.exp)
        self.out = REPO / "sim" / "native-device-characterization" / "corners" / "TEST"

    def test_each_sweep_is_its_own_request_with_its_own_measurements(self):
        self.assertEqual([u.analysis for u in self.units], ["dc vg -1.0 2.0 0.001", "dc vsw 0 3.63 0.001"])
        reqs = [cr.build_batch_request(self.exp, make_pdk(), self.matrix, 300, unit=u) for u in self.units]
        vg, vsw = ({m["name"] for m in r["measurements"]} for r in reqs)
        self.assertEqual(vg, {"meas_vth_n05l25", "meas_vth_n05l8", "meas_vth_n03l08"})
        self.assertFalse(vg & vsw)
        self.assertEqual(len(vg) + len(vsw), len(self.exp.measurements))
        for r in reqs:
            self.assertEqual(r["corners"]["supply_v"], {"va": [2.97, 3.3, 3.63]})

    def reports(self, **kw):
        return [(u, unit_report(self.exp, u, self.matrix, **kw)) for u in self.units]

    def test_join_is_by_corner_not_by_report_order(self):
        reports = self.reports()
        for _, rep in reports:
            rep["corners"].reverse()
        reports[1][1]["corners"].sort(key=lambda c: (c["temperature_c"], c["process"]))
        results = cr.results_from_reports(self.exp, self.matrix, reports, self.out, 300)
        self.assertEqual(len(results), 45)
        self.assertTrue(all(r["pass"] for r in results), [r["corner_id"] for r in results if not r["pass"]])

    def test_measurement_ownership_is_enforced_on_the_report(self):
        # a sweep-2 report that also carries a wild vth value must not be graded
        reports = [(u, unit_report(self.exp, u, self.matrix, decoys=[("vth_n05l25", 99.0)] if i else ()))
                   for i, u in enumerate(self.units)]
        results = cr.results_from_reports(self.exp, self.matrix, reports, self.out, 300)
        self.assertTrue(all(r["pass"] for r in results))

    def test_a_dropped_sweep_result_fails_that_corner_only(self):
        victim = self.matrix[11].id
        reports = [self.reports()[0], (self.units[1], unit_report(self.exp, self.units[1], self.matrix, drop=victim))]
        results = cr.results_from_reports(self.exp, self.matrix, reports, self.out, 300)
        self.assertEqual([r["corner_id"] for r in results if not r["pass"]], [victim])
        bad = next(r for r in results if r["corner_id"] == victim)
        self.assertIn("sweep2=missing", bad["batch_status"])
        self.assertTrue(any("not reported" in c["reason"] for c in bad["measurements"]))

    def test_a_missing_required_measurement_cannot_pass(self):
        reports = self.reports()
        for c in reports[0][1]["corners"]:
            c["measurements"] = c["measurements"][1:]  # drop vth_n05l25 everywhere
        results = cr.results_from_reports(self.exp, self.matrix, reports, self.out, 300)
        self.assertFalse(any(r["pass"] for r in results))


class BackendSelection(unittest.TestCase):
    def ns(self, **kw):
        base = dict(quick=False, backend="auto")
        base.update(kw)
        return argparse.Namespace(**base)

    def test_auto_sends_a_grid_to_the_fleet_and_one_point_to_local(self):
        grid = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", 27.0, 3.3)]
        self.assertEqual(cr.resolve_backend(self.ns(), grid), "batch")
        self.assertEqual(cr.resolve_backend(self.ns(), grid[:1]), "local")
        self.assertEqual(cr.resolve_backend(self.ns(backend="batch"), grid), "batch")

    def test_quick_is_always_local(self):
        pts = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ff", 125.0, 3.63)]
        self.assertEqual(cr.resolve_backend(self.ns(quick=True), pts), "local")
        self.assertEqual(cr.resolve_backend(self.ns(quick=True, backend="local"), pts), "local")

    def test_explicit_local_grid_is_refused_with_a_pointer_to_the_fleet(self):
        grid = [cr.Corner("tt", 27.0, 3.3), cr.Corner("ss", 27.0, 3.3)]
        with self.assertRaises(cr.HarnessError) as ctx:
            cr.resolve_backend(self.ns(backend="local"), grid)
        self.assertIn("--backend batch", str(ctx.exception))
        self.assertEqual(cr.resolve_backend(self.ns(backend="local"), grid[:1]), "local")

    def test_default_backend_is_auto_not_local(self):
        self.assertEqual(cr.parse_args([]).backend, "auto")


class StopAfterSimulation(Exception):
    pass


class CliDispatch(unittest.TestCase):
    """`main()` routes the selection to the right backend, once per request, and a
    refused local grid launches nothing. The simulators are fakes that count calls;
    evidence storage aborts the run before anything is written."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="corner-run-dispatch-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.exp_dir = root / "experiment"
        self.exp_dir.mkdir()
        manifest = json.loads((EXPERIMENT / "experiment.json").read_text())
        manifest["schematic"] = "tb.sch"
        (self.exp_dir / "experiment.json").write_text(json.dumps(manifest))
        (self.exp_dir / "tb.sch").write_text("v {xschem}\n")
        self.batch_calls, self.local_calls, self.netlists = [], [], []

        def fake_netlist(schematic, out_dir, pdk):
            self.netlists.append(schematic)
            out_dir.mkdir(parents=True, exist_ok=True)
            f = out_dir / "tb.spice"
            f.write_text("V1 VDD 0 'vsup'\nR1 VDD 0 1k\n.end\n")
            return f

        def fake_batch(exp, matrix, netlist, request, run_dir, subdir="batch"):
            self.batch_calls.append((list(matrix), request))
            return fake_report(matrix), {
                "pdk": {"installed_commit": PINNED, "lib_file": "x"}, "ngspice": "ngspice (fleet)",
                "batch": {"job_id": "j", "status": "pass", "runner_klt": "r", "fleet_pdk_version": "v"},
            }

        def fake_local(exp, pdk, corner, netlist, request, run_dir, subdir):
            self.local_calls.append((corner, request))
            return fake_report([corner])

        def stop(*a, **k):
            raise StopAfterSimulation()

        for patch in (
            mock.patch.object(cr, "datetime", FixedDatetime),
            mock.patch.object(cr, "git_state", lambda: {"sha": "deadbee", "branch": "t", "dirty": False}),
            mock.patch.object(cr, "resolve_pdk", lambda pin: make_pdk()),
            mock.patch.object(cr, "REPO_ROOT", root),
            mock.patch.object(cr, "BUILD_DIR", root / "build"),
            mock.patch.object(cr, "netlist_with_klt", fake_netlist),
            mock.patch.object(cr, "submit_batch", fake_batch),
            mock.patch.object(cr, "run_local", fake_local),
            mock.patch.object(evidence_store, "STAGE_ROOT", root / ".stage"),
            mock.patch.object(evidence_store, "MANIFEST_DIR", root / ".manifests"),
            mock.patch.object(evidence_store, "preflight", lambda: None),
            mock.patch.object(evidence_store, "store_run", stop),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def run_main(self, *argv):
        with self.assertRaises(StopAfterSimulation):
            cr.main([str(self.exp_dir), *argv])

    def test_bare_invocation_is_one_fleet_submission_and_no_local_run(self):
        self.run_main()
        self.assertEqual(len(self.batch_calls), 1)
        self.assertEqual(len(self.batch_calls[0][0]), 45)
        self.assertEqual(self.local_calls, [])

    def test_a_single_selected_point_is_one_local_run(self):
        self.run_main("--process", "tt", "--temp", "27", "--supply", "3.3", "--subset-reason", "probe")
        self.assertEqual(self.batch_calls, [])
        self.assertEqual([c.id for c, _ in self.local_calls], ["tt_27c_3.30v"])
        self.assertEqual(self.local_calls[0][1]["backend"], "local")

    def test_quick_visits_exactly_the_listed_points_in_order(self):
        exp = json.loads((self.exp_dir / "experiment.json").read_text())
        want = [cr.Corner(p, float(t), float(v)).id for p, t, v in exp["quick_subset"]]
        self.run_main("--quick", "--subset-reason", "liveness")
        self.assertEqual([c.id for c, _ in self.local_calls], want)
        self.assertEqual(self.batch_calls, [])

    def test_a_multi_point_selection_without_backend_goes_to_the_fleet(self):
        self.run_main("--process", "tt,ss", "--subset-reason", "two processes")
        self.assertEqual(len(self.batch_calls), 1)
        self.assertEqual(self.local_calls, [])

    def test_explicit_local_grid_is_refused_before_anything_launches(self):
        with self.assertRaises(cr.HarnessError) as ctx:
            cr.main([str(self.exp_dir), "--backend", "local"])
        self.assertIn("--backend batch", str(ctx.exception))
        self.assertEqual((self.batch_calls, self.local_calls, self.netlists), ([], [], []))

    def test_subset_reason_is_still_required(self):
        with self.assertRaises(cr.HarnessError):
            cr.main([str(self.exp_dir), "--process", "tt"])
        self.assertEqual((self.batch_calls, self.local_calls), ([], []))

    def test_dry_run_prints_requests_and_submits_nothing(self):
        with mock.patch("builtins.print") as out:
            self.assertEqual(cr.main([str(self.exp_dir), "--dry-run"]), 0)
        text = "\n".join(str(c.args[0]) for c in out.call_args_list if c.args)
        self.assertIn("klt sim request", text)
        self.assertEqual((self.batch_calls, self.local_calls), ([], []))
        self.assertFalse((self.exp_dir / "records").exists())

    def test_fleet_submit_errors_surface_verbatim(self):
        def boom(*a, **k):
            raise cr.HarnessError("batch submit produced no usable report: batch_no_capacity")
        with mock.patch.object(cr, "submit_batch", boom):
            with self.assertRaises(cr.HarnessError) as ctx:
                cr.main([str(self.exp_dir)])
        self.assertIn("batch_no_capacity", str(ctx.exception))
        self.assertEqual(self.local_calls, [])


if __name__ == "__main__":
    unittest.main()
