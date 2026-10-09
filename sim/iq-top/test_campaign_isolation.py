#!/usr/bin/env python3
"""Campaign-level isolation test for run_iq_campaign.analyze_state (issue #133).

Stdlib only, no SPICE, no records written: a synthetic klt report in a temp
directory carries three corners -- one good waveform, one structurally
malformed waveform (ragged row -> load_wave ValueError) and one numerically
invalid waveform (NaN current -> grade invalid_input).  The bad points must be
recorded as nonconverged/invalid_input, the good point must still be graded,
and only the good point may produce a trace.

Run: python3 -I sim/iq-top/test_campaign_isolation.py
"""

from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import iq_checker as qc  # noqa: E402
import run_iq_campaign as rc  # noqa: E402

STATE = "iq-total"
VF = 3.3
TEMPS = [-40.0, 27.0, 125.0]  # good, ragged, nan


def wave_doc(wave: dict) -> dict:
    names = list(wave)
    return {"variables": [{"name": n} for n in names], "points": [[wave[n][i] for n in names] for i in range(len(wave["time"]))]}


class CampaignIsolation(unittest.TestCase):
    def setUp(self):
        self.man = copy.deepcopy(rc.load_manifest())
        self.man["corners"] = {"process": ["tt"], "temperature_c": TEMPS, "supply_v": [VF]}
        self.td = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.td.name)
        d = self.run_dir / STATE / rc.sim_common.rate_tag(self.man["measurement"]["rate_v_per_s"])
        d.mkdir(parents=True)
        good = qc.synth(STATE, VF)
        ragged = wave_doc(good)
        ragged["points"][100] = ragged["points"][100][:-1]
        nan = {k: list(v) for k, v in good.items()}
        nan["i(bvdd)"][-5] = float("nan")
        docs = [wave_doc(good), ragged, wave_doc(nan)]
        corners = []
        for temp, doc in zip(TEMPS, docs):
            wp = d / f"wave_{temp:g}.json"
            wp.write_text(json.dumps(doc))  # json writes NaN as a bare token; json.load reads it back
            corners.append({"process": "tt", "temperature_c": temp, "supply_v": {"vset": VF}, "status": "ok",
                            "measurements": [], "diagnostics": [], "artifacts": {"waveform": str(wp)}})
        (d / "report.json").write_text(json.dumps({"status": "ok", "corner_count": len(corners), "corners": corners}))

    def tearDown(self):
        self.td.cleanup()

    def test_bad_waveforms_do_not_lose_the_good_point(self):
        traces: dict = {}
        res = rc.analyze_state(STATE, self.run_dir, self.man, traces)
        pts = res["points"]
        good, ragged, nan = (pts[rc.corner_id("tt", t, VF)] for t in TEMPS)
        self.assertEqual(len(pts), 3)
        self.assertEqual(good["status"], "ok")
        self.assertFalse(good.get("invalid_input"))
        self.assertAlmostEqual(good["i_total_a"], 20e-6, delta=1e-15)
        for bad in (ragged, nan):
            self.assertEqual(bad["status"], "nonconverged")
            self.assertTrue(bad.get("invalid_input"))
            self.assertIn("invalid input", bad["reason"])
        self.assertIn("waveform unreadable", ragged["reason"])
        self.assertIn("non-finite", nan["reason"])
        # only the good point has a trace, and the trace serialises as strict JSON
        self.assertEqual(set(traces.get(STATE, {})), {rc.corner_id("tt", TEMPS[0], VF)})
        text = json.dumps(traces[STATE], allow_nan=False)
        self.assertTrue(all(math.isfinite(x) for x in json.loads(text)[rc.corner_id("tt", TEMPS[0], VF)]["i(bvdd)"]))


if __name__ == "__main__":
    unittest.main()
