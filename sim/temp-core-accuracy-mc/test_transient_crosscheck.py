#!/usr/bin/env python3
"""The operating-point cross-check refuses a record whose logs are not readable (issue #325).

`transient_crosscheck()` compares this experiment's nominal DC-sweep PTAT/CTAT against
the #86 EN-high `base` transient values, reading the per-corner logs of the record
pinned in `SOLVER_RECORD` straight out of the tree.  Those logs are committed, so the
read works -- but `run_solver_sweep.py` now stages new runs' logs in the fleet artifact
store, so a future `SOLVER_RECORD` bump would point at a record with nothing to read.

Before this change the loop simply found no files and returned `n_compared = 0`, which
the record renders as a cross-check with "worst |dPTAT| = 0 V" -- a cross-check that
compared nothing reading as one that agreed.  These tests pin the refusal instead:

  * a `SOLVER_RECORD` with no committed per-corner logs raises, naming `klt artifact get`,
  * the pinned record's logs ARE present in the tree, so the real call does not raise.

Stdlib only: no SPICE, no PDK, no fleet, no record written.

Run: python3 -I sim/temp-core-accuracy-mc/test_transient_crosscheck.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "bin"))
import run_accuracy_mc as ram  # noqa: E402

EMPTY_NOMINAL = {"corners": {}}


class StoreEraRecordIsRefusedTest(unittest.TestCase):
    def test_a_record_without_committed_logs_raises(self):
        """A store-era (or simply absent) cross-check record is a hard refusal."""
        with mock.patch.object(
            ram, "SOLVER_RECORD", "sim/temp-core-startup-solver/records/29990101-000000-deadbee"
        ):
            with self.assertRaises(SystemExit) as cm:
                ram.transient_crosscheck(EMPTY_NOMINAL)
        msg = str(cm.exception)
        self.assertIn("klt artifact get", msg)
        self.assertIn("29990101-000000-deadbee", msg)
        self.assertIn("compared nothing", msg)

    def test_the_pinned_record_has_its_logs_committed(self):
        """The guard must not fire on the record actually pinned today."""
        logs = (
            ram.REPO_ROOT
            / ram.SOLVER_RECORD.replace("records", "corners")
            / "en-high__base"
        )
        self.assertTrue(logs.is_dir(), f"{logs} is missing: SOLVER_RECORD is unreadable")
        self.assertTrue(any(logs.glob("*.log")), f"{logs} has no per-corner logs")
        # no raise, and it reports a count rather than inventing a comparison
        out = ram.transient_crosscheck(EMPTY_NOMINAL)
        self.assertEqual(out["source"], ram.SOLVER_RECORD)
        self.assertEqual(out["n_compared"], 0)  # no nominal corners were passed in


if __name__ == "__main__":
    unittest.main(verbosity=2)
