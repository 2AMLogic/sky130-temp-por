#!/usr/bin/env python3
"""Tests for `manifests/check-citations.py` (issue #299). Stdlib only, no klt.

The branch under test is the attestation one: `klt signoff --attest`
envelopes record a sha256 for every file their inventory lists, but the
block manifest pins those envelopes to their *inventory* file's hash, never
to the attested sources. Nothing in the graded chain re-hashes the sources,
so editing one leaves the pin, the re-rendered report and the byte-compare
green while the envelope describes files that no longer exist — which is
how item 1 went stale for four commits and item 9 for eight files.

These cases pin the behaviour that closes it: a fresh file passes, an edited
or missing one is STALE, checks with no `content_hash` are skipped rather
than counted, attested paths resolve against the process cwd (not against
the envelope's directory, unlike the two citation shapes), an envelope with
no `attestation` block is unaffected, and a digest this script cannot
re-compute is reported as unverified rather than read as either stale or
fresh.

Run: python3 -I manifests/test_check_citations.py
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parent / "check-citations.py"

# The script's filename is not a Python identifier, so it is loaded by path
# rather than imported. Tests exercise main() in-process so they can assert
# on the exact STALE text, not merely on the exit status.
_spec = importlib.util.spec_from_file_location("check_citations", _MODULE_PATH)
cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cc)

MANIFEST = "manifests/test-manifest.json"
ENVELOPE = "manifests/attestations/item-9.json"
INVENTORY = "manifests/inventories/item-9.json"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _present(path: str, data: bytes, role: str = "testbench") -> dict:
    return {"check": "present", "role": role, "path": path,
            "passed": True, "content_hash": _sha(data)}


def _attestation_envelope(checks: list, source: str = INVENTORY) -> dict:
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "t1_item": 9,
        "source": source,
        "provenance": {"input": {"path": {"path": source, "scope": "repo"},
                                 "content_hash": _sha(b"inventory")}},
        "attestation": {
            "producer": "klt signoff --attest",
            "hash_algorithm": "sha256-raw-bytes",
            "inventory_schema_version": 1,
            "check_count": len(checks),
            "passed_count": len(checks),
            "checks": checks,
        },
    }


@contextlib.contextmanager
def _repo(files: dict, evidence: dict):
    """A temp repo root, made the process cwd, holding `files` and a manifest.

    `files` maps repo-relative paths to bytes (JSON payloads are passed as
    already-encoded bytes); `evidence` is the manifest's evidence map.
    """
    previous = Path.cwd()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        payload = dict(files)
        payload[MANIFEST] = json.dumps(
            {"kind": "block-manifest", "block": "test",
             "evidence": evidence}, indent=2).encode()
        for rel, data in payload.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        os.chdir(root)
        try:
            yield root
        finally:
            os.chdir(previous)


def _run() -> tuple:
    """main() against the temp repo's manifest; returns (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    try:
        rc = cc.main(["check-citations.py", MANIFEST])
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
    return rc, out.getvalue(), err.getvalue()


def _one_attested(checks: list, files: dict) -> dict:
    """Shorthand: a repo whose only cited envelope is an attestation one."""
    payload = dict(files)
    payload[ENVELOPE] = json.dumps(_attestation_envelope(checks)).encode()
    return payload


class AttestedFileFreshnessTest(unittest.TestCase):
    def test_fresh_file_passes_and_is_counted(self):
        body = b"print('fresh')\n"
        files = _one_attested([_present("sim/bin/sim_common.py", body)],
                              {"sim/bin/sim_common.py": body})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded file hash(es) verified fresh", out)

    def test_edited_file_is_stale(self):
        recorded = b"print('as attested')\n"
        ondisk = b"print('edited since')\n"
        files = _one_attested([_present("sim/bin/sim_common.py", recorded)],
                              {"sim/bin/sim_common.py": ondisk})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        # The line names the item, the envelope, the role, the path, and
        # both hashes — enough to act on without opening the envelope.
        self.assertIn("item 9", err)
        self.assertIn(ENVELOPE, err)
        self.assertIn("attested-testbench", err)
        self.assertIn("sim/bin/sim_common.py", err)
        self.assertIn(_sha(recorded)[len("sha256:"):], err)
        self.assertIn(hashlib.sha256(ondisk).hexdigest(), err)
        # ...and the remedy is the re-attest command, not the re-render one.
        self.assertIn("klt signoff --attest 9", err)
        self.assertIn(INVENTORY, err)

    def test_missing_file_is_stale_not_a_crash(self):
        files = _one_attested([_present("sim/gone.py", b"body\n")], {})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        self.assertIn("sim/gone.py", err)
        self.assertIn("does not exist", err)
        self.assertIn("klt signoff --attest 9", err)

    def test_paths_resolve_against_cwd_not_the_envelope_directory(self):
        """Attested paths are repo-root-relative; the citation shapes are not.

        Resolving them against `manifests/attestations/` would look for
        `manifests/attestations/design/netlist.py` and report every attested
        file as missing.
        """
        body = b"# netlist exporter\n"
        files = _one_attested([_present("design/netlist.py", body, role="source")],
                              {"design/netlist.py": body})
        with _repo(files, {"9": {"file": ENVELOPE}}) as root:
            self.assertFalse((root / "manifests/attestations/design").exists())
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded file hash(es)", out)


class SkippedCheckTest(unittest.TestCase):
    def test_command_and_pin_checks_are_skipped_not_counted(self):
        body = b"body\n"
        checks = [
            _present("sim/bin/corner-run.py", body),
            {"check": "command", "role": "cold_start", "cwd": ".",
             "argv": ["python3", "sim/bin/corner-run.py", "--dry-run"],
             "exit_status": 0, "passed": True},
            {"check": "pin", "role": "tools", "passed": True,
             "value": {"xschem": "3.4.7", "ngspice": "46"}},
        ]
        files = _one_attested(checks, {"sim/bin/corner-run.py": body})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        # One counted pair, not three: a check with no recorded hash claims
        # nothing this script can verify, so counting it would overstate
        # the coverage the summary line reports.
        self.assertIn("1 recorded file hash(es)", out)

    def test_envelope_with_no_attestation_block_is_unaffected(self):
        envelope = {"schema_version": 1, "kind": "generic", "status": "pass",
                    "summary": "hand-written, binds a path set",
                    "provenance": {"input": {"paths": ["layout/top.gds"]}}}
        files = {"manifests/attestations/item-2.json": json.dumps(envelope).encode()}
        with _repo(files, {"2": {"file": "manifests/attestations/item-2.json"}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("0 recorded file hash(es)", out)

    def test_malformed_attestation_shapes_do_not_crash(self):
        """A check list that is not a list, and entries this script cannot read."""
        for checks in ("not-a-list", 7, None):
            envelope = _attestation_envelope([])
            envelope["attestation"]["checks"] = checks
            files = {ENVELOPE: json.dumps(envelope).encode()}
            with _repo(files, {"9": {"file": ENVELOPE}}):
                rc, out, err = _run()
            self.assertEqual(rc, 0, "checks={!r}: {}".format(checks, err))
            self.assertIn("0 recorded file hash(es)", out)

        # Entries that are not dicts, or whose path/hash are not strings,
        # are skipped rather than crashing on a dict path (the shape
        # `provenance.input.path` actually uses in these envelopes).
        body = b"ok\n"
        checks = ["string-entry", 42, None,
                  {"check": "present", "path": {"path": "x", "scope": "repo"},
                   "content_hash": _sha(b"x")},
                  {"check": "present", "path": "sim/ok.py", "content_hash": None},
                  _present("sim/ok.py", body)]
        files = _one_attested(checks, {"sim/ok.py": body})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded file hash(es)", out)


class UnverifiableDigestTest(unittest.TestCase):
    def test_non_sha256_digest_is_reported_as_unverified(self):
        """A digest this script cannot re-compute must not read as fresh.

        It must not read as *stale* either: comparing a blake2b digest
        against a sha256 one would mismatch, and a plain STALE line would
        send someone re-attesting a file that never drifted.
        """
        body = b"body\n"
        check = _present("sim/ok.py", body)
        check["content_hash"] = "blake2b:" + hashlib.blake2b(body).hexdigest()
        envelope = _attestation_envelope([check])
        envelope["attestation"]["hash_algorithm"] = "blake2b-raw-bytes"
        files = {ENVELOPE: json.dumps(envelope).encode(), "sim/ok.py": body}
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        self.assertIn("was NOT", err)
        self.assertIn("blake2b-raw-bytes", err)
        self.assertNotIn("the evidence went stale", err)


class CitationBranchRegressionTest(unittest.TestCase):
    """The two pre-existing shapes still resolve against the envelope's directory."""

    def test_drc_artifact_branch_still_checked(self):
        gds = b"GDS-BYTES\n"
        envelope = {"schema_version": 1, "status": "clean",
                    "file": "temp_por_top.gds",
                    "provenance": {"input": {"content_hash": _sha(gds)}}}
        files = {"layout/temp_por_top/drc.json": json.dumps(envelope).encode(),
                 "layout/temp_por_top/temp_por_top.gds": gds}
        with _repo(files, {"3": {"file": "layout/temp_por_top/drc.json"}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded file hash(es)", out)

        files["layout/temp_por_top/temp_por_top.gds"] = b"REDRAWN\n"
        with _repo(files, {"3": {"file": "layout/temp_por_top/drc.json"}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("artifact", err)
        # The citation remedy, not the attestation one.
        self.assertIn("re-render the evidence", err)
        self.assertNotIn("klt signoff --attest", err)

    def test_lvs_compare_branch_still_checked(self):
        layout, reference = b"* layout\n", b"* reference\n"
        envelope = {"schema_version": 1, "status": "match",
                    "layout": "temp_por_top.spice",
                    "reference": "temp_por_top.ref.spice",
                    "environment": {
                        "layout_sha256": hashlib.sha256(layout).hexdigest(),
                        "reference_sha256": hashlib.sha256(reference).hexdigest()}}
        files = {"layout/temp_por_top/lvs.json": json.dumps(envelope).encode(),
                 "layout/temp_por_top/temp_por_top.spice": layout,
                 "layout/temp_por_top/temp_por_top.ref.spice": reference}
        with _repo(files, {"4": {"file": "layout/temp_por_top/lvs.json"}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("2 recorded file hash(es)", out)

        files["layout/temp_por_top/temp_por_top.ref.spice"] = b"* regenerated\n"
        with _repo(files, {"4": {"file": "layout/temp_por_top/lvs.json"}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("compare-reference", err)


class MixedEnvelopeTest(unittest.TestCase):
    def test_one_stale_line_per_drifted_file_across_items(self):
        """The real failure mode: several attested files drift in one envelope."""
        fresh, drifted = b"fresh\n", b"recorded\n"
        checks = [_present("sim/a.py", drifted), _present("sim/b.py", drifted),
                  _present("sim/c.py", fresh)]
        files = _one_attested(checks, {"sim/a.py": b"edited-a\n",
                                       "sim/b.py": b"edited-b\n",
                                       "sim/c.py": fresh})
        with _repo(files, {"9": {"file": ENVELOPE}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        lines = [ln for ln in err.splitlines() if "STALE" in ln]
        self.assertEqual(len(lines), 2, err)
        self.assertTrue(any("sim/a.py" in ln for ln in lines))
        self.assertTrue(any("sim/b.py" in ln for ln in lines))
        self.assertFalse(any("sim/c.py" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
