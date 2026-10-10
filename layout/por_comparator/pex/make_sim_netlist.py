#!/usr/bin/env python3
"""Derive the simulation-ready post-layout netlist from the raw klt extraction (issue #124).

Input : por_comparator.pex.spice  (klt extract --parasitics --deck sky130, committed verbatim)
Output: por_comparator.pex.sim.spice

Two mechanical, disclosed edits; nothing else is touched (no R/C value, W/L, or topology change):

1. Pin order.  The extracted .SUBCKT lists pins alphabetically (BIAS_OK IBIAS POR_RAW VDD VREF VSS) but the
   schematic and every testbench instantiate positionally as `VDD VSS IBIAS VREF BIAS_OK POR_RAW`
   (2AMLogic/klayout-tools#2890).  The extracted cell is renamed `por_comparator_pex` and a wrapper
   `.subckt por_comparator <schematic order>` instantiates it by name.
2. MOS flavour.  The layout carries no hvi thick-oxide marker (layout/por_comparator/README.md, Known gaps 1),
   so the deck binds every MOS to the 1.8 V flavour, but the cell is drawn for the 5 V devices the schematic
   instantiates.  `sky130_fd_pr__{n,p}fet_01v8` is rewritten to `sky130_fd_pr__{n,p}fet_g5v0d10v5` (same W/L).

Stdlib only.  Usage: make_sim_netlist.py [--check]
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "por_comparator.pex.spice"
DST = HERE / "por_comparator.pex.sim.spice"
SCHEMATIC_PINS = "VDD VSS IBIAS VREF BIAS_OK POR_RAW".split()


def derive(text: str) -> str:
    m = re.search(r"^\.SUBCKT por_comparator ([^\n]+)$", text, re.M)
    assert m, "no .SUBCKT por_comparator"
    assert sorted(m.group(1).split()) == sorted(SCHEMATIC_PINS), m.group(1)
    text = text.replace(m.group(0), ".SUBCKT por_comparator_pex " + m.group(1))
    assert text.count(".ENDS por_comparator") == 1
    text = text.replace(".ENDS por_comparator", ".ENDS por_comparator_pex")
    n_before = len(re.findall(r"sky130_fd_pr__[np]fet_01v8", text))
    text = re.sub(r"sky130_fd_pr__([np])fet_01v8", r"sky130_fd_pr__\1fet_g5v0d10v5", text)
    banner = (
        "* DERIVED from por_comparator.pex.spice by make_sim_netlist.py (issue #124) -- do not edit.\n"
        f"* edits: (1) subckt renamed por_comparator_pex + wrapper restoring the schematic pin order; (2) {n_before} MOS\n"
        "* models 01v8 -> g5v0d10v5 (layout lacks the hvi marker; see script docstring). R/C/W/L untouched.\n"
    )
    wrapper = (
        "\n.SUBCKT por_comparator " + " ".join(SCHEMATIC_PINS) + "\n"
        "Xpex " + " ".join(m.group(1).split()) + " por_comparator_pex\n"
        ".ENDS por_comparator\n"
    )
    # Xpex lists nets in the extracted subckt's own (alphabetical) pin order, so net names bind by name.
    return banner + text.rstrip("\n") + "\n" + wrapper


if __name__ == "__main__":
    out = derive(SRC.read_text())
    if "--check" in sys.argv:
        sys.exit(0 if DST.read_text() == out else "stale: re-run make_sim_netlist.py")
    DST.write_text(out)
    print(f"wrote {DST}")
