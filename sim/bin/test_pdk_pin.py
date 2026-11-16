#!/usr/bin/env python3
"""PDK pin enforcement tests (issue #188). Stdlib only, no SPICE, no installed PDK.

Builds throwaway ``<root>/ciel/sky130/versions/<hash>/sky130A`` trees (the
layout ciel installs) and checks that corner-run.py's ``--print-env`` and
design/netlist.py's ``find_pdk()`` accept the pinned revision and refuse any
other, including a tree with no ``versions`` component ("unknown").

Since issue #292 ``find_pdk()`` is a thin wrapper over corner-run.py's own
``load_pin``/``resolve_pdk``, so these cases also cover the one shared
resolver both entry points go through -- and, since issue #304, that there is
exactly *one* loaded copy of it per process to go through.

Since issue #388 it also asserts the pin-refusal *message* invariant as a
source contract: one ``pdk_mismatch_message`` definition repo-wide, every
``not pdk.matches_pin`` guard raising through it, and the two-site
fail-closed asymmetry (see ``PdkMismatchMessageInvariantTests``).

Run: python3 -I sim/bin/test_pdk_pin.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
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

sys.path.insert(0, str(BIN))
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()  # the shared resolver (issue #292)


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
        self.assertEqual(cr.installed_commit(root / "sky130A"), PINNED)
        self.assertEqual(netlist.find_pdk().installed_commit, PINNED)

    def test_find_pdk_uses_the_shared_resolver(self):
        # find_pdk() must not carry its own copy of the resolution rules: no
        # private Pdk/pin-loader/revision-reader, and the object it returns is
        # corner-run.py's own Pdk (issue #292).
        for gone in ("Pdk", "load_pdk_pin", "installed_revision", "ENDS_RE"):
            self.assertFalse(
                hasattr(netlist, gone),
                f"design/netlist.py still defines {gone}",
            )
        os.environ["PDK_ROOT"] = str(make_tree(self.base, PINNED))
        self.assertIsInstance(netlist.find_pdk(), cr.Pdk)

    def test_find_pdk_honours_pin_defaults(self):
        # sim/pdk.json's default_pdk_root/variant -- not a hardcoded
        # ~/.ciel + sky130A -- decide what an unset PDK_ROOT/PDK resolves to.
        root = make_tree(self.base, PINNED, PIN["variant"])
        os.environ.pop("PDK_ROOT", None)
        pin = dict(PIN, default_pdk_root=str(root))
        original_load_pin = cr.load_pin
        cr.load_pin = lambda: pin
        try:
            pdk = netlist.find_pdk()
        finally:
            cr.load_pin = original_load_pin
        self.assertEqual(pdk.root, root)
        self.assertEqual(pdk.variant, PIN["variant"])

    def test_find_pdk_refuses_missing_model_library(self):
        # The shared resolver also requires the pin's ngspice_lib file, and the
        # refusal must still happen before klt netlist is ever invoked.
        root = make_tree(self.base, PINNED)
        (root / "sky130A" / PIN["ngspice_lib"]).resolve().unlink()
        os.environ["PDK_ROOT"] = str(root)
        with self.assertRaises(netlist.PdkNotFound) as cm:
            netlist.find_pdk()
        self.assertIn(PIN["ngspice_lib"], str(cm.exception))


class LoaderSingleCopyTests(unittest.TestCase):
    """`load_corner_run()` hands every caller the one registered copy (issue #304).

    The shim execs `corner-run.py` by path, so nothing but the loader itself
    stops a second exec. A second copy means a second `Pdk`/`HarnessError`:
    the module-level `cr = load_corner_run()` every campaign runner holds
    would stop being the module `corner_id()`, `netlist_tb_head()` and
    `design/netlist.py`'s `corner_run()` resolve against, and an exception
    raised through one would not be caught by the other's class name.
    """

    def test_loader_returns_the_registered_module(self):
        self.assertIs(sys.modules["corner_run"], cr)
        self.assertIs(sim_common.load_corner_run(), cr)

    def test_corner_id_does_not_register_a_second_copy(self):
        self.assertEqual(sim_common.corner_id("tt", 27.0, 1.8), "tt_27c_1.80v")
        self.assertIs(sys.modules["corner_run"], cr)
        self.assertIs(sim_common.load_corner_run(), cr)

    def test_resolver_entry_points_share_one_class_set(self):
        sim_common.corner_id("tt", 27.0, 1.8)
        self.assertIs(netlist.corner_run(), cr)
        self.assertIs(netlist.corner_run().Pdk, cr.Pdk)
        self.assertIs(netlist.corner_run().HarnessError, cr.HarnessError)


def raise_statement(lines: list[str], guard_idx: int, where: str = "") -> str | None:
    """The raise statement serving the ``if`` guard at ``guard_idx``, or None.

    A one-line ``if ...: raise ...`` guard is the line itself; otherwise walk
    forward past blank/comment lines to the first statement. If that is not a
    ``raise`` (bind-then-raise is unsupported) return None. Otherwise collect
    through the paren-balanced end of the statement -- however long -- so
    multi-line raises come back whole. A statement still open at end of file
    raises ``AssertionError`` naming ``where`` rather than returning partial
    text.
    """
    guard = lines[guard_idx]
    _, _, tail = guard.partition(":")
    if "raise" in tail:
        return guard
    collected: list[str] = []
    depth: int | None = None
    for line in lines[guard_idx + 1:]:
        if depth is None:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stripped.startswith("raise"):
                return None
            depth = line.count("(") - line.count(")")
        else:
            depth += line.count("(") - line.count(")")
        collected.append(line)
        if depth <= 0:
            return "\n".join(collected)
    if collected:
        raise AssertionError(
            f"{where or f'line {guard_idx + 1}'}: raise statement after the "
            "guard is unterminated (unbalanced parentheses to end of file)")
    return None


class RaiseStatementTests(unittest.TestCase):
    """``raise_statement`` itself: window, truncation and non-raise handling (#398)."""

    def test_one_line_guard_is_the_statement(self):
        lines = ["if not pdk.matches_pin: raise X(1)", "other()"]
        self.assertEqual(raise_statement(lines, 0), lines[0])

    def test_short_raise(self):
        lines = ["if g:", "    # why", "", "    raise X(", "        a,", "    )", "y()"]
        self.assertEqual(raise_statement(lines, 0), "\n".join(lines[3:6]))

    def test_long_raise_is_returned_whole(self):
        body = [f"        part{i}," for i in range(20)]
        lines = ["if g:", "    raise X(", *body, "        '--allow-pdk-mismatch',", "    )"]
        got = raise_statement(lines, 0)
        self.assertIn("--allow-pdk-mismatch", got)
        self.assertTrue(got.endswith("    )"))

    def test_raise_on_last_line_of_file(self):
        self.assertEqual(raise_statement(["if g:", "    raise X()"], 0), "    raise X()")

    def test_unterminated_raise_fails_loudly_naming_site(self):
        with self.assertRaises(AssertionError) as cm:
            raise_statement(["if g:", "    raise X(", "        a,"], 0, "f.py:1")
        self.assertIn("f.py:1", str(cm.exception))
        self.assertIn("unterminated", str(cm.exception))

    def test_non_raise_first_statement_returns_none(self):
        self.assertIsNone(raise_statement(["if g:", "    msg = f()", "    raise X(msg)"], 0))

    def test_guard_at_end_of_file_returns_none(self):
        self.assertIsNone(raise_statement(["if g:"], 0))


class PdkMismatchMessageInvariantTests(unittest.TestCase):
    """``pdk_mismatch_message`` is the one refusal text every pin guard raises (issue #388).

    #338/PR #355 routed the last hand-copied pin-refusal messages onto
    ``cr.pdk_mismatch_message`` and recorded the invariant only in a docstring
    (``design/netlist.py``). The drifted copies it replaced went unnoticed for
    ~2 months with every test green, so the invariant is asserted here at the
    source level, in the shape of ``test_runner_fleet_pdk.py``'s guards:

    * exactly one definition across ``sim/`` and ``design/``, and the message
      literal only in ``sim/bin/corner-run.py``;
    * every ``not pdk.matches_pin`` guard -- derived from the sources, not
      listed -- raises through the helper, so a sixth site joins the contract
      or fails here;
    * the refusal asymmetry is a two-way table: the fail-closed sites are
      named with expected counts, and the overridable ones must keep offering
      ``--allow-pdk-mismatch``.

    The asymmetry is deliberate (issue #338): ``--print-env`` output is eval'd
    by ``pdk-env.sh`` and must never offer an override, and
    ``design/netlist.py``'s argparse exposes no ``--allow-pdk-mismatch`` flag
    to offer. This guard preserves that behavior; it does not revise it.

    Stdlib source matching only: no runner is imported, and every scan skips
    this file itself because it quotes the needles it asserts on.
    """

    # Repo-relative posix path -> expected number of fail-closed guards in it.
    # The two entries: design/netlist.py's find_pdk() guard and corner-run.py's
    # --print-env guard. A fail-closed guard that appears, disappears or gains
    # an override must update this table deliberately.
    FAIL_CLOSED = {
        "design/netlist.py": 1,
        "sim/bin/corner-run.py": 1,
    }

    GUARD_RE = re.compile(r"^\s*(?:el)?if\b.*\bnot pdk\.matches_pin\b")

    def sources(self) -> dict[str, list[str]]:
        """Every ``.py`` under ``sim/`` and ``design/`` except this file, as {rel: lines}."""
        this_file = Path(__file__).resolve()
        found = {
            p.relative_to(REPO).as_posix(): p.read_text().splitlines()
            for root in ("sim", "design")
            for p in sorted((REPO / root).rglob("*.py"))
            if p.resolve() != this_file
        }
        self.assertTrue(found, "no sources found under sim/ and design/")
        return found

    def test_pdk_mismatch_message_has_exactly_one_definition(self):
        hits = [(rel, n) for rel, lines in self.sources().items()
                for n, line in enumerate(lines, start=1)
                if re.search(r"\bdef\s+pdk_mismatch_message\s*\(", line)]
        self.assertEqual(
            sorted({rel for rel, _ in hits}), ["sim/bin/corner-run.py"],
            "pdk_mismatch_message must have exactly one definition, in "
            "sim/bin/corner-run.py; found:\n  "
            + "\n  ".join(f"{rel}:{n}" for rel, n in hits))

    def test_the_message_literal_lives_only_in_corner_run(self):
        needle = "is open_pdks"
        hits = [(rel, n) for rel, lines in self.sources().items()
                for n, line in enumerate(lines, start=1)
                if needle in line]
        self.assertEqual(
            sorted({rel for rel, _ in hits}), ["sim/bin/corner-run.py"],
            f"the pin-refusal literal {needle!r} escaped corner-run.py:\n  "
            + "\n  ".join(f"{rel}:{n}" for rel, n in hits))

    def test_every_refusal_guard_raises_through_the_helper(self):
        fail_closed: dict[str, list[str]] = {}
        for rel, lines in self.sources().items():
            for n, line in enumerate(lines):
                if not self.GUARD_RE.match(line):
                    continue
                where = f"{rel}:{n + 1}"
                raise_src = raise_statement(lines, n, where)
                self.assertIsNotNone(
                    raise_src, f"{where}: first statement after the 'not pdk.matches_pin' "
                    "guard is not a raise; bind-then-raise is not supported by "
                    "this helper -- raise directly through pdk_mismatch_message")
                self.assertIn(
                    "pdk_mismatch_message", raise_src,
                    f"{where}: pin refusal does not route through "
                    "pdk_mismatch_message (hand-copied message text?)")
                if "allow_pdk_mismatch" in line:
                    self.assertIn(
                        "--allow-pdk-mismatch", raise_src,
                        f"{where}: overridable guard no longer offers "
                        "--allow-pdk-mismatch")
                else:
                    self.assertNotIn(
                        "--allow-pdk-mismatch", raise_src,
                        f"{where}: fail-closed guard offers the "
                        "--allow-pdk-mismatch override it must not offer")
                    fail_closed.setdefault(rel, []).append(where)
        self.assertEqual(
            {rel: len(sites) for rel, sites in fail_closed.items()},
            self.FAIL_CLOSED,
            "fail-closed pin refusals drifted from the two-way table (a site "
            "appeared, disappeared or changed side):\n  expected "
            f"{self.FAIL_CLOSED}\n  found: "
            + "; ".join(f"{rel}: {', '.join(sites)}"
                        for rel, sites in sorted(fail_closed.items()))
            + "\n  update FAIL_CLOSED deliberately if the asymmetry changed")


if __name__ == "__main__":
    unittest.main()
