"""Regression test for variant ownership of the supply-ramp recorder's local probe."""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_ramp_campaign as campaign


class RecordCrosscheckTest(unittest.TestCase):
    def test_only_probed_variant_records_crosscheck_in_either_order(self):
        probed = "diag-mn1-l20"
        sibling = "as-drawn"
        for order in ((probed, sibling), (sibling, probed)):
            with self.subTest(order=order), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                run = root / "run"
                probe = run / "crosscheck"
                probe.mkdir(parents=True)
                (run / "run.json").write_text(json.dumps({"variants": order}))
                (probe / "variant.txt").write_text(probed + "\n")
                fixtures = campaign.HERE / "selftest"
                local = {"artifacts": {"waveform": str(fixtures / "single_release.wave.json")}}
                (probe / "report.json").write_text(json.dumps({"corners": [local]}))
                fleet = {
                    "process": "tt",
                    "temperature_c": 27,
                    "supply_v": {"vset": 3.3},
                    "artifacts": {"waveform": str(fixtures / "double_release.wave.json")},
                }
                for variant in order:
                    rate = run / variant / campaign.rate_tag(1e4)
                    rate.mkdir(parents=True)
                    (rate / "report.json").write_text(json.dumps({"corners": [fleet]}))

                pdk = SimpleNamespace(variant="sky130A", installed_commit="test", matches_pin=False)
                tools = {"ngspice": "ngspice-46", "xschem": "test", "python": "test", "platform": "test"}
                with (
                    patch.multiple(campaign, HERE=root, BUILD=root, REPO_ROOT=root),
                    patch.object(campaign.cr, "resolve_pdk", return_value=pdk),
                    patch.object(campaign.sim_common, "host_tool_versions", return_value=tools),
                    patch.multiple(
                        campaign.evidence_store,
                        STAGE_ROOT=root / "stage",
                        MANIFEST_DIR=root / "manifests",
                        preflight_or_exit=Mock(),
                        store_or_exit=Mock(return_value=(root / "manifest.json", root / "summary.md")),
                    ),
                    patch.object(campaign, "datetime") as clock,
                ):
                    # Each variant needs a distinct second for its append-only record ID.
                    clock.now.side_effect = [datetime(2026, 1, 1, 0, 0, s) for s in (0, 1)]
                    self.assertEqual(campaign.main(["record", "--run-id", "run", "--author", "test"]), 0)

                paths = sorted((root / "records").glob("*.json"))
                self.assertEqual(len(paths), 2)
                for variant, path in zip(order, paths):
                    record = json.loads(path.read_text())
                    self.assertEqual(record["variant"]["name"], variant)
                    markdown = path.with_suffix(".md").read_text()
                    comparison = record["crosscheck"]
                    if variant == probed:
                        self.assertEqual(comparison["local"]["verdict"], "PASS")
                        self.assertEqual(comparison["fleet"]["verdict"], "FAIL")
                        self.assertIn(f"variant {probed}", comparison["text"])
                        self.assertIn("## Local cross-check", markdown)
                        self.assertIn(comparison["text"], markdown)
                    else:
                        self.assertIsNone(comparison)
                        self.assertNotIn("## Local cross-check", markdown)


if __name__ == "__main__":
    unittest.main()
