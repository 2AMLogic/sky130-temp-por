#!/usr/bin/env python3
"""Shared ``klt``-invocation plumbing for this repo's layout build scripts.

One caller today: ``layout/bin/compose-cell.py``, the per-cell
gen/compose/DRC/extract/LVS chain. The contract kept here is about *the
tool*, not about that one chain -- shell out to ``klt ... --format json``,
treat a missing or unparsable JSON response as fatal, treat an ``error``
object in an otherwise well-formed response as fatal (but *not* every
non-zero exit -- see :func:`run_klt`), serialize every committed
artifact with one fixed JSON spelling (see :func:`write_json`), and WARN
(not fail) when the installed ``klt``'s commit drifts from
``layout/pdk.json``'s pin (see :func:`check_klt_pin`, issue #51). Keeping
it in its own module rather than inline in ``compose-cell.py`` is what
lets a second ``klt``-driving script inherit the contract by import
instead of restating it; there is no such second script yet, and no
extraction history behind this file -- it was written here, as-is.

These are scripts, not an installed package, so an importer puts this
file's own directory on ``sys.path`` and imports it by bare module name.
``compose-cell.py``, a sibling in ``layout/bin/``, spells that::

    sys.path.insert(0, str(Path(__file__).resolve().parent))   # layout/bin/*
    from _klt_common import BuildError, check_klt_pin, run_klt, write_json  # noqa: E402

An importer from outside ``layout/bin/`` would insert the same directory by
an explicit repo-relative path (``REPO_ROOT / "layout" / "bin"``) instead.
"""

from __future__ import annotations

import json
import subprocess
import sys
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


def check_klt_pin(
    pdk_json: Path,
    *,
    env: dict[str, str],
    klt: str = "klt",
) -> None:
    """WARN on stderr if the installed *klt*'s commit differs from the pin.

    *pdk_json* is ``layout/pdk.json`` -- its ``klt_commit_pin`` field (the
    git commit ``klt version --format json``'s own ``git_commit`` is
    expected to start with) is the unambiguous half of the pin;
    ``klt_version_pin``'s leading semver is *not* authoritative on its own
    -- the same commit can carry different package versions across builds
    (a `+g<hash>` local build) and, conversely, the same package version
    string has been observed against more than one commit in a churning
    toolchain (see ``layout/README.md``). Comparing commits directly is
    what lets a stale install self-report plainly instead of surfacing
    many steps later as a confusing "unrecognized key(s)" error from deep
    inside a ``klt gen-compose`` call (issue #51).

    This is deliberately a WARNING, not a :class:`BuildError` -- the pin is
    "a provenance pin, not a hard gate" (``layout/pdk.json``'s own
    ``_comment``), so a caller wants this to run once per invocation and
    fall through either way. Any failure to read the pin file or to run
    ``klt version`` is swallowed silently: this is a best-effort diagnostic
    layered on top of the pass/fail contract :func:`run_klt` already
    enforces, not part of that contract itself.
    """
    try:
        pdk = json.loads(pdk_json.read_text())
    except (OSError, json.JSONDecodeError):
        return
    pin = pdk.get("klt_commit_pin")
    if not pin:
        return
    try:
        response = run_klt(["version"], env=env, klt=klt)
    except BuildError:
        return
    commit = response.get("git_commit") or ""
    if commit.startswith(pin):
        return
    print(
        f"warning: installed {klt}'s git_commit "
        f"{commit or '<unknown>'!r} does not match {pdk_json}'s "
        f"klt_commit_pin {pin!r} -- the committed evidence under "
        f"{pdk_json.parent}/ was generated/verified against a different "
        f"klt build. A stale klt can fail deep in the chain with a "
        f"confusing 'unrecognized key(s)' error instead of this plain "
        f"warning; if you hit one, re-provision klt from the pinned "
        f"commit first (see layout/README.md).",
        file=sys.stderr,
    )


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
