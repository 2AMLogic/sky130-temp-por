#!/usr/bin/env python3
"""Stubbed-input tests for the accuracy-MC record's `PDK` / `Tools` lines (issue #312).

`run_accuracy_mc.py` used to write a hardcoded open_pdks commit labelled
"(sim/pdk.json pin)" and a `'?'` ngspice fallback into every record it produced.  The
commit was wrong twice over: it was not the pin (`sim/pdk.json` was re-pinned for #188),
and it was not the recording host's install either -- it was the *fleet runners'* stamp
from the October runs.  `observed_provenance()` / `render_pdk_tools_lines()` now derive
both halves from the run's own `report.json` data, and these tests pin the properties
that keep them honest:

  * a version appears only when a term reported it,
  * an unobserved version reads `unknown` -- never a default, never first-found-only,
  * the fleet half of the PDK line is the *runner's* stamp, never the client-resolved
    `provenance.pdk` -- those two genuinely differ on real runs,
  * the recording host's half is never presented as the fleet's.

The sibling file `sim/temp-core-startup-solver/test_record_provenance.py` asserts the
same contract for `run_solver_sweep.py` (issue #306); the source-level counterpart is
`RunnerVersionLiteralTest` in `sim/bin/test_sim_common_provenance.py`.  Which FIELD is the
fleet's PDK is decided once, by `sim_common.runner_pdk()`, and asserted across every
runner in `sim/bin/test_runner_fleet_pdk.py` (issue #328); what stays here is this
runner's per-process-job wiring and the lines it renders.

Stdlib only: no SPICE, no PDK, no fleet, no record written.  `LoadTermContractTest`
builds a run directory of stub `report.json` files under a temp dir so the real
`load_term()` is exercised against the same shape the other tests stub.

Run: python3 -I sim/temp-core-accuracy-mc/test_record_provenance.py
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_accuracy_mc as ram  # noqa: E402
sim_common = ram.sim_common  # the shared pin-state vocabulary, through the module under test

PIN = {"open_pdks_commit": "f" * 40, "ngspice_lib": "libs.tech/combined/sky130.lib.spice"}

RUNNER_PDK = "open_pdks " + "a" * 40   # what the fleet actually simulated under
CLIENT_PDK = "open_pdks " + "f" * 40   # what the *client* resolved -- never the fleet's


class _Pdk:
    """The four attributes `render_pdk_tools_lines()` reads off corner-run's resolved PDK."""

    def __init__(self, matches_pin=True, installed_commit="a" * 40):
        self.variant = "sky130A"
        self.installed_commit = installed_commit
        self.matches_pin = matches_pin
        self.pin = PIN


def job_env(engine="47", runner_pdk=RUNNER_PDK, job="klt-sim-dead"):
    """One process section's `environment`, shaped like a real klt batch `report.json`.

    Note where each half lives: the runner's own install stamp hangs off
    `remote.worker_environment.pdk` (per job), while `engine_version` sits on the
    environment itself -- which is why `load_term()` has to keep BOTH per process job.
    """
    return {
        "engine": "ngspice",
        "engine_version": engine,
        "remote": {
            "job_id": job,
            "worker_environment": {"pdk": {"variant": "sky130A", "stamp_text": runner_pdk}},
        },
    }


def ran(engine="47", runner_pdk=RUNNER_PDK, client_pdk=CLIENT_PDK, job="klt-sim-dead", procs=None):
    """One `ents` entry for a term whose fleet jobs produced a usable report.

    A real klt batch `report.json` carries *two* PDK values: the runner's own install
    stamp under `environment.remote.worker_environment.pdk`, and the client-resolved PDK
    under `provenance.pdk`.  They default to different commits on purpose, so a reader
    that takes the client's value fails these tests instead of silently reporting the
    wrong half (the real divergence is recorded in
    `sim/bias-core-smoke/records/20261023-171642-e69f5b2e.json`).

    `procs` is `{name: {engine, runner_pdk, job}}` for a mismatch term, which is one fleet
    job PER PROCESS section; it defaults to the single section the keyword args describe.
    The entry mirrors `load_term()` exactly, **including** that `report['environment']` is
    the FIRST process section alone -- that is what makes a first-found reader detectable
    here, where a stub with one merged environment per term could not see it (issue #312).
    """
    envs = {k: job_env(**v) for k, v in (procs or {"all": {"engine": engine, "runner_pdk": runner_pdk, "job": job}}).items()}
    first = next(iter(envs.values()))
    return {
        "report": {"corners": [], "environment": first,  # first process section ONLY, as load_term merges it
                   "provenance": {"pdk": {"name": "sky130A", "version": client_pdk}}},  # client side
        "jobs": {k: v["remote"] for k, v in envs.items()},
        "engines": {k: v["engine_version"] for k, v in envs.items()},
        "missing_procs": [],
    }


def not_run():
    """A term the fleet refused outright: no report, so nothing to observe."""
    return {"report": None, "jobs": {}, "engines": {}, "missing_procs": []}


def lines(ents, pdk=None, klt="klayout-tools 0.9.0", backend="batch", pin=PIN):
    """`(pdk_line, tools_line)` for a stubbed set of term entries."""
    prov = ram.observed_provenance(ents, pin)
    fleet = {t: {"jobs": e["jobs"]} for t, e in ents.items() if e["report"] is not None}
    rec = {"klt": klt, "backend": backend}
    return prov, ram.render_pdk_tools_lines(rec, pdk or _Pdk(), prov, fleet)


class FleetEngineTest(unittest.TestCase):
    """AC 2: the sorted set of every term's engine, `unknown` when none reported one."""

    def test_one_engine_observed_is_reported_once(self):
        prov, (_, tools) = lines({"nominal": ran(engine="46"), "pnp": ran(engine="46")})
        self.assertEqual(prov["fleet_engine"], "ngspice-46")
        self.assertIn("fleet engine ngspice-46;", tools)

    def test_two_terms_on_different_engines_list_both(self):
        """Edge case (d): first-found would have hidden the second engine entirely."""
        prov, (_, tools) = lines({"nominal": ran(engine="46"), "pnp": ran(engine="47")})
        self.assertEqual(prov["fleet_engine"], "ngspice-46, ngspice-47")
        self.assertIn("fleet engine ngspice-46, ngspice-47;", tools)

    def test_no_engine_reported_is_unknown_not_a_question_mark(self):
        """Edge case (c): the `'?'` fallback this change removes."""
        prov, (_, tools) = lines({"nominal": not_run(), "pnp": not_run()})
        self.assertEqual(prov["fleet_engine"], "unknown")
        self.assertIn("fleet engine unknown;", tools)
        self.assertNotIn("?", tools)
        # `ngspice-unknown` is not a version: the tag is applied per observed engine, so
        # the unobserved case carries no engine token at all.
        self.assertNotIn("ngspice-unknown", tools)

    def test_a_term_reporting_no_engine_does_not_invent_one(self):
        prov, (_, tools) = lines({"nominal": ran(engine=None), "pnp": ran(engine="46")})
        self.assertEqual(prov["fleet_engine"], "ngspice-46")

    def test_partial_run_reports_only_the_terms_that_ran(self):
        prov, _ = lines({"nominal": ran(engine="46"), "amp": not_run(), "pnp": ran(engine="47")})
        self.assertEqual(prov["fleet_engine"], "ngspice-46, ngspice-47")


class WithinTermJobsTest(unittest.TestCase):
    """AC 2, one level down: a MISMATCH TERM IS ONE FLEET JOB PER PROCESS SECTION.

    A full run is 7 mismatch terms x 5 process sections + nominal = 36 jobs.  Joining over
    `report['environment']` samples the first usable process of each term -- 8 of those 36
    -- so a runner on a different PDK or engine in any non-first section was dropped while
    the header said "the fleet runners that executed the grid reported ...".  These cases
    disagree WITHIN a term; the cross-term cases above could not see it.
    """

    FIVE = {"tt": {"engine": "46", "runner_pdk": "open_pdks " + "a" * 40, "job": "j0"},
            "ss": {"engine": "47", "runner_pdk": "open_pdks " + "b" * 40, "job": "j1"},
            "ff": {"engine": "47", "runner_pdk": "open_pdks " + "b" * 40, "job": "j2"},
            "sf": {"engine": "47", "runner_pdk": "open_pdks " + "b" * 40, "job": "j3"},
            "fs": {"engine": "47", "runner_pdk": "open_pdks " + "b" * 40, "job": "j4"}}

    def test_process_jobs_of_one_term_disagreeing_report_every_stamp_and_engine(self):
        prov, (pdk_line, tools) = lines({"pnp": ran(procs=self.FIVE)})
        self.assertEqual(prov["fleet_pdk"], "open_pdks " + "a" * 40 + ", open_pdks " + "b" * 40)
        self.assertEqual(prov["fleet_engine"], "ngspice-46, ngspice-47")
        self.assertIn("b" * 40, pdk_line)      # the four non-first jobs, previously invisible
        self.assertIn("ngspice-47", tools)

    def test_every_process_job_is_counted_not_just_the_first(self):
        prov, _ = lines({"pnp": ran(procs=self.FIVE)})
        self.assertEqual(prov["fleet_pdk_jobs"], 5)
        self.assertEqual(prov["fleet_engine_jobs"], 5)

    def test_the_merged_first_process_environment_is_not_the_source(self):
        """The exact defect: the merged `report['environment']` IS the `tt` section, so a
        reader that uses it still passes every cross-term test while reporting only
        `tt`'s stamp and engine."""
        ent = ran(procs=self.FIVE)
        self.assertEqual(ent["report"]["environment"]["engine_version"], "46")   # first section
        prov = ram.observed_provenance({"pnp": ent}, PIN)
        self.assertNotEqual(prov["fleet_engine"], "ngspice-46")
        self.assertNotEqual(prov["fleet_pdk"], "open_pdks " + "a" * 40)

    def test_jobs_across_terms_and_processes_are_all_joined(self):
        prov, _ = lines({"nominal": ran(engine="45", runner_pdk="open_pdks " + "c" * 40),
                         "pnp": ran(procs=self.FIVE)})
        self.assertEqual(prov["fleet_engine"], "ngspice-45, ngspice-46, ngspice-47")
        self.assertEqual(prov["fleet_pdk_jobs"], 6)


class CoverageNoteTest(unittest.TestCase):
    """A value joined over the jobs that answered must not read as one they all agreed on.

    Chosen behaviour (the open question in #315's review): annotate ONLY the ambiguous
    case -- some jobs reported, others did not.  All-reported needs no caveat, and
    none-reported already renders `unknown`, which says it plainly.
    """

    def test_a_partial_stamp_says_how_many_jobs_reported(self):
        prov, (pdk_line, _) = lines({"pnp": ran(procs={
            "tt": {"runner_pdk": "open_pdks " + "a" * 40, "job": "j0"},
            "ss": {"runner_pdk": None, "job": "j1"},
            "ff": {"runner_pdk": None, "job": "j2"}})})
        self.assertEqual(prov["fleet_pdk_reporting"], 1)
        self.assertEqual(prov["fleet_pdk_jobs"], 3)
        self.assertIn("reported `open_pdks " + "a" * 40 + "` (from 1 of 3 fleet jobs; "
                      "the rest reported none)", pdk_line)

    def test_a_partial_engine_says_how_many_jobs_reported(self):
        prov, (_, tools) = lines({"pnp": ran(procs={"tt": {"engine": "46", "job": "j0"},
                                                    "ss": {"engine": None, "job": "j1"}})})
        self.assertIn("fleet engine ngspice-46 (from 1 of 2 fleet jobs; the rest reported none);", tools)

    def test_unanimous_coverage_adds_no_caveat(self):
        _, (pdk_line, tools) = lines({"pnp": ran(procs={"tt": {"job": "j0"}, "ss": {"job": "j1"}})})
        self.assertNotIn("fleet jobs;", pdk_line)
        self.assertNotIn("fleet jobs;", tools)

    def test_no_coverage_at_all_stays_plain_unknown(self):
        _, (pdk_line, tools) = lines({"pnp": ran(procs={"tt": {"engine": None, "runner_pdk": None, "job": "j0"},
                                                        "ss": {"engine": None, "runner_pdk": None, "job": "j1"}})})
        self.assertIn("reported `unknown`", pdk_line)
        self.assertNotIn("0 of 2", pdk_line)
        self.assertIn("fleet engine unknown;", tools)


class LoadTermContractTest(unittest.TestCase):
    """The stub above is only evidence if the real `load_term()` produces that shape.

    This is where the #315 defect actually lived: `observed_provenance()` read a key
    (`report['environment']`) that `load_term()` fills from the first process section
    only, and every stubbed test agreed with it.  Builds a run directory of `report.json`
    files -- stdlib only, no SPICE, no PDK, no fleet -- and runs the real loader.
    """

    def _run_dir(self, term, procs):
        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        for name, spec in procs.items():
            sub = d / term / name
            sub.mkdir(parents=True)
            (sub / "report.json").write_text(json.dumps({
                "corners": [{"corner_id": f"{name}_mm/1.80V/x/mc0", "status": "ok",
                             "measurements": [{"name": "ptat_m40", "value": 1.0}]}],
                "environment": job_env(**spec)}))
        return d

    def test_load_term_keeps_every_process_job_s_stamp_and_engine(self):
        d = self._run_dir("pnp", WithinTermJobsTest.FIVE)
        ent = ram.load_term(d, "pnp")
        self.assertEqual(sorted(ent["jobs"]), sorted(WithinTermJobsTest.FIVE))
        self.assertEqual(sorted(set(ent["engines"].values())), ["46", "47"])
        prov = ram.observed_provenance({"pnp": ent}, PIN)
        self.assertEqual(prov["fleet_engine"], "ngspice-46, ngspice-47")
        self.assertEqual(prov["fleet_pdk"], "open_pdks " + "a" * 40 + ", open_pdks " + "b" * 40)
        self.assertEqual(prov["fleet_pdk_jobs"], 5)

    def test_a_missing_process_section_is_not_counted_as_a_job(self):
        """`load_term()` lists it in `missing_procs`; it reported nothing, so it is not
        one of the M jobs the coverage note divides by."""
        d = self._run_dir("pnp", {k: v for k, v in WithinTermJobsTest.FIVE.items() if k != "fs"})
        ent = ram.load_term(d, "pnp")
        self.assertIn("fs", ent["missing_procs"])
        self.assertEqual(ram.observed_provenance({"pnp": ent}, PIN)["fleet_pdk_jobs"], 4)


class PdkLineTest(unittest.TestCase):
    """AC 1: no literal commit, no unconditional pin claim, both hosts named."""

    def test_matching_pin_uses_the_shared_ternary_wording(self):
        """Edge case (a): installed PDK equals the pin."""
        _, (pdk_line, _) = lines({"nominal": ran()}, pdk=_Pdk(matches_pin=True))
        self.assertIn("sky130A @ open_pdks `" + "a" * 40 + "` (matches sim/pdk.json pin)", pdk_line)
        self.assertIn("on the host that wrote this record", pdk_line)

    def test_mismatching_pin_is_flagged_not_asserted_as_a_match(self):
        """Edge case (b): installed PDK differs from the pin."""
        _, (pdk_line, _) = lines({"nominal": ran()}, pdk=_Pdk(matches_pin=False, installed_commit="b" * 40))
        self.assertIn("**MISMATCH vs sim/pdk.json pin**", pdk_line)
        self.assertNotIn("(matches sim/pdk.json pin)", pdk_line)
        self.assertIn("b" * 40, pdk_line)

    def test_the_models_library_text_is_preserved(self):
        """AC 1 keeps the trailing models clause -- it is what `_mm` sampling depends on."""
        _, (pdk_line, _) = lines({"nominal": ran()})
        self.assertIn("models `libs.tech/combined/sky130.lib.spice` (`_mm` sections for mismatch)", pdk_line)

    def test_the_fleet_pdk_is_the_one_the_runners_reported(self):
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk="open_pdks " + "c" * 40),
                                     "pnp": ran(runner_pdk="open_pdks " + "c" * 40)})
        self.assertEqual(prov["fleet_pdk"], "open_pdks " + "c" * 40)
        self.assertIn("the fleet runners that executed the grid reported `open_pdks "
                      + "c" * 40 + "`", pdk_line)

    def test_the_client_resolved_pdk_is_never_cited_as_the_fleet_s(self):
        """`provenance.pdk` is what the *client* resolved; citing it would make an
        unverified fleet read as pinned -- the stated-not-observed claim #312 removes."""
        runner, client = "open_pdks " + "c" * 40, "open_pdks " + "9" * 40
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=runner, client_pdk=client)})
        self.assertEqual(prov["fleet_pdk"], runner)
        self.assertIn(runner, pdk_line)
        self.assertNotIn(client, pdk_line)

    def test_a_runner_that_reports_no_stamp_is_unknown_not_the_client_s(self):
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=None, client_pdk="open_pdks " + "9" * 40)})
        self.assertEqual(prov["fleet_pdk"], "unknown")
        self.assertIn("reported `unknown`", pdk_line)
        self.assertNotIn("9" * 40, pdk_line)

    def test_disagreeing_fleet_pdks_are_both_reported(self):
        _, (pdk_line, _) = lines({"nominal": ran(runner_pdk="open_pdks " + "c" * 40),
                                  "pnp": ran(runner_pdk="open_pdks " + "d" * 40)})
        self.assertIn("open_pdks " + "c" * 40 + ", open_pdks " + "d" * 40, pdk_line)

    def test_the_host_half_is_never_presented_as_the_fleet_s(self):
        """Both halves are named, and the host's commit is not offered as the grid's."""
        _, (pdk_line, _) = lines({"nominal": ran(runner_pdk=None)}, pdk=_Pdk(installed_commit="e" * 40))
        host, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn("e" * 40, host)
        self.assertNotIn("e" * 40, fleet_half)


class FleetPinVerdictLineTest(unittest.TestCase):
    """Issue #333: the PDK line states how the runners' stamp compares with the pin.

    These fixtures were already shaped for it: `RUNNER_PDK` is `a`*40 while
    `PIN["open_pdks_commit"]` and `CLIENT_PDK` are both `f`*40, so the default stub is a
    runner OFF the pin whose client is ON it.  A verdict taken from the client -- the
    #312/#328 defect -- would read `match` on every one of these.
    """

    ON_PIN = "open_pdks " + PIN["open_pdks_commit"]

    def test_a_runner_off_the_pin_is_a_mismatch_even_though_the_client_matches(self):
        prov, (pdk_line, _) = lines({"nominal": ran()})
        self.assertEqual(prov["fleet_matches_pin"], "mismatch")
        _, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn("MISMATCH", fleet_half)

    def test_a_runner_on_the_pin_is_a_match(self):
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=self.ON_PIN)})
        self.assertEqual(prov["fleet_matches_pin"], "match")
        _, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn(sim_common.pin_state(True), fleet_half)
        self.assertNotIn("MISMATCH", fleet_half)

    def test_a_runner_that_stamped_nothing_is_not_reported_not_a_mismatch(self):
        """36 fleet jobs, none of which said what they ran: unverifiable, not wrong."""
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=None, client_pdk=self.ON_PIN)})
        self.assertEqual(prov["fleet_matches_pin"], "not-reported")
        _, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn(sim_common.fleet_pin_state("not-reported"), fleet_half)
        self.assertNotIn("MISMATCH", fleet_half)

    def test_a_mixed_set_across_terms_is_a_mismatch(self):
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=self.ON_PIN), "pnp": ran()})
        self.assertEqual(prov["fleet_matches_pin"], "mismatch")
        self.assertIn("MISMATCH", pdk_line.split("; the fleet runners", 1)[1])

    def test_the_verdict_sits_beside_the_coverage_note_not_instead_of_it(self):
        """Partial coverage and the verdict answer different questions: how many jobs
        spoke, and whether what they said is the pin."""
        prov, (pdk_line, _) = lines({"nominal": ran(runner_pdk=self.ON_PIN),
                                     "pnp": ran(runner_pdk=None)})
        self.assertEqual(prov["fleet_matches_pin"], "match")
        self.assertEqual((prov["fleet_pdk_jobs"], prov["fleet_pdk_reporting"]), (2, 1))
        self.assertIn("from 1 of 2 fleet jobs", pdk_line)
        self.assertIn(sim_common.pin_state(True), pdk_line.split("; the fleet runners", 1)[1])

    def test_the_line_states_what_an_equal_commit_does_not_establish(self):
        _, (pdk_line, _) = lines({"nominal": ran(runner_pdk=self.ON_PIN)})
        self.assertIn(sim_common.PIN_COMMIT_LIMIT, pdk_line)

    def test_the_two_halves_keep_their_own_verdicts(self):
        """The host's bool and the fleet's three-state are about different machines."""
        _, (pdk_line, _) = lines({"nominal": ran(runner_pdk=self.ON_PIN)},
                                 pdk=_Pdk(matches_pin=False, installed_commit="b" * 40))
        host, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn("MISMATCH", host)                         # the HOST is off the pin
        self.assertIn(sim_common.pin_state(True), fleet_half)   # the FLEET is on it
        self.assertNotIn("MISMATCH", fleet_half)


class ToolsLineTest(unittest.TestCase):
    def test_client_klt_and_backend_are_the_caller_s_own_strings(self):
        _, (_, tools) = lines({"nominal": ran()}, klt="klt 1.2.3", backend="local")
        self.assertTrue(tools.startswith("- **Tools**: klt 1.2.3 (client); backend `local`;"), tools)

    def test_fleet_job_ids_are_still_listed(self):
        _, (_, tools) = lines({"nominal": ran(job="klt-sim-aaa"), "pnp": ran(job="klt-sim-bbb")})
        self.assertIn("fleet jobs: nominal[all]=klt-sim-aaa, pnp[all]=klt-sim-bbb", tools)

    def test_a_record_with_no_usable_report_still_renders(self):
        """A run the fleet refused outright is still a valid (NOT-RUN) record."""
        prov, both = lines({"nominal": not_run(), "pnp": not_run()})
        self.assertEqual(len(both), 2)
        self.assertEqual(prov["fleet_pdk"], "unknown")
        self.assertEqual(prov["fleet_engine"], "unknown")
        self.assertEqual((prov["fleet_pdk_jobs"], prov["fleet_engine_jobs"]), (0, 0))
        self.assertTrue(both[1].endswith("fleet jobs: "), both[1])


class RenderedLinesCarryNoLiteralTest(unittest.TestCase):
    """Whatever the inputs, the rendered lines may only contain versions that came in
    through them -- the source-level counterpart lives in
    `sim/bin/test_sim_common_provenance.py` (`RunnerVersionLiteralTest`)."""

    def test_every_version_token_traces_to_an_input(self):
        _, both = lines({"nominal": ran(engine="46")}, klt="klayout-tools 0.9.0")
        for line in both:
            for token in re.findall(r"\b\d+\.\d+\.\d+\b", line):
                self.assertEqual(token, "0.9.0", f"untraceable version {token!r} in {line!r}")
            for token in re.findall(r"ngspice-\d+", line):
                self.assertEqual(token, "ngspice-46", line)

    def test_nothing_observed_leaves_no_version_token_anywhere(self):
        """The regression this change exists to prevent: with no fleet data at all, no
        commit, engine or instance may appear in either line."""
        _, (pdk_line, tools) = lines({"nominal": not_run()}, pdk=_Pdk(installed_commit="a" * 40))
        fleet_half = pdk_line.split("; the fleet runners", 1)[1]
        tools_fleet = tools.split("(client);", 1)[1]
        for line in (fleet_half, tools_fleet):
            self.assertNotRegex(line, r"ngspice-\d|\b[0-9a-f]{40}\b|\b\d+\.\d+\.\d+\b",
                                f"a default version survived into {line!r}")


if __name__ == "__main__":
    unittest.main()
