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
  * a corner with **no report at all** -- absent from the analysis, not present-with-None,
                                   which is how a lost process section arrives (issue #318) --
                                   counts as not compared as well: grading is against the
                                   expected `PROCS x SUPPLIES` grid, so the corner count
                                   cannot shrink to the corners that happened to report;
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


GRID = [(p, v) for p in m.PROCS for v in m.SUPPLIES]
# The 15 corner names the control must grade, written out rather than derived from PROCS x
# SUPPLIES, so these tests state the expected grid independently of the grader enforcing it.
GRID_NAMES = ["ff_2.97V", "ff_3.30V", "ff_3.63V", "fs_2.97V", "fs_3.30V", "fs_3.63V",
              "sf_2.97V", "sf_3.30V", "sf_3.63V", "ss_2.97V", "ss_3.30V", "ss_3.63V",
              "tt_2.97V", "tt_3.30V", "tt_3.63V"]


def full_grid(overrides=None, drop=()):
    """{corner: samples} over the whole PROCS x SUPPLIES grid: two flat samples per corner.

    `overrides` replaces individual corners' sample dicts (to make one corner invalid, or
    non-flat); `drop` removes corners from the mapping entirely, which is what a corner with
    no report at all looks like by the time `analyse_term` runs -- `load_term` contributes no
    key for it.  An entry of `drop` is either a corner key or a bare process name, meaning
    that whole process section's three supplies (issue #318).
    """
    corners = {k: {0: curve(), 1: curve()} for k in GRID}
    for d in drop:
        for k in ([(d, v) for v in m.SUPPLIES] if isinstance(d, str) else [d]):
            del corners[k]
    corners.update(overrides or {})
    return corners


class SelfCheckTest(unittest.TestCase):
    """The synthetic fixtures must actually exercise the guards they claim to."""

    def test_curve_passes_every_operating_point_guard(self):
        self.assertEqual(m.guard_check(curve()), [])

    def test_an_invalid_sample_is_rejected(self):
        self.assertTrue(m.guard_check(BAD))

    def test_the_fixture_grid_is_the_modules_expected_corner_set(self):
        self.assertEqual(len(GRID), 15)
        self.assertEqual(sorted(f"{p}_{v:.2f}V" for p, v in GRID), GRID_NAMES)
        self.assertEqual(sorted(GRID), sorted(m.GRID))


class VacuousPassTest(unittest.TestCase):
    """The reproduction from issue #310: every `none` sample failed, yet the control read PASS."""

    def setUp(self):
        self.an = graded(full_grid({k: {1: BAD, 2: BAD} for k in GRID}))

    def test_nothing_was_compared(self):
        self.assertEqual([cs["n_valid"] for cs in self.an.values()], [0] * 15)
        self.assertEqual([cs["max_dev_from_nominal_V"] for cs in self.an.values()], [None] * 15)

    def test_the_old_fold_would_have_produced_a_passing_zero(self):
        # The exact expression this issue removed -- kept here so the hole stays visible.
        self.assertEqual(max((cs["max_dev_from_nominal_V"] or 0.0) for cs in self.an.values()), 0.0)

    def test_control_is_not_verified(self):
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners_compared"], 0)
        self.assertEqual(c["corners_not_compared"], GRID_NAMES)

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
        self.an = graded(full_grid({("ff", 3.63): {0: BAD, 1: BAD}}))

    def test_the_compared_corners_are_flat(self):
        self.assertEqual(self.an[("tt", 3.3)]["max_dev_from_nominal_V"], 0.0)
        self.assertEqual(self.an[("ss", 2.97)]["max_dev_from_nominal_V"], 0.0)

    def test_control_is_not_verified_despite_flat_compared_corners(self):
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners"], 15)
        self.assertEqual(c["n_corners_compared"], 14)
        self.assertEqual(c["corners_not_compared"], ["ff_3.63V"])

    def test_the_uncompared_corner_is_named_in_the_rendered_line(self):
        line = m.control_line(m.none_control(self.an))
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("ff_3.63V", line)
        self.assertIn("1 of 15 corners compared nothing", line)

    def test_the_subset_max_is_still_disclosed(self):
        c = m.none_control(self.an)
        self.assertEqual(c["max_dev_from_nominal_V"], 0.0)
        self.assertIn("over the 14 corners that were compared", m.control_line(c).lower())


class UnusableNominalTest(unittest.TestCase):
    """A corner whose NOMINAL reference failed a guard compared nothing either."""

    def setUp(self):
        noms = {k: curve() for k in GRID}
        noms[("ss", 3.3)] = BAD
        self.an = graded(full_grid(), nominals=noms)

    def test_corner_with_a_bad_nominal_is_counted_as_not_compared(self):
        self.assertTrue(self.an[("ss", 3.3)]["nominal_invalid"])
        self.assertIsNone(self.an[("ss", 3.3)]["max_dev_from_nominal_V"])
        c = m.none_control(self.an)
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["corners_not_compared"], ["ss_3.30V"])


class MissingCornerTest(unittest.TestCase):
    """A corner with no report at all must be graded, not skipped (issue #318).

    `load_term` appends a process section whose request produced no usable report to
    `missing_procs` and contributes **no key** for its corners, so `analyse_term` never
    sees them -- they are absent rather than present-with-nothing-compared.  Grading over
    whatever keys happen to be in `an` let a `none` term that lost a whole process section
    render **PASS** "over all 12 corners": a max over 12 of the 15 corners, certifying the
    switching wrappers on three corners that were never simulated.  The control therefore
    grades against the expected `PROCS x SUPPLIES` grid.
    """

    def test_a_missing_process_section_is_not_verified(self):
        c = m.none_control(graded(full_grid(drop=["fs"])))
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners"], 15)
        self.assertEqual(c["n_corners_compared"], 12)
        self.assertEqual(c["corners_not_compared"], ["fs_2.97V", "fs_3.30V", "fs_3.63V"])

    def test_the_missing_process_corners_are_named_in_the_rendered_line(self):
        line = m.control_line(m.none_control(graded(full_grid(drop=["fs"]))))
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("3 of 15 corners compared nothing", line)
        for name in ("fs_2.97V", "fs_3.30V", "fs_3.63V"):
            self.assertIn(name, line)

    def test_a_single_missing_corner_is_not_verified(self):
        c = m.none_control(graded(full_grid(drop=[("ss", 3.63)])))
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["n_corners"], 15)
        self.assertEqual(c["n_corners_compared"], 14)
        self.assertEqual(c["corners_not_compared"], ["ss_3.63V"])

    def test_a_missing_corner_alongside_a_non_flat_one_reports_the_subset_max(self):
        c = m.none_control(graded(full_grid({("tt", 3.3): {0: curve(), 1: curve(dptat=1e-3)}},
                                            drop=["fs"])))
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertAlmostEqual(c["max_dev_from_nominal_V"], 1e-3)
        self.assertEqual(c["corners_not_compared"], ["fs_2.97V", "fs_3.30V", "fs_3.63V"])

    def test_an_absent_corner_grades_exactly_like_one_that_compared_nothing(self):
        absent = m.none_control(graded(full_grid(drop=["fs"])))
        invalid = m.none_control(graded(full_grid({("fs", v): {0: BAD} for v in m.SUPPLIES})))
        self.assertEqual(absent, invalid)

    def test_an_empty_analysis_names_the_whole_grid(self):
        c = m.none_control({})
        self.assertEqual(c["verdict"], "NOT VERIFIED")
        self.assertEqual(c["corners_not_compared"], GRID_NAMES)
        self.assertIsNone(c["max_dev_from_nominal_V"])

    def test_a_corner_outside_the_grid_is_still_graded(self):
        # The grid is a floor, not a filter: a key the function was handed is never dropped.
        c = m.none_control(graded(full_grid({("tt", 3.0): {0: curve(dptat=1e-3)}})))
        self.assertEqual(c["n_corners"], 16)
        self.assertEqual(c["n_corners_compared"], 16)
        self.assertEqual(c["verdict"], "FAIL")

    def test_the_compare_renderer_also_sees_the_missing_process(self):
        line = m.compare_control_line("baseline", m.none_control(graded(full_grid(drop=["fs"]))))
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("3 of 15 corners compared nothing", line)
        self.assertIn("fs_3.30V", line)


class PassAndFailTest(unittest.TestCase):
    """With every corner compared, the control grades on the measurement alone."""

    def test_flat_control_passes(self):
        an = graded(full_grid())
        c = m.none_control(an)
        self.assertEqual(c["verdict"], "PASS")
        self.assertEqual(c["max_dev_from_nominal_V"], 0.0)
        self.assertEqual(c["corners_not_compared"], [])
        self.assertEqual(c["n_corners_compared"], c["n_corners"])
        self.assertEqual(c["n_corners"], 15)
        self.assertIn("PASS", m.control_line(c))

    def test_a_control_above_the_flatness_threshold_fails(self):
        an = graded(full_grid({("tt", 3.3): {0: curve(), 1: curve(dptat=1e-3)}}))
        c = m.none_control(an)
        self.assertEqual(c["verdict"], "FAIL")
        self.assertAlmostEqual(c["max_dev_from_nominal_V"], 1e-3)
        line = m.control_line(c)
        self.assertIn("FAIL", line)
        self.assertNotIn("PASS", line)

    def test_the_flatness_threshold_is_the_module_constant(self):
        an = graded(full_grid())
        self.assertEqual(m.none_control(an)["flat_threshold_V"], m.CONTROL_FLAT_V)


class ControlShapeTest(unittest.TestCase):
    """The control block is all measurement: no literal is written into a record."""

    def test_keys_are_exactly_the_graded_fields(self):
        c = m.none_control(graded(full_grid()))
        self.assertEqual(set(c), {"max_dev_from_nominal_V", "n_corners", "n_corners_compared",
                                  "corners_not_compared", "flat_threshold_V", "verdict"})

    def test_the_retired_hardcoded_control_value_is_gone(self):
        # `controls.none_max_sd_V` was written as the literal 0.0 with no reader (issue #310).
        self.assertNotIn("none_max_sd_V", m.none_control(graded(full_grid())))
        self.assertNotIn("none_max_sd_V", (HERE / "run_accuracy_mc.py").read_text())


class CompareRendererTest(unittest.TestCase):
    """The variant-compare record's per-deck control bullet has the same three states."""

    def test_absent_term_is_not_available(self):
        line = m.compare_control_line("baseline", None)
        self.assertIn("NOT AVAILABLE", line)
        self.assertNotIn("PASS", line)

    def test_partially_compared_deck_is_not_verified(self):
        c = m.none_control(graded(full_grid({("ff", 2.97): {0: BAD}})))
        line = m.compare_control_line("mirror-degen", c)
        self.assertIn("NOT VERIFIED", line)
        self.assertNotIn("PASS", line)
        self.assertIn("ff_2.97V", line)

    def test_fully_compared_flat_deck_passes(self):
        c = m.none_control(graded(full_grid()))
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
                    # the whole expected grid, not just the corners this record happened to carry
                    self.assertEqual(c["n_corners"], 15)
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
