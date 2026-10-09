#!/usr/bin/env python3
"""Run design/netlist.py's pinout/cross-cell invariants on the COMMITTED
design/netlist/*.spice files. Stdlib only; needs neither xschem nor a PDK.

This is the CI-runnable subset of ``design/netlist.py --check``. It does NOT
verify that the committed netlists match the schematics (that needs xschem and
the sky130 PDK, so run ``python3 design/netlist.py --check`` locally).
"""
import importlib.util
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("netlist_export", here / "netlist.py")
mod = importlib.util.module_from_spec(spec)
sys.modules["netlist_export"] = mod
spec.loader.exec_module(mod)

netlists, failures = {}, []
for cell in mod.cells():
    path = mod.NETLIST_DIR / f"{cell}.spice"
    if not path.is_file():
        failures.append(f"{path.relative_to(mod.REPO_ROOT)} is missing")
    else:
        netlists[cell] = path.read_text()
if not failures:
    try:
        failures = mod.check_invariants(netlists)
    except mod.ExportError as exc:
        failures = [str(exc)]
if failures:
    print("FAIL:", file=sys.stderr)
    for f in failures:
        print(f"  - {f}", file=sys.stderr)
    sys.exit(1)
print(f"OK: invariants hold on {len(netlists)} committed netlist(s)")
