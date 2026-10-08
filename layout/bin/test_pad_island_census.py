"""Focused regressions for pad-island-census.py's issue-#81 changes.

Run from the repo root:

    python3 -m unittest layout/bin/test_pad_island_census.py

The `_device_body_cuts` cases need `klayout.db`; run them under the
interpreter `klt` runs on (e.g. the venv `klt` lives in) or they skip.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("pad_island_census", _HERE / "pad-island-census.py")
census = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(census)

try:
    import klayout.db as kdb  # noqa: F401

    HAVE_KLAYOUT = True
except ImportError:  # pragma: no cover - depends on the interpreter
    HAVE_KLAYOUT = False


def _port(name, x, y):
    return {"name": name, "x_um": x, "y_um": y, "layer": {"layer": 67, "datatype": 20}}


class ProbePointsTest(unittest.TestCase):
    def _assembly(self, tmp: Path, sibling_ports, declared_ports):
        sib = tmp / "sib"
        sib.mkdir()
        (sib / "compose.response.json").write_text(json.dumps({"ports": sibling_ports}))
        top = tmp / "top"
        top.mkdir()
        spec = {
            "cell": "top",
            "blocks": [
                {
                    "id": "b",
                    "cell": {"gds_path": "../sib/sib.gds", "ports": declared_ports},
                }
            ],
            "placement": {"origins_um": {"b": {"x": 10.0, "y": -5.0}}},
            "connectivity": [{"net": "n", "pins": [{"block": "b", "port": "p"}]}],
        }
        return spec, top

    def test_promoted_port_is_frame_checked_against_sibling(self):
        with tempfile.TemporaryDirectory() as d:
            spec, top = self._assembly(Path(d), [_port("p", 1.0, 2.0)], [_port("p", 1.0, 2.0)])
            (probe,) = census._probe_points(spec, top)
        self.assertEqual(probe["probe_source"], "sibling_compose_response")
        self.assertIs(probe["declared_matches_source"], True)
        self.assertEqual((probe["x_um"], probe["y_um"]), (11.0, -3.0))

    def test_unpromoted_sibling_port_falls_back_to_declaration(self):
        # The sibling reports ports, but not `p` (an internal net it cannot
        # promote): use the assembly's declaration, translated once, and say so.
        with tempfile.TemporaryDirectory() as d:
            spec, top = self._assembly(Path(d), [_port("other", 0.0, 0.0)], [_port("p", 3.0, 4.0)])
            (probe,) = census._probe_points(spec, top)
        self.assertEqual(probe["probe_source"], "assembly_declaration_unpromoted_sibling_port")
        self.assertIsNone(probe["declared_matches_source"])
        self.assertEqual((probe["x_um"], probe["y_um"]), (13.0, -1.0))

    def test_port_missing_from_both_sources_still_fails(self):
        with tempfile.TemporaryDirectory() as d:
            spec, top = self._assembly(Path(d), [_port("other", 0.0, 0.0)], [])
            with self.assertRaises(SystemExit):
                census._probe_points(spec, top)


@unittest.skipUnless(HAVE_KLAYOUT, "klayout.db not importable on this interpreter")
class DeviceBodyCutsTest(unittest.TestCase):
    def _layout(self):
        layout = kdb.Layout()
        layout.dbu = 0.001
        top = layout.create_cell("TOP")
        poly = layout.layer(66, 20)
        mark = layout.layer(66, 13)
        # One poly bar with a resistor-ID mark across its middle.
        top.shapes(poly).insert(kdb.Box(0, 0, 3000, 200))
        top.shapes(mark).insert(kdb.Box(1000, -100, 2000, 300))
        return layout, top

    def test_body_is_subtracted_and_splits_the_conductor(self):
        layout, top = self._layout()
        spec = {
            "stackup": [{"name": "poly", "layer": "66/20"}],
            "devices": [{"body_layer": "66/13", "on": "poly"}],
        }
        cuts = census._device_body_cuts(kdb, layout, top, spec)
        self.assertEqual(set(cuts), {"poly"})
        poly = census._region(kdb, layout, top, (66, 20)) - cuts["poly"]
        self.assertEqual(poly.merged().count(), 2)  # two terminals, no bridge

    def test_unknown_role_is_rejected(self):
        layout, top = self._layout()
        spec = {
            "stackup": [{"name": "poly", "layer": "66/20"}],
            "devices": [{"body_layer": "66/13", "on": "met9"}],
        }
        with self.assertRaises(SystemExit):
            census._device_body_cuts(kdb, layout, top, spec)

    def test_no_devices_means_no_cuts(self):
        layout, top = self._layout()
        self.assertEqual(census._device_body_cuts(kdb, layout, top, {"stackup": []}), {})


if __name__ == "__main__":
    unittest.main()
