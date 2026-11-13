#!/usr/bin/env python3
"""Stubbed-input tests for the solver sweep's record `PDK` / `Tools` lines (issue #306).

`run_solver_sweep.py` used to write `fleet runner klt 0.5.0` and a hardcoded open_pdks
commit into every record it produced, so a record asserted tool and PDK versions that
were not the ones observed.  `observed_provenance()` / `render_provenance_lines()` now
derive both lines from the run's own `summary` / `report.json` data, and these tests pin
the three properties that keep them honest:

  * a version appears only when a job reported it,
  * an unobserved version reads `unknown` -- never a default and never first-found-only,
  * the client/runner mismatch sentence appears only when a mismatch was observed.

Stdlib only: no SPICE, no PDK, no run directory, no record written.

Run: python3 -I sim/temp-core-startup-solver/test_record_provenance.py
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_solver_sweep as rss  # noqa: E402

PIN = {"open_pdks_commit": "f" * 40, "ngspice_lib": "libs.tech/combined/sky130.lib.spice"}


class _Pdk:
    """The four attributes `render_provenance_lines()` reads off corner-run's resolved PDK."""

    def __init__(self, matches_pin=True, installed_commit="a" * 40):
        self.variant = "sky130A"
        self.installed_commit = installed_commit
        self.matches_pin = matches_pin
        self.pin = PIN


def ran(runner="0.9.0", client="0.9.0", engine="47", instance="c7i.4xlarge", pdk_version="open_pdks " + "a" * 40):
    """One `summary` entry for a combo that ran, plus its matching `res` entry."""
    s = {
        "status": "ran",
        "fleet": {"job_id": "klt-sim-dead", "instance_type": instance, "lifecycle": "spot",
                  "runner_klt_version": runner, "client_klt_version": client, "elapsed_seconds": 1},
        "ngspice_engine_version": engine,
    }
    rep = {"report": {"provenance": {"pdk": {"name": "sky130A", "version": pdk_version}}}}
    return s, rep


def not_run():
    """A fleet refusal: `cmd_record` records no `fleet` block and no engine version."""
    return {"status": "NOT-RUN", "refusal": {"code": "batch_no_capacity"}}, {"report": None}


def build(combos, pdk=None, klt_client="klayout-tools 0.9.0", backend="batch"):
    summary = {f"c{i}": s for i, (s, _) in enumerate(combos)}
    res = {f"c{i}": r for i, (_, r) in enumerate(combos)}
    prov = rss.observed_provenance(summary, res)
    return prov, rss.render_provenance_lines(prov, pdk or _Pdk(), klt_client, backend)


class ToolsLineTest(unittest.TestCase):
    def test_versions_present_and_equal_states_no_mismatch(self):
        prov, (_, tools) = build([ran(), ran()])
        self.assertEqual(prov["klt_skew"], [])
        self.assertIn("fleet runner klt `0.9.0`", tools)
        self.assertIn("fleet `ngspice-47`", tools)
        self.assertIn("on Spot `c7i.4xlarge`", tools)
        self.assertIn("backend `batch`", tools)
        self.assertNotIn("mismatch", tools)

    def test_runner_differs_from_client_states_the_mismatch(self):
        prov, (_, tools) = build([ran(runner="0.5.0", client="0.7.0"), ran()])
        self.assertEqual(prov["klt_skew"], [("0.5.0", "0.7.0")])
        self.assertIn("client/runner klt mismatch warning observed", tools)
        self.assertIn("runner 0.5.0 vs client 0.7.0", tools)
        # ...and the runner klt is the observed SET, not whichever job came first
        self.assertIn("fleet runner klt `0.5.0, 0.9.0`", tools)

    def test_nothing_observed_is_unknown_not_a_default_version(self):
        """The regression this change exists to prevent."""
        _, (pdk_line, tools) = build([not_run(), not_run()])
        self.assertIn("fleet `unknown`", tools)
        self.assertIn("on Spot `unknown`", tools)
        self.assertIn("fleet runner klt `unknown`", tools)
        self.assertIn("announced `unknown`", pdk_line)
        self.assertNotIn("mismatch", tools)
        # The client's own klt string is a legitimate input and stays; nothing about the
        # FLEET may carry a version when no job reported one.
        fleet_half = tools.split("(client);", 1)[1]
        for line in (pdk_line, fleet_half):
            self.assertNotRegex(line, r"ngspice-\d|\b\d+\.\d+\.\d+\b|c7i|m7i",
                                f"a default version survived into {line!r}")

    def test_all_combos_not_run_renders_without_raising(self):
        """A record in which the fleet refused every combo is still a valid record."""
        prov, lines = build([not_run()] * 10)
        self.assertEqual(len(lines), 2)
        self.assertEqual(prov["fleet_ngspice"], "unknown")
        self.assertEqual(prov["fleet_pdk"], "unknown")

    def test_partial_run_reports_only_what_ran(self):
        prov, (_, tools) = build([ran(engine="46"), not_run(), ran(engine="47", instance="m7i.4xlarge")])
        self.assertEqual(prov["fleet_ngspice"], "ngspice-46, ngspice-47")
        self.assertIn("on Spot `c7i.4xlarge, m7i.4xlarge`", tools)

    def test_a_job_missing_a_field_does_not_invent_one(self):
        prov, (_, tools) = build([ran(runner=None, engine=None, instance=None)])
        self.assertEqual(prov["fleet_runner_klt"], "unknown")
        self.assertEqual(prov["fleet_ngspice"], "unknown")
        self.assertEqual(prov["klt_skew"], [])  # no runner version => nothing to compare
        self.assertIn("fleet runner klt `unknown`", tools)

    def test_client_klt_is_the_caller_s_own_string(self):
        _, (_, tools) = build([ran()], klt_client="klt 1.2.3")
        self.assertTrue(tools.startswith("- **Tools**: klt 1.2.3 (client);"), tools)


class PdkLineTest(unittest.TestCase):
    def test_matching_pin_uses_the_shared_ternary_wording(self):
        _, (pdk_line, _) = build([ran()], pdk=_Pdk(matches_pin=True))
        self.assertIn("sky130A @ open_pdks `" + "a" * 40 + "` (matches sim/pdk.json pin)", pdk_line)
        self.assertIn("models `libs.tech/combined/sky130.lib.spice`", pdk_line)
        self.assertIn("on the host that wrote this record", pdk_line)

    def test_mismatching_pin_is_flagged_not_asserted_as_a_match(self):
        _, (pdk_line, _) = build([ran()], pdk=_Pdk(matches_pin=False, installed_commit="b" * 40))
        self.assertIn("**MISMATCH vs sim/pdk.json pin**", pdk_line)
        self.assertNotIn("(matches sim/pdk.json pin)", pdk_line)
        self.assertIn("b" * 40, pdk_line)

    def test_the_fleet_pdk_is_the_one_the_jobs_announced(self):
        """The grid ran on the fleet, so the fleet's own report is reported separately
        from the recording host's install -- neither stands in for the other."""
        _, (pdk_line, _) = build([ran(pdk_version="open_pdks " + "c" * 40), ran(pdk_version="open_pdks " + "c" * 40)])
        self.assertIn("the fleet jobs' own `report.json` announced `open_pdks " + "c" * 40 + "`", pdk_line)

    def test_disagreeing_fleet_pdks_are_both_reported(self):
        _, (pdk_line, _) = build([ran(pdk_version="open_pdks " + "c" * 40), ran(pdk_version="open_pdks " + "d" * 40)])
        self.assertIn("open_pdks " + "c" * 40 + ", open_pdks " + "d" * 40, pdk_line)

    def test_a_report_without_provenance_is_unknown(self):
        summary = {"c0": ran()[0]}
        res = {"c0": {"report": {"corners": []}}}
        prov = rss.observed_provenance(summary, res)
        self.assertEqual(prov["fleet_pdk"], "unknown")


class RenderedLinesCarryNoLiteralTest(unittest.TestCase):
    """Whatever the inputs, the rendered lines may only contain versions that came in
    through them -- the source-level counterpart lives in
    `sim/bin/test_sim_common_provenance.py` (`RunnerVersionLiteralTest`)."""

    def test_every_version_token_traces_to_an_input(self):
        _, lines = build([ran(runner="0.5.0", client="0.7.0", engine="46", instance="c7i.4xlarge")])
        allowed = {"0.5.0", "0.7.0", "0.9.0"}  # runner, client, and the stub klt_client
        for line in lines:
            for token in re.findall(r"\b\d+\.\d+\.\d+\b", line):
                self.assertIn(token, allowed, f"untraceable version {token!r} in {line!r}")
            for token in re.findall(r"ngspice-\d+", line):
                self.assertEqual(token, "ngspice-46", line)


if __name__ == "__main__":
    unittest.main()
