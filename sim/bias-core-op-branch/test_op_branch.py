#!/usr/bin/env python3
"""Verdict / solver-comparison agreement tests for `run_op_branch.py` (issue #544).

`verdict_text()` used to close its physicality finding with "the branch reported moves
when only the numerics change (see `solver_dependence`)". It said so whenever every
off-branch point was non-physical, so it derived a solver-comparison finding from the
physicality classification alone -- and never read its `checks` parameter. The two
findings are independent: a non-physical solution can appear under BOTH solvers at the
same supply voltage, so the off-branch sets can be identical, `solver_dependence` FAILS
(nothing flips), and the verdict still claimed movement.

The verdict now makes only the physicality finding and defers branch movement to the
`solver_dependence` check, which is where the supply points that flip are listed (the
JSON `checks[]` and the record's Markdown). These tests pin that for the records the
runner writes next, under both sweep cases, from ONE committed record so the two cases
differ in nothing but the comparison itself:

  * differing -- `records/20261113-160939-9211b20a.json` as committed: KLU lands
    off-branch at 2.97 / 3.31 / 3.35 / 3.63 V, the sparse solver at 3.25 / 3.48 / 3.59 V;
  * identical -- the same record with each KLU sweep measurement copied onto the sparse
    sweep point at the same supply, keeping the sparse variant, solver and point id
    (the reproduction in issue #544).

The physicality classification is pinned separately, against the committed record's own
verdict and through `evaluate()`: which verdict class a record gets follows from the
per-point `nonphysical[...]` checks alone, under either comparison.

Stdlib only: no SPICE, no PDK, no fleet, no records written.

Run: python3 -I sim/bias-core-op-branch/test_op_branch.py
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_op_branch as rob  # noqa: E402

RECORD = HERE / "records" / "20261113-160939-9211b20a.json"

KLU_OFF = [2.97, 3.31, 3.35, 3.63]
SPARSE_OFF = [3.25, 3.48, 3.59]
SPARSE_SOLVER = "SPARSE 1.3"

# On-branch under BOTH solvers in the committed record, so a point injected here leaves
# each case's comparison exactly as it was.
PLAUSIBLE_SUPPLY = 3.0

# What ngspice would print for an off-branch point that IS a possible circuit state:
# VREF outside the good window, the supply SOURCING current, every node inside the rails.
PLAUSIBLE_RAW = "vref = 2.5\n-i(v1) = 5e-06\n"

# The sentence the verdict used to emit whatever `solver_dependence` said.
MOVEMENT_CLAIM = "moves when only the numerics change"

# The physicality finding ends here in both the committed and the current verdict.
PHYSICALITY_HALF_END = " They are false"


def klu_copied_onto_sparse(points: list[dict]) -> list[dict]:
    """Each KLU sweep measurement copied onto the sparse sweep point at the same supply.

    The sparse variant, solver and point id are the sparse column's own, so this stays a
    comparison between two solver columns -- now with identical off-branch sets."""
    klu = {p["supply_v"]: p for p in points if p["role"] == "sweep" and p["variant"] == "klu"}
    out = []
    for p in points:
        if p["role"] == "sweep" and p["variant"] == "sparse":
            copied = copy.deepcopy(klu[p["supply_v"]])
            for key in ("point_id", "variant", "solver"):
                copied[key] = p[key]
            p = copied
        out.append(copy.deepcopy(p))
    return out


COMMITTED = json.loads(RECORD.read_text())
CASES = {
    "differing": COMMITTED["points"],
    "identical": klu_copied_onto_sparse(COMMITTED["points"]),
}


def solver_dependence(results: list[dict]) -> dict:
    return next(c for c in rob.cross_checks(results) if c["name"] == "solver_dependence")


def n_off(results: list[dict]) -> int:
    return sum(p["branch"] == "off" for p in results)


class VerdictAgreesWithSolverComparison(unittest.TestCase):
    """The verdict asserts physicality only; branch movement is the check's finding."""

    def assert_physicality_only(self, results: list[dict], verdict: str) -> None:
        self.assertTrue(
            verdict.startswith(
                f"SOLVER ARTIFACT: all {n_off(results)} off-branch point(s) are non-physical"
            ),
            verdict,
        )
        self.assertNotIn(MOVEMENT_CLAIM, verdict)
        self.assertIn("`solver_dependence`", verdict)

    def test_differing_sets_flip_and_the_check_lists_them(self):
        results = copy.deepcopy(CASES["differing"])
        self.assertEqual(rob.off_supplies(results, "klu"), KLU_OFF)
        self.assertEqual(rob.off_supplies(results, "sparse"), SPARSE_OFF)
        dep = solver_dependence(results)
        self.assertTrue(dep["pass"])
        for supply in KLU_OFF + SPARSE_OFF:
            self.assertIn(f"'{supply:.2f}'", dep["detail"])
        verdict = rob.verdict_text(results)
        self.assert_physicality_only(results, verdict)
        # the explanation of WHY the points are non-physical is the committed record's, verbatim
        committed = COMMITTED["verdict"]
        self.assertEqual(
            verdict[: verdict.index(PHYSICALITY_HALF_END)],
            committed[: committed.index(PHYSICALITY_HALF_END)],
        )

    def test_identical_sets_do_not_flip_and_the_verdict_claims_no_movement(self):
        results = copy.deepcopy(CASES["identical"])
        klu = [p for p in results if p["role"] == "sweep" and p["variant"] == "klu"]
        sparse = [p for p in results if p["role"] == "sweep" and p["variant"] == "sparse"]
        self.assertEqual(len(sparse), len(klu))
        self.assertEqual({p["solver"] for p in sparse}, {SPARSE_SOLVER})
        self.assertTrue(all(p["point_id"].startswith("sweep-sparse_") for p in sparse))
        self.assertEqual(rob.off_supplies(results, "sparse"), rob.off_supplies(results, "klu"))
        dep = solver_dependence(results)
        self.assertFalse(dep["pass"])
        self.assertIn("changes: []", dep["detail"])
        self.assert_physicality_only(results, rob.verdict_text(results))


class PhysicalityClassificationIsIndependent(unittest.TestCase):
    """Which verdict class a record gets follows from the per-point `nonphysical[...]`
    checks alone -- under either solver comparison."""

    @staticmethod
    def plausible_off_branch(variant: str) -> dict:
        """`evaluate()`'s own result for an off-branch point that is a possible circuit
        state, so the classification is driven through the runner, not asserted beside it."""
        point = rob.Point(
            point_id=f"sweep-{variant}_{rob.PROCESS}_{rob.TEMP_C:g}c_{PLAUSIBLE_SUPPLY:.2f}v",
            role="sweep",
            variant=variant,
            supply_v=PLAUSIBLE_SUPPLY,
            temp_c=rob.TEMP_C,
            purpose="synthetic physically plausible off-branch point",
        )
        return rob.evaluate(
            {"point": point, "deck": "", "raw": PLAUSIBLE_RAW, "rc": 0, "timed_out": False}
        )

    def test_a_physically_plausible_point_is_suspected_under_both_comparisons(self):
        for case, flips in (("differing", True), ("identical", False)):
            with self.subTest(case):
                results = copy.deepcopy(CASES[case])
                self.assertEqual(solver_dependence(results)["pass"], flips)
                for i, p in enumerate(results):
                    if p["role"] == "sweep" and p["supply_v"] == PLAUSIBLE_SUPPLY:
                        results[i] = self.plausible_off_branch(p["variant"])
                injected = [
                    p for p in results if p["role"] == "sweep" and p["supply_v"] == PLAUSIBLE_SUPPLY
                ]
                self.assertEqual([p["branch"] for p in injected], ["off", "off"])
                for p in injected:
                    nonphysical = next(c for c in p["checks"] if c["name"].startswith("nonphysical["))
                    self.assertFalse(nonphysical["pass"])
                self.assertEqual(solver_dependence(results)["pass"], flips)
                verdict = rob.verdict_text(results)
                self.assertTrue(
                    verdict.startswith(
                        "REAL SECOND EQUILIBRIUM SUSPECTED: 2 off-branch point(s) are "
                        "physically plausible"
                    ),
                    verdict,
                )


if __name__ == "__main__":
    unittest.main()
