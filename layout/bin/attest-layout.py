#!/usr/bin/env python3
"""Write the T1 item 2 (Layout) artifact-anchored envelope for one composed cell.

``klt signoff --attest`` covers items 1, 9 and 10 only, so item 2's envelope is
written here, in the shape klayout-tools' ``docs/cli/signoff.md`` ("Items 1, 2,
9, and 10: bind them to an audited artifact") grades:

* ``t1_item: 2`` and ``provenance.input.paths`` binding the committed stream
  **and** the recipe that generates it, with ``provenance.input.content_hash``
  the set's combined digest (what ``manifests/sky130-temp-por.json`` pins);
* ``provenance.regeneration`` -- this script *actually* rebuilds the cell from
  its recipe into a scratch directory (the same ``compose_cell`` chain
  ``compose-cell.py --check`` runs) and records the digest of what that run
  produced. If the rebuild is not byte-identical to the committed stream the
  claim would be false, so the script refuses to write the envelope.

Usage (repo root)::

    python3 layout/bin/attest-layout.py layout/temp_por_top/cell.json \\
        -o manifests/attestations/item-2.json

The envelope's ``status: "pass"`` asserts only that the stream is committed and
reproducible. It says nothing about DRC/ERC/LVS cleanliness: the ``summary``
points at the recorded results instead, so the blind spots travel with the claim.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import BuildError, run_klt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_compose_cell():
    spec = importlib.util.spec_from_file_location(
        "compose_cell", Path(__file__).resolve().parent / "compose-cell.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def set_digest(members: dict[str, str]) -> str:
    """klt's combined digest: sha256 of ``<hex>  <path>\\n`` lines, sorted bytewise."""
    lines = "".join(
        f"{members[p].removeprefix('sha256:')}  {p}\n"
        for p in sorted(members, key=lambda p: p.encode())
    )
    return "sha256:" + hashlib.sha256(lines.encode()).hexdigest()


def build_envelope(cell_json: Path, summary: str) -> dict:
    spec = json.loads(cell_json.read_text())
    cell = spec["cell"]
    gds = cell_json.parent / f"{cell}.gds"
    rel = lambda p: p.resolve().relative_to(REPO_ROOT).as_posix()  # noqa: E731
    members = {rel(gds): file_hash(gds), rel(cell_json): file_hash(cell_json)}

    # Regenerate into a scratch directory and hash what the recipe produces now.
    compose_cell = _load_compose_cell()
    with tempfile.TemporaryDirectory(prefix="klt-attest-layout-") as tmp:
        compose_cell.compose_cell(spec, cell_json.parent, Path(tmp))
        regenerated = {
            rel(gds): file_hash(Path(tmp) / f"{cell}.gds"),
            rel(cell_json): members[rel(cell_json)],
        }
    if regenerated != members:
        raise BuildError(
            f"{cell}: the recipe does not regenerate the committed stream "
            "byte-for-byte; refusing to attest a regeneration claim"
        )

    version = run_klt(["version", "--format", "json"], env=dict(os.environ), cwd=REPO_ROOT)
    digest = set_digest(members)
    return {
        "schema_version": 1,
        "kind": "generic",
        "status": "pass",
        "t1_item": 2,
        "summary": summary,
        "source": rel(cell_json),
        "provenance": {
            "klt_version": version["version"],
            "klayout_version": version["klayout_version"],
            "pdk": None,
            "deck": None,
            "input": {
                "content_hash": digest,
                "paths": [
                    {
                        "path": {"path": path, "scope": "repo"},
                        "content_hash": members[path],
                    }
                    for path in sorted(members)
                ],
            },
            "regeneration": {
                "generator": (
                    f"python3 layout/bin/compose-cell.py {rel(cell_json)} --check"
                ),
                "regenerated_hash": set_digest(regenerated),
            },
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("cell_json", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--summary", required=True)
    args = parser.parse_args(argv)
    try:
        envelope = build_envelope(args.cell_json.resolve(), args.summary)
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(envelope, indent=2) + "\n")
    print(f"wrote {args.output} ({envelope['provenance']['input']['content_hash']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
