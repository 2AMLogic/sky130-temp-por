#!/usr/bin/env python3
"""normalize() tests for design/netlist.py (issue #295). Stdlib only, no PDK,
no xschem, no klt, no SPICE.

``klt netlist`` >= 0.9.x prepends a ``** klt-netlist-inputs: {...}`` provenance
comment whose presence depends on the klt version and whose content names the
installed ``xschem_version``. design/netlist.py promises byte-identical
netlists on any machine, so :func:`netlist.normalize` drops that line; these
tests pin that behaviour, and pin that it drops *nothing else*.

Run: python3 -I design/test_netlist_normalize.py
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path

DESIGN = Path(__file__).resolve().parent
REPO = DESIGN.parent

# The real provenance line as emitted by klt 0.9.2.dev885+ge4c446bd91f2.
PROVENANCE = (
    '** klt-netlist-inputs: {"pdk_variant": "sky130A", '
    '"rcfile": "xschemrc", "xschem_version": "3.4.7"}'
)


def load(name: str, path: Path):
    """Import a module by path (the repo's house pattern, cf. sim/bin/test_pdk_pin.py)."""
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


netlist = load("normalize_netlist", DESIGN / "netlist.py")


class TestProvenanceLineStripped(unittest.TestCase):
    def test_provenance_line_removed_and_everything_else_kept(self):
        """The marker line goes; every other line survives, in order."""
        raw = "\n".join([
            "** sch_path: /abs/design/bias_core.sch",
            PROVENANCE,
            ".subckt bias_core VDD VSS IBIAS VREF BIAS_OK",
            "*.PININFO VDD:B VSS:B IBIAS:O VREF:O BIAS_OK:O",
            "XMP1 NA PG VDD VDD sky130_fd_pr__pfet_g5v0d10v5 L=4 W=8",
            ".ends",
        ]) + "\n"
        got = netlist.normalize(raw)
        self.assertNotIn("klt-netlist-inputs", got)
        self.assertEqual(
            got.splitlines(),
            [
                "** sch_path: /abs/design/bias_core.sch",
                ".subckt bias_core VDD VSS IBIAS VREF BIAS_OK",
                "*.PININFO VDD:B VSS:B IBIAS:O VREF:O BIAS_OK:O",
                "XMP1 NA PG VDD VDD sky130_fd_pr__pfet_g5v0d10v5 L=4 W=8",
                ".ends",
            ],
        )

    def test_every_marker_occurrence_removed(self):
        """klt emits one per cell, so a hierarchical netlist can carry several."""
        raw = "\n".join([
            PROVENANCE,
            ".subckt a VDD VSS",
            ".ends",
            PROVENANCE,
            ".subckt b VDD VSS",
            ".ends",
        ]) + "\n"
        got = netlist.normalize(raw)
        self.assertNotIn("klt-netlist-inputs", got)
        self.assertEqual(len(got.splitlines()), 4)

    def test_marker_matched_at_line_start_only(self):
        """A line that merely *contains* the text is circuit content: keep it."""
        kept = [
            "* a comment mentioning ** klt-netlist-inputs: in prose",
            "XR1 A B sky130_fd_pr__res_high_po L=1 W=1 $ ** klt-netlist-inputs: {}",
            " " + PROVENANCE,  # indented: not a line-start match
        ]
        got = netlist.normalize("\n".join(kept) + "\n")
        self.assertEqual(got.splitlines(), kept)

    def test_prefix_constant_is_the_klt_marker(self):
        """The constant normalize() keys on matches what klt actually emits."""
        self.assertTrue(PROVENANCE.startswith(netlist.KLT_INPUTS_PREFIX))


class TestUnrelatedBehaviourUnchanged(unittest.TestCase):
    def test_netlist_without_provenance_line_is_untouched(self):
        """A pre-0.9 klt export normalizes exactly as it did before #295."""
        raw = "\n".join([
            "** sch_path: design/temp_core.sch",
            ".subckt temp_core VDD VSS IBIAS EN PTAT CTAT",
            ".ends",
        ]) + "\n"
        self.assertEqual(netlist.normalize(raw), raw)

    def test_repo_root_rewritten_to_relative(self):
        raw = f"** sch_path: {REPO}{os.sep}design/temp_core.sch\n"
        self.assertEqual(netlist.normalize(raw), "** sch_path: design/temp_core.sch\n")

    def test_trailing_whitespace_stripped(self):
        self.assertEqual(netlist.normalize(".ends   \n"), ".ends\n")

    def test_output_ends_in_exactly_one_newline(self):
        for raw in (".ends", ".ends\n", ".ends\n\n\n", f".ends\n{PROVENANCE}\n"):
            with self.subTest(raw=raw):
                self.assertEqual(netlist.normalize(raw), ".ends\n")


if __name__ == "__main__":
    unittest.main()
