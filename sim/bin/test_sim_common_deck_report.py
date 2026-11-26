#!/usr/bin/env python3
"""Tests for the one deck-list report check every `decks[]` runner runs after its submit (issue #528).

Three campaign runners -- `sim/pnp-mismatch/run_pnp_mismatch.py`,
`sim/bias-core-op-branch/run_op_branch.py` and
`sim/por-bias-ok-early-assert/run_early_assert.py` -- end their batch submit the same
way: read the report `submit_prepared()` wrote, index its units, and refuse the run when
there is nothing to grade.  Each carried its own copy of that block, and each copy
re-parsed klt's stdout with an unguarded ``json.loads``.  ``submit_prepared()`` already
classifies a stdout that does not parse as ``NO-JSON``, but the re-parse never reached
the refusal that reports it: a NONEMPTY malformed report raised ``JSONDecodeError`` and
took klt's stderr with it, and only an EMPTY stdout arrived at the intended
``HarnessError``.  ``sim_common.require_deck_report()`` is now the one path from a
finished submit to ``(report, units)``.

Three layers, innermost first:

  * the helper on report fixtures written to temporary directories -- the four shapes the
    issue names (valid units, an empty unit list, empty stdout, malformed nonempty
    stdout) and the other ways a report can be unusable;
  * the issue's own experiment: ``submit_prepared()`` itself, behind a mocked
    ``subprocess.run``, then the helper on the files it wrote;
  * each of the three runners driven in-process through ``main()`` to the point where it
    stops, with PDK resolution, git state, netlisting and the artifact store stubbed: a
    refusal after exactly ONE submission with nothing recorded, and a partial report
    passed through to the campaign's own missing-unit policy.

Stdlib only: no SPICE, no PDK, no fleet, no klt, no record or manifest written.

Run: python3 -I sim/bin/test_sim_common_deck_report.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from collections import namedtuple
from pathlib import Path
from unittest import mock

BIN = Path(__file__).resolve().parent
REPO_ROOT = BIN.parent.parent
sys.path.insert(0, str(BIN))

import evidence_store  # noqa: E402
import sim_common as sc  # noqa: E402

cr = sc.load_corner_run()

# klt's own words for a submit that died before it had a report: a non-zero exit, a
# stdout that is not JSON, and the diagnostic on stderr (issue #528's reproduction).
EXIT = 2
STDERR = 'Traceback (most recent call last):\n  File "klt", line 1\nklt: fleet refused the job\n'
DIAGNOSTIC = "klt: fleet refused the job"
OUTCOME = {"exit": EXIT, "status": "NO-JSON"}


def unit(uid: str) -> dict:
    return {"id": uid, "status": "pass", "exit_code": 0, "timed_out": False,
            "stdout": f"{uid}/stdout.bin", "stderr": f"{uid}/stderr.bin"}


def deck_report(*units: dict) -> str:
    """klt's `--format json` stdout for a `decks[]` job that ran `units`."""
    return json.dumps({"schema_version": 3, "mode": "decks", "status": "pass", "outdir": "/nonexistent/out",
                       "unit_count": len(units), "passed": len(units), "errored": 0, "timed_out": 0,
                       "units": list(units)})


def submitted(td: Path, stdout: str, stderr: str | None = STDERR) -> Path:
    """A request directory holding what `submit_prepared()` leaves behind."""
    d = Path(td) / "run" / "batch"
    d.mkdir(parents=True)
    (d / "request.json").write_text("{}\n")
    (d / "report.json").write_text(stdout)
    if stderr is not None:
        (d / "klt.stderr").write_text(stderr)
    return d


def klt_sim(stdout: str, stderr: str = STDERR, returncode: int = EXIT) -> subprocess.CompletedProcess:
    """What `subprocess.run()` hands back for the ONE `klt sim` of a driven run."""
    return subprocess.CompletedProcess(["klt", "sim"], returncode, stdout, stderr)


# --------------------------------------------------------------------------
# the helper, on report fixtures
# --------------------------------------------------------------------------


class RequireDeckReportTest(unittest.TestCase):
    def require(self, stdout: str) -> tuple[dict, dict[str, dict]]:
        with tempfile.TemporaryDirectory() as td:
            return sc.require_deck_report(submitted(td, stdout), dict(OUTCOME))

    def refusal(self, stdout: str, stderr: str | None = STDERR) -> Exception:
        """The refusal for `stdout`, after asserting it is a `HarnessError` and nothing else."""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(cr.HarnessError) as caught:
                sc.require_deck_report(submitted(td, stdout, stderr), dict(OUTCOME))
        return caught.exception

    def test_valid_report_returns_the_report_and_its_units(self):
        report, units = self.require(deck_report(unit("u1"), unit("u2")))
        self.assertEqual(report, json.loads(deck_report(unit("u1"), unit("u2"))))
        self.assertEqual(list(units), ["u1", "u2"])
        self.assertEqual(units["u2"], unit("u2"))

    def test_empty_unit_list_is_refused(self):
        self.refusal(deck_report())

    def test_a_report_without_units_is_refused(self):
        """klt's own error envelope is a JSON object that indexes nothing."""
        self.refusal(json.dumps({"error": {"code": "batch_no_capacity", "message": "fleet refused the job"}}))

    def test_empty_stdout_is_refused_with_the_stderr(self):
        """The one shape that already reached the refusal before #528; it still does."""
        self.assertIn(DIAGNOSTIC, str(self.refusal("")))

    def test_malformed_nonempty_stdout_is_refused_with_the_stderr(self):
        """The defect: this stdout used to raise `JSONDecodeError` and drop the stderr."""
        self.assertIn(DIAGNOSTIC, str(self.refusal("runner unavailable")))

    def test_json_that_is_not_an_object_is_refused(self):
        for stdout in ("[]", "[{}]", "42", '"runner unavailable"', "null", "true"):
            with self.subTest(stdout=stdout):
                self.refusal(stdout)

    def test_units_that_is_not_a_list_is_refused(self):
        for units in (None, 5, {"u1": unit("u1")}, "u1"):
            with self.subTest(units=units):
                self.refusal(json.dumps({"status": "pass", "units": units}))

    def test_units_without_an_id_are_refused(self):
        self.refusal(json.dumps({"status": "pass", "units": [1, None, {"status": "pass"}, {"id": ""}]}))

    def test_units_with_unusable_ids_are_refused_not_indexed(self):
        for bad in (["p0"], {"k": "v"}, 42, True, 1.5, ""):
            with self.subTest(id=bad):
                self.refusal(json.dumps({"status": "pass", "units": [{"id": bad}]}))

    def test_valid_units_pass_through_beside_malformed_ids(self):
        mixed = json.dumps({"status": "pass", "units": [{"id": ["p0"]}, {"id": 42}, unit("ok"), {"id": {}}]})
        _, units = self.require(mixed)
        self.assertEqual(list(units), ["ok"])

    def test_missing_report_is_refused_not_a_file_error(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(cr.HarnessError):
                sc.require_deck_report(Path(td) / "never-submitted", dict(OUTCOME))

    def test_missing_stderr_does_not_mask_the_refusal(self):
        err = str(self.refusal("runner unavailable", stderr=None))
        self.assertIn("NOT falling back to a local grid", err)
        self.assertIn("klt stderr: \n", err)

    def test_the_refusal_is_the_harness_error_every_runner_catches(self):
        """One class per process (issue #304): `sim_common` and the runners resolve the same
        `corner-run.py`, so what is raised here is what `except cr.HarnessError` catches."""
        err = self.refusal("runner unavailable")
        self.assertIs(type(err), cr.HarnessError)
        self.assertNotIsInstance(err, ValueError)  # a `JSONDecodeError` is one

    def test_refusal_names_exit_status_stderr_and_request(self):
        with tempfile.TemporaryDirectory() as td:
            d = submitted(td, "runner unavailable")
            with self.assertRaises(cr.HarnessError) as caught:
                sc.require_deck_report(d, {"exit": 2, "status": "NO-JSON"})
        self.assertEqual(
            str(caught.exception),
            "batch submit produced no usable deck report (klt exit 2, report status NO-JSON); "
            "NOT falling back to a local grid.\n"
            f"  klt stderr: {STDERR.strip()}\n"
            f"  request:    {d / 'request.json'}",
        )

    def test_the_submit_summary_is_read_not_reshaped(self):
        with tempfile.TemporaryDirectory() as td:
            outcome = {"exit": 2, "status": "NO-JSON"}
            with self.assertRaises(cr.HarnessError):
                sc.require_deck_report(submitted(td, "runner unavailable"), outcome)
            self.assertEqual(outcome, {"exit": 2, "status": "NO-JSON"})

    def test_stderr_is_stripped_and_bounded(self):
        err = str(self.refusal("runner unavailable", stderr="\n\n" + "x" * 5000 + "\n"))
        self.assertIn(f"klt stderr: {'x' * sc.DECK_STDERR_CAP}\n", err)
        self.assertNotIn("x" * (sc.DECK_STDERR_CAP + 1), err)

    def test_cap_is_overridable(self):
        with tempfile.TemporaryDirectory() as td:
            d = submitted(td, "runner unavailable", stderr="y" * 5000)
            with self.assertRaises(cr.HarnessError) as caught:
                sc.require_deck_report(d, dict(OUTCOME), cap=50)
        self.assertIn(f"klt stderr: {'y' * 50}\n", str(caught.exception))

    def test_raw_report_bytes_are_left_as_written(self):
        """`report.json` is what klt printed: the operator's evidence of what the fleet said."""
        for stdout in ("runner unavailable", deck_report(unit("u1"))):
            with self.subTest(stdout=stdout), tempfile.TemporaryDirectory() as td:
                d = submitted(td, stdout)
                before = ((d / "report.json").read_bytes(), (d / "klt.stderr").read_bytes())
                try:
                    sc.require_deck_report(d, dict(OUTCOME))
                except cr.HarnessError:
                    pass
                self.assertEqual(((d / "report.json").read_bytes(), (d / "klt.stderr").read_bytes()), before)

    def test_a_partial_report_is_passed_through(self):
        """Which requested ids came back is each campaign's business, not the shared check's."""
        report, units = self.require(deck_report(unit("only-one-of-six")))
        self.assertEqual(list(units), ["only-one-of-six"])
        self.assertEqual(report["status"], "pass")


# --------------------------------------------------------------------------
# the issue's experiment: submit_prepared() itself, then the helper on what it wrote
# --------------------------------------------------------------------------


class AfterSubmitPreparedTest(unittest.TestCase):
    def submit(self, td: str, proc: subprocess.CompletedProcess):
        d = Path(td) / "run" / "batch"
        with mock.patch.object(sc.subprocess, "run", return_value=proc) as run:
            outcome = sc.submit_prepared(d, None, {"decks": [{"id": "u1", "deck": "u1/deck.spice"}]},
                                         "msg", "label")
        return d, outcome, run

    def test_malformed_stdout_refuses_with_the_fleet_diagnostic(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            d, outcome, run = self.submit(td, klt_sim("runner unavailable", stderr="example diagnostic"))
            self.assertEqual(outcome, {"exit": 2, "status": "NO-JSON"})
            self.assertEqual(run.call_count, 1)
            with self.assertRaises(cr.HarnessError) as caught:
                sc.require_deck_report(d, outcome)
            self.assertEqual((d / "report.json").read_text(), "runner unavailable")
            self.assertEqual((d / "klt.stderr").read_text(), "example diagnostic")
        self.assertIn("example diagnostic", str(caught.exception))
        self.assertIn("klt exit 2, report status NO-JSON", str(caught.exception))

    def test_empty_stdout_refuses_with_the_fleet_diagnostic(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            d, outcome, _ = self.submit(td, klt_sim("", stderr="example diagnostic"))
            self.assertEqual(outcome, {"exit": 2, "status": "NO-JSON"})
            self.assertEqual((d / "report.json").read_text(), "")
            with self.assertRaises(cr.HarnessError) as caught:
                sc.require_deck_report(d, outcome)
        self.assertIn("example diagnostic", str(caught.exception))

    def test_a_valid_report_returns_its_unit(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            d, outcome, _ = self.submit(td, klt_sim(deck_report(unit("u1")), stderr="", returncode=0))
            self.assertEqual(outcome, {"exit": 0, "status": "pass"})
            report, units = sc.require_deck_report(d, outcome)
        self.assertEqual(list(units), ["u1"])
        self.assertEqual(report, json.loads(deck_report(unit("u1"))))


# --------------------------------------------------------------------------
# the three runners, each driven through main() to the point where it stops
# --------------------------------------------------------------------------


def load(path: Path, name: str):
    """Import a `run_*.py` whose filename is not an identifier-friendly module name."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


Runner = namedtuple("Runner", "mod argv partial")

#: slug -> (module, argv that submits, what the campaign does about a missing unit)
RUNNERS = {
    "pnp-mismatch": Runner(
        load(REPO_ROOT / "sim" / "pnp-mismatch" / "run_pnp_mismatch.py", "run_pnp_mismatch_mod"), [], "fails the run"),
    "bias-core-op-branch": Runner(
        load(REPO_ROOT / "sim" / "bias-core-op-branch" / "run_op_branch.py", "run_op_branch_mod"),
        ["--quick"], "fails the point"),
    "por-bias-ok-early-assert": Runner(
        load(REPO_ROOT / "sim" / "por-bias-ok-early-assert" / "run_early_assert.py", "run_early_assert_mod"),
        [], "logs it"),
}


class ReachedStore(Exception):
    """The artifact-store tripwire: the runner got past the report check and tried to record."""


GIT = {"sha": "0123abcd", "branch": "builder-test", "dirty": False}


def make_pdk() -> "cr.Pdk":
    """A PDK that matches the pin, at a root nothing will read."""
    pin = cr.load_pin()
    root = Path("/nonexistent/pdk-root")
    return cr.Pdk(pin=pin, root=root, variant="sky130A", dir=root / "sky130A",
                  installed_commit=pin["open_pdks_commit"], lib_file=root / "sky130A" / pin["ngspice_lib"])


def fake_netlist(schematic: Path, out_dir: Path, pdk) -> Path:
    """Stand in for `klt netlist`: the file `netlist_with_klt()` would have produced."""
    out_dir.mkdir(parents=True, exist_ok=True)
    produced = out_dir / (schematic.stem + ".spice")
    produced.write_text("* testbench netlist, as `klt netlist` would have written it\nV1 VDD 0 3.3\nR1 VDD 0 1k\n.end\n")
    return produced


def drive(mod, argv: list[str], proc: subprocess.CompletedProcess, tmp: Path):
    """Run `mod.main(argv)` in-process until it stops; report how far it got.

    Returns `(raised, run, store, printed)`: the exception `main()` stopped with (None when
    it returned), the `subprocess.run` mock -- its `call_count` is how many klt invocations
    the run made -- the `evidence_store.store_or_exit` tripwire, and the run's stdout.
    Everything a real run would need from this host is stubbed: the artifact-store
    preflight, PDK resolution, git state and netlisting.  Scratch goes under `tmp`, the
    staged and manifested roots point there too, and storing raises `ReachedStore`, so a
    run that should have stopped is caught before it can record anything anywhere.
    """
    printed = io.StringIO()
    with mock.patch.object(sc.subprocess, "run", return_value=proc) as run, \
            mock.patch.object(evidence_store, "store_or_exit", side_effect=ReachedStore) as store, \
            mock.patch.object(evidence_store, "preflight_or_exit"), \
            mock.patch.object(evidence_store, "STAGE_ROOT", tmp / "stage"), \
            mock.patch.object(evidence_store, "MANIFEST_DIR", tmp / "manifests"), \
            mock.patch.object(cr, "resolve_pdk", return_value=make_pdk()), \
            mock.patch.object(cr, "git_state", return_value=dict(GIT)), \
            mock.patch.object(cr, "netlist_with_klt", side_effect=fake_netlist), \
            mock.patch.object(mod, "BUILD_DIR", tmp / "build"), \
            contextlib.redirect_stdout(printed):
        try:
            mod.main(argv)
            raised = None
        except (cr.HarnessError, ReachedStore) as err:
            raised = err
    return raised, run, store, printed.getvalue()


def evidence_listing(mod) -> list[str]:
    """Every file under the runner's record and snapshot directories: what a run appends to."""
    out = []
    for sub in ("records", "netlist-snapshots"):
        d = mod.HERE / sub
        if d.is_dir():
            out += [str(p.relative_to(mod.HERE)) for p in d.rglob("*") if p.is_file()]
    return sorted(out)


class RunnersStopAtTheSharedRefusal(unittest.TestCase):
    #: what klt printed -> the report status `submit_prepared()` records for it
    UNUSABLE = {
        "malformed nonempty stdout": ("runner unavailable", "NO-JSON"),
        "empty stdout": ("", "NO-JSON"),
        "empty unit list": (deck_report(), "pass"),
        "list unit id": (json.dumps({"status": "error", "units": [{"id": ["p0"]}]}), "error"),
        "object unit id": (json.dumps({"status": "error", "units": [{"id": {"k": "p0"}}]}), "error"),
        "numeric unit id": (json.dumps({"status": "error", "units": [{"id": 42}]}), "error"),
        "boolean unit id": (json.dumps({"status": "error", "units": [{"id": True}]}), "error"),
        "klt error envelope": (json.dumps({"error": {"code": "batch_no_capacity", "message": "fleet refused"}}), "?"),
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="deck-refuse-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_an_unusable_report_refuses_after_one_submission_with_the_fleet_diagnostic(self):
        for slug, (mod, argv, _) in RUNNERS.items():
            before = evidence_listing(mod)
            for shape, (stdout, status) in self.UNUSABLE.items():
                with self.subTest(runner=slug, report=shape):
                    raised, run, store, printed = drive(mod, argv, klt_sim(stdout), self.tmp)
                    self.assertIsInstance(raised, cr.HarnessError, f"stopped with {raised!r}")
                    msg = str(raised)
                    self.assertIn(f"klt exit {EXIT}, report status {status}", msg)
                    self.assertIn("NOT falling back to a local grid", msg)
                    self.assertIn(f"exit {EXIT}, report status {status}", printed)  # the [done] line said so too
                    self.assertEqual(run.call_count, 1, "exactly one klt invocation")
                    cmd = run.call_args.args[0]
                    self.assertEqual(cmd[:2], ["klt", "sim"])
                    self.assertIn("batch", cmd)
                    request = Path(cmd[2])
                    self.assertEqual(request.name, "request.json")
                    self.assertGreater(len(json.loads(request.read_text())["decks"]), 1)
                    self.assertIn(f"  klt stderr: {STDERR.strip()}\n  request:    {request}", msg)
                    self.assertEqual((request.parent / "report.json").read_text(), stdout)
                    self.assertEqual((request.parent / "klt.stderr").read_text(), STDERR)
                    store.assert_not_called()
                    self.assertFalse((self.tmp / "stage").exists(), "a stage directory was created")
                    self.assertFalse((self.tmp / "manifests").exists(), "a manifest was written")
                    self.assertEqual(evidence_listing(mod), before, "a record or snapshot was written")

    def test_a_partial_report_reaches_each_campaign_s_own_missing_unit_policy(self):
        """The shared check only decides whether there is anything to grade; a unit the fleet
        lost stays under the policy each campaign already had (the issue's regression risk)."""
        partial = klt_sim(deck_report(unit("a-unit-nobody-requested")), stderr="", returncode=0)
        for slug, (mod, argv, policy) in RUNNERS.items():
            with self.subTest(runner=slug, policy=policy):
                raised, run, store, printed = drive(mod, argv, partial, self.tmp)
                self.assertEqual(run.call_count, 1)
                self.assertNotIn("no usable deck report", printed + str(raised))
                if policy == "fails the run":
                    self.assertIsInstance(raised, cr.HarnessError, f"stopped with {raised!r}")
                    self.assertIn("the fleet returned no unit for", str(raised))
                    store.assert_not_called()
                else:
                    self.assertIsInstance(raised, ReachedStore, f"stopped with {raised!r}")
                    store.assert_called_once()
                    self.assertEqual(store.call_args.args[0], mod.SLUG)


# --------------------------------------------------------------------------
# Source-level regression guard: no runner may re-parse the submitted report itself
# --------------------------------------------------------------------------


class NoRunnerParsesTheReportItselfTest(unittest.TestCase):
    def main_body(self, mod) -> str:
        src = Path(mod.__file__).read_text()
        self.assertEqual(src.count("\ndef main("), 1, "the guard splits the source at `def main(`")
        return src.split("\ndef main(", 1)[1]

    def test_every_deck_list_runner_is_in_the_table(self):
        """A fourth `decks[]` runner must be added here, not given a fourth copy of the check."""
        found = {p.parent.name for p in (REPO_ROOT / "sim").glob("*/run_*.py") if "deck_request(" in p.read_text()}
        self.assertEqual(found, set(RUNNERS))

    def test_every_runner_takes_the_shared_path_in_main(self):
        for slug, (mod, _, _) in RUNNERS.items():
            with self.subTest(runner=slug):
                self.assertEqual(self.main_body(mod).count("require_deck_report("), 1)

    def test_no_runner_reads_the_report_or_the_stderr_itself_after_the_submit(self):
        """The three former copies, by the text they were written in: an unguarded re-parse
        of `report.json` and a hand-read `klt.stderr` inside `main()`."""
        for slug, (mod, _, _) in RUNNERS.items():
            with self.subTest(runner=slug):
                body = self.main_body(mod)
                self.assertNotIn('"report.json"', body)
                self.assertNotIn('"klt.stderr"', body)
                self.assertNotIn("no usable deck report", Path(mod.__file__).read_text())


if __name__ == "__main__":
    unittest.main(verbosity=2)
