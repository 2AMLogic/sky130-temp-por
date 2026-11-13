#!/usr/bin/env python3
"""Tests for the shared campaign submit bootstrap (issue #307). Stdlib only, no SPICE.

Every fleet campaign runner's ``cmd_run`` opened with its own copy of three things:
the run id + run-directory rule (``open_run``), the bounded submit pool whose
exceptions become recorded ``{"error": ...}`` entries (``fan_out``), and the
submit-time clean-tree guard (``refuse_unsubmittable``).  The nine copies had drifted
-- three had no tree guard at all, one spelled the worker cap so that ``--jobs 0``
crashed, and the "does not exist" / "exists" wordings differed.  These tests pin the
consolidated behaviour.

Run: python3 -I sim/bin/test_sim_common_bootstrap.py
"""
from __future__ import annotations

import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_common as sc  # noqa: E402

RUN_ID_RE = re.compile(r"^\d{8}-\d{6}-deadbee$")


class OpenRunTest(unittest.TestCase):
    def test_derives_run_id_from_timestamp_and_sha(self):
        with tempfile.TemporaryDirectory() as td:
            run_id, run_dir, now = sc.open_run(Path(td), None, "deadbee")
            self.assertRegex(run_id, RUN_ID_RE)
            self.assertEqual(run_id, f"{now:%Y%m%d-%H%M%S}-deadbee")
            self.assertEqual(run_dir, Path(td) / run_id)
            self.assertTrue(run_dir.is_dir())

    def test_explicit_run_id_wins(self):
        with tempfile.TemporaryDirectory() as td:
            run_id, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee")
            self.assertEqual(run_id, "my-run")
            self.assertEqual(run_dir, Path(td) / "my-run")

    def test_fresh_run_refuses_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "my-run").mkdir()
            with self.assertRaises(SystemExit) as cm:
                sc.open_run(Path(td), "my-run", "deadbee")
            self.assertIn("exists; refusing to reuse a run id", str(cm.exception))

    def test_require_demands_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit) as cm:
                sc.open_run(Path(td), "my-run", "deadbee", reuse="require")
            self.assertIn("does not exist", str(cm.exception))
            self.assertFalse((Path(td) / "my-run").exists())  # never created by a retry

    def test_require_accepts_and_does_not_recreate(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "my-run"
            d.mkdir()
            (d / "run.json").write_text("{}")
            _, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", reuse="require")
            self.assertEqual(run_dir, d)
            self.assertTrue((run_dir / "run.json").is_file())

    def test_allow_creates_when_missing(self):
        with tempfile.TemporaryDirectory() as td:
            _, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", reuse="allow")
            self.assertTrue(run_dir.is_dir())

    def test_allow_accepts_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "my-run").mkdir()
            _, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", reuse="allow")
            self.assertTrue(run_dir.is_dir())

    def test_sub_nests_below_the_run_id(self):
        with tempfile.TemporaryDirectory() as td:
            run_id, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", sub="mirror-degen")
            self.assertEqual(run_id, "my-run")  # the run id itself is unprefixed
            self.assertEqual(run_dir, Path(td) / "my-run" / "mirror-degen")
            self.assertTrue(run_dir.is_dir())

    def test_sub_refusal_is_per_variant_not_per_run(self):
        """A variant run shares its baseline's run id, so only its own subdir may collide."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "my-run").mkdir()
            _, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", sub="mirror-degen")
            self.assertTrue(run_dir.is_dir())
            with self.assertRaises(SystemExit):
                sc.open_run(Path(td), "my-run", "deadbee", sub="mirror-degen")

    def test_create_false_applies_the_rule_without_creating(self):
        with tempfile.TemporaryDirectory() as td:
            _, run_dir, _ = sc.open_run(Path(td), "my-run", "deadbee", create=False)
            self.assertFalse(run_dir.exists())
            (Path(td) / "my-run").mkdir()
            with self.assertRaises(SystemExit):
                sc.open_run(Path(td), "my-run", "deadbee", create=False)

    def test_build_dir_is_created_with_parents(self):
        with tempfile.TemporaryDirectory() as td:
            _, run_dir, _ = sc.open_run(Path(td) / "sim" / "build" / "slug", "my-run", "deadbee")
            self.assertTrue(run_dir.is_dir())

    def test_unknown_reuse_mode_is_a_programming_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(ValueError):
                sc.open_run(Path(td), "my-run", "deadbee", reuse=True)


class FanOutTest(unittest.TestCase):
    def test_results_are_in_unit_order_not_completion_order(self):
        def fn(u):
            if u == 1:  # the first unit finishes last
                threading.Event().wait(0.05)
            return {"unit": u}

        self.assertEqual(sc.fan_out(fn, [1, 2, 3, 4], 2), [{"unit": u} for u in (1, 2, 3, 4)])

    def test_exception_becomes_an_error_entry_in_place(self):
        def fn(u):
            if u == 2:
                raise RuntimeError("boom")
            return {"unit": u}

        got = sc.fan_out(fn, [1, 2, 3], 2)
        self.assertEqual(got, [{"unit": 1}, {"error": "RuntimeError('boom')"}, {"unit": 3}])

    def test_one_failure_does_not_abandon_the_rest(self):
        ran = []

        def fn(u):
            ran.append(u)
            raise ValueError(u)

        got = sc.fan_out(fn, list(range(5)), 2)
        self.assertEqual(sorted(ran), list(range(5)))
        self.assertTrue(all("error" in r for r in got))

    def test_tag_prefixes_the_label_onto_every_result(self):
        got = sc.fan_out(lambda u: {"exit": 0}, ["a", "b"], 2, label=lambda u: f"v-{u}", tag="variant")
        self.assertEqual(got, [{"variant": "v-a", "exit": 0}, {"variant": "v-b", "exit": 0}])
        self.assertEqual(list(got[0]), ["variant", "exit"])  # tag first, as hand-merged

    def test_tag_is_applied_to_an_error_entry_too(self):
        def fn(u):
            raise RuntimeError("boom")

        got = sc.fan_out(fn, ["a"], 2, label=lambda u: u, tag="case")
        self.assertEqual(got, [{"case": "a", "error": "RuntimeError('boom')"}])

    def test_a_result_key_wins_over_the_tag(self):
        """submit_request() returns its own `variant`; the hand-written merge let it win."""
        got = sc.fan_out(lambda u: {"variant": "nominal/por"}, ["n"], 2,
                         label=lambda u: u, tag="variant")
        self.assertEqual(got, [{"variant": "nominal/por"}])

    def test_label_without_tag_leaves_results_untouched(self):
        got = sc.fan_out(lambda u: {"exit": 0}, ["a"], 2, label=lambda u: u)
        self.assertEqual(got, [{"exit": 0}])

    def test_worker_cap_holds_at_two(self):
        live, peak, lock = 0, 0, threading.Lock()
        gate = threading.Event()

        def fn(u):
            nonlocal live, peak
            with lock:
                live += 1
                peak = max(peak, live)
            gate.wait(0.05)
            with lock:
                live -= 1
            return {"unit": u}

        sc.fan_out(fn, list(range(8)), 64)
        self.assertLessEqual(peak, 2)

    def test_jobs_zero_still_runs(self):
        """min(2, jobs) raised ValueError from ThreadPoolExecutor in eight of nine copies."""
        self.assertEqual(sc.fan_out(lambda u: {"unit": u}, [1, 2], 0), [{"unit": 1}, {"unit": 2}])

    def test_no_units_is_an_empty_list(self):
        self.assertEqual(sc.fan_out(lambda u: {"unit": u}, [], 2), [])


class RefuseUnsubmittableTest(unittest.TestCase):
    def test_clean_tree_passes(self):
        self.assertIsNone(sc.refuse_unsubmittable({"dirty": False}, False))

    def test_dirty_tree_refuses(self):
        with self.assertRaises(SystemExit) as cm:
            sc.refuse_unsubmittable({"dirty": True}, False)
        self.assertIn("dirty tree", str(cm.exception))
        self.assertIn("--allow-dirty", str(cm.exception))

    def test_allow_dirty_overrides(self):
        self.assertIsNone(sc.refuse_unsubmittable({"dirty": True}, True))

    def test_unpushed_is_only_refused_when_required(self):
        gi = {"dirty": False, "pushed_to_remote": False}
        self.assertIsNone(sc.refuse_unsubmittable(gi, False))
        with self.assertRaises(SystemExit) as cm:
            sc.refuse_unsubmittable(gi, False, require_pushed=True)
        self.assertIn("pushed=False", str(cm.exception))

    def test_require_pushed_passes_on_a_clean_pushed_tree(self):
        self.assertIsNone(sc.refuse_unsubmittable(
            {"dirty": False, "pushed_to_remote": True}, False, require_pushed=True))

    def test_require_pushed_still_refuses_a_dirty_tree(self):
        with self.assertRaises(SystemExit) as cm:
            sc.refuse_unsubmittable({"dirty": True, "pushed_to_remote": True}, False, require_pushed=True)
        self.assertIn("dirty=True", str(cm.exception))

    def test_allow_dirty_overrides_the_pushed_check_too(self):
        self.assertIsNone(sc.refuse_unsubmittable(
            {"dirty": True, "pushed_to_remote": False}, True, require_pushed=True))

    def test_dirty_tree_is_not_recordable_either(self):
        """The record-time twin keeps its own wording; both name --allow-dirty."""
        with self.assertRaises(SystemExit) as cm:
            sc.refuse_unrecordable({"dirty": True}, None, False, False)
        self.assertIn("refusing to record", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
