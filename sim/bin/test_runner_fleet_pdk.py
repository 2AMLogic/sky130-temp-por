#!/usr/bin/env python3
"""Every fleet runner records the PDK its RUNNERS reported, never the client's (issue #328).

A klt batch `report.json` carries two PDK values and they genuinely differ:

  * `environment.remote.worker_environment.pdk` -- the install the fleet machine that
    executed the corners actually ran under, and
  * `provenance.pdk` -- the PDK the submitting *client* resolved for itself.

`sim/bin/corner-run.py` settled that the first is the one a record may call the fleet's;
#306 and #312 then fixed two more runners, each with a private copy of the same walk.
Three campaign runners stored the client's value under the key `fleet_pdk_report` anyway:
`sim/glitch-top/records/20261113-082829-da28d31-vdd_level-rerun181.json` records
`pdk.fleet_pdk_report.source = "search root: ~/.ciel"` -- a search root on the
*submitting* host, with the client's commit, under a label that says fleet.

This file is the cross-runner contract: ONE table of runners, each fed a stub report
whose two PDK values disagree, so a seventh runner cannot quietly reintroduce the
mislabel and so the fix cannot regress in one runner while the other six stay right.
Three source-level guards back it up -- the record-side wiring must go through
`sim_common.fleet_pdk_fields()`, no runner may state the fleet's PDK as unreported, and
(issue #333) no runner may state that the stamp is recorded but not compared with the
`sim/pdk.json` pin.

Issue #333 extended the contract from "what did the runner report?" to "how does it
compare with the pin?".  Each runner is driven through all THREE states of
`pdk.fleet_matches_pin` -- `match`, `mismatch`, `not-reported` -- because the defect that
made this three-state rather than a bool was a real one: `corner-run.py` compared
`fleet_pdk_commit()`'s `"unknown"` against the pin, found it unequal, and recorded an
*unstamped* fleet run as a MISMATCH.  The negative controls below (a stamp with no 40-hex
commit must be `not-reported`; a mixed set must be `mismatch`) are what separate a real
three-state verdict from a renamed bool.

Stdlib only: no SPICE, no PDK, no fleet, no records written.

Run: python3 -I sim/bin/test_runner_fleet_pdk.py
"""

from __future__ import annotations

import copy
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
for _d in ("sim/brownout-top", "sim/glitch-top", "sim/supply-ramp-top", "sim/iq-top",
           "sim/temp-core-startup-solver", "sim/temp-core-accuracy-mc", "sim/bin"):
    sys.path.insert(0, str(REPO_ROOT / _d))

import sim_common  # noqa: E402
import run_accuracy_mc as ram  # noqa: E402
import run_brownout_campaign as rb  # noqa: E402
import run_glitch_campaign as rg  # noqa: E402
import run_iq_campaign as riq  # noqa: E402
import run_iq_sensitivity as ris  # noqa: E402
import run_ramp_campaign as rr  # noqa: E402
import run_solver_sweep as rss  # noqa: E402

RUNNER_STAMP = "open_pdks " + "c" * 40          # what the fleet machine ran under
CLIENT_STAMP = "open_pdks " + "9" * 40          # what the CLIENT resolved -- never the fleet's
OFF_PIN_STAMP = "open_pdks " + "d" * 40         # a runner on a DIFFERENT open_pdks build
NO_COMMIT_STAMP = "open_pdks sky130A (no commit in this stamp)"
RUNNER_PDK = {"variant": "sky130A", "stamp_text": RUNNER_STAMP}
CLIENT_PDK = {"name": "sky130A", "version": CLIENT_STAMP, "source": "search root: ~/.ciel",
              "ambiguous_sources": ["search root: ~/.volare"]}

# The pin every driver compares against: the stub RUNNER's own commit, so the default
# report is a `match` and each non-match state is produced by changing the REPORT (what a
# real run varies), never by moving the pin.
PIN = {"open_pdks_commit": "c" * 40}


def stamped(text: str) -> dict:
    """A `worker_environment.pdk` whose stamp is `text`."""
    return {"variant": "sky130A", "stamp_text": text}

PROC, TEMP, SUPPLY = "tt", 27.0, 3.3


def stub_report(corners: list[dict], *, runner=RUNNER_PDK, client=CLIENT_PDK) -> dict:
    """A gradeable klt batch report carrying both PDK values (the client's by default)."""
    remote = {"job_id": "klt-sim-dead", "instance_type": "c7a.2xlarge", "lifecycle": "spot",
              "runner_klt_version": "0.9.1", "client_klt_version": "0.9.1",
              "elapsed_seconds": 1, "state": "SUCCEEDED"}
    if runner is not None:
        remote["worker_environment"] = {"pdk": dict(runner)}
    rep = {"status": "ok", "corner_count": len(corners), "corners": corners,
           "environment": {"engine": "ngspice", "engine_version": "47", "remote": remote}}
    if client is not None:
        rep["provenance"] = {"klt_version": "0.9.1", "pdk": dict(client)}
    return rep


def one_corner() -> dict:
    """One corner with no artifacts: every grader records it as unusable, which is all
    these tests need -- the PDK fields are provenance, not grading."""
    return {"process": PROC, "temperature_c": TEMP, "supply_v": {"vset": SUPPLY},
            "status": "error", "runtime_s": 1.0, "artifacts": {}, "diagnostics": [], "measurements": []}


def write_report(d: Path, **kw) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / "report.json").write_text(json.dumps(stub_report([one_corner()], **kw)))


def one_point_manifest(mod, **kw):
    """That module's manifest trimmed to a single corner (fewer stub reports to write)."""
    man = copy.deepcopy(sim_common.load_manifest(mod.MANIFEST))
    man["corners"] = {**man["corners"], "process": [PROC], "temperature_c": [TEMP],
                      "supply_v": [SUPPLY] if isinstance(man["corners"].get("supply_v"), list)
                      else man["corners"].get("supply_v")}
    man["corners"].update(kw)
    return man


# --------------------------------------------------------------------------
# One driver per runner: fn(run_dir, pin, **report kwargs) -> the fleet `pdk` fields
# --------------------------------------------------------------------------


def _brownout(run_dir: Path, pin: dict, **kw) -> dict:
    man = one_point_manifest(rb, supply_v=[SUPPLY])
    r = rb.plan_requests(man)[0]
    write_report(run_dir / r["tag"], **kw)
    res = rb.analyze_request(r, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields([res["info"].get("runner_pdk")], pin)


def _glitch(run_dir: Path, pin: dict, **kw) -> dict:
    man = one_point_manifest(rg, supply_v=[SUPPLY])
    r = rg.plan_requests(man, rg.CLASSES[0])[0]
    write_report(run_dir / r["tag"], **kw)
    res = rg.analyze_request(r, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields([res["info"].get("runner_pdk")], pin)


def _ramp(run_dir: Path, pin: dict, **kw) -> dict:
    man = one_point_manifest(rr, supply_v=[SUPPLY])
    variant = next(iter(man["variants"]))
    rate = rr.all_rates(man)[0][0]
    write_report(run_dir / variant / rr.rate_tag(rate), **kw)
    res = rr.analyze_variant(variant, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields((q.get("runner_pdk") for q in res["requests"]), pin)


def _iq_campaign(run_dir: Path, pin: dict, **kw) -> dict:
    man = one_point_manifest(riq, supply_v=[SUPPLY])
    state = riq.STATES[0]
    write_report(run_dir / state / sim_common.rate_tag(man["measurement"]["rate_v_per_s"]), **kw)
    res = riq.analyze_state(state, run_dir, man, {})
    return sim_common.fleet_pdk_fields([res["requests"].get("runner_pdk")], pin)


def _iq_sensitivity(run_dir: Path, pin: dict, **kw) -> dict:
    man = one_point_manifest(riq, supply_v=[SUPPLY])
    name = next(iter(ris.sens(man)["variants"]))
    write_report(run_dir / name / ris.STATE / sim_common.rate_tag(man["measurement"]["rate_v_per_s"]), **kw)
    res = ris.analyze_variant(name, run_dir, man, {})
    return sim_common.fleet_pdk_fields([res["requests"].get("runner_pdk")], pin)


def _solver(run_dir: Path, pin: dict, **kw) -> dict:
    """Driven at its own seam: `observed_provenance()` over one combo's loaded report."""
    combo = f"{rss.SCENARIOS[0]}__{next(iter(rss.VARIANTS))}"
    summary = {combo: {"status": "ran", "fleet": {"runner_klt_version": "0.9.1", "client_klt_version": "0.9.1"},
                       "ngspice_engine_version": "47"}}
    res = {combo: {"report": stub_report([], **kw), "points": {}}}
    prov = rss.observed_provenance(summary, res, pin)
    return {k: prov[k] for k in FLEET_KEYS}


def _accuracy_mc(run_dir: Path, pin: dict, **kw) -> dict:
    rep = stub_report([], **kw)
    ents = {"nominal": {"report": rep, "jobs": {"all": rep["environment"]["remote"]},
                        "engines": {"all": "47"}, "missing_procs": []}}
    prov = ram.observed_provenance(ents, pin)
    return {k: prov[k] for k in FLEET_KEYS}


FLEET_KEYS = ("fleet_pdk", "fleet_pdk_jobs", "fleet_pdk_reporting", "fleet_matches_pin")

RUNNERS = {
    "brownout-top/run_brownout_campaign.py": _brownout,
    "glitch-top/run_glitch_campaign.py": _glitch,
    "supply-ramp-top/run_ramp_campaign.py": _ramp,
    "iq-top/run_iq_campaign.py": _iq_campaign,
    "iq-top/run_iq_sensitivity.py": _iq_sensitivity,
    "temp-core-startup-solver/run_solver_sweep.py": _solver,
    "temp-core-accuracy-mc/run_accuracy_mc.py": _accuracy_mc,
}


class FleetPdkIsTheRunnersTest(unittest.TestCase):
    """The contract, run against every runner that records a fleet PDK."""

    def fields(self, driver, pin: dict = PIN, **kw) -> dict:
        with tempfile.TemporaryDirectory() as td:
            return driver(Path(td), pin, **kw)

    def verdicts(self, **kw) -> dict:
        """`{runner: fleet_matches_pin}` across the whole table, for one report shape."""
        return {name: self.fields(driver, **kw)["fleet_matches_pin"]
                for name, driver in RUNNERS.items()}

    def test_the_runner_stamp_is_what_each_runner_records(self):
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                got = self.fields(driver)
                self.assertEqual(got["fleet_pdk"], RUNNER_STAMP)
                self.assertEqual((got["fleet_pdk_jobs"], got["fleet_pdk_reporting"]), (1, 1))

    def test_no_runner_records_the_client_resolved_pdk_as_the_fleet_s(self):
        """The defect: `provenance.pdk` under a `fleet_*` key.  The stub's two values
        disagree, so a runner that reads the client's half fails here."""
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                self.assertNotIn(CLIENT_STAMP, str(self.fields(driver)))

    def test_a_runner_that_reported_no_stamp_is_unknown_not_the_client_s(self):
        """`unknown` beats borrowing the client's value: an unverified fleet must not
        read as pinned."""
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                got = self.fields(driver, runner=None)
                self.assertEqual(got["fleet_pdk"], "unknown")
                self.assertNotIn(CLIENT_STAMP, str(got))
                self.assertEqual((got["fleet_pdk_jobs"], got["fleet_pdk_reporting"]), (1, 0))

    def test_a_report_with_no_client_provenance_at_all_still_reports_the_runner(self):
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                self.assertEqual(self.fields(driver, client=None)["fleet_pdk"], RUNNER_STAMP)


class FleetMatchesPinIsThreeStateTest(unittest.TestCase):
    """Every runner records the pin COMPARISON, in three states (issue #333).

    Same table, same stub reports: what changes is that each record now carries a verdict
    rather than a stamp a reader must compare by hand.  Driven through the report, not the
    pin, so each case is one a real fleet run could produce.
    """

    fields = FleetPdkIsTheRunnersTest.fields
    verdicts = FleetPdkIsTheRunnersTest.verdicts

    def test_every_runner_records_the_field_at_all(self):
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                self.assertIn("fleet_matches_pin", self.fields(driver))

    def test_a_runner_on_the_pin_is_a_match(self):
        self.assertEqual(self.verdicts(), {name: "match" for name in RUNNERS})

    def test_a_runner_on_a_different_open_pdks_is_a_mismatch(self):
        self.assertEqual(self.verdicts(runner=stamped(OFF_PIN_STAMP)),
                         {name: "mismatch" for name in RUNNERS})

    def test_a_runner_that_reported_no_stamp_is_not_reported_not_a_mismatch(self):
        """The live defect issue #333 fixes, asserted for all seven runners at once:
        `corner-run.py` turned this state into `**MISMATCH vs sim/pdk.json pin**` and
        exit 3, because it compared the string `"unknown"` against the pin."""
        self.assertEqual(self.verdicts(runner=None),
                         {name: "not-reported" for name in RUNNERS})

    def test_negative_control_a_stamp_with_no_commit_is_not_reported(self):
        """The check that separates a real three-state verdict from a renamed bool: the
        runner DID report a PDK, it just named no 40-hex commit.  Nothing to compare is
        not the same finding as compared-and-wrong."""
        got = self.verdicts(runner=stamped(NO_COMMIT_STAMP))
        self.assertEqual(got, {name: "not-reported" for name in RUNNERS})
        for name in RUNNERS:
            self.assertNotEqual(got[name], "mismatch", name)

    def test_negative_control_a_mixed_set_is_a_mismatch_not_a_match(self):
        """Driven at the shared producer, because only some runners join >1 job: a grid is
        not on the pin because part of it was."""
        mixed = sim_common.fleet_pdk_fields(
            [stamped(RUNNER_STAMP), stamped(OFF_PIN_STAMP)], PIN)
        self.assertEqual(mixed["fleet_matches_pin"], "mismatch")
        self.assertEqual((mixed["fleet_pdk_jobs"], mixed["fleet_pdk_reporting"]), (2, 2))

    def test_the_verdict_is_always_one_of_the_three_strings_never_a_bool(self):
        for kw in ({}, {"runner": None}, {"runner": stamped(OFF_PIN_STAMP)},
                   {"runner": stamped(NO_COMMIT_STAMP)}):
            for name, got in self.verdicts(**kw).items():
                with self.subTest(f"{name} {kw}"):
                    self.assertIsInstance(got, str)
                    self.assertNotIsInstance(got, bool)
                    self.assertIn(got, ("match", "mismatch", "not-reported"))

    def test_the_client_resolved_pdk_never_decides_the_verdict(self):
        """The client is on the pin and the runner is not: the verdict must follow the
        RUNNER, or a record would call an unverified fleet pinned."""
        got = self.verdicts(runner=stamped(OFF_PIN_STAMP),
                            client={"name": "sky130A", "version": "open_pdks " + "c" * 40})
        self.assertEqual(got, {name: "mismatch" for name in RUNNERS})

    def test_coverage_is_recorded_beside_the_verdict_not_folded_into_it(self):
        """Partial coverage is not a fourth state -- `fleet_pdk_jobs` /
        `fleet_pdk_reporting` carry it, so a verdict over the jobs that ANSWERED can be
        rendered as exactly that."""
        partial = sim_common.fleet_pdk_fields([stamped(RUNNER_STAMP), {}, {}], PIN)
        self.assertEqual(partial["fleet_matches_pin"], "match")
        self.assertEqual((partial["fleet_pdk_jobs"], partial["fleet_pdk_reporting"]), (3, 1))

    def test_a_local_run_with_no_fleet_jobs_at_all_is_not_reported(self):
        """A non-batch run has no fleet job to compare, and must not read as either a
        match or a mismatch."""
        local = sim_common.fleet_pdk_fields([], PIN)
        self.assertEqual(local["fleet_matches_pin"], "not-reported")
        self.assertEqual(local["fleet_pdk"], "unknown")


class RenderedVerdictTest(unittest.TestCase):
    """The rendered text must carry the same verdict, derived -- and no state may render
    as another (issue #333)."""

    def clause(self, fields):
        return sim_common.fleet_pdk_clause(fields["fleet_pdk"], fields["fleet_matches_pin"])

    def fields(self, driver, pin: dict = PIN, **kw) -> dict:
        with tempfile.TemporaryDirectory() as td:
            return driver(Path(td), pin, **kw)

    def test_each_state_renders_distinctly_for_every_runner(self):
        shapes = {"match": {}, "mismatch": {"runner": stamped(OFF_PIN_STAMP)},
                  "not-reported": {"runner": None},
                  "not-reported-no-commit": {"runner": stamped(NO_COMMIT_STAMP)}}
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                rendered = {k: self.clause(self.fields(driver, **kw)) for k, kw in shapes.items()}
                self.assertIn(sim_common.pin_state(True), rendered["match"])
                self.assertIn("MISMATCH", rendered["mismatch"])
                for k in ("match", "not-reported", "not-reported-no-commit"):
                    self.assertNotIn("MISMATCH", rendered[k], k)
                for k in ("mismatch", "not-reported", "not-reported-no-commit"):
                    self.assertNotIn(sim_common.pin_state(True), rendered[k], k)
                # the two ways into `not-reported` differ in the stamp they name, but
                # neither claims a comparison it did not make
                for k in ("not-reported", "not-reported-no-commit"):
                    self.assertIn(sim_common.fleet_pin_state("not-reported"), rendered[k])

    def test_no_rendered_clause_contains_a_hand_written_verdict_literal(self):
        """Derived, never a literal: the verdict wording comes from `fleet_pin_state()`,
        so it cannot drift from the `fleet_matches_pin` field beside it."""
        for name, driver in RUNNERS.items():
            with self.subTest(name):
                f = self.fields(driver)
                self.assertIn(sim_common.fleet_pin_state(f["fleet_matches_pin"]),
                              self.clause(f))


class SourceGuardTest(unittest.TestCase):
    """Mechanism, not documentation: the two greps that keep the shape from returning."""

    STALE_CLAIM = re.compile(r"(?i)not reported by the runner"
                             r"|runner does not report|does not report (its |the )?pdk")

    # Issue #333's sibling of the above.  After #328 the four record texts said, still
    # weakly, that the runner's stamp is RECORDED and not COMPARED with the pin.  The
    # comparison exists now, so that sentence is the next literal to go stale into
    # append-only records -- and a record that declines to compare while the field beside
    # it carries a verdict is worse than one that never had the field.  Derive it
    # (`fleet_pdk_clause()` + `fleet_pin_state()`).
    # The lookahead keeps it to a PDK claim: `run_accuracy_mc.py`'s none-control grading
    # legitimately says "a corner that was not compared", which is about a measurement,
    # not about the pin.  Matched over a TWO-LINE window -- see the test below.
    STALE_UNCOMPARED = re.compile(r"(?i)(?=.*\b(pin|pdk|stamp)\b)"
                                 r".*?(not compare[sd]?\b"
                                 r"|never compared"
                                 r"|assumed, not verified, to match the (sim/pdk\.json )?pin)")

    def runners(self) -> dict[str, str]:
        found = {p.relative_to(REPO_ROOT / "sim").as_posix(): p.read_text()
                 for p in sorted((REPO_ROOT / "sim").glob("*/run_*.py"))}
        self.assertTrue(found, "no runner sources found")
        return found

    def test_every_runner_that_records_a_fleet_pdk_is_in_this_file_s_table(self):
        """A new runner recording a fleet PDK joins the table above or fails here --
        otherwise the contract silently stops covering the repo."""
        recording = {rel for rel, src in self.runners().items() if "fleet_pdk" in src}
        self.assertEqual(recording - set(RUNNERS), set(),
                         "a runner records a fleet PDK but is not covered by RUNNERS")
        self.assertEqual(set(RUNNERS) - recording, set(),
                         "RUNNERS names a runner that no longer records a fleet PDK")

    def test_the_record_side_goes_through_the_shared_fields_helper(self):
        for rel, src in self.runners().items():
            if rel not in RUNNERS:
                continue
            with self.subTest(rel):
                self.assertIn("sim_common.fleet_pdk_fields(", src)

    def test_no_runner_states_the_fleet_pdk_as_unreported(self):
        """Four records carried "the fleet PDK commit is not reported by the runner" as a
        literal; the runners do report it, and records are append-only, so the stale claim
        can never be corrected where it landed.  Derive it (`fleet_pdk_clause()`)."""
        offenders = [f"{rel}:{n}: {line.strip()}"
                     for rel, src in self.runners().items()
                     for n, line in enumerate(src.splitlines(), start=1)
                     if self.STALE_CLAIM.search(line)]
        self.assertEqual(offenders, [], "a runner states the fleet PDK as unreported:\n  "
                         + "\n  ".join(offenders))

    def test_no_runner_states_that_the_stamp_is_not_compared_with_the_pin(self):
        """Four records carried "recorded ... not compared with the sim/pdk.json pin" as a
        literal.  Every runner compares it now (issue #333), so the claim is false and
        records are append-only.  Derive the verdict instead of stating its absence.

        Scanned over a sliding TWO-LINE window, not line by line: all four of the original
        literals were wrapped in source, and one of them (`run_iq_campaign.py`'s "this
        record does" / " not compare that stamp with the sim/pdk.json pin") split the verb
        from its object, so a line-at-a-time grep -- the shape
        `test_no_runner_states_the_fleet_pdk_as_unreported` uses -- missed it outright.
        """
        offenders = []
        for rel, src in self.runners().items():
            lines = src.splitlines()
            flagged: list[int] = []
            for n in range(len(lines)):
                if flagged and flagged[-1] == n - 1:
                    continue  # already reported as the previous window's first line
                if self.STALE_UNCOMPARED.search(" ".join(lines[n:n + 2])):
                    flagged.append(n)
            offenders += [f"{rel}:{n + 1}: {lines[n].strip()}" for n in flagged]
        self.assertEqual(offenders, [],
                         "a runner states the fleet PDK stamp as uncompared with the pin:\n  "
                         + "\n  ".join(offenders))

    def test_every_covered_runner_records_the_three_state_verdict_field(self):
        """The field cannot be added to the shared helper and then dropped by a runner
        that rebuilds its `pdk` block by hand: it must reach the record."""
        for rel, src in self.runners().items():
            if rel not in RUNNERS:
                continue
            with self.subTest(rel):
                self.assertNotIn("fleet_matches_pin\"] =", src,
                                 "the verdict must come from the shared producer, not be assigned")


if __name__ == "__main__":
    unittest.main()
