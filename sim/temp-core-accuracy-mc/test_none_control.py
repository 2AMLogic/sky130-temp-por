#!/usr/bin/env python3
"""Tests for the `none` negative control's three-state grading (issue #310).

The `none` term is what every record of this experiment leans on to say its per-term
attribution can be trusted: every device is wrapped to sigma = 0, so each sample must
reproduce its corner's nominal curve exactly.  `analyse_term` leaves a corner's
``max_dev_from_nominal_V`` at ``None`` when nothing was compared there (no valid sample,
or no usable nominal point), and the grader used to fold that with ``or 0.0`` -- turning
"nothing was compared" into "0 V deviation" and rendering **PASS**.  An all-invalid
`none` term therefore certified the attribution it exists to police, and corners that
dropped out of a partially failed run silently left the max.

These tests pin the properties that close that hole:

  * all `none` samples invalid  -> NOT VERIFIED, never PASS, and no 0 V number is claimed;
  * any corner not compared     -> NOT VERIFIED even when every compared corner is flat,
                                   and the uncompared corners are named in the record;
  * a nominal point that failed a guard counts as "not compared" too;
  * every corner compared       -> PASS below the flatness threshold, FAIL above it;
  * the control dict carries no hardcoded literal (the retired `none_max_sd_V`);
  * **re-grading the committed runs' `none` evidence still reads 0.0 V / PASS** --
    the guard is prospective, it retracts nothing (acceptance step 4 of #310).

The last class re-derives the control from the committed, append-only corner evidence
(`corners/<rid>/samples-none.csv` + `nominal_*.log`) through the real `analyse_term` /
`none_control`; it reads those files and writes nothing.

Stdlib only: no SPICE, no PDK, no run directory, no record written.

Run: python3 -I sim/temp-core-accuracy-mc/test_none_control.py
"""
from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_accuracy_mc as m  # noqa: E402

# The three evaluation points of a guard-passing PTAT/CTAT curve (rounded from the committed
# tt/3.30 V nominal log). PTAT is monotonic in T, CTAT/isup/loop-closure are inside the guards.
_POINTS = ((-40, 1.09942, 0.782469), (27, 1.41410, 0.658261), (125, 1.87658, 0.466130))
BAD = {"_error": "no convergence"}


def curve(dptat=0.0):
    """One guard-passing sample, offset from the nominal curve by `dptat` volts at every T."""
    v = {}
    for t, ptat, ctat in _POINTS:
        g = m.tagT(t)
        v.update({f"ptat_{g}": ptat + dptat, f"ctat_{g}": ctat,
                  f"na_{g}": ctat, f"nb_{g}": ctat, f"isup_{g}": -7.3e-6})
    return v


def graded(corners, nominals=None):
    """`analyse_term` over {corner: {sample: values}}, with a flat nominal per corner by default."""
    nominals = {k: curve() for k in corners} if nominals is None else nominals
    ent = {"corners": dict(corners)}
    nom = {"corners": {k: {None: v} for k, v in nominals.items()}}
    return m.analyse_term(ent, nom)


class SelfCheckTest(unittest.TestCase):
    """The synthetic fixtures must actually exercise the guards they claim to."""

    def test_curve_passes_every_operating_point_guard(self):
        self.assertEqual(m.guard_check(curve()), [])

    def test_an_invalid_sample_is_rejected(self):
        self.assertTrue(m.guard_check(BAD))


class VacuousPassTest(unittest.TestCase):
    """The reproduction from issue #310: every `none` sample failed, yet the control read PASS."""

    def setUp(self):
        self.an = graded({("tt", 3.3): {1: BAD, 2: BAD}, ("ss", 3.0): {1: BAD}},
                         nominals={("tt", 3.3): curve(), ("ss", 3.0): curve()})

    def test_nothing_was_compared(self):
        self.assertEqual([cs["n_valid"] for cs in self.an.values()], [0, 0])
        self.assertEqual([cs["max_dev_from_nominal_V"] for cs in self.an.values()], [None, None])

    def test_the_old_fold_would_have_produced_a_passing_zero(self):
        # The exact expression this issue removed -- kept here so the hole stays visible.
        self.assertEqual(max((cs["max_dev_from_nominal_V"] or 0.0) for cs in self.an.values()), 0.0)

    def test_control_is_not_verified(self):
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners_compared"], 0)
        self.assertEqual(c["corners_not_compared"], ["ss_3.00V", "tt_3.30V"])

    def test_no_zero_volt_measurement_is_claimed(self):
        self.assertIsNone(m.none_control(self.an)["max_dev_from_nominal_V"])

    def test_rendered_control_does_not_say_pass(self):
        line = m.control_line(m.none_control(self.an))
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("No corner was compared at all", line)


class PartiallyFailedRunTest(unittest.TestCase):
    """A corner with no valid sample must not silently drop out of the max."""

    def setUp(self):
        self.an = graded({("tt", 3.3): {0: curve(), 1: curve()},
                          ("ss", 2.97): {0: curve(), 1: curve()},
                          ("ff", 3.63): {0: BAD, 1: BAD}})

    def test_the_compared_corners_are_flat(self):
        self.assertEqual(self.an[("tt", 3.3)]["max_dev_from_nominal_V"], 0.0)
        self.assertEqual(self.an[("ss", 2.97)]["max_dev_from_nominal_V"], 0.0)

    def test_control_is_not_verified_despite_flat_compared_corners(self):
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners"], 3)
        self.assertEqual(c["n_corners_compared"], 2)
        self.assertEqual(c["corners_not_compared"], ["ff_3.63V"])

    def test_the_uncompared_corner_is_named_in_the_rendered_line(self):
        line = m.control_line(m.none_control(self.an))
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("ff_3.63V", line)
        self.assertIn("1 of 3 corners compared nothing", line)

    def test_the_subset_max_is_still_disclosed(self):
        c = m.none_control(self.an)
        self.assertEqual(c["max_dev_from_nominal_V"], 0.0)
        self.assertIn("over the 2 corners that were compared", m.control_line(c).lower())


class UnusableNominalTest(unittest.TestCase):
    """A corner whose NOMINAL reference failed a guard compared nothing either."""

    def setUp(self):
        self.an = graded({("tt", 3.3): {0: curve(), 1: curve()}, ("ss", 3.3): {0: curve()}},
                         nominals={("tt", 3.3): curve(), ("ss", 3.3): BAD})

    def test_corner_with_a_bad_nominal_is_counted_as_not_compared(self):
        self.assertTrue(self.an[("ss", 3.3)]["nominal_invalid"])
        self.assertIsNone(self.an[("ss", 3.3)]["max_dev_from_nominal_V"])
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["corners_not_compared"], ["ss_3.30V"])


class PassAndFailTest(unittest.TestCase):
    """With every corner compared, the control grades on the measurement alone."""

    def test_flat_control_passes(self):
        an = graded({("tt", 3.3): {0: curve(), 1: curve()}, ("ss", 2.97): {0: curve()}})
        c = m.none_control(an)
        self.assertEqual(c["verdict"], "PASS")
        self.assertEqual(c["max_dev_from_nominal_V"], 0.0)
        self.assertEqual(c["corners_not_compared"], [])
        self.assertEqual(c["n_corners_compared"], c["n_corners"])
        self.assertIn("PASS", m.control_line(c))

    def test_a_control_above_the_flatness_threshold_fails(self):
        an = graded({("tt", 3.3): {0: curve(), 1: curve(dptat=1e-3)}})
        c = m.none_control(an)
        self.assertEqual(c["verdict"], "FAIL")
        self.assertAlmostEqual(c["max_dev_from_nominal_V"], 1e-3)
        line = m.control_line(c)
        self.assertIn("FAIL", line)
        self.assertNotIn("PASS", line)

    def test_the_flatness_threshold_is_the_module_constant(self):
        an = graded({("tt", 3.3): {0: curve(), 1: curve()}})
        self.assertEqual(m.none_control(an)["flat_threshold_V"], m.CONTROL_FLAT_V)


class ControlShapeTest(unittest.TestCase):
    """The control block is all measurement: no literal is written into a record."""

    def test_keys_are_exactly_the_graded_fields(self):
        c = m.none_control(graded({("tt", 3.3): {0: curve()}}))
        self.assertEqual(set(c), {"max_dev_from_nominal_V", "n_corners", "n_corners_compared",
                                  "corners_not_compared", "flat_threshold_V", "verdict"})

    def test_the_retired_hardcoded_control_value_is_gone(self):
        # `controls.none_max_sd_V` was written as the literal 0.0 with no reader (issue #310).
        self.assertNotIn("none_max_sd_V", m.none_control(graded({("tt", 3.3): {0: curve()}})))
        self.assertNotIn("none_max_sd_V", (HERE / "run_accuracy_mc.py").read_text())


class CompareRendererTest(unittest.TestCase):
    """The variant-compare record's per-deck control bullet has the same three states."""

    def test_absent_term_is_not_available(self):
        line = m.compare_control_line("baseline", None)
        self.assertIn("NOT AVAILABLE", line)
        self.assertNotIn("PASS", line)

    def test_partially_compared_deck_is_not_verified(self):
        c = m.none_control(graded({("tt", 3.3): {0: curve()}, ("ff", 2.97): {0: BAD}}))
        line = m.compare_control_line("mirror-degen", c)
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("ff_2.97V", line)

    def test_fully_compared_flat_deck_passes(self):
        c = m.none_control(graded({("tt", 3.3): {0: curve()}}))
        self.assertIn("PASS", m.compare_control_line("baseline", c))


# ---------------------------------------------------------------------------------------------
# Acceptance step 4 of #310: re-grading an existing run still reads 0.0 V / PASS.
#
# The run directories under sim/build/ are git-ignored, so the committed, append-only corner
# evidence is the durable input: samples-none.csv holds every `none` sample's measurements and
# nominal_<proc>_<supply>v.log the same-corner reference. Both are read-only here.

RECORDS = {
    "20261011-165400-69d13ac": [("", None)],
    "20261011-165907-69d13ac": [("", None)],
    "20261107-235128-679442ca": [("baseline", "baseline"), ("mirror-degen", "mirror-degen")],
}
CSV_COLS = [f"{f}_{m.tagT(t)}" for t in m.TEMPS for f in m.FIELDS]


def read_committed_none(rid, subdir):
    """-> (analyse_term result, {corner: n_valid from the CSV's own valid column})"""
    cdir = HERE / "corners" / rid / subdir
    corners, csv_valid = {}, {}
    with (cdir / "samples-none.csv").open() as fh:
        for row in csv.DictReader(fh):
            key = (row["process"], float(row["supply_V"]))
            corners.setdefault(key, {})[int(row["sample"])] = {c: float(row[c]) for c in CSV_COLS}
            csv_valid[key] = csv_valid.get(key, 0) + int(row["valid"])
    nominals = {}
    for key in corners:
        lines = (cdir / f"nominal_{key[0]}_{key[1]:.2f}v.log").read_text().splitlines()[1:]
        nominals[key] = dict((k, float(v)) for k, _, v in (ln.partition(" = ") for ln in lines) if k)
    return graded(corners, nominals), csv_valid


class CommittedRunsStillPassTest(unittest.TestCase):
    """Every committed record's `none` control was really measured; the new grading keeps it."""

    def test_regrading_each_committed_run_reads_zero_volts_and_passes(self):
        for rid, parts in RECORDS.items():
            for subdir, deck in parts:
                with self.subTest(record=rid, deck=deck or "record"):
                    an, csv_valid = read_committed_none(rid, subdir)
                    c = m.none_control(an)
                    self.assertEqual(c["corners_not_compared"], [])
                    self.assertEqual(c["n_corners_compared"], c["n_corners"])
                    self.assertEqual(c["max_dev_from_nominal_V"], 0.0)
                    self.assertEqual(c["verdict"], "PASS")
                    # every corner really had samples to compare, so the PASS is not vacuous
                    self.assertTrue(all(cs["n_valid"] > 0 for cs in an.values()))
                    self.assertEqual({k: cs["n_valid"] for k, cs in an.items()}, csv_valid)

    def test_the_regrade_reproduces_each_records_own_per_corner_counts(self):
        for rid in ("20261011-165400-69d13ac", "20261011-165907-69d13ac"):
            with self.subTest(record=rid):
                rec = json.loads((HERE / "records" / f"{rid}.json").read_text())
                an, _ = read_committed_none(rid, "")
                self.assertEqual({f"{p}_{v:.2f}V": cs["n_valid"] for (p, v), cs in an.items()},
                                 {k: v["n_valid"] for k, v in rec["per_corner"]["none"].items()})
                self.assertEqual(rec["controls"]["none_max_dev_from_nominal_V"], 0.0)


if __name__ == "__main__":
    unittest.main()
