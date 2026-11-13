#!/usr/bin/env python3
"""Unit tests for the shared record `pdk` / `tools` provenance builder (issue #297).

The point of `sim_common.record_pdk_tools()` is that every tool version in a record is
*derived from what actually ran* -- the fleet's ngspice from each corner's klt log, the
fleet runner's klt from each request, the host's from `corner-run.tool_versions()`.  The
seven fleet runners used to assemble this block by hand, and four of them had drifted
into stating a constant (`ngspice-46 (per fleet log)`, `ngspice-42 (host)`, `the 0.5.0
runner`, `host xschem is 3.4.4`) that no longer matched the tools in use.

These tests pin the two properties that made that drift possible:
  * a version only ever appears if an input carried it, and
  * an input that carries nothing yields the explicit string `unknown`, never a default
    version and never a silently-omitted key.

Stdlib only, no SPICE, no PDK: the host half is stubbed so the test is hermetic.

Run: python3 -I sim/bin/test_sim_common_provenance.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sim_common as sc  # noqa: E402

HOST = {
    "ngspice": "ngspice-47 : Circuit level simulation program",
    "xschem": "XSCHEM V3.4.7",
    "platform": "Linux 7.0.0 x86_64",
    "python": "3.12.3",
}


class _Pdk:
    """The three `pdk` attributes the builder reads (corner-run's resolved-PDK object)."""

    variant = "sky130A"
    installed_commit = "a" * 40
    matches_pin = True


PIN = {"open_pdks_commit": "a" * 40, "ngspice_lib": "libs.tech/ngspice/sky130.lib.spice"}
META = {"klt_client": "klayout-tools 0.9.0"}


def build(**kw):
    """`record_pdk_tools()` with the host half stubbed (no ngspice/xschem on the box)."""
    with mock.patch.object(sc, "host_tool_versions", return_value=HOST):
        return sc.record_pdk_tools(_Pdk(), PIN, META, **kw)


class FleetNgspiceTest(unittest.TestCase):
    """The single klt-log banner regex the five campaign runners used to each carry."""

    def test_extracts_the_announced_version(self):
        self.assertEqual(sc.fleet_ngspice("...\nngspice-47 done\n..."), "ngspice-47")

    def test_takes_the_first_announcement(self):
        self.assertEqual(sc.fleet_ngspice("ngspice-46 done\nngspice-47 done\n"), "ngspice-46")

    def test_no_banner_is_none_not_a_guess(self):
        self.assertIsNone(sc.fleet_ngspice(""))
        self.assertIsNone(sc.fleet_ngspice("ngspice-47 starting"))  # not the `done` banner
        self.assertIsNone(sc.fleet_ngspice("ngspice done"))  # no version in the banner


class JoinedVersionsTest(unittest.TestCase):
    def test_sorted_deduplicated_join(self):
        items = [{"v": "b"}, {"v": "a"}, {"v": "b"}]
        self.assertEqual(sc.joined_versions(items, "v"), "a, b")

    def test_empty_and_missing_and_none_entries_are_unknown(self):
        self.assertEqual(sc.joined_versions([], "v"), "unknown")
        self.assertEqual(sc.joined_versions([{}, {"v": None}, {"v": ""}, None], "v"), "unknown")


class RecordPdkToolsTest(unittest.TestCase):
    def test_fleet_versions_come_from_the_inputs(self):
        points = [{"ngspice": "ngspice-47"}, {"ngspice": "ngspice-47"}, {"ngspice": "ngspice-46"}]
        requests = [{"runner_klt_version": "0.9.0"}, {"runner_klt_version": None}]
        _, tools = build(points=points, requests=requests)
        self.assertEqual(tools["fleet_ngspice"], "ngspice-46, ngspice-47")
        self.assertEqual(tools["fleet_runner_klt"], "0.9.0")

    def test_no_inputs_yields_unknown_not_a_default_version(self):
        """The regression this builder exists to prevent: an unobserved fleet version must
        read `unknown`, never a literal left over from whenever the code was written."""
        _, tools = build()
        self.assertEqual(tools["fleet_ngspice"], "unknown")
        self.assertEqual(tools["fleet_runner_klt"], "unknown")
        # ...and no other recorded field smuggles a fleet version back in (the host's own
        # banner is the one place an `ngspice-NN` may legitimately appear).
        for key, value in tools.items():
            if key == "ngspice":
                continue
            self.assertNotRegex(str(value), r"ngspice-\d+", f"stale fleet literal in tools[{key!r}]")

    def test_alternate_field_names(self):
        _, tools = build(points=[{"ng": "ngspice-47"}], requests=[{"klt": "0.9.0"}],
                         ngspice_key="ng", runner_key="klt")
        self.assertEqual(tools["fleet_ngspice"], "ngspice-47")
        self.assertEqual(tools["fleet_runner_klt"], "0.9.0")

    def test_host_versions_are_read_not_stated(self):
        _, tools = build()
        self.assertEqual(tools["ngspice"], HOST["ngspice"] + sc.HOST_NGSPICE_SUFFIX)
        self.assertEqual(tools["xschem"], HOST["xschem"])
        self.assertEqual(tools["platform"], HOST["platform"])
        self.assertEqual(tools["python"], HOST["python"])
        self.assertEqual(tools["klt_client"], META["klt_client"])

    def test_host_tools_off_records_no_host_engine(self):
        """A driver that never invokes ngspice/xschem (run_reassert_diagnosis) must not
        claim a host engine version it did not use."""
        _, tools = build(host_tools=False)
        self.assertNotIn("ngspice", tools)
        self.assertNotIn("xschem", tools)
        self.assertEqual(tools["python"], HOST["python"])  # platform/python still recorded

    def test_pdk_block(self):
        pdk, _ = build()
        self.assertEqual(pdk, {
            "variant": "sky130A", "installed_commit": "a" * 40, "pinned_commit": "a" * 40,
            "matches_pin": True, "root": sc.HOST_PDK_ROOT, "lib_file": sc.RUNNER_LIB_FILE,
        })
        self.assertIn(sc.MODEL_LIB, sc.RUNNER_LIB_FILE)

    def test_optional_keys_are_omitted_not_defaulted(self):
        pdk, tools = build(lib_file=None, root=None, fleet_note=None, xschem_note=None)
        self.assertNotIn("lib_file", pdk)
        self.assertNotIn("root", pdk)
        self.assertNotIn("fleet_note", tools)
        self.assertNotIn("xschem_note", tools)

    def test_notes_default_to_the_shared_version_free_text(self):
        """The ramp runner's own copies named `the 0.5.0 runner` and `xschem is 3.4.4`;
        the shared notes state the same behaviour without a version that can go stale."""
        _, tools = build()
        self.assertEqual(tools["fleet_note"], sc.FLEET_NOTE)
        self.assertEqual(tools["xschem_note"], sc.XSCHEM_NOTE)
        for note in (sc.FLEET_NOTE, sc.XSCHEM_NOTE):
            self.assertNotRegex(note, r"\d+\.\d+\.\d+|ngspice-\d+", f"version literal in {note!r}")

    def test_thresholds_style_custom_lib_file(self):
        pdk, _ = build(lib_file=f"$PDK_ROOT/sky130A/{PIN['ngspice_lib']}")
        self.assertEqual(pdk["lib_file"], f"$PDK_ROOT/sky130A/{PIN['ngspice_lib']}")

    def test_renderer_accepts_the_built_block(self):
        """`render_pdk_tools_repo_state()` is the shared consumer; the default shape must
        satisfy every key it reads."""
        pdk, tools = build()
        lines = sc.render_pdk_tools_repo_state(
            {"pdk": pdk, "tools": tools, "git": {"sha": "deadbee", "branch": "main", "dirty": False}}
        )
        self.assertIn("sky130A", lines[0])
        self.assertIn("ngspice-47", lines[1])
        self.assertIn("XSCHEM V3.4.7", lines[1])


class HostNgspiceTagTest(unittest.TestCase):
    """The short `ngspice-NN` token the ramp/iq local-vs-fleet cross-check sentences use
    in place of the `ngspice-42 (host)` literals they used to carry."""

    def test_tag_is_extracted_from_the_banner(self):
        with mock.patch.object(sc, "host_tool_versions", return_value=HOST):
            self.assertEqual(sc.host_ngspice_tag(), "ngspice-47")

    def test_missing_version_is_unknown(self):
        with mock.patch.object(sc, "host_tool_versions", return_value={**HOST, "ngspice": "not found"}):
            self.assertEqual(sc.host_ngspice_tag(), "unknown")


if __name__ == "__main__":
    unittest.main()
