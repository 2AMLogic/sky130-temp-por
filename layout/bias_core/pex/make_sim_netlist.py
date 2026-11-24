#!/usr/bin/env python3
"""Derive the simulation-ready post-layout bias_core netlist from the raw klt extraction (issue #487).

Input : bias_core.pex.spice  (klt extract --parasitics --deck sky130 --pins VDD,VSS,IBIAS,VREF,BIAS_OK, committed verbatim)
Output: bias_core.pex.sim.spice

Two mechanical, disclosed edits; nothing else is touched (no R/C value, W/L, or topology change):

1. Net names.  The layout labels each pin twice (`VDD` and `vdd`), so the extractor emits the merged name
   `VDD|vdd` (also `VDD|vdd__t7` for per-terminal star nodes).  `|` is not a safe SPICE node character, so the
   lower-case alias is dropped: `VDD|vdd` -> `VDD`, `VDD|vdd__t7` -> `VDD__t7`.  The subckt pin ORDER from `--pins` is already the schematic
   order (VDD VSS IBIAS VREF BIAS_OK); asserted below, so no wrapper is needed.
2. MOS flavour.  The layout carries no hvi thick-oxide marker, so the deck binds every MOS to the 1.8 V flavour, but
   the cell is drawn for the 5 V devices the schematic instantiates.  `sky130_fd_pr__{n,p}fet_01v8` is rewritten to
   `sky130_fd_pr__{n,p}fet_g5v0d10v5` (same W/L).  Same rewrite as layout/por_comparator/pex/make_sim_netlist.py.

Stdlib only.  Usage: make_sim_netlist.py [--check]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "bias_core.pex.spice"
DST = HERE / "bias_core.pex.sim.spice"
SCHEMATIC_PINS = "VDD VSS IBIAS VREF BIAS_OK".split()


def derive(text: str) -> str:
    m = re.search(r"^\.SUBCKT bias_core ([^\n]+)$", text, re.M)
    assert m, "no .SUBCKT bias_core"
    pins = [p.split("|")[0] for p in m.group(1).split()]
    assert pins == SCHEMATIC_PINS, pins
    # only comment lines and node names may carry '|'; every alias is <UPPER>|<lower of the same name>
    alias = re.compile(r"([A-Z_0-9]+)\|([a-z_0-9]+?)(__t\d+)?(?![A-Za-z_0-9])")
    aliases = alias.findall(text)
    assert all(a.lower() == b for a, b, _ in aliases), aliases
    n_alias = len(aliases)
    text = alias.sub(r"\1\3", text)
    assert "|" not in text
    n_mos = len(re.findall(r"sky130_fd_pr__[np]fet_01v8", text))
    text = re.sub(r"sky130_fd_pr__([np])fet_01v8", r"sky130_fd_pr__\1fet_g5v0d10v5", text)
    banner = (
        "* DERIVED from bias_core.pex.spice by make_sim_netlist.py (issue #487) -- do not edit.\n"
        f"* edits: (1) {n_alias} 'NAME|alias' net-name aliases collapsed to NAME; (2) {n_mos} MOS models 01v8 -> g5v0d10v5\n"
        "* (layout lacks the hvi marker; see script docstring). R/C/W/L untouched; pin order already schematic order.\n"
    )
    return banner + text.rstrip("\n") + "\n"


if __name__ == "__main__":
    out = derive(SRC.read_text())
    if "--check" in sys.argv:
        sys.exit(0 if DST.read_text() == out else "stale: re-run make_sim_netlist.py")
    DST.write_text(out)
    print(f"wrote {DST}")
