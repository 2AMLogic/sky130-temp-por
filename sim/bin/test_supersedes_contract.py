#!/usr/bin/env python3
"""The `supersedes` record field is falsy-for-no-predecessor in NEW records (issue #353).

Operator ruling (2026-11-23, option a): a record with no predecessor stores a falsy
value (`null`) in its machine-readable `supersedes` field; the display string `(none)`
is spelled only by renderers, as `rec['supersedes'] or '(none)'`.  Committed records are
append-only evidence and keep their four legacy encodings (`null`, `""`, `"(none)"`,
absent) -- see `sim/README.md`; this file never reads or rewrites them.

What is pinned here:
  * `sim_common.add_record_args()` declares `--author`/`--supersedes` with `default=None`,
    and `add_common_args()` goes through it;
  * the `compare` and `record` subparsers of the two runners yield `None` when the flag is
    omitted and the given id when supplied (the JSON value);
  * source guards: no runner writes the `"(none)"` sentinel into a record, none string-
    compares it back, none hand-writes the `Supersedes` bullet, and the two report footers
    render the id verbatim or `(none)` through the shared idiom;
  * no `sim/*/run_*.py` hand-rolls `--author`/`--supersedes` any more.

Stdlib only: no SPICE, no PDK, no fleet, no record written.

Run: python3 -I sim/bin/test_supersedes_contract.py
"""
from __future__ import annotations

import argparse
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import sim_common  # noqa: E402

RUNNERS = {
    "accuracy": REPO_ROOT / "sim/temp-core-accuracy-mc/run_accuracy_mc.py",
    "solver": REPO_ROOT / "sim/temp-core-startup-solver/run_solver_sweep.py",
}
FOOTER = "f\"- **Supersedes**: {rec['supersedes'] or '(none)'}\""


class RecordArgsTest(unittest.TestCase):
    def parse(self, *argv):
        p = argparse.ArgumentParser()
        sim_common.add_record_args(p)
        return p.parse_args(list(argv))

    def test_omitted_flags_are_none_not_a_sentinel(self):
        a = self.parse()
        self.assertIsNone(a.supersedes)
        self.assertIsNone(a.author)

    def test_supplied_id_passes_through(self):
        self.assertEqual(self.parse("--supersedes", "20261011-165400-69d13ac").supersedes,
                         "20261011-165400-69d13ac")

    def test_common_args_use_the_same_declaration(self):
        p = argparse.ArgumentParser()
        sim_common.add_common_args(p, timeout_default=60)
        a = p.parse_args([])
        self.assertIsNone(a.supersedes)
        self.assertIsNone(a.author)


class SubparserDefaultsTest(unittest.TestCase):
    """`compare` and `record` of both runners: omitted -> None, supplied -> the id."""

    def parse(self, runner, argv):
        mod = __import__(runner)
        captured = {}
        orig = argparse.ArgumentParser.parse_args

        def spy(self, *a, **k):
            ns = orig(self, *a, **k)
            captured["ns"] = ns
            raise SystemExit(0)  # stop before any command runs

        argparse.ArgumentParser.parse_args = spy
        old_argv = sys.argv
        sys.argv = [runner, *argv]
        try:
            with self.assertRaises(SystemExit):
                mod.main()
        finally:
            argparse.ArgumentParser.parse_args = orig
            sys.argv = old_argv
        return captured["ns"]

    def setUp(self):
        for key in ("accuracy", "solver"):
            d = str(RUNNERS[key].parent)
            if d not in sys.path:
                sys.path.insert(0, d)

    def test_each_lane_omitted_and_supplied(self):
        cases = [("run_accuracy_mc", "record"), ("run_accuracy_mc", "compare"),
                 ("run_solver_sweep", "record")]
        for runner, sub in cases:
            with self.subTest(runner=runner, sub=sub):
                self.assertIsNone(self.parse(runner, [sub, "--run-id", "r1"]).supersedes)
                self.assertEqual(
                    self.parse(runner, [sub, "--run-id", "r1", "--supersedes", "RID"]).supersedes, "RID")


class SourceGuardTest(unittest.TestCase):
    def test_no_sentinel_written_or_compared(self):
        for name, path in RUNNERS.items():
            src = path.read_text()
            with self.subTest(name):
                self.assertNotRegex(src, r'supersedes\s*or\s*"\(none\)"')
                self.assertNotRegex(src, r'\[.supersedes.\]\s*!=\s*"\(none\)"')

    def test_footers_render_through_the_shared_idiom(self):
        for name, path in RUNNERS.items():
            src = path.read_text()
            with self.subTest(name):
                self.assertIn(FOOTER, src)
                self.assertNotIn('"- **Supersedes**: (none)"', src)
        self.assertEqual(RUNNERS["accuracy"].read_text().count(FOOTER), 2)  # record + compare

    def test_record_dicts_carry_the_raw_value(self):
        for name, path in RUNNERS.items():
            with self.subTest(name):
                self.assertIn('"supersedes": args.supersedes', path.read_text())

    def test_no_runner_hand_rolls_author_supersedes(self):
        offenders = []
        pat = re.compile(r'add_argument\("--(author|supersedes)"')
        for f in sorted((REPO_ROOT / "sim").glob("*/run_*.py")):
            for n, line in enumerate(f.read_text().splitlines(), 1):
                # the two record-only subparsers declare just --supersedes with default=None
                if pat.search(line) and "default=None" not in line:
                    offenders.append(f"{f.relative_to(REPO_ROOT)}:{n}")
        self.assertEqual(offenders, [], "use sim_common.add_record_args(): " + ", ".join(offenders))


if __name__ == "__main__":
    unittest.main()
