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
Two source-level guards back it up -- the record-side wiring must go through
`sim_common.fleet_pdk_fields()`, and no runner may state the fleet's PDK as unreported.

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
RUNNER_PDK = {"variant": "sky130A", "stamp_text": RUNNER_STAMP}
CLIENT_PDK = {"name": "sky130A", "version": CLIENT_STAMP, "source": "search root: ~/.ciel",
              "ambiguous_sources": ["search root: ~/.volare"]}

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
# One driver per runner: (name, source file, fn(run_dir, **report kwargs) -> fleet fields)
# --------------------------------------------------------------------------


def _brownout(run_dir: Path, **kw) -> dict:
    man = one_point_manifest(rb, supply_v=[SUPPLY])
    r = rb.plan_requests(man)[0]
    write_report(run_dir / r["tag"], **kw)
    res = rb.analyze_request(r, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields([res["info"].get("runner_pdk")])


def _glitch(run_dir: Path, **kw) -> dict:
    man = one_point_manifest(rg, supply_v=[SUPPLY])
    r = rg.plan_requests(man, rg.CLASSES[0])[0]
    write_report(run_dir / r["tag"], **kw)
    res = rg.analyze_request(r, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields([res["info"].get("runner_pdk")])


def _ramp(run_dir: Path, **kw) -> dict:
    man = one_point_manifest(rr, supply_v=[SUPPLY])
    variant = next(iter(man["variants"]))
    rate = rr.all_rates(man)[0][0]
    write_report(run_dir / variant / rr.rate_tag(rate), **kw)
    res = rr.analyze_variant(variant, run_dir, man, run_dir / "corners", write=False)
    return sim_common.fleet_pdk_fields(q.get("runner_pdk") for q in res["requests"])


def _iq_campaign(run_dir: Path, **kw) -> dict:
    man = one_point_manifest(riq, supply_v=[SUPPLY])
    state = riq.STATES[0]
    write_report(run_dir / state / sim_common.rate_tag(man["measurement"]["rate_v_per_s"]), **kw)
    res = riq.analyze_state(state, run_dir, man, {})
    return sim_common.fleet_pdk_fields([res["requests"].get("runner_pdk")])


def _iq_sensitivity(run_dir: Path, **kw) -> dict:
    man = one_point_manifest(riq, supply_v=[SUPPLY])
    name = next(iter(ris.sens(man)["variants"]))
    write_report(run_dir / name / ris.STATE / sim_common.rate_tag(man["measurement"]["rate_v_per_s"]), **kw)
    res = ris.analyze_variant(name, run_dir, man, {})
    return sim_common.fleet_pdk_fields([res["requests"].get("runner_pdk")])


def _solver(run_dir: Path, **kw) -> dict:
    """Driven at its own seam: `observed_provenance()` over one combo's loaded report."""
    combo = f"{rss.SCENARIOS[0]}__{next(iter(rss.VARIANTS))}"
    summary = {combo: {"status": "ran", "fleet": {"runner_klt_version": "0.9.1", "client_klt_version": "0.9.1"},
                       "ngspice_engine_version": "47"}}
    res = {combo: {"report": stub_report([], **kw), "points": {}}}
    prov = rss.observed_provenance(summary, res)
    return {k: prov[k] for k in ("fleet_pdk", "fleet_pdk_jobs", "fleet_pdk_reporting")}


def _accuracy_mc(run_dir: Path, **kw) -> dict:
    rep = stub_report([], **kw)
    ents = {"nominal": {"report": rep, "jobs": {"all": rep["environment"]["remote"]},
                        "engines": {"all": "47"}, "missing_procs": []}}
    prov = ram.observed_provenance(ents)
    return {k: prov[k] for k in ("fleet_pdk", "fleet_pdk_jobs", "fleet_pdk_reporting")}


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

    def fields(self, driver, **kw) -> dict:
        with tempfile.TemporaryDirectory() as td:
            return driver(Path(td), **kw)

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


class SourceGuardTest(unittest.TestCase):
    """Mechanism, not documentation: the two greps that keep the shape from returning."""

    STALE_CLAIM = re.compile(r"(?i)not reported by the runner"
                             r"|runner does not report|does not report (its |the )?pdk")

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


if __name__ == "__main__":
    unittest.main()
