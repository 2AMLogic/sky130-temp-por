#!/usr/bin/env python3
"""Tests for the shared per-request report triage (issue #322). Stdlib only, no SPICE.

Every campaign grader starts its request loop the same way: read this request's
``report.json``, or record why it cannot be graded, then copy the fleet job fields
into the request record.  Six hand copies had drifted -- three wordings for a
missing report, two for a report without corners, stderr-tail caps of 500/600/800,
and two copies that dropped ``client_klt_version`` so their records could not show a
client-versus-runner klt version skew.  These tests pin the consolidated behaviour.

Issue #530 adds the documents that parse as JSON but are not an object (``[]``,
``null``, a string, a number, a boolean): ``submit_prepared`` raised from ``.get()``
after saving the diagnostic it was about to lose, and the retry predicate accepted
``"corners"`` and ``["corners"]``.

Run: python3 -I sim/bin/test_sim_common_report_triage.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


# klt stdout that is valid JSON but not an object.  ``klt sim --format json`` prints an
# object, so these are the tail of the "malformed output drops the fleet diagnostic"
# class rather than an observed fleet failure (issue #530).
NON_OBJECT_STDOUT = ("[]", "null", '"x"', "42", "false", '"corners"', '["corners"]')
NO_JSON = "NO JSON (klt failed before a report existed): "
STDERR = "klt: submit failed: the fleet diagnostic\n"


def _mock_submit(td: str, stdout: str, stderr: str = STDERR) -> tuple[Path, Path, dict]:
    """One mocked exit-2 ``klt sim`` through ``submit_prepared``: ``(d, run_dir, summary)``.

    Fails the test unless klt ran exactly once.
    """
    run_dir = Path(td) / "build"
    d = run_dir / "tt" / "r1"
    klt = subprocess.CompletedProcess(["klt", "sim"], 2, stdout=stdout, stderr=stderr)
    with mock.patch.object(sc.subprocess, "run", return_value=klt) as run:
        with mock.patch.object(sc, "say"):  # the [submit]/[done] lines are noise here
            summary = sc.submit_prepared(d, "* netlist\n.end\n", {}, "msg", "label")
    if run.call_count != 1:
        raise AssertionError(f"klt ran {run.call_count} times; expected exactly one submission")
    return d, run_dir, summary


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
        cases = [('{"corners": []}', True), ('{"status": "fail"}', False), ("not json", False), (None, False)]
        cases += [(body, False) for body in NON_OBJECT_STDOUT]
        for body, usable in cases:
            with tempfile.TemporaryDirectory() as td:
                d = _request(td, report=body)
                rep, _ = sc.load_request_report(d, Path(td) / "build", Path(td))
                self.assertEqual(rep is not None, sc.report_usable(d / "report.json"), body)
                self.assertEqual(sc.report_usable(d / "report.json"), usable, body)

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


class NonObjectReportTest(unittest.TestCase):
    """The three helpers, driven from one mocked submission and its saved output.

    A real run meets the saved stdout in that order: ``submit_prepared`` writes
    ``report.json``/``klt.stderr``, a grader triages them through
    ``load_request_report``, and ``report_usable`` decides a retry.  Before issue
    #530 the first raised ``AttributeError`` from ``.get()`` on a list, a string or
    ``None`` -- after writing both files, so no caller reached its post-submit
    check -- and the third raised ``TypeError`` on ``null`` and a number while
    accepting ``"corners"`` and ``["corners"]``.
    """

    def test_submit_returns_the_exit_code_and_no_json_for_every_non_object(self):
        for stdout in NON_OBJECT_STDOUT:
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as td:
                d, _, summary = _mock_submit(td, stdout)
                self.assertEqual(summary, {"exit": 2, "status": "NO-JSON"})
                self.assertEqual((d / "report.json").read_text(), stdout)  # saved verbatim
                self.assertEqual((d / "klt.stderr").read_text(), STDERR)

    def test_malformed_stdout_control(self):
        """The non-object cases are held to what unparseable text always did."""
        with tempfile.TemporaryDirectory() as td:
            d, _, summary = _mock_submit(td, "not json at all")
            self.assertEqual(summary, {"exit": 2, "status": "NO-JSON"})
            self.assertEqual((d / "report.json").read_text(), "not json at all")
            self.assertEqual((d / "klt.stderr").read_text(), STDERR)

    def test_an_object_supplies_its_own_status(self):
        for stdout, status in (('{"status": "fail"}', "fail"), ("{}", "?")):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as td:
                self.assertEqual(_mock_submit(td, stdout)[2], {"exit": 2, "status": status})

    def test_saved_non_object_report_triages_like_malformed_json(self):
        """Grading, retry and the submission agree with the malformed-text control."""
        with tempfile.TemporaryDirectory() as td:
            control, run_dir, _ = _mock_submit(td, "not json at all")
            expected = sc.load_request_report(control, run_dir, Path(td))[1]
            self.assertEqual(expected, NO_JSON + STDERR)
        for stdout in NON_OBJECT_STDOUT:
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as td:
                d, run_dir, summary = _mock_submit(td, stdout)
                rep, why = sc.load_request_report(d, run_dir, Path(td))
                self.assertEqual(summary["status"], "NO-JSON")
                self.assertIsNone(rep)
                self.assertEqual(why, expected)  # the same stderr, so the same reason
                self.assertFalse(sc.report_usable(d / "report.json"))

    def test_non_object_stderr_tail_is_scrubbed_and_capped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td) / "build"
            noise = "x" * 900
            d, _, _ = _mock_submit(td, "[]", stderr=f"{noise}\ndeck {run_dir}/tt/r1/netlist.spice failed")
            _, why = sc.load_request_report(d, run_dir, Path(td))
            tail = why[len(NO_JSON):]
            self.assertLessEqual(len(tail), sc.TRIAGE_CAP)
            self.assertIn("<build>/tt/r1/netlist.spice", tail)
            self.assertNotIn(str(run_dir), tail)

    def test_non_object_without_stderr_does_not_raise(self):
        """klt can refuse before writing either file; the tail is read only when it exists."""
        with tempfile.TemporaryDirectory() as td:
            d, run_dir, _ = _mock_submit(td, "null", stderr="")
            (d / "klt.stderr").unlink()
            self.assertEqual(sc.load_request_report(d, run_dir, Path(td)), (None, NO_JSON))

    def test_an_object_with_empty_corners_still_qualifies(self):
        body = {"status": "ok", "corners": []}
        with tempfile.TemporaryDirectory() as td:
            d, run_dir, summary = _mock_submit(td, json.dumps(body))
            self.assertEqual(summary, {"exit": 2, "status": "ok"})
            self.assertEqual(sc.load_request_report(d, run_dir, Path(td)), (body, None))
            self.assertTrue(sc.report_usable(d / "report.json"))

    def test_an_object_without_corners_keeps_its_own_reason(self):
        """An object without corners is klt's own refusal: it keeps its reason, not the stderr tail."""
        with tempfile.TemporaryDirectory() as td:
            d, run_dir, summary = _mock_submit(td, '{"status": "fail"}')
            self.assertEqual(summary["status"], "fail")
            rep, why = sc.load_request_report(d, run_dir, Path(td))
            self.assertIsNone(rep)
            self.assertEqual(why, "klt error (no corners reported): " + "{'status': 'fail'}")
            self.assertFalse(sc.report_usable(d / "report.json"))

    def test_a_missing_report_is_still_not_submitted(self):
        with tempfile.TemporaryDirectory() as td:
            d, run_dir, _ = _mock_submit(td, "[]")
            (d / "report.json").unlink()
            self.assertEqual(sc.load_request_report(d, run_dir, Path(td)), (None, sc.NOT_SUBMITTED))
            self.assertFalse(sc.report_usable(d / "report.json"))


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
