#!/usr/bin/env python3
"""PDK pin enforcement tests (issue #188). Stdlib only, no SPICE, no installed PDK.

Builds throwaway ``<root>/ciel/sky130/versions/<hash>/sky130A`` trees (the
layout ciel installs) and checks that corner-run.py's ``--print-env`` and
design/netlist.py's ``find_pdk()`` accept the pinned revision and refuse any
other, including a tree with no ``versions`` component ("unknown").

Run: python3 -I sim/bin/test_pdk_pin.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent
REPO = BIN.parent.parent
PIN = json.loads((REPO / "sim" / "pdk.json").read_text())
PINNED = PIN["open_pdks_commit"]
OTHER = "0" * 40


def load(name: str, path: Path):
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


netlist = load("pdk_pin_netlist", REPO / "design" / "netlist.py")


def make_tree(base: Path, revision: str | None, variant: str = "sky130A") -> Path:
    """Return a PDK_ROOT whose <variant> symlink resolves into versions/<revision>."""
    root = base / "root"
    if revision is None:
        real = base / "flat" / variant
    else:
        real = base / "ciel" / "sky130" / "versions" / revision / variant
    (real / "libs.tech" / "combined").mkdir(parents=True)
    (real / PIN["ngspice_lib"]).write_text("* stub\n")
    root.mkdir()
    (root / variant).symlink_to(real)
    return root


def print_env(root: Path, **extra: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PDK_ROOT", "PDK")}
    env.update(PDK_ROOT=str(root), **extra)
    return subprocess.run(
        [sys.executable, str(BIN / "corner-run.py"), "--print-env"],
        capture_output=True, text=True, env=env,
    )


class PinTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ("PDK_ROOT", "PDK")}
        os.environ.pop("PDK", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def test_print_env_accepts_pin(self):
        r = print_env(make_tree(self.base, PINNED))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("export PDK_ROOT=", r.stdout)

    def test_print_env_refuses_other_revision(self):
        r = print_env(make_tree(self.base, OTHER))
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("export", r.stdout)
        self.assertIn(OTHER, r.stderr)
        self.assertIn(PINNED, r.stderr)
        self.assertIn("ciel enable", r.stderr)

    def test_print_env_refuses_unknown_revision(self):
        r = print_env(make_tree(self.base, None))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown", r.stderr)

    def test_find_pdk_accepts_pin(self):
        os.environ["PDK_ROOT"] = str(make_tree(self.base, PINNED))
        self.assertEqual(netlist.find_pdk().variant, "sky130A")

    def test_find_pdk_refuses_other_revision(self):
        os.environ["PDK_ROOT"] = str(make_tree(self.base, OTHER))
        with self.assertRaises(netlist.PdkNotFound) as cm:
            netlist.find_pdk()
        for needle in (OTHER, PINNED, "ciel enable"):
            self.assertIn(needle, str(cm.exception))

    def test_find_pdk_refuses_unknown_revision(self):
        os.environ["PDK_ROOT"] = str(make_tree(self.base, None))
        with self.assertRaises(netlist.PdkNotFound):
            netlist.find_pdk()

    def test_variant_override(self):
        os.environ["PDK_ROOT"] = str(make_tree(self.base, PINNED, "sky130B"))
        os.environ["PDK"] = "sky130B"
        self.assertEqual(netlist.find_pdk().variant, "sky130B")

    def test_bak_sibling_not_picked_up(self):
        # A ".bak-*" sibling of the pinned version must not change the verdict.
        root = make_tree(self.base, PINNED)
        (self.base / "ciel" / "sky130" / "versions" / f"{PINNED}.bak-1" / "sky130A").mkdir(parents=True)
        os.environ["PDK_ROOT"] = str(root)
        self.assertEqual(netlist.installed_revision(root / "sky130A"), PINNED)


if __name__ == "__main__":
    unittest.main()
