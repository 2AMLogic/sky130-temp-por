#!/usr/bin/env python3
"""Live-artifact freshness for `klt signoff` block-manifest citations.

`klt signoff --manifest` grades a citation's freshness against the hash the
cited envelope *recorded* (`provenance.input.content_hash`) and against the
manifest's pinned `content_hash` — it never re-hashes the artifact on disk.
That leaves one rot path nothing in the graded chain covers: a design or
layout file that changes *without* its evidence envelope being re-rendered
keeps its old recorded hash, so the manifest, the pin, and the committed
report all still agree — with each other, and with an artifact that no
longer exists.

This script closes that gap for every envelope cited by the block manifest
(`sky130-temp-por.json`): it re-hashes the committed files each cited
envelope recorded hashes for, and requires equality. Today that is:

- a `klt drc` / `klt extract` envelope's top-level ``file`` (resolved
  against the envelope's own directory) against its
  ``provenance.input.content_hash`` — the drawn layout stream;
- a `klt lvs` envelope's ``layout`` and ``reference`` netlists against its
  ``environment.layout_sha256`` / ``environment.reference_sha256`` — the two
  halves of the compare. The LVS envelope shape carries no
  ``provenance.input.content_hash`` a manifest pin could bind to
  (`klt signoff` cannot pin it), so this re-hash is the only machine
  freshness gate an LVS citation has;
- a `klt signoff --attest` envelope's ``attestation.checks[]`` entries that
  carry both ``path`` and ``content_hash`` — the design sources, testbenches
  and hygiene files items 1, 9 and 10 attest (issue #299). Those paths are
  repo-root-relative (the same envelope's ``command`` checks record
  ``cwd: "."``), so they resolve against the process cwd, **not** against the
  envelope's own directory like the two citation shapes above.

The attestation branch covers a gap the rest of the chain structurally
cannot: the manifest pins an attestation envelope to its *inventory* file's
hash, never to the attested sources, so editing an attested source leaves
the pin, the re-rendered report and the byte-compare all green while the
envelope describes files that no longer exist. Before #299 this was not
hypothetical — item 1's `design/netlist.py` had been stale on `main` since
`6d11c6ec`, and 8 of item 9's 40 recorded files were stale, with no job red.
CI still cannot re-run the ``command`` checks of items 1 and 9 (those need
xschem and the sky130 PDK, which a stock runner has not), but it can and now
does re-hash every file those envelopes recorded a hash for.

Checks carrying no ``content_hash`` (``command``, ``pin``) are skipped: they
claim something this script cannot re-verify, so counting them would
overstate the coverage. An envelope with no ``attestation`` block is
unaffected.

Exit 0 prints one summary line naming the count of verified hash pairs;
exit 1 prints one ``STALE`` line per drifted or missing file, each naming
the item, the envelope, the role, the path, the recorded hash, the actual
hash, and the command that repairs it. Other envelope kinds are recognized
but skipped: a citation this script cannot map to on-disk files claims
nothing about them either way.

Run:   python3 manifests/check-citations.py manifests/sky130-temp-por.json
Tests: python3 -I manifests/test_check_citations.py
"""

import hashlib
import json
import sys
from pathlib import Path

# Pair kinds. The kind selects the remedy a STALE line names, because the
# two shapes are repaired by different commands: a citation is re-rendered
# from its tool run, an attestation is re-attested from its inventory.
CITATION = "citation"
ATTESTATION = "attestation"


def _norm(value):
    text = (value or "").strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return text


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _attested_pairs(envelope):
    """``attestation.checks[]`` entries that recorded a file hash.

    Paths are repo-root-relative, so they are returned unresolved and are
    read against the process cwd — the same cwd the manifest's own evidence
    paths resolve against.
    """
    pairs = []
    attestation = envelope.get("attestation")
    if not isinstance(attestation, dict):
        return pairs
    checks = attestation.get("checks")
    if not isinstance(checks, list):
        return pairs
    for check in checks:
        if not isinstance(check, dict):
            continue
        path = check.get("path")
        recorded = check.get("content_hash")
        if not isinstance(path, str) or not isinstance(recorded, str):
            continue
        role = "attested-{}".format(check.get("role") or "file")
        pairs.append((ATTESTATION, role, Path(path), recorded))
    return pairs


def _pairs(envelope, envelope_dir):
    """Map an envelope's recorded hashes to the files they hashed.

    Returns ``(kind, role, path, recorded)`` tuples with ``path`` already
    resolved: citation artifacts against the envelope's own directory,
    attested files against the process cwd.
    """
    pairs = []
    provenance = envelope.get("provenance") or {}
    input_block = provenance.get("input") or {}
    if envelope.get("file") and input_block.get("content_hash"):
        pairs.append((CITATION, "artifact", envelope_dir / envelope["file"],
                      input_block["content_hash"]))
    environment = envelope.get("environment") or {}
    if envelope.get("layout") and environment.get("layout_sha256"):
        pairs.append((CITATION, "compare-layout", envelope_dir / envelope["layout"],
                      environment["layout_sha256"]))
    if envelope.get("reference") and environment.get("reference_sha256"):
        pairs.append((CITATION, "compare-reference",
                      envelope_dir / envelope["reference"],
                      environment["reference_sha256"]))
    pairs.extend(_attested_pairs(envelope))
    return pairs


def _remedy(kind, item_id, envelope, envelope_path):
    """The command that repairs a stale pair of this kind."""
    if kind != ATTESTATION:
        return ("re-render the evidence and refresh the manifest and "
                "signoff-report together")
    source = envelope.get("source")
    if not isinstance(source, str) or not source:
        source = "manifests/inventories/item-{}.json".format(item_id)
    return ("re-attest it with `klt signoff --attest {item} --inventory {inv} "
            "-o {envelope}`, then re-render the manifest and report "
            "together".format(item=item_id, inv=source, envelope=envelope_path))


def main(argv):
    manifest_path = Path(argv[1]) if len(argv) > 1 else Path(
        "manifests/sky130-temp-por.json")
    failures = []
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as exc:
        print("check-citations: UNREADABLE: manifest {} cannot be read: {}".format(
            manifest_path, exc), file=sys.stderr)
        return 1
    evidence = manifest.get("evidence") or {}
    if not isinstance(evidence, dict):
        print("check-citations: UNREADABLE: manifest {} carries no evidence "
              "map".format(manifest_path), file=sys.stderr)
        return 1
    checked = 0
    for item_id, entry in sorted(evidence.items()):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            continue
        envelope_path = Path(entry["file"])
        try:
            envelope = json.loads(envelope_path.read_text())
        except (OSError, ValueError) as exc:
            failures.append("item {}: cited envelope {} cannot be read: {}".format(
                item_id, envelope_path, exc))
            continue
        for kind, role, artifact, recorded in _pairs(envelope, envelope_path.parent):
            checked += 1
            remedy = _remedy(kind, item_id, envelope, envelope_path)
            if kind == ATTESTATION and not recorded.strip().startswith("sha256:"):
                # Fail loudly rather than compare a non-sha256 digest against
                # a sha256 one: an unverifiable check must not read as stale
                # (which would send someone re-attesting for no reason) and
                # must not read as passing either.
                failures.append(
                    "item {}: {} records {} {} at hash {!r}, which carries no "
                    "recognized `sha256:` prefix (the envelope's "
                    "attestation.hash_algorithm is {!r}) — this script can "
                    "only re-hash sha256, so the recorded hash was NOT "
                    "verified".format(
                        item_id, envelope_path, role, artifact, recorded,
                        (envelope.get("attestation") or {}).get("hash_algorithm")))
                continue
            if not artifact.is_file():
                failures.append(
                    "item {}: {} names {} {} at recorded hash {}, but that "
                    "file does not exist — {}".format(
                        item_id, envelope_path, role, artifact,
                        _norm(recorded), remedy))
                continue
            actual = _sha256(artifact)
            if actual != _norm(recorded):
                failures.append(
                    "item {}: {} records {} {} at recorded hash {}, "
                    "but the committed file hashes {} — the evidence went "
                    "stale; {}".format(
                        item_id, envelope_path, role, artifact,
                        _norm(recorded), actual, remedy))
    if failures:
        for line in failures:
            print("check-citations: STALE: {}".format(line), file=sys.stderr)
        return 1
    print("check-citations: {} recorded file hash(es) verified "
          "fresh against the committed files".format(checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
