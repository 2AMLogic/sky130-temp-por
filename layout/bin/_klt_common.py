#!/usr/bin/env python3
"""Shared ``klt``-invocation plumbing for this repo's layout build scripts.

One caller today: ``layout/bin/compose-cell.py``, the per-cell
gen/compose/DRC/extract/LVS chain. The contract kept here is about *the
tool*, not about that one chain -- shell out to ``klt ... --format json``,
treat a missing or unparsable JSON response as fatal, treat an ``error``
object in an otherwise well-formed response as fatal (but *not* every
non-zero exit -- see :func:`run_klt`), and serialize every committed
artifact with one fixed JSON spelling (see :func:`write_json`). Keeping it
in its own module rather than inline in ``compose-cell.py`` is what lets a
second ``klt``-driving script inherit the contract by import instead of
restating it; there is no such second script yet, and no extraction history
behind this file -- it was written here, as-is.

These are scripts, not an installed package, so an importer puts this
file's own directory on ``sys.path`` and imports it by bare module name.
``compose-cell.py``, a sibling in ``layout/bin/``, spells that::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    from _klt_common import BuildError, run_klt, write_json  # noqa: E402

An importer from outside ``layout/bin/`` would insert the same directory by
an explicit repo-relative path (``REPO_ROOT / "layout" / "bin"``) instead.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class BuildError(RuntimeError):
    """A step of the chain failed."""


def run_klt(
    args: list[str],
    *,
    env: dict[str, str],
    cwd: Path | None = None,
    klt: str = "klt",
) -> dict:
    """Run ``klt`` with ``--format json``, from *cwd*, and parse its response.

    By convention a ``layout/bin/`` caller invokes from the artifact's own
    output directory with *relative* paths, so that every committed response
    records repo-relative provenance and no absolute home path leaks into the
    evidence (the leak ``klt env-provenance --scan`` exists to catch). *cwd*
    is optional rather than required so that a caller with no such artifact
    directory to invoke from -- a one-off query whose response is never
    committed -- can simply run in its own working directory.

    *klt* is the binary to invoke, for callers that expose a ``--klt``/``$KLT``
    override; it defaults to whatever ``klt`` is on ``$PATH``.

    A non-zero exit is not automatically fatal. Several subcommands "ran
    fine, here is the bad news" through the response body, and the callers
    want to report that from the body rather than from a traceback:
    ``klt gen-compose`` exits 3 for a partial success (some net unrouted),
    ``klt lvs`` exits 3 for a clean-run mismatch, and ``klt equiv`` exits 3
    for a proven counterexample / 4 for an inconclusive (timed-out) proof.
    A response that is not JSON at all is fatal, as is a well-formed
    response carrying an ``error`` object -- note that under ``--format
    json`` klt writes the error envelope to *stderr* and leaves stdout
    empty, so a genuine failure normally lands in the first of those two
    cases, with the envelope surfaced through the captured stderr.
    """
    proc = subprocess.run(
        [klt, *args, "--format", "json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
        check=False,
    )
    try:
        response = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BuildError(
            f"{klt} {' '.join(args)} produced no JSON response "
            f"(exit {proc.returncode}):\n{proc.stdout}\n{proc.stderr}"
        ) from exc
    if "error" in response:
        raise BuildError(
            f"{klt} {' '.join(args)} failed: {response['error'].get('message')}"
        )
    return response


def write_json(path: Path, payload: dict) -> None:
    """Write *payload* as this repo's committed-artifact JSON spelling.

    Two-space indent, insertion order preserved (``sort_keys=False``, so a
    response's own field order survives into the committed file and stays
    diffable against the tool's output), one trailing newline. Parent
    directories are created if missing, so a caller writing into a
    not-yet-existing output tree (``layout/<cell>/`` for a cell being composed
    for the first time) does not have to pre-create it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
