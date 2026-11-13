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

import re
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
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


# --------------------------------------------------------------------------
# Source-level regression guard: no campaign runner may STATE a tool version
# --------------------------------------------------------------------------
#
# The builder above makes deriving a version easy; this guard makes stating one
# detectable.  It is the second half of issue #306: `run_solver_sweep.py` kept a
# `fleet runner klt 0.5.0` literal for two months after #297 removed the same shape
# from the seven campaign runners, because the only check was a grep in a merged PR
# body (`0\.5\.0 runner`, which does not match `runner klt 0.5.0`).  A grep that lives
# in a PR body guards nothing; this one runs in CI on every push.

RUNNER_GLOB = "sim/*/run_*.py"

VERSION_LITERAL_PATTERNS = (
    ("fleet/host ngspice version", re.compile(r"ngspice[- ]\d{2,}")),
    ("klt version", re.compile(r"\bklt\b[^\n]{0,16}?\d+\.\d+\.\d+")),
    ("xschem version", re.compile(r"(?i)\bxschem\b[^\n]{0,16}?\d+\.\d+\.\d+")),
    ("open_pdks commit", re.compile(r"\b[0-9a-f]{40}\b")),
)

# A runner may be waived ONLY with an open issue that removes it.  `test_waivers_are_not
# _stale` fails once a waived file is clean, so a waiver cannot outlive its fix.
# Empty is the healthy state: every runner derives its tool versions.  The dict stays so
# the waiver mechanism (and `test_waivers_are_not_stale`) remains available and tested.
WAIVED_RUNNERS: dict[str, str] = {}


def scan_version_literals(text: str) -> list[tuple[int, str, str]]:
    """`(line number, what it is, the offending line)` for every stated tool version.

    Matches the *source*, not a rendered record: an f-string placeholder
    (`f"ngspice-{v}"`, `` f"klt `{runner_klt}`" ``) carries no digits and is therefore
    invisible here, which is exactly the distinction the guard is drawing -- derived is
    fine, stated is not.
    """
    hits = []
    for n, line in enumerate(text.splitlines(), start=1):
        for label, rx in VERSION_LITERAL_PATTERNS:
            if rx.search(line):
                hits.append((n, label, line.strip()))
    return hits


# The two lines `run_solver_sweep.py` carried before #306, verbatim from
# `git show fd299ead:sim/temp-core-startup-solver/run_solver_sweep.py`.  Keeping them as
# a fixture means "the guard would have caught this" stays asserted forever, not just on
# the commit that added the guard.  Note that even on this version the *ngspice* half was
# already derived (`ngspice-{next(...)}`) -- what was stated were the open_pdks commit and
# the runner's klt, which is precisely what the guard reports.
PRE_306_SOLVER_LINES = (
    '         "- **PDK**: sky130A @ open_pdks `c6d73a35f524070e85faff4a6a9eef49553ebc2b` (matches sim/pdk.json pin), models `libs.tech/combined/sky130.lib.spice` (sha256 48de7c67...)",'
    "\n"
    '         f"- **Tools**: {klt_client} (client); fleet ngspice-{next((s.get(\'ngspice_engine_version\') for s in summary.values() if s.get(\'ngspice_engine_version\')), \'?\')} on Spot `c7i/m7i.4xlarge`, fleet runner klt 0.5.0 (version mismatch warning from the client, reported per job below); backend `{meta[\'klt_sim_backend_env\']}`",'
    "\n"
)

# The shapes #297 removed from the seven campaign runners, kept so the ngspice and xschem
# patterns stay exercised after the last in-tree example of each is gone.
RETIRED_CAMPAIGN_LITERALS = (
    '    "ngspice": "ngspice-46 (per fleet log)",\n'
    '    "xschem_note": "host xschem is 3.4.4",\n'
)


class RunnerVersionLiteralTest(unittest.TestCase):
    """No `sim/*/run_*.py` may state a tool version as a literal (issue #306)."""

    def runners(self) -> list[Path]:
        found = sorted(REPO_ROOT.glob(RUNNER_GLOB))
        self.assertTrue(found, f"no runner matched {RUNNER_GLOB} under {REPO_ROOT}")
        return found

    def test_no_runner_states_a_tool_version_literal(self):
        offenders = []
        for path in self.runners():
            rel = path.relative_to(REPO_ROOT).as_posix()
            if rel in WAIVED_RUNNERS:
                continue
            for n, label, line in scan_version_literals(path.read_text()):
                offenders.append(f"{rel}:{n}: {label}: {line}")
        self.assertEqual(
            offenders, [],
            "a runner states a tool version instead of deriving it from the run:\n  "
            + "\n  ".join(offenders)
            + "\n\nDerive it (sim_common.joined_versions / record_pdk_tools / "
              "cr.resolve_pdk), or add an entry to WAIVED_RUNNERS naming the issue "
              "that removes it.",
        )

    def test_waivers_are_not_stale(self):
        """A waived runner that is now clean must lose its waiver, or the next literal
        it grows goes unreported."""
        for rel, why in WAIVED_RUNNERS.items():
            path = REPO_ROOT / rel
            self.assertTrue(path.is_file(), f"WAIVED_RUNNERS names a missing file: {rel}")
            self.assertIn("#", why, f"waiver for {rel} names no tracking issue")
            self.assertTrue(
                scan_version_literals(path.read_text()),
                f"{rel} no longer states a tool version -- drop its WAIVED_RUNNERS entry ({why})",
            )

    def test_the_guard_flags_the_shape_that_regressed(self):
        """All four patterns fire, on the lines that actually carried them."""
        hits = scan_version_literals(PRE_306_SOLVER_LINES)
        self.assertEqual(
            {(n, label) for n, label, _ in hits},
            {(1, "open_pdks commit"), (2, "klt version")},
            f"guard missed a pre-#306 literal: {hits}",
        )
        retired = scan_version_literals(RETIRED_CAMPAIGN_LITERALS)
        self.assertEqual(
            {(n, label) for n, label, _ in retired},
            {(1, "fleet/host ngspice version"), (2, "xschem version")},
            f"guard missed a retired campaign-runner literal: {retired}",
        )

    def test_the_guard_ignores_a_derived_version(self):
        """An f-string placeholder is not a literal; the guard must not fire on the
        post-#306 shape, or the only way to pass it would be to say nothing at all."""
        derived = (
            'f"- **Tools**: {klt_client} (client); fleet `{prov[\'fleet_ngspice\']}` on '
            'Spot `{prov[\'fleet_instance_type\']}`, fleet runner klt '
            '`{prov[\'fleet_runner_klt\']}`; backend `{backend}`"\n'
            'f"- **PDK**: {pdk.variant} @ open_pdks `{pdk.installed_commit}` ({pin_state})"\n'
        )
        self.assertEqual(scan_version_literals(derived), [])


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
