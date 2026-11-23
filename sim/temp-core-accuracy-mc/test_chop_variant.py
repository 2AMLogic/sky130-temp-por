#!/usr/bin/env python3
"""Tests for the `chop-degen` variant of run_accuracy_mc and the phase-pairing residual
analysis of sim/temp-core-chop-offset (issue #461).

The variant is what issue #461 is: the #284 mirror rewrite composed with cross-coupled
input/output choppers around the temp_core input pair, expressed as a rewrite of the
GENERATED deck only.  These tests pin the properties that make the two-phase residual
solve trustworthy:

  * the rewrite lands on the committed netlist and re-wires exactly XMI1/XMI2;
  * every device the rewrite ADDS belongs to a mismatch term (switches -> `amp`,
    XRDEG -> `mirror`), so no device is outside the attribution;
  * the `none` deck wraps the switches with the mmoff_* wrappers (sigma = 0 control
    covers the new devices too);
  * the two DC phase decks are device-identical -- they differ ONLY in the four
    chopper control literals -- so two requests sharing corners/seed/N draw the same
    per-sample mismatch (the pairing property the residual average depends on);
  * build_netlist refuses the phase/transient combinations that do not exist;
  * the transient deck carries the PULSE controls and gear;
  * phase pairing: a complete valid pair is averaged; a sample with a MISSING phase is
    counted incomplete, never averaged; a guard failure in ONE phase invalidates the
    pair; a failed nominal reference excludes the corner;
  * the residual is referred through G = 26 V/V and the cancellation ratio is computed
    from single-phase vs paired spreads.

Stdlib only: no SPICE, no PDK, no run directory, no record written.

Run: python3 -I sim/temp-core-accuracy-mc/test_chop_variant.py
"""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM_DIR / "temp-core-chop-offset"))
import run_accuracy_mc as m  # noqa: E402
import run_chop_offset as x  # noqa: E402

CHOP = m.CHOP_VARIANT


def cell_devices(netlist, cell="temp_core"):
    """instance-name -> line, for the X-devices of one subckt of a generated deck."""
    out, inside = {}, False
    for ln in netlist.splitlines():
        s = ln.strip()
        if s.lower().startswith(".subckt"):
            inside = s.split()[1] == cell
            continue
        if s.lower().startswith(".ends"):
            inside = False
            continue
        if inside and s.upper().startswith("X"):
            out[s.split()[0].upper()] = s
    return out


class TestChopVariantRegistered(unittest.TestCase):
    def test_variant_listed_with_description(self):
        self.assertIn(CHOP, m.VARIANTS)
        self.assertIn("chopped amplifier", m.VARIANT_DESC[CHOP])

    def test_switches_grouped_into_amp_term(self):
        for sw in m.CHOP_SW:
            self.assertEqual(m.temp_core_group(f"X{sw}N", CHOP), "amp")
            self.assertEqual(m.temp_core_group(f"X{sw}P", CHOP), "amp")
        # the variant's other additions stay where #284 put them
        for i in (1, 2, 3):
            self.assertEqual(m.temp_core_group(f"XRDEG{i}", CHOP), "mirror")
        # the original amplifier devices are still the amp term, and the groups are unchanged
        self.assertEqual(m.temp_core_group("XMI1", CHOP), "amp")
        self.assertEqual(m.temp_core_group("XML2", CHOP), "amp")
        self.assertEqual(m.temp_core_group("XMP3", CHOP), "mirror")
        self.assertEqual(m.temp_core_group("XQ8A", CHOP), "pnp")
        # grouping of the pre-existing variants must not move
        self.assertEqual(m.temp_core_group("XRDEG1", "mirror-degen"), "mirror")
        self.assertEqual(m.temp_core_group("XSWI1N", "mirror-degen"), "other")
        self.assertEqual(m.temp_core_group("XSWI1N", "baseline"), "other")


class TestChopRewrite(unittest.TestCase):
    def test_input_pair_rewired_and_switches_added(self):
        deck = m.build_netlist("amp", CHOP, phase="a")
        devs = cell_devices(deck)
        self.assertIn("XMI1", devs)
        tok = devs["XMI1"].split()
        self.assertEqual((tok[1], tok[2]), ("ND1", "NGA1"), "XMI1 drain/gate must be re-wired")
        tok = devs["XMI2"].split()
        self.assertEqual((tok[1], tok[2]), ("ND2", "NGA2"), "XMI2 drain/gate must be re-wired")
        self.assertNotIn("NGA1", [t for t in devs["XMI1"].split()][3:])  # gate node used once
        for sw in m.CHOP_SW:  # all 16 switch instances present
            self.assertIn(f"X{sw}N", devs, f"missing nfet half of {sw}")
            self.assertIn(f"X{sw}P", devs, f"missing pfet half of {sw}")
        # the mirror rewrite composed: XMP1 source on the degeneration node, XRDEG1 present
        self.assertEqual(devs["XMP1"].split()[3], "SDG1")
        self.assertIn("XRDEG1", devs)
        # control sources present
        txt = "\n".join(deck.splitlines())
        for s in ("VCKA CHA 0", "VCKAB CHAB 0", "VCKB CHB 0", "VCKBB CHBB 0"):
            self.assertIn(s, txt)
        # regression (the pin-order bug): the CLOCK must sit on gate pin 2 of every switch --
        # an earlier draft put the signal node on the gate and the clock on a terminal, which
        # turned every pass gate into a follower that never switched
        for sw, (n1, n2, ph) in m.CHOP_SW.items():
            g, gi = ("CHA", "CHAB") if ph == "a" else ("CHB", "CHBB")
            nf = devs[f"X{sw}N"].split()
            pf = devs[f"X{sw}P"].split()
            self.assertEqual((nf[1], nf[2], nf[3], nf[4]), (n1, g, n2, "VSS"), f"{sw} nfet pins")
            self.assertEqual((pf[1], pf[2], pf[3], pf[4]), (n1, gi, n2, "VDD"), f"{sw} pfet pins")

    def test_refuses_unexpected_input_pair(self):
        lines = ["XMI1 N9 N9 NT NT sky130_fd_pr__pfet_g5v0d10v5 L=4 W=32 m=1", ".ends"]
        with self.assertRaises(SystemExit):
            m.chop_amplifier(lines, phase="a")

    def test_refuses_missing_input_pair(self):
        with self.assertRaises(SystemExit):
            m.chop_amplifier(["XMI2 N2 NB NT NT sky130_fd_pr__pfet_g5v0d10v5 L=4 W=32 m=1", ".ends"], phase="a")

    def test_needs_phase_or_clock(self):
        with self.assertRaises(SystemExit):
            m.chop_amplifier(["XMI1 N1 NA NT NT sky130_fd_pr__pfet_g5v0d10v5 L=4 W=32 m=1",
                              "XMI2 N2 NB NT NT sky130_fd_pr__pfet_g5v0d10v5 L=4 W=32 m=1", ".ends"])


class TestPhaseDeckIdentity(unittest.TestCase):
    """The pairing property: phase A and B decks differ ONLY in control literals."""

    @staticmethod
    def decks(term):
        a = m.build_netlist(term, CHOP, phase="a").splitlines()
        b = m.build_netlist(term, CHOP, phase="b").splitlines()
        return a, b

    def test_device_lines_identical_across_phases(self):
        for term in ("nominal", "none", "amp"):
            a, b = self.decks(term)
            self.assertEqual(len(a), len(b))
            da = [ln for ln in a if ln.upper().startswith("X") and " " in ln]
            db = [ln for ln in b if ln.upper().startswith("X") and " " in ln]
            self.assertEqual(da, db, f"{term}: instance lines must be phase-identical")

    def test_only_control_and_header_differ(self):
        a, b = self.decks("amp")
        diff = [(x, y) for x, y in zip(a, b) if x != y]
        self.assertEqual(len(diff), 5, "header comment + the four control literals only")
        for x, y in diff[1:]:
            self.assertTrue(x.startswith("VCK") and y.startswith("VCK"), diff)

    def test_phase_a_straight_phase_b_crossed(self):
        a = {t[0]: t[3] for t in (ln.split() for ln in m.build_netlist("amp", CHOP, phase="a").splitlines() if ln.startswith("VCK"))}
        b = {t[0]: t[3] for t in (ln.split() for ln in m.build_netlist("amp", CHOP, phase="b").splitlines() if ln.startswith("VCK"))}
        self.assertEqual(a["VCKA"], "2.5")
        self.assertEqual(a["VCKAB"], "0")
        self.assertEqual(a["VCKB"], "0")
        self.assertEqual(b["VCKA"], "0")
        self.assertEqual(b["VCKB"], "2.5")


class TestWrappingAndValidation(unittest.TestCase):
    def test_none_deck_wraps_switches(self):
        deck = m.build_netlist("none", CHOP, phase="a")
        # pin order is the models' d g s b: the CLOCK sits on pin 2 (gate), signal nodes on d/s
        self.assertIn("XSWI1N NA CHA NGA1 VSS mmoff_nfet", deck)
        self.assertIn("XSWI1P NA CHAB NGA1 VDD mmoff_pfet", deck)
        self.assertIn("XSWO3N ND1 CHB N2 VSS mmoff_nfet", deck)
        self.assertIn("XSWO4P ND2 CHBB N1 VDD mmoff_pfet", deck)
        wrapped = sum(1 for ln in deck.splitlines() if ln.startswith("XSW") and "mmoff_" in ln)
        self.assertEqual(wrapped, 16)

    def test_nominal_deck_leaves_switches_unwrapped(self):
        deck = m.build_netlist("nominal", CHOP, phase="a")
        self.assertIn("XSWI1N NA CHA NGA1 VSS sky130_fd_pr__nfet_g5v0d10v5", deck)
        self.assertNotIn("XSW mmoff", deck)

    def test_phase_validation(self):
        with self.assertRaises(SystemExit):
            m.build_netlist("amp", CHOP)  # no phase
        with self.assertRaises(SystemExit):
            m.build_netlist("amp", "baseline", phase="a")
        with self.assertRaises(SystemExit):
            m.build_netlist("amp", "mirror-degen", phase="a")
        with self.assertRaises(SystemExit):
            m.build_netlist("amp", CHOP, phase="a", tran=m.CHOP_TRAN_DEFAULT)

    def test_tran_deck_has_pulse_controls_and_gear(self):
        deck = m.build_netlist("amp", CHOP, tran=m.CHOP_TRAN_DEFAULT)
        self.assertIn("PULSE(0 2.5 0 ", deck)
        self.assertIn("method=gear", deck)
        self.assertIn("VCKB CHB 0 PULSE(0 2.5 5e-05", deck)  # CHB delayed half a period
        # make-before-break: both phases on for more than half the period
        pw = 0.55 * m.CHOP_TRAN_DEFAULT["period_s"]
        self.assertIn(f"{pw:.6g}", deck)

    def test_tran_measurements_window_is_integer_cycles(self):
        ms = m.tran_measurements(m.CHOP_TRAN_DEFAULT)
        names = {m_["name"] for m_ in ms}
        self.assertEqual(names, {"ptat_pp", "ptat_avg", "ctat_pp", "ctat_avg", "isup_avg"})
        tr = m.CHOP_TRAN_DEFAULT
        t1 = tr["settle_s"] + tr["ncycles_avg"] * tr["period_s"]
        self.assertLessEqual(t1, tr["tstop_s"])
        self.assertIn(f"TO={t1:.6g}", ms[0]["spice"])


# -------------------------------------------------------------------------------------------
# phase pairing (run_chop_offset), on synthetic value dicts in the real guard format
# -------------------------------------------------------------------------------------------

def curve(dptat=0.0):
    """One guard-passing sample (the committed tt/3.30 V nominal shape), PTAT offset by dptat V."""
    pts = ((-40, 1.09942, 0.782469), (27, 1.41410, 0.658261), (125, 1.87658, 0.466130))
    v = {}
    for t, ptat, ctat in pts:
        g = m.tagT(t)
        v.update({f"ptat_{g}": ptat + dptat, f"ctat_{g}": ctat, f"na_{g}": 0.7, f"nb_{g}": 0.7, f"isup_{g}": -1e-6})
    return v


def ent(corners):
    """A minimal load_term-shaped entity: corners only (pairing touches nothing else)."""
    return {"corners": corners, "report": {"corners": [1]}, "refusal": None, "missing_procs": [], "jobs": {}, "engines": {}}


class TestPhasePairing(unittest.TestCase):
    KEY = ("tt", 3.30)

    def pair(self, sa, sb, noma=None, nomb=None):
        noma = curve() if noma is None else noma
        nomb = curve() if nomb is None else nomb
        ents_amp = {"a": ent({self.KEY: {**sa, None: curve()}}), "b": ent({self.KEY: {**sb, None: curve()}})}
        ents_nom = {"a": ent({self.KEY: {None: noma}}), "b": ent({self.KEY: {None: nomb}})}
        return x.pair_phases(ents_amp, ents_nom)[self.KEY], x.residual_mV(
            {self.KEY: x.pair_phases(ents_amp, ents_nom)[self.KEY]})[self.KEY]

    def test_complete_pair_averages_and_cancels_first_order(self):
        # phase A carries +1 mV*G of output offset, phase B -1 mV*G: the average must cancel it
        cs, resid = self.pair({1: curve(+26e-3)}, {1: curve(-26e-3)})
        self.assertEqual(cs["n_pairs"], 1)
        self.assertEqual(cs["incomplete"], [])
        self.assertEqual(cs["invalid"], [])
        r27 = resid[27][1]
        self.assertLess(abs(r27), 1e-9, "first-order offset must cancel in the pair average")

    def test_residual_referred_through_G_in_mV(self):
        # an AVERAGE pair offset of +26 mV output = 1.0 mV input-referred at G = 26 V/V
        cs, resid = self.pair({1: curve(+52e-3)}, {1: curve(0.0)})
        self.assertAlmostEqual(resid[27][1], 1.0, places=9)

    def test_missing_phase_counts_incomplete_not_averaged(self):
        cs, resid = self.pair({1: curve(), 2: curve()}, {1: curve()})
        self.assertEqual(cs["n_pairs"], 1)
        self.assertEqual(cs["incomplete"], [2])
        self.assertNotIn(2, resid[27])

    def test_guard_failure_in_one_phase_invalidates_the_pair(self):
        bad = curve()
        bad["ptat_p125"] = 3.0  # outside the ptat_V guard window
        cs, resid = self.pair({1: bad}, {1: curve()})
        self.assertEqual(cs["n_pairs"], 0)
        self.assertEqual(len(cs["invalid"]), 1)
        self.assertIn("a", cs["invalid"][0]["reasons"], "the failing phase is named")
        self.assertEqual(resid, None)  # type: ignore[comparison-overlap]

    def test_failed_nominal_reference_excludes_the_corner(self):
        badnom = curve()
        badnom["isup_p27"] = -1.0  # outside the isup guard window
        cs, resid = self.pair({1: curve()}, {1: curve()}, noma=badnom)
        self.assertIsNone(cs["nom_avg"])
        self.assertEqual(cs["n_pairs"], 1)  # pairs still formed; the corner reports no residual
        self.assertIsNone(resid)
        self.assertTrue(cs["nominal_invalid"]["a"])

    def test_stats_shape(self):
        vals = {i: 0.001 * i for i in range(1, 11)}
        s = x.stat_mV(list(vals.values()))
        self.assertEqual(s["n"], 10)
        self.assertAlmostEqual(s["mean"], 0.0055, places=12)
        self.assertAlmostEqual(s["sd"], statistics_stdev(list(vals.values())), places=12)
        self.assertAlmostEqual(s["max_abs"], 0.01, places=12)

    def test_cancellation_ratio_discriminates_pairing(self):
        # paired spread far below single-phase spread -> ratio below the independent-draw limit
        single = [1.0, 1.2, 0.8]
        paired = [0.01, 0.02, 0.0]
        ratio = x.stat_mV(paired)["sd"] / x.stat_mV(single)["sd"]
        self.assertLess(ratio, x.PAIRING_FACTOR_LIMIT)
        # independent draws would give ~1/sqrt(2)
        indep = [0.7 * v for v in single]
        self.assertGreater(x.stat_mV(indep)["sd"] / x.stat_mV(single)["sd"] * 1.01, x.PAIRING_FACTOR_LIMIT)


def statistics_stdev(xs):
    import statistics as st
    return st.stdev(xs)


class TestTranResidual(unittest.TestCase):
    def test_residual_vs_nominal_transient(self):
        tran = {("tt", 3.30, 27): {
            "nominal": {"vals": {"ptat_avg": 1.4141, "ptat_pp": 0.002, "ctat_avg": 0.6582, "ctat_pp": 0.001}, "error": None},
            "amp": {"samples": {1: {"ptat_avg": 1.4141 + 26e-3, "ptat_pp": 0.003, "ctat_avg": 0.6583, "ctat_pp": 0.0015},
                                2: {"ptat_avg": None, "ptat_pp": None, "ctat_avg": None, "ctat_pp": None, "_error": "x"}},
                    "error": None}}}
        r = x.tran_residual_mV(tran)[("tt", 3.30, 27)]
        self.assertEqual(r["resid_stats"]["n"], 1)  # sample 2 is unextractable, excluded
        self.assertAlmostEqual(r["rows"][0]["resid_in_mV"], 1.0, places=9)  # 26 mV out / G
        self.assertAlmostEqual(r["ptat_pp_stats"]["max_abs"], 3.0, places=9)
        self.assertAlmostEqual(r["nom_ptat_pp_mV"], 2.0, places=9)

    def test_missing_nominal_marks_rows_invalid(self):
        tran = {("tt", 3.30, 27): {"nominal": {"vals": None, "error": "no usable corner in report"},
                                   "amp": {"samples": {1: {"ptat_avg": 1.0, "ptat_pp": 0.1, "ctat_avg": 0.6, "ctat_pp": 0.1}}, "error": None}}}
        r = x.tran_residual_mV(tran)[("tt", 3.30, 27)]
        self.assertFalse(r["rows"][0]["valid"])
        self.assertTrue(math.isnan(r["resid_stats"]["mean"]))


if __name__ == "__main__":
    unittest.main()
