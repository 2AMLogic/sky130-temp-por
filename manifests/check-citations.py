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

- a `klt drc` / `klt erc` / `klt extract` envelope's top-level ``file``
  against its ``provenance.input.content_hash`` — the drawn layout stream;
- a `klt lvs` envelope's ``layout`` and ``reference`` netlists against its
  ``environment.layout_sha256`` / ``environment.reference_sha256`` — the two
  halves of the compare. The LVS envelope shape carries no
  ``provenance.input.content_hash`` a manifest pin could bind to
  (`klt signoff` cannot pin it), so this re-hash is the only machine
  freshness gate an LVS citation has.

Two shapes of indirection sit above those hashes, and both are walked:

- an item's ``evidence`` entry is either one citation object or a **list**
  of them — item 11 cites `erc.json` and `lvs.json` together — and every
  citation in a list is checked;
- an envelope's ``file`` is either a plain string, relative to the
  envelope's own directory (`drc.json`'s ``"temp_por_top.gds"``), or the
  schema-2 object ``{"path": …, "scope": "repo"}`` whose ``path`` is
  repo-root-relative (`erc.json`). ``scope: "external"`` names a file
  outside the repo and carries no committed artifact to re-hash.

**Attestation envelopes are deliberately not handled here (issue #303).**
#299 briefly gave this script a second branch that re-hashed the
``attestation.checks[]`` entries of items 1, 9 and 10, because CI could not
re-attest items 1 and 9 — their freshness commands need xschem and the
sky130 PDK. That premise no longer holds: those commands are now marked
``"local_only": true`` in their inventories, so
`klt signoff --attest N ... --check` skips *the command* (reporting
``[SKIP] … local_only``, never as passed) while still re-hashing every
inventoried file and diffing the whole envelope. `signoff-manifest.yml`
therefore runs that `--check` unconditionally for items 1, 9 and 10, and
klt's own gate is a strict superset of what this script re-hashed: it also
diffs the inventory pin, the check count and every committed outcome. One
mechanism per behaviour (`.loom/docs/ci-principles.md`), and the canary
exercises the pinned tool's own feature rather than a repo-owned copy of it.

Exit 0 prints one summary line naming the count of verified hash pairs.
Exit 1 prints one ``STALE`` line per drifted or missing artifact — naming
the item, the envelope, the role, the recorded hash and the actual hash —
and one ``UNMAPPABLE`` line per evidence entry, citation or ``file`` form
the checker cannot resolve to committed files.

``UNMAPPABLE`` is an error rather than a skip (`.loom/docs/ci-principles.md`):
a manifest item walked past in silence is a check that cannot run looking
like one that passed, and the set of entry shapes is small and
repo-controlled. It is a claim about the *shape* of the manifest entry and
of the envelope's ``file`` — **not** about the envelope's contents. A
readable envelope carrying no recognized hash shape (an attestation
envelope, a hand-written one) still contributes zero pairs and stays green:
such a citation says nothing about on-disk artifacts either way.

Run:   python3 manifests/check-citations.py manifests/sky130-temp-por.json
Tests: python3 -I manifests/test_check_citations.py
"""

import hashlib
import json
import sys
from pathlib import Path


class Unmappable(Exception):
    """A manifest entry, citation or ``file`` form that resolves to nothing.

    Raised, never swallowed: the whole point of this script is that an item
    it cannot check must not be indistinguishable from one it checked.
    """


def _norm(value):
    text = (value or "").strip()
    if text.startswith("sha256:"):
        text = text[len("sha256:"):]
    return text


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _describe(value):
    """A one-line, JSON-ish rendering of an unmappable value for the log."""
    try:
        return json.dumps(value, sort_keys=True)
    except (TypeError, ValueError):
        return repr(value)


def _citations(entry):
    """Normalize one manifest ``evidence`` entry to a list of citations.

    `klt signoff` accepts either a single citation object or a list of them
    for an item whose evidence spans several envelopes (item 11). Anything
    else is unmappable rather than skipped.
    """
    if isinstance(entry, dict):
        return [entry]
    if isinstance(entry, list):
        if not entry:
            raise Unmappable("evidence entry is an empty list, which cites "
                             "nothing and so verifies nothing")
        return entry
    raise Unmappable(
        "evidence entry is a {} ({}), not a citation object or a list of "
        "them".format(type(entry).__name__, _describe(entry)))


def _artifact(file_value, envelope_dir):
    """Resolve an envelope's recorded file reference to a committed path.

    A plain string resolves against the envelope's own directory, which is
    what `klt drc` / `klt lvs` record their artifacts relative to. The
    schema-2 object form (`klt erc`) instead carries a repo-root-relative
    ``path`` under ``scope: "repo"`` — the same root the manifest's own
    ``file`` paths resolve against, i.e. the process cwd.
    ``{"path": null, "scope": "external"}`` names a file outside the repo:
    there is no committed artifact to re-hash, so it is unmappable.
    """
    if isinstance(file_value, str):
        return envelope_dir / file_value
    if isinstance(file_value, dict):
        if (file_value.get("scope") == "repo"
                and isinstance(file_value.get("path"), str)):
            return Path(file_value["path"])
        raise Unmappable(
            "file reference {} is not a repo-scoped path this checker can "
            "re-hash".format(_describe(file_value)))
    raise Unmappable(
        "file reference {} is neither a path string nor a {{path, scope}} "
        "object".format(_describe(file_value)))


def _pairs(envelope, envelope_dir):
    """Map an envelope's recorded hashes to the files they hashed.

    Returns ``(role, path, recorded)`` tuples with ``path`` already resolved
    per `_artifact`. A recorded hash with no file reference — or a file
    reference with no recorded hash — yields no pair: there is nothing to
    compare. A file reference this script cannot resolve, paired with a hash
    that *is* recorded, raises `Unmappable` instead.
    """
    pairs = []
    provenance = envelope.get("provenance") or {}
    input_block = provenance.get("input") or {}
    if envelope.get("file") and input_block.get("content_hash"):
        pairs.append(("artifact", _artifact(envelope["file"], envelope_dir),
                      input_block["content_hash"]))
    environment = envelope.get("environment") or {}
    if envelope.get("layout") and environment.get("layout_sha256"):
        pairs.append(("compare-layout",
                      _artifact(envelope["layout"], envelope_dir),
                      environment["layout_sha256"]))
    if envelope.get("reference") and environment.get("reference_sha256"):
        pairs.append(("compare-reference",
                      _artifact(envelope["reference"], envelope_dir),
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
        try:
            citations = _citations(entry)
        except Unmappable as exc:
            failures.append(("UNMAPPABLE", "item {}: {}".format(item_id, exc)))
            continue
        for citation in citations:
            if not isinstance(citation, dict) or not isinstance(
                    citation.get("file"), str):
                failures.append(("UNMAPPABLE", (
                    "item {}: citation {} names no string `file`, so no "
                    "envelope can be read for it").format(
                        item_id, _describe(citation))))
                continue
            envelope_path = Path(citation["file"])
            try:
                envelope = json.loads(envelope_path.read_text())
            except (OSError, ValueError) as exc:
                failures.append(("STALE", (
                    "item {}: cited envelope {} cannot be read: {}").format(
                        item_id, envelope_path, exc)))
                continue
            try:
                pairs = _pairs(envelope, envelope_path.parent)
            except Unmappable as exc:
                failures.append(("UNMAPPABLE", "item {}: {}: {}".format(
                    item_id, envelope_path, exc)))
                continue
            for role, artifact, recorded in pairs:
                checked += 1
                if not artifact.is_file():
                    failures.append(("STALE", (
                        "item {}: {} names {} {}, which does not exist").format(
                            item_id, envelope_path, role, artifact)))
                    continue
                actual = _sha256(artifact)
                if actual != _norm(recorded):
                    failures.append(("STALE", (
                        "item {}: {} cites {} {} at recorded hash {}, "
                        "but the committed file hashes {} — the citation went "
                        "stale; re-render the evidence and refresh the manifest "
                        "and signoff-report together").format(
                            item_id, envelope_path, role, artifact,
                            _norm(recorded), actual)))
    if failures:
        for label, line in failures:
            print("check-citations: {}: {}".format(label, line), file=sys.stderr)
        return 1
    print("check-citations: {} recorded artifact hash(es) verified "
          "fresh against the committed files".format(checked))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
