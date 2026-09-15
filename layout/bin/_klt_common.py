#!/usr/bin/env python3
"""Shared ``klt``-invocation plumbing for this repo's build/verify scripts.

Used by ``layout/bin/compose-cell.py`` (the per-cell
gen/compose/DRC/extract/LVS chain), ``layout/bin/pex-netlist.py`` (the
post-layout parasitic-netlist library build), and
``sim/digital-synthesis/harness/synthesize-and-verify.py`` (the
synthesize/equiv/gate-cosim chain behind the ``level: gate`` evidence
record). All three drive the same tool the same way -- shell out to ``klt
... --format json``, treat a missing/unparsable JSON response as fatal,
treat an ``error`` object in an otherwise well-formed response as fatal,
and (for the two that write artifacts) serialize their JSON with one fixed
spelling -- so the contract lives here once instead of in a copy per
script.

Extracted per issue #49, following ``design/_pdk_search.py``'s precedent
(issue #25): before the extraction, ``pex-netlist.py``'s own ``run_klt``
docstring said "Same contract as ``layout/bin/compose-cell.py``'s helper of
the same name", which is a duplication note, not a shared contract. Now it
is one. The digital-synthesis harness adopted it per issue #133, which
retired a fourth-copy reimplementation that had quietly diverged (it never
checked for the ``error`` object, and it treated *every* non-zero exit as
fatal -- see :func:`run_klt`'s note on ``klt equiv``'s 3/4).

Import it the way ``design/netlist.py`` imports ``_pdk_search`` -- these are
scripts, not an installed package, so the importer puts this file's own
directory on ``sys.path`` and imports it by bare module name. It lives under
``layout/bin/`` because that is where it was extracted from; an importer
outside that tree spells the same insert with an explicit path::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    sys.path.insert(0, str(REPO_ROOT / "layout" / "bin"))      # elsewhere
    from _klt_common import BuildError, run_klt, write_json  # noqa: E402
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

    The ``layout/bin/`` callers always invoke from the artifact's own output
    directory with *relative* paths, so that every committed response records
    repo-relative provenance and no absolute home path leaks into the
    evidence (the leak ``klt env-provenance --scan`` exists to catch). *cwd*
    defaults to the caller's own working directory for the callers that
    cannot do that -- ``klt synthesize``/``klt equiv`` resolve every path in
    their responses to an absolute path regardless of how the request was
    invoked, so the digital-synthesis harness gets the same hygiene by
    sanitizing the response on the way into its record instead.

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
    not-yet-existing output tree (``layout/pex/raw/`` on a fresh build) does
    not have to pre-create it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
