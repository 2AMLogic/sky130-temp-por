#!/usr/bin/env python3
"""Tests for the shared archived-attempt reader (issue #293). Stdlib only, no SPICE.

``cap_retry`` archives each refused submit as ``attemptN/report.json`` (klt's stdout)
plus ``attemptN/klt.stderr``, and klt writes its JSON error envelope to *stderr* when
it refuses before producing a report.  Every campaign runner used to carry its own
reader of those directories; the copies had drifted apart (three read only
``report.json``, five sorted lexically).  These tests pin the consolidated behaviour.

Run: python3 -I sim/bin/test_sim_common_attempts.py
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_common as sc  # noqa: E402

CAP_MSG = "8 instance(s) already running + 1 requested exceeds BATCH_MAX_CONCURRENT_INSTANCES=8"


def _attempt(d: Path, n: int, report: str | None = None, stderr: str | None = None) -> Path:
    ad = d / f"attempt{n}"
    ad.mkdir(parents=True, exist_ok=True)
    if report is not None:
        (ad / "report.json").write_text(report)
    if stderr is not None:
        (ad / "klt.stderr").write_text(stderr)
    return ad


class AttemptMessagesTest(unittest.TestCase):
    def test_envelope_only_in_stderr_is_read(self):
        """The drift this consolidation fixes: a cap refusal's envelope goes to stderr."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report="", stderr=json.dumps({"error": {"message": CAP_MSG}}))
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), [CAP_MSG])

    def test_report_json_wins_over_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report=json.dumps({"error": {"message": "from report"}}),
                     stderr=json.dumps({"error": {"message": "from stderr"}}))
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), ["from report"])

    def test_status_only_report(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report=json.dumps({"status": "fail", "corners": []}))
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), ["report status fail"])

    def test_envelope_after_leading_noise(self):
        """klt can print a plain-text line ahead of its JSON error document."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, stderr='klt: submit failed\n{"error": {"message": "' + CAP_MSG + '"}}\n')
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), [CAP_MSG])

    def test_unparseable_falls_back_to_stderr_tail(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report="not json at all", stderr="traceback: boom\n")
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)),
                             ["unparseable report: traceback: boom"])

    def test_unparseable_with_no_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report="{")
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), ["unparseable report"])

    def test_empty_report_and_empty_stderr(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report="", stderr="   \n")
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), ["unparseable report"])

    def test_no_attempt_dirs_is_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            d.mkdir()
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)), [])

    def test_missing_request_dir_is_empty_list(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(sc.attempt_messages(Path(td) / "never-submitted", Path(td), Path(td)), [])

    def test_eleven_attempts_sort_numerically(self):
        """Lexical sort put attempt10/attempt11 ahead of attempt2 in five of the six copies."""
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            for n in range(1, 12):
                _attempt(d, n, report=json.dumps({"error": {"message": f"try {n}"}}))
            self.assertEqual(sc.attempt_messages(d, Path(td), Path(td)),
                             [f"try {n}" for n in range(1, 12)])

    def test_non_numeric_attempt_dir_is_tolerated(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 2, report=json.dumps({"error": {"message": "two"}}))
            (d / "attempt-scratch").mkdir()
            msgs = sc.attempt_messages(d, Path(td), Path(td))
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[-1], "two")  # the unnumbered dir sorts first, never crashes

    def test_message_is_scrubbed_and_capped(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir, repo_root = Path(td) / "build", Path(td)
            d = run_dir / "r"
            long_msg = f"deck at {run_dir}/tag/netlist.spice failed: " + "x" * 500
            _attempt(d, 1, report=json.dumps({"error": {"message": long_msg}}))
            got = sc.attempt_messages(d, run_dir, repo_root)[0]
            self.assertEqual(len(got), 400)
            self.assertIn("<build>/tag/netlist.spice", got)
            self.assertNotIn(str(run_dir), got)

    def test_cap_is_overridable(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "r"
            _attempt(d, 1, report=json.dumps({"error": {"message": "y" * 900}}))
            self.assertEqual(len(sc.attempt_messages(d, Path(td), Path(td), cap=700)[0]), 700)


class ClassifyErrorTest(unittest.TestCase):
    def test_model_not_found_from_log(self):
        self.assertEqual(sc.classify_error({}, "could not find a valid modelname for ..."),
                         "model_not_found")

    def test_timeout_beats_other_codes(self):
        corner = {"diagnostics": [{"code": "sim_error"}, {"code": "run_timeout"}]}
        self.assertEqual(sc.classify_error(corner, ""), "timeout")

    def test_codes_are_sorted_and_deduped(self):
        corner = {"diagnostics": [{"code": "b"}, {"code": "a"}, {"code": "b"}, {"code": None}]}
        self.assertEqual(sc.classify_error(corner, ""), "error:a,b")

    def test_no_diagnostics(self):
        self.assertEqual(sc.classify_error({}, ""), "error")
        self.assertEqual(sc.classify_error({"diagnostics": []}, ""), "error")

    def test_all_codes_none(self):
        self.assertEqual(sc.classify_error({"diagnostics": [{"code": None}]}, ""), "error:")


class PointLogTest(unittest.TestCase):
    def test_sections_and_missing_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir, repo_root = Path(td) / "build", Path(td)
            run_dir.mkdir()
            (run_dir / "deck.spice").write_text("* deck\n.end\n")
            corner = {"artifacts": {"deck": str(run_dir / "deck.spice")},
                      "diagnostics": [{"severity": "error", "code": "c1", "message": "bad"}]}
            out = sc.point_log(corner, ["# point: x"], run_dir, repo_root)
            self.assertIn("# ==== klt sim deck (exact input given to ngspice on the runner) ====", out)
            self.assertIn("| * deck", out)
            self.assertIn("| error/c1: bad", out)
            self.assertIn("(no ngspice log retrieved)", out)

    def test_no_artifacts_at_all(self):
        with tempfile.TemporaryDirectory() as td:
            out = sc.point_log({}, ["# h"], Path(td), Path(td))
            self.assertIn("(no deck retrieved)", out)
            self.assertIn("(no ngspice log retrieved)", out)


if __name__ == "__main__":
    unittest.main()
