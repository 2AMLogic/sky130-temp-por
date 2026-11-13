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
`RunnerVersionLiteralTest` in `sim/bin/test_sim_common_provenance.py`.

Stdlib only: no SPICE, no PDK, no run directory, no record written.

Run: python3 -I sim/temp-core-accuracy-mc/test_record_provenance.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_accuracy_mc as ram  # noqa: E402

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


def ran(engine="47", runner_pdk=RUNNER_PDK, client_pdk=CLIENT_PDK, job="klt-sim-dead"):
    """One `ents` entry for a term whose fleet jobs produced a usable report.

    The shape mirrors a real klt batch `report.json`, which carries *two* PDK values: the
    runner's own install stamp under `environment.remote.worker_environment.pdk`, and the
    client-resolved PDK under `provenance.pdk`.  They default to different commits on
    purpose, so a reader that takes the client's value fails these tests instead of
    silently reporting the wrong half (the real divergence is recorded in
    `sim/bias-core-smoke/records/20261023-171642-e69f5b2e.json`).
    """
    return {
        "report": {
            "corners": [],
            "environment": {
                "engine": "ngspice",
                "engine_version": engine,
                "remote": {
                    "job_id": job,
                    "worker_environment": {"pdk": {"variant": "sky130A", "stamp_text": runner_pdk}},
                },
            },
            "provenance": {"pdk": {"name": "sky130A", "version": client_pdk}},  # client side
        },
        "jobs": {"all": {"job_id": job}},
        "missing_procs": [],
    }


def not_run():
    """A term the fleet refused outright: no report, so nothing to observe."""
    return {"report": None, "jobs": {}, "missing_procs": []}


def lines(ents, pdk=None, klt="klayout-tools 0.9.0", backend="batch"):
    """`(pdk_line, tools_line)` for a stubbed set of term entries."""
    prov = ram.observed_provenance(ents)
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

    def test_a_report_without_a_runner_environment_is_unknown(self):
        ents = {"nominal": {"report": {"corners": []}, "jobs": {}, "missing_procs": []}}
        self.assertEqual(ram.observed_provenance(ents)["fleet_pdk"], "unknown")

    def test_the_host_half_is_never_presented_as_the_fleet_s(self):
        """Both halves are named, and the host's commit is not offered as the grid's."""
        _, (pdk_line, _) = lines({"nominal": ran(runner_pdk=None)}, pdk=_Pdk(installed_commit="e" * 40))
        host, fleet_half = pdk_line.split("; the fleet runners", 1)
        self.assertIn("e" * 40, host)
        self.assertNotIn("e" * 40, fleet_half)


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
        self.assertEqual(prov, {"fleet_pdk": "unknown", "fleet_engine": "unknown"})
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
