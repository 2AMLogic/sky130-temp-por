#!/usr/bin/env python3
"""Export ngspice netlists from the xschem sources in ``design/``.

    python3 design/netlist.py            # regenerate design/netlist/*.spice
    python3 design/netlist.py --check    # verify committed netlists are current
    python3 design/netlist.py --cell bias_core

Every ``design/*.sch`` cell is netlisted **as a ``.subckt``** (never as a flat
deck) into ``design/netlist/<cell>.spice``:

* once ``temp_por_top.sch`` exists (issue #10), ``temp_por_top.spice`` will
  carry the whole hierarchy -- the top cell plus every sub-circuit definition
  it instantiates.
* each sub-circuit also gets its own single-``.subckt`` file, so a testbench
  can target one half of the block without dragging in the rest.

The export is deterministic: absolute paths that xschem records in ``sch_path``
/ ``sym_path`` comments are rewritten repo-relative, so the same sources produce
byte-identical netlists on any machine. ``--check`` re-runs the export into a
temporary directory and diffs it against what is committed; it fails if the
committed netlists are stale, if the export is not reproducible, or if a
pinout/port-order invariant is broken.

Ported from gf180-temp-por/design/netlist.py (issue #6) with two deliberate
scope cuts, both option (b) from that issue's Implementation Guidance -- kept
inline here rather than factored into shared modules, so this issue's scope
stays schematic entry rather than simulation/layout infrastructure:

* **PDK discovery** is inlined below (:func:`find_pdk`) instead of delegated
  to a ``sim/harness/pdk.py``-equivalent module -- ``sim/`` is still an empty
  stub in this repo (see ``spec/porting-plan.md`` Sec4 item 1, sim-harness
  port, not yet filed). The resolution order mirrors ``design/xschemrc`` and
  ``sky130-bandgap/sim/harness``'s own PDK_ROOT/PDK-with-volare-fallback
  convention, so both stay in sync by construction.
* **The ratified-port-list assertion** uses a small inlined SPICE
  ``.subckt`` port-list parser (:func:`subckt_ports`) instead of importing
  ``layout/lvs_reference.py``, which also does not exist yet in this repo
  (layout/DRC/LVS is explicitly out of scope for issue #6). The parser
  itself is a straight port of ``lvs_reference.py``'s own
  ``logical_lines``/``subckt_ports`` (gf180-temp-por, stdlib-only, no PDK
  dependency) -- when a real ``layout/lvs_reference.py`` lands in this repo,
  this copy should be deleted in favour of importing it, exactly as gf180's
  own module docstring intends.

Until ``temp_por_top.sch`` exists (issue #10), there is no ratified top-level
cell to assert the pinout against, so the top-level and cross-cell
invariants in :func:`check_invariants` are skipped -- everything else
(the reproducibility/staleness check, and the per-cell
symbol-pins-match-schematic-ports check) still runs for whatever cells are
committed.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

DESIGN_DIR = Path(__file__).resolve().parent
REPO_ROOT = DESIGN_DIR.parent
NETLIST_DIR = DESIGN_DIR / "netlist"
XSCHEMRC = DESIGN_DIR / "xschemrc"

TOP_CELL = "temp_por_top"

# The ratified top-level pinout, in netlist port order, once temp_por_top
# exists (issue #10). Sourced from spec/porting-plan.md Sec2.8's
# reconciliation and this repo's own decision records; changing it here is
# not enough -- change the decision record first.
#   VDD, VSS  DR-001 (sky130 5V I/O-class supply pair, 3.3 V nominal)
#   PTAT/CTAT DR-002 (analog-only wave 1, both pads -- architecture carryover)
#   RESETn    DR-002 (active-low, push-pull -- architecture carryover)
RATIFIED_TOP_PORTS = ["VDD", "VSS", "PTAT", "CTAT", "RESETn"]

SYM_PIN_RE = re.compile(r"^B\s+\d+\s+\S+\s+\S+\s+\S+\s+\S+\s*\{(.*)\}\s*$")
SCH_PIN_RE = re.compile(r"^C\s+\{devices/(i|o|io)pin\.sym\}\s+.*?\{(.*)\}\s*$")

# -- inlined SPICE .subckt parsing (see module docstring: ported from
# gf180-temp-por/layout/lvs_reference.py's logical_lines/subckt_ports,
# stdlib-only, no PDK dependency) --------------------------------------
SUBCKT_RE = re.compile(r"^\.subckt\s+(\S+)\s+(.*)$", re.IGNORECASE)
ENDS_RE = re.compile(r"^\.ends\b", re.IGNORECASE)


class ExportError(RuntimeError):
    pass


class PdkNotFound(RuntimeError):
    pass


class Pdk:
    """Resolved PDK location: ``path`` is the variant dir (contains libs.tech/)."""

    def __init__(self, path: Path, variant: str):
        self.path = path
        self.variant = variant


def find_pdk() -> Pdk:
    """Resolve the sky130 PDK: PDK_ROOT/PDK env vars, else the volare default.

    Mirrors design/xschemrc's own resolution order exactly (PDK_ROOT falls
    back to ``~/.volare``, PDK falls back to ``sky130A``), so a schematic
    that opens fine interactively netlists the same way here.
    """
    root = os.environ.get("PDK_ROOT") or str(Path.home() / ".volare")
    variant = os.environ.get("PDK") or "sky130A"
    path = Path(root) / variant
    if not (path / "libs.tech").is_dir():
        raise PdkNotFound(
            f"no sky130 PDK at {path} (expected {path}/libs.tech/...). "
            f"Install the sky130A PDK (volare) or set PDK_ROOT/PDK."
        )
    return Pdk(path=path, variant=variant)


def logical_lines(text: str) -> list[str]:
    """Join SPICE ``+`` continuations; drop comments and blanks."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.lstrip().startswith("+"):
            if not out:
                raise ExportError("continuation line with nothing to continue")
            out[-1] = f"{out[-1]} {line.lstrip()[1:].strip()}"
        else:
            out.append(line.strip())
    return out


def subckt_ports(netlist: str, cell: str) -> list[str]:
    """The formal port list of ``.subckt <cell> ...`` in ``netlist``."""
    for line in logical_lines(netlist):
        match = SUBCKT_RE.match(line)
        if match and match.group(1) == cell:
            return match.group(2).split()
    raise ExportError(f".subckt {cell} not found in its own netlist")


# -- cell discovery / export ---------------------------------------------


def cells() -> list[str]:
    """All cells in design/, top level first (if it exists) then alphabetical."""
    names = sorted(p.stem for p in DESIGN_DIR.glob("*.sch"))
    if not names:
        raise ExportError(f"no *.sch files in {DESIGN_DIR}")
    if TOP_CELL in names:
        return [TOP_CELL] + [n for n in names if n != TOP_CELL]
    return names


def xschem_env() -> dict[str, str]:
    """Environment for xschem: the PDK design/xschemrc itself would resolve."""
    pdk = find_pdk()
    env = dict(os.environ)
    env["PDK_ROOT"] = str(pdk.path.parent)
    env["PDK"] = pdk.variant
    # Keep batch runs off the user's ~/.xschem state.
    env.setdefault("XSCHEM_USER_LIBRARY_PATH", str(DESIGN_DIR))
    return env


def normalize(text: str) -> str:
    """Make xschem output machine-independent (and therefore diffable)."""
    text = text.replace(str(REPO_ROOT) + os.sep, "")
    # Trailing whitespace is not load bearing and varies with symbol text.
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return text.rstrip("\n") + "\n"


def export_cell(cell: str, outdir: Path, env: dict[str, str]) -> str:
    """Run xschem headless on one cell and return its normalized netlist."""
    sch = DESIGN_DIR / f"{cell}.sch"
    if not sch.is_file():
        raise ExportError(f"no such cell: {sch}")
    cmd = [
        "xschem",
        "-x",  # no X11: batch
        "-q",  # quit when done
        "-n",  # netlist
        "-s",  # spice
        "-r",  # no tclreadline (stdin/stdout may be redirected)
        "--rcfile", str(XSCHEMRC),
        "-o", str(outdir),
        str(sch),
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    produced = outdir / f"{cell}.spice"
    if proc.returncode != 0 or not produced.is_file():
        raise ExportError(
            f"xschem failed for {cell} (exit {proc.returncode})\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    text = normalize(produced.read_text())
    header = (
        f"* {cell} -- generated by design/netlist.py from design/{cell}.sch\n"
        f"* Do not edit: edit the schematic and re-run the export.\n"
    )
    return header + text


def symbol_pins(cell: str) -> list[str] | None:
    """Pin names, in order, from design/<cell>.sym (None if there is no symbol)."""
    sym = DESIGN_DIR / f"{cell}.sym"
    if not sym.is_file():
        return None
    pins: list[str] = []
    for line in sym.read_text().splitlines():
        match = SYM_PIN_RE.match(line)
        if not match:
            continue
        attrs = match.group(1)
        name = re.search(r"\bname=(\S+)", attrs)
        if name:
            pins.append(name.group(1))
    return pins


def schematic_ports(cell: str) -> list[str]:
    """Port names, in order, from the ipin/opin/iopin instances in <cell>.sch."""
    ports: list[str] = []
    for line in (DESIGN_DIR / f"{cell}.sch").read_text().splitlines():
        match = SCH_PIN_RE.match(line)
        if not match:
            continue
        lab = re.search(r"\blab=(\S+)", match.group(2))
        if lab:
            ports.append(lab.group(1))
    return ports


def instance_lines(netlist: str, cell: str) -> list[list[str]]:
    """Instance lines of `cell` inside the top-level .subckt block."""
    found = []
    for line in netlist.splitlines():
        tokens = line.split()
        if len(tokens) >= 2 and tokens[0].lower().startswith("x") and tokens[-1] == cell:
            found.append(tokens)
    return found


def check_invariants(netlists: dict[str, str]) -> list[str]:
    """Pinout / port-order invariants. Returns a list of failure messages."""
    failures: list[str] = []

    if TOP_CELL in netlists:
        top_ports = subckt_ports(netlists[TOP_CELL], TOP_CELL)
        if top_ports != RATIFIED_TOP_PORTS:
            failures.append(
                f"top-level pinout drifted from the ratified interface:\n"
                f"    expected: {RATIFIED_TOP_PORTS}\n"
                f"    netlist:  {top_ports}\n"
                f"  (DR-001 supply pair, DR-002 PTAT/CTAT/RESETn architecture"
                f" carryover)"
            )
    # else: no temp_por_top yet (issue #10) -- nothing to assert the
    # ratified pinout against.

    for cell, netlist in netlists.items():
        ports = subckt_ports(netlist, cell)
        pins = symbol_pins(cell)
        if pins is None:
            failures.append(f"{cell}: no design/{cell}.sym -- cell is not instantiable")
            continue
        # xschem takes the .subckt port list from the *symbol* when one exists,
        # so a symbol whose pins have drifted from the schematic's own pins
        # silently drops or renames a port on every instantiation. Compare the
        # two sources directly rather than trusting the netlist alone.
        sch_pins = schematic_ports(cell)
        if pins != sch_pins:
            failures.append(
                f"{cell}: symbol pins and schematic ports disagree.\n"
                f"    {cell}.sym:  {pins}\n"
                f"    {cell}.sch:  {sch_pins}\n"
                f"  xschem netlists the ports from the symbol, so this silently\n"
                f"  miswires or drops a port on every instantiation of the cell."
            )
        if pins != ports:
            failures.append(
                f"{cell}: symbol pin order does not match the exported .subckt.\n"
                f"    {cell}.sym:  {pins}\n"
                f"    .subckt:    {ports}"
            )

    if TOP_CELL in netlists:
        top = netlists[TOP_CELL]
        for cell in netlists:
            if cell == TOP_CELL:
                continue
            instances = instance_lines(top, cell)
            if not instances:
                failures.append(f"{cell}: not instantiated in {TOP_CELL}")
                continue
            width = len(subckt_ports(netlists[cell], cell))
            for tokens in instances:
                nets = tokens[1:-1]
                if len(nets) != width:
                    failures.append(
                        f"{TOP_CELL}: instance {tokens[0]} of {cell} connects "
                        f"{len(nets)} nets, but {cell} has {width} ports"
                    )
    return failures


def run(check: bool, only: str | None, verbose: bool) -> int:
    try:
        env = xschem_env()
    except PdkNotFound as exc:
        print(f"design/netlist.py: {exc}", file=sys.stderr)
        return 2

    wanted = [only] if only else cells()
    netlists: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix="sky130-temp-por-netlist-") as tmp:
        outdir = Path(tmp)
        for cell in wanted:
            netlists[cell] = export_cell(cell, outdir, env)
            if verbose:
                print(f"  netlisted {cell}")

    status = 0
    if only:
        # A single-cell run cannot evaluate the cross-cell invariants.
        failures: list[str] = []
    else:
        failures = check_invariants(netlists)

    if check:
        for cell, text in netlists.items():
            committed = NETLIST_DIR / f"{cell}.spice"
            if not committed.is_file():
                failures.append(f"{committed.relative_to(REPO_ROOT)} is missing")
                continue
            have = committed.read_text()
            if have != text:
                diff = "\n".join(
                    difflib.unified_diff(
                        have.splitlines(),
                        text.splitlines(),
                        fromfile=f"committed/{cell}.spice",
                        tofile=f"regenerated/{cell}.spice",
                        lineterm="",
                    )
                )
                failures.append(
                    f"{cell}: committed netlist is stale or the export is not "
                    f"reproducible:\n{diff}"
                )
    else:
        NETLIST_DIR.mkdir(exist_ok=True)
        for cell, text in netlists.items():
            target = NETLIST_DIR / f"{cell}.spice"
            target.write_text(text)
            print(f"wrote {target.relative_to(REPO_ROOT)}")

    if failures:
        print("\nFAIL:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        status = 1
    elif check:
        print(f"OK: {len(netlists)} netlist(s) reproduce byte-for-byte and the "
              f"pinout invariants hold.")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export ngspice netlists from design/*.sch via xschem.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; verify the committed netlists are current and the "
             "pinout invariants hold",
    )
    parser.add_argument(
        "--cell",
        help="export a single cell (skips the cross-cell invariant checks)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    try:
        return run(check=args.check, only=args.cell, verbose=args.verbose)
    except ExportError as exc:
        print(f"design/netlist.py: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
