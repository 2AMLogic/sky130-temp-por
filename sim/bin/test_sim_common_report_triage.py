#!/usr/bin/env python3
"""Tests for the shared per-request report triage (issue #322). Stdlib only, no SPICE.

Every campaign grader starts its request loop the same way: read this request's
``report.json``, or record why it cannot be graded, then copy the fleet job fields
into the request record.  Six hand copies had drifted -- three wordings for a
missing report, two for a report without corners, stderr-tail caps of 500/600/800,
and two copies that dropped ``client_klt_version`` so their records could not show a
client-versus-runner klt version skew.  These tests pin the consolidated behaviour.

Run: python3 -I sim/bin/test_sim_common_report_triage.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_common as sc  # noqa: E402


def _request(td: str, *, report: str | None = None, stderr: str | None = None) -> Path:
    d = Path(td) / "build" / "tt" / "r1"
    d.mkdir(parents=True, exist_ok=True)
    if report is not None:
        (d / "report.json").write_text(report)
    if stderr is not None:
        (d / "klt.stderr").write_text(stderr)
    return d


class LoadRequestReportTest(unittest.TestCase):
    def test_no_report_is_not_submitted(self):
        """The `NOT SUBMITTED` prefix is load-bearing: test_solver_sensitivity.py asserts on it."""
        with tempfile.TemporaryDirectory() as td:
            d = _request(td)
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "NOT SUBMITTED / no report")
            self.assertEqual(why, sc.NOT_SUBMITTED)
            self.assertTrue(sc.NOT_SUBMITTED.startswith("NOT SUBMITTED"))

    def test_missing_request_dir_is_not_submitted(self):
        """A request whose directory was never created is still just "not submitted"."""
        with tempfile.TemporaryDirectory() as td:
            rep, why = sc.load_request_report(Path(td) / "never", Path(td), Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "NOT SUBMITTED / no report")

    def test_unparseable_report_reports_the_stderr_tail(self):
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report="not json at all", stderr="klt: submit failed: boom\n")
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "NO JSON (klt failed before a report existed): klt: submit failed: boom\n")

    def test_unparseable_report_with_no_stderr_does_not_raise(self):
        """klt can refuse before writing either file; the old copies read klt.stderr unguarded."""
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report="{")
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "NO JSON (klt failed before a report existed): ")

    def test_report_without_corners_reports_the_error_message(self):
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report=json.dumps({"error": {"message": "batch_no_capacity"}}))
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "klt error (no corners reported): batch_no_capacity")

    def test_report_without_corners_or_error_falls_back_to_the_whole_report(self):
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report=json.dumps({"status": "fail"}))
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(rep)
            self.assertIn("'status': 'fail'", why)

    def test_good_report_returns_the_report_and_no_reason(self):
        with tempfile.TemporaryDirectory() as td:
            body = {"status": "ok", "corner_count": 2, "corners": [{"process": "tt"}, {"process": "ss"}]}
            d = _request(td, report=json.dumps(body))
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(why)
            self.assertEqual(rep, body)

    def test_empty_corners_list_is_still_gradeable(self):
        """The predicate is `"corners" in rep`, matching report_usable() on the retry path."""
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report=json.dumps({"status": "ok", "corners": []}))
            rep, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIsNone(why)
            self.assertEqual(rep["corners"], [])

    def test_agrees_with_report_usable(self):
        """The two predicates must never disagree: one grades, the other decides a retry."""
        for body in ('{"corners": []}', '{"status": "fail"}', "not json", None):
            with tempfile.TemporaryDirectory() as td:
                d = _request(td, report=body)
                rep, _ = sc.load_request_report(d, Path(td) / "build", Path(td))
                self.assertEqual(rep is not None, sc.report_usable(d / "report.json"), body)

    def test_stderr_tail_is_scrubbed_and_capped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "build"
            noise = "x" * 900
            d = _request(td, report="{", stderr=f"{noise}\ndeck {run_dir}/tt/r1/netlist.spice failed")
            _, why = sc.load_request_report(d, run_dir, Path(td))
            tail = why[len("NO JSON (klt failed before a report existed): "):]
            self.assertLessEqual(len(tail), sc.TRIAGE_CAP)
            self.assertIn("<build>/tt/r1/netlist.spice", tail)
            self.assertNotIn(str(run_dir), tail)

    def test_error_message_is_scrubbed_and_capped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "build"
            msg = f"deck {run_dir}/tt/r1/netlist.spice rejected: " + "y" * 900
            d = _request(td, report=json.dumps({"error": {"message": msg}}))
            _, why = sc.load_request_report(d, run_dir, Path(td))
            body = why[len("klt error (no corners reported): "):]
            # The cap bounds the raw message; scrubbing then shortens it further, since
            # it replaces an absolute build path with "<build>".  Both copies capped
            # before scrubbing, so the bound is on what is read, not on what is stored.
            self.assertLess(len(body), sc.TRIAGE_CAP)
            self.assertTrue(body.endswith("y"))  # truncated mid-run, no trailing text
            self.assertIn("<build>/tt/r1/netlist.spice", body)
            self.assertNotIn(str(run_dir), body)

    def test_home_directory_is_scrubbed(self):
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report=json.dumps({"error": {"message": "/home/someone/pdk missing"}}))
            _, why = sc.load_request_report(d, Path(td) / "build", Path(td))
            self.assertIn("<home>/pdk missing", why)

    def test_cap_is_overridable(self):
        with tempfile.TemporaryDirectory() as td:
            d = _request(td, report=json.dumps({"error": {"message": "z" * 900}}))
            _, why = sc.load_request_report(d, Path(td) / "build", Path(td), cap=50)
            self.assertEqual(why, "klt error (no corners reported): " + "z" * 50)


class FleetJobFieldsTest(unittest.TestCase):
    REMOTE = {"job_id": "klt-sim-abc", "instance_type": "c7a.2xlarge", "lifecycle": "spot",
              "runner_klt_version": "0.9.1", "client_klt_version": "0.8.0",
              "elapsed_seconds": 412, "state": "SUCCEEDED"}

    def test_every_shared_key_is_recorded(self):
        rep = {"status": "ok", "corner_count": 45, "environment": {"remote": dict(self.REMOTE)}}
        got = sc.fleet_job_fields(rep)
        self.assertEqual(got, {**self.REMOTE, "corner_count": 45, "outcome": "ok"})

    def test_client_klt_version_is_always_present(self):
        """Thresholds and the re-assertion diagnosis dropped it, so their records could
        not show a client-versus-runner klt version skew the other four could."""
        rep = {"status": "ok", "environment": {"remote": dict(self.REMOTE)}}
        self.assertEqual(sc.fleet_job_fields(rep)["client_klt_version"], "0.8.0")
        self.assertIn("client_klt_version", sc.FLEET_JOB_KEYS)

    def test_version_skew_is_visible(self):
        rep = {"status": "ok", "environment": {"remote": {"runner_klt_version": "0.9.1", "client_klt_version": "0.8.0"}}}
        got = sc.fleet_job_fields(rep)
        self.assertNotEqual(got["runner_klt_version"], got["client_klt_version"])

    def test_shape_is_constant_when_the_fleet_reported_nothing(self):
        """Keys are recorded as None, never dropped: a record's shape never varies."""
        for rep in ({}, {"environment": {}}, {"environment": {"remote": None}}, {"environment": None}):
            got = sc.fleet_job_fields(rep)
            self.assertEqual(set(got), set(sc.FLEET_JOB_KEYS) | {"corner_count", "outcome"}, rep)
            self.assertTrue(all(v is None for v in got.values()), rep)

    def test_a_local_run_without_a_remote_section_is_not_an_error(self):
        rep = {"status": "ok", "corner_count": 1, "corners": [{}]}
        got = sc.fleet_job_fields(rep)
        self.assertEqual(got["outcome"], "ok")
        self.assertEqual(got["corner_count"], 1)
        self.assertIsNone(got["job_id"])

    def test_unknown_remote_keys_are_not_copied(self):
        """The key list is closed: a new klt field does not silently enter every record."""
        rep = {"status": "ok", "environment": {"remote": {"job_id": "j", "surprise": "nope"}}}
        self.assertNotIn("surprise", sc.fleet_job_fields(rep))


if __name__ == "__main__":
    unittest.main()
