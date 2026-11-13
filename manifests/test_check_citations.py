#!/usr/bin/env python3
"""Tests for `manifests/check-citations.py` (issues #299, #303). Stdlib only, no klt.

The script re-hashes the committed artifacts a cited evidence envelope
recorded a sha256 for, closing the one rot path the graded chain cannot
see: `klt signoff --manifest` compares a citation against the hash the
envelope *recorded*, never against the file on disk, so a layout or netlist
that changes without its envelope being re-rendered leaves the manifest,
the pin and the byte-compared report all green.

Two citation shapes are in scope, and both resolve their artifacts against
the **envelope's own directory**:

- a `klt drc` / `klt extract` envelope's top-level `file` against
  `provenance.input.content_hash`;
- a `klt lvs` envelope's `layout` / `reference` netlists against
  `environment.layout_sha256` / `reference_sha256` — the only machine
  freshness gate an LVS citation has, since its shape carries no
  `provenance.input.content_hash` for a manifest pin to bind to.

`klt signoff --attest` envelopes are deliberately **out** of scope since
#303: items 1, 9 and 10 mark their toolchain-bound commands
`"local_only": true`, so `klt signoff --attest N ... --check` now runs
unconditionally in CI — skipping only the command, never the file hashes —
and its gate is a strict superset of the per-file re-hash #299 added here.
`test_attestation_envelope_is_not_rehashed_here` pins that boundary so the
branch is not quietly reintroduced alongside klt's own check.

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
DRC = "layout/temp_por_top/drc.json"
LVS = "layout/temp_por_top/lvs.json"


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


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


def _drc_envelope(gds: bytes) -> bytes:
    return json.dumps({"schema_version": 1, "status": "clean",
                       "file": "temp_por_top.gds",
                       "provenance": {"input": {"content_hash": _sha(gds)}}}).encode()


def _lvs_envelope(layout: bytes, reference: bytes) -> bytes:
    return json.dumps({
        "schema_version": 1, "status": "match",
        "layout": "temp_por_top.spice",
        "reference": "temp_por_top.ref.spice",
        "environment": {
            "layout_sha256": hashlib.sha256(layout).hexdigest(),
            "reference_sha256": hashlib.sha256(reference).hexdigest()}}).encode()


class DrcArtifactBranchTest(unittest.TestCase):
    """A `file` + `provenance.input.content_hash` citation (items 3, 11)."""

    def test_fresh_artifact_passes_and_is_counted(self):
        gds = b"GDS-BYTES\n"
        files = {DRC: _drc_envelope(gds),
                 "layout/temp_por_top/temp_por_top.gds": gds}
        with _repo(files, {"3": {"file": DRC}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded artifact hash(es)", out)

    def test_redrawn_artifact_is_stale(self):
        gds = b"GDS-BYTES\n"
        files = {DRC: _drc_envelope(gds),
                 "layout/temp_por_top/temp_por_top.gds": b"REDRAWN\n"}
        with _repo(files, {"3": {"file": DRC}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        # The line names the item, the envelope, the role, both hashes and
        # the remedy — enough to act on without opening the envelope.
        self.assertIn("item 3", err)
        self.assertIn(DRC, err)
        self.assertIn("artifact", err)
        self.assertIn(_sha(gds)[len("sha256:"):], err)
        self.assertIn(hashlib.sha256(b"REDRAWN\n").hexdigest(), err)
        self.assertIn("re-render the evidence", err)

    def test_missing_artifact_is_stale_not_a_crash(self):
        files = {DRC: _drc_envelope(b"GDS-BYTES\n")}
        with _repo(files, {"3": {"file": DRC}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("STALE", err)
        self.assertIn("does not exist", err)

    def test_artifact_resolves_against_the_envelope_directory(self):
        """`file` is relative to the envelope, not to the repo root.

        Resolving it against the process cwd would look for `temp_por_top.gds`
        at the root and report a present artifact as missing.
        """
        gds = b"GDS-BYTES\n"
        files = {DRC: _drc_envelope(gds),
                 "layout/temp_por_top/temp_por_top.gds": gds}
        with _repo(files, {"3": {"file": DRC}}) as root:
            self.assertFalse((root / "temp_por_top.gds").exists())
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("1 recorded artifact hash(es)", out)


class LvsCompareBranchTest(unittest.TestCase):
    """Both halves of an unpinned LVS compare (items 4, 11)."""

    def test_both_netlists_are_counted(self):
        layout, reference = b"* layout\n", b"* reference\n"
        files = {LVS: _lvs_envelope(layout, reference),
                 "layout/temp_por_top/temp_por_top.spice": layout,
                 "layout/temp_por_top/temp_por_top.ref.spice": reference}
        with _repo(files, {"4": {"file": LVS}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("2 recorded artifact hash(es)", out)

    def test_regenerated_reference_is_stale(self):
        layout, reference = b"* layout\n", b"* reference\n"
        files = {LVS: _lvs_envelope(layout, reference),
                 "layout/temp_por_top/temp_por_top.spice": layout,
                 "layout/temp_por_top/temp_por_top.ref.spice": b"* regenerated\n"}
        with _repo(files, {"4": {"file": LVS}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("compare-reference", err)
        self.assertNotIn("compare-layout", err)

    def test_bare_hex_digest_compares_without_a_sha256_prefix(self):
        """`environment.*_sha256` records bare hex, unlike a pinned citation."""
        layout, reference = b"* layout\n", b"* reference\n"
        envelope = json.loads(_lvs_envelope(layout, reference))
        self.assertFalse(envelope["environment"]["layout_sha256"].startswith("sha256:"))
        files = {LVS: json.dumps(envelope).encode(),
                 "layout/temp_por_top/temp_por_top.spice": layout,
                 "layout/temp_por_top/temp_por_top.ref.spice": reference}
        with _repo(files, {"4": {"file": LVS}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("2 recorded artifact hash(es)", out)


class UnmappedEnvelopeTest(unittest.TestCase):
    def test_attestation_envelope_is_not_rehashed_here(self):
        """#303: `klt signoff --attest ... --check` owns attested files now.

        Items 1, 9 and 10 mark their toolchain-bound commands `local_only`,
        so CI runs `--check` for all three unconditionally and klt re-hashes
        every inventoried file itself (and diffs the pin, the check count and
        every committed outcome besides). A second, repo-owned re-hash of
        `attestation.checks[]` here would be two mechanisms for one
        behaviour, so an attested file that drifted is *not* this script's
        finding: it counts nothing and stays green.
        """
        recorded, ondisk = b"print('as attested')\n", b"print('edited since')\n"
        envelope = {
            "schema_version": 1, "kind": "generic", "status": "pass",
            "t1_item": 9, "source": "manifests/inventories/item-9.json",
            "provenance": {"input": {"content_hash": _sha(b"inventory")}},
            "attestation": {
                "producer": "klt signoff --attest",
                "hash_algorithm": "sha256-raw-bytes",
                "check_count": 1, "passed_count": 1,
                "checks": [{"check": "present", "role": "testbench",
                            "path": "sim/bin/sim_common.py", "passed": True,
                            "content_hash": _sha(recorded)}],
            },
        }
        files = {"manifests/attestations/item-9.json": json.dumps(envelope).encode(),
                 "sim/bin/sim_common.py": ondisk}
        with _repo(files, {"9": {"file": "manifests/attestations/item-9.json"}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("0 recorded artifact hash(es)", out)
        self.assertNotIn("STALE", err)

    def test_envelope_with_no_recognized_shape_is_unaffected(self):
        envelope = {"schema_version": 1, "kind": "generic", "status": "pass",
                    "summary": "hand-written, binds a path set",
                    "provenance": {"input": {"paths": ["layout/top.gds"]}}}
        files = {"manifests/attestations/item-2.json": json.dumps(envelope).encode()}
        with _repo(files, {"2": {"file": "manifests/attestations/item-2.json"}}):
            rc, out, err = _run()
        self.assertEqual(rc, 0, err)
        self.assertIn("0 recorded artifact hash(es)", out)

    def test_half_recorded_shapes_do_not_crash(self):
        """A `file`/`layout` with no recorded hash, and a hash with no file."""
        for envelope in (
            {"schema_version": 1, "file": "temp_por_top.gds"},
            {"schema_version": 1, "provenance": {"input": {"content_hash": _sha(b"x")}}},
            {"schema_version": 1, "layout": "a.spice", "environment": {}},
            {"schema_version": 1, "environment": {"layout_sha256": "deadbeef"}},
            {"schema_version": 1, "provenance": None, "environment": None},
        ):
            files = {DRC: json.dumps(envelope).encode()}
            with _repo(files, {"3": {"file": DRC}}):
                rc, out, err = _run()
            self.assertEqual(rc, 0, "{!r}: {}".format(envelope, err))
            self.assertIn("0 recorded artifact hash(es)", out)

    def test_unreadable_envelope_fails_loudly(self):
        files = {DRC: b"{not json"}
        with _repo(files, {"3": {"file": DRC}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        self.assertIn("cannot be read", err)
        self.assertIn(DRC, err)


class MixedEnvelopeTest(unittest.TestCase):
    def test_one_stale_line_per_drifted_artifact_across_items(self):
        """The real failure mode: several citations drift in one commit."""
        gds, layout, reference = b"GDS-BYTES\n", b"* layout\n", b"* reference\n"
        files = {DRC: _drc_envelope(gds),
                 "layout/temp_por_top/temp_por_top.gds": b"REDRAWN\n",
                 LVS: _lvs_envelope(layout, reference),
                 "layout/temp_por_top/temp_por_top.spice": b"* re-extracted\n",
                 "layout/temp_por_top/temp_por_top.ref.spice": reference}
        with _repo(files, {"3": {"file": DRC}, "4": {"file": LVS}}):
            rc, _out, err = _run()
        self.assertEqual(rc, 1)
        lines = [ln for ln in err.splitlines() if "STALE" in ln]
        self.assertEqual(len(lines), 2, err)
        self.assertTrue(any("item 3" in ln and "artifact" in ln for ln in lines))
        self.assertTrue(any("item 4" in ln and "compare-layout" in ln for ln in lines))
        self.assertFalse(any("compare-reference" in ln for ln in lines))


if __name__ == "__main__":
    unittest.main()
