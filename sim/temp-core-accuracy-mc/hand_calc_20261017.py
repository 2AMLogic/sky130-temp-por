#!/usr/bin/env python3
"""Hand (Pelgrom) estimate of the temp_core mismatch terms vs the #105 Monte Carlo (issue #187).

Evidence only; nothing under spec/ changes. Standard library only (run with ``python3 -I``).

For each (process, supply, T) point below it runs ONE local single-corner ngspice .op on the
committed snapshot netlist of record 20261011-165907-69d13ac (a debug-scale probe, not a grid;
the Monte Carlo itself is not re-run), reads gm/Id of the mirror/amplifier devices and the PTAT
loop voltages, evaluates the closed-form per-term sigma, and prints it next to the sigma of the
same quantity over the record's per-sample CSV.

Mismatch constants are the PDK's own (libs.tech/combined/continuous/models_global.spice, the
``_mm`` sections the campaign used): per-device sigma(delvto) = A_VT / sqrt(L*W*mult) with
A_VT = 12 mV.um (5 V pfet) and 8.2 mV.um (5 V nfet); resistor sigma(dR/R) = 4.64e-2/sqrt(W*L);
PNP sigma(dIS/IS) = 0.13*1.662e-2 for the W3p40L3p40 device (unit device, /sqrt(mult)).
"""
import csv
import math
import os
import re
import statistics as st
import subprocess
import sys
import tempfile

REC = "20261011-165907-69d13ac"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAP = os.path.join(HERE, "netlist-snapshots", REC, "nominal.spice")
CORN = os.path.join(HERE, "corners", REC)
PDK = os.environ.get("PDK_ROOT_SKY130A", os.path.expanduser("~/.volare/sky130A"))
LIB = os.path.join(PDK, "libs.tech/combined/sky130.lib.spice")

A_VT_P, A_VT_N = 12e-3, 8.2e-3  # V.um
SIG_IS_Q = 0.13 * 1.662e-2  # relative, unit W3p40L3p40 PNP
SIG_RES = 4.64e-2  # relative.sqrt(um^2)
K_Q = 8.617333e-5  # V/K
P, N = "msky130_fd_pr__pfet_g5v0d10v5", "msky130_fd_pr__nfet_g5v0d10v5"
POINTS = [("tt", "3.30", 27), ("tt", "3.30", 125), ("sf", "2.97", 125)]


def op(proc, vdd, temp):
    """One single-corner local .op; returns the numbers the hand calculation needs."""
    body = "\n".join(open(SNAP).read().splitlines()[7:-1])  # drop header/.control and trailing .end
    body = re.sub(r"^VSUP VDD 0 .*$", f"VSUP VDD 0 {vdd}", body, flags=re.M)
    pr = []
    for dev, mod in (("xmi1", P), ("xmp1", P), ("xmp2", P), ("xmp3", P), ("xml1", N)):
        for q in ("gm", "id"):
            pr.append(f"print @m.xdut.{dev}.{mod}[{q}]")
    deck = (f"* hand-calc probe {proc} {vdd} V {temp} C\n.lib {LIB} {proc}\n.temp {temp}\n{body}\n"
            ".control\nset ng_nomodcheck\nop\n" + "\n".join(pr) +
            "\nprint v(ptat) v(xdut.nb) v(xdut.nc) v(xdut.na)\n.endc\n.end\n")
    with tempfile.TemporaryDirectory() as d:
        f = os.path.join(d, "probe.sp")
        open(f, "w").write(deck)
        out = subprocess.run(["ngspice", "-b", f], capture_output=True, text=True, timeout=300).stdout
    v = {k: float(x) for k, x in re.findall(r"^(\S+) = (\S+)$", out, flags=re.M)}
    g = lambda dev, mod, q: v[f"@m.xdut.{dev}.{mod}[{q}]"]
    return {
        "gmid_mp": [g(d, P, "gm") / g(d, P, "id") for d in ("xmp1", "xmp2", "xmp3")],
        "i_mp": g("xmp2", P, "id"),
        "gm_i": g("xmi1", P, "gm"), "gm_l": g("xml1", N, "gm"),
        "ptat": v["v(ptat)"], "x": v["v(xdut.nb)"] - v["v(xdut.nc)"],
    }


def nominal(proc, vdd):
    t = open(os.path.join(CORN, f"nominal_{proc}_{vdd}v.log")).read()
    return {k: float(x) for k, x in re.findall(r"(\w+) = (\S+)", t)}


def mc_sigma(term, proc, vdd, temp):
    n = nominal(proc, vdd)
    s = (n["ptat_p125"] - n["ptat_m40"]) / 165.0
    col = {27: "ptat_p27", 125: "ptat_p125"}[temp]
    rows = [r for r in csv.DictReader(open(os.path.join(CORN, f"samples-{term}.csv")))
            if r["valid"] == "1" and r["process"] == proc and abs(float(r["supply_V"]) - float(vdd)) < 1e-6]
    return st.stdev([(float(r[col]) - n[col]) / s for r in rows]), len(rows), s


def main():
    print("| corner | T (C) | term | hand 1-sigma (degC) | MC 1-sigma (degC, n) | hand/MC |")
    print("|---|---|---|---|---|---|")
    detail = []
    for proc, vdd, temp in POINTS:
        o = op(proc, vdd, temp)
        _, _, s = mc_sigma("pnp", proc, vdd, temp)
        vt = K_Q * (temp + 273.15)
        gain = o["ptat"] / o["x"]  # PTAT = I2*(R2+R2TRIM), x = I2*R1  ->  (R2+R2TRIM)/R1
        c = vt / o["x"]  # d(I2R1)/d(ln I1/I2) = Vt, relative to x
        # amplifier: MI1/MI2 (pfet L4 W32) and ML1/ML2 (nfet L8 W8), temp_core sizes
        s_mi = A_VT_P / math.sqrt(4 * 32)
        s_ml = A_VT_N / math.sqrt(8 * 8)
        vos = math.sqrt(2 * s_mi ** 2 + 2 * (o["gm_l"] / o["gm_i"] * s_ml) ** 2)
        amp = gain * vos / s
        # mirror: MP1..3 (pfet L4 W8), dI3/I3 = d3 - d2 + c*(d1 - d2)
        s_d = [g * A_VT_P / math.sqrt(4 * 8) for g in o["gmid_mp"]]
        mir = o["ptat"] * math.sqrt(s_d[2] ** 2 + (1 + c) ** 2 * s_d[1] ** 2 + c ** 2 * s_d[0] ** 2) / s
        pnp = gain * vt * math.sqrt(1 + 1 / 8) * SIG_IS_Q / s
        r1, r2, r2t = (SIG_RES / math.sqrt(2 * l) for l in (119.47, 2652.6, 450.88))
        w2, w2t = 2652.6 / (2652.6 + 450.88), 450.88 / (2652.6 + 450.88)
        res = o["ptat"] * math.sqrt(r1 ** 2 + (w2 * r2) ** 2 + (w2t * r2t) ** 2) / s
        hand = {"amp": amp, "mirror": mir, "pnp": pnp, "res": res}
        hand["all"] = math.sqrt(sum(v * v for v in hand.values()))
        for term in ("amp", "mirror", "pnp", "res", "all"):
            m, n, _ = mc_sigma(term, proc, vdd, temp)
            print(f"| {proc}_{vdd}V | {temp} | {term} | {hand[term]:.2f} | {m:.2f} ({n}) | {hand[term] / m:.2f} |")
        detail.append(f"{proc}_{vdd}V {temp}C: S={s * 1e3:.3f} mV/C gain={gain:.2f} x=I2R1={o['x'] * 1e3:.1f} mV "
                      f"Vt={vt * 1e3:.2f} mV I(MP2)={o['i_mp'] * 1e6:.3f} uA "
                      f"gm/Id(MP1..3)={[round(g, 2) for g in o['gmid_mp']]}/V gmL/gmI={o['gm_l'] / o['gm_i']:.3f} "
                      f"sigma_Vos={vos * 1e3:.2f} mV sigma_dI/I(MP)={[round(100 * d, 2) for d in s_d]} % "
                      f"c=Vt/x={c:.3f}")
    print()
    print("\n".join(detail))


if __name__ == "__main__":
    sys.exit(main())
