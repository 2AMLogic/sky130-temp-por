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
(`sky130-temp-por.json`): it re-hashes the committed artifacts each cited
envelope recorded hashes for, and requires equality. Today that is:

- a `klt drc` / `klt extract` envelope's top-level ``file`` (resolved
  against the envelope's own directory) against its
  ``provenance.input.content_hash`` — the drawn layout stream;
- a `klt lvs` envelope's ``layout`` and ``reference`` netlists against its
  ``environment.layout_sha256`` / ``environment.reference_sha256`` — the two
  halves of the compare. The LVS envelope shape carries no
  ``provenance.input.content_hash`` a manifest pin could bind to
  (`klt signoff` cannot pin it), so this re-hash is the only machine
  freshness gate an LVS citation has.

Exit 0 prints one summary line naming the count of verified hash pairs;
exit 1 prints one ``STALE`` line per drifted or missing artifact, each
naming the envelope, the role, the recorded hash, and the actual hash.
Other envelope kinds are recognized but skipped: a citation this script
cannot map to on-disk artifacts claims nothing about them either way.
"""

import hashlib
import json
import sys
from pathlib import Path


def _norm(value):
    text = (value or "").strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return text


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pairs(envelope, envelope_dir):
    """Map an envelope's recorded hashes to the files they hashed."""
    pairs = []
    provenance = envelope.get("provenance") or {}
    input_block = provenance.get("input") or {}
    if envelope.get("file") and input_block.get("content_hash"):
        pairs.append(("artifact", envelope_dir / envelope["file"],
                      input_block["content_hash"]))
    environment = envelope.get("environment") or {}
    if envelope.get("layout") and environment.get("layout_sha256"):
        pairs.append(("compare-layout", envelope_dir / envelope["layout"],
                      environment["layout_sha256"]))
    if envelope.get("reference") and environment.get("reference_sha256"):
        pairs.append(("compare-reference", envelope_dir / envelope["reference"],
                      environment["reference_sha256"]))
    return pairs


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
        for role, artifact, recorded in _pairs(envelope, envelope_path.parent):
            checked += 1
            if not artifact.is_file():
                failures.append(
                    "item {}: {} names {} {}, which does not exist".format(
                        item_id, envelope_path, role, artifact))
                continue
            actual = _sha256(artifact)
            if actual != _norm(recorded):
                failures.append(
                    "item {}: {} cites {} {} at recorded hash {}, "
                    "but the committed file hashes {} — the citation went "
                    "stale; re-render the evidence and refresh the manifest "
                    "and signoff-report together".format(
                        item_id, envelope_path, role, artifact,
                        _norm(recorded), actual))
    if failures:
        for line in failures:
            print("check-citations: STALE: {}".format(line), file=sys.stderr)
        return 1
    print("check-citations: {} recorded artifact hash(es) verified "
          "fresh against the committed files".format(checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
