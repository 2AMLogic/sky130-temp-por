#!/usr/bin/env python3
"""Early-BIAS_OK / POR_RAW-pulse extractor for the forced-offset experiment (issue #495).

Stdlib only.  Input: columns ``time vdd por_raw bias_ok resetn na`` of one quasi-static
VDD sweep (UP at +rate V/s from 0 V to the peak, DOWN at -rate V/s).  Only the UP
segment is graded -- the pulse in question is a release-then-reassert during ramp-up.

Definitions (this experiment's own; none is a ratified bound):

* A signal is "high" when it exceeds ``0.5 * v(vdd)`` (supply-tracking mid-level); state
  is only defined where ``v(vdd) >= V_VALID`` (1.0 V), as in the #102 extractor.
* ``bias_ok_up_v``  = interpolated VDD of BIAS_OK's FIRST rising crossing on the UP segment.
* POR_RAW intervals = maximal runs where POR_RAW is high on the UP segment.  The LAST run
  that is still high at the UP peak is the genuine VPOR-up release; every other run is a
  PULSE (a release followed by a re-assert).  Each pulse records start/end VDD and its
  width in volts and seconds (``t`` is the real time axis, so the seconds are measured,
  not derived from the rate).
* ``por_up_v`` = VDD at which the genuine release begins (None if POR_RAW never stays high).
* RESETn is "released" when it exceeds ``0.5 * v(vdd)`` while VDD >= V_VALID.  A PULSE
  *propagates* iff RESETn is released at any sample inside the pulse's window extended by
  ``settle_s`` (so a delayed deglitch output is still attributed); ``resetn_early_v`` is
  the VDD of the first release when it lands BEFORE the genuine POR_RAW release, else None.
"""
from __future__ import annotations

V_VALID = 1.0


def load_wrdata(text: str) -> dict[str, list[float]]:
    cols = ("t", "vdd", "por_raw", "bias_ok", "resetn", "na")
    out: dict[str, list[float]] = {c: [] for c in cols}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < len(cols):
            continue
        try:
            vals = [float(p) for p in parts[: len(cols)]]
        except ValueError:
            continue
        for c, v in zip(cols, vals):
            out[c].append(v)
    return out


def _lerp(x0, y0, x1, y1, y):
    return x0 if y1 == y0 else x0 + (x1 - x0) * (y - y0) / (y1 - y0)


def _runs(t, vdd, sig, hi_idx):
    """Maximal high runs of sig>0.5*vdd over samples [0, hi_idx]; returns list of dicts."""
    runs, cur = [], None
    for i in range(hi_idx + 1):
        if vdd[i] < V_VALID:
            continue
        high = sig[i] > 0.5 * vdd[i]
        if high and cur is None:
            if i > 0 and vdd[i - 1] >= V_VALID:
                a, b = sig[i - 1] - 0.5 * vdd[i - 1], sig[i] - 0.5 * vdd[i]
                f = (0 - a) / (b - a) if b != a else 1.0
                v0, t0 = vdd[i - 1] + f * (vdd[i] - vdd[i - 1]), t[i - 1] + f * (t[i] - t[i - 1])
            else:
                v0, t0 = vdd[i], t[i]
            cur = {"v0": v0, "t0": t0, "i0": i}
        elif not high and cur is not None:
            a, b = sig[i - 1] - 0.5 * vdd[i - 1], sig[i] - 0.5 * vdd[i]
            f = (0 - a) / (b - a) if b != a else 0.0
            cur.update(v1=vdd[i - 1] + f * (vdd[i] - vdd[i - 1]), t1=t[i - 1] + f * (t[i] - t[i - 1]), i1=i, open=False)
            runs.append(cur)
            cur = None
    if cur is not None:
        cur.update(v1=vdd[hi_idx], t1=t[hi_idx], i1=hi_idx, open=True)
        runs.append(cur)
    return runs


def extract(w: dict[str, list[float]], settle_s: float = 2e-3) -> dict:
    t, vdd = w["t"], w["vdd"]
    if len(t) < 10:
        return {"status": "no_data", "n_samples": len(t)}
    hi = max(range(len(vdd)), key=lambda i: vdd[i])
    res: dict = {"status": "ok", "n_samples": len(t), "vdd_peak_v": vdd[hi]}
    bok = _runs(t, vdd, w["bias_ok"], hi)
    res["bias_ok_up_v"] = bok[0]["v0"] if bok else None
    res["bias_ok_runs_up"] = len(bok)
    por = _runs(t, vdd, w["por_raw"], hi)
    genuine = por[-1] if por and por[-1]["open"] else None
    pulses = por[:-1] if genuine else por
    res["por_up_v"] = genuine["v0"] if genuine else None
    res["pulse_count"] = len(pulses)
    rst = _runs(t, vdd, w["resetn"], hi)
    res["resetn_up_v"] = rst[-1]["v0"] if rst and rst[-1]["open"] else None
    out = []
    for p in pulses:
        win = (p["t0"], p["t1"] + settle_s)
        prop = any(r["t0"] <= win[1] and r["t1"] >= win[0] for r in rst if not (genuine and r["t0"] >= genuine["t0"]))
        out.append({
            "v_start": p["v0"], "v_end": p["v1"], "width_v": p["v1"] - p["v0"],
            "t_start_s": p["t0"], "width_s": p["t1"] - p["t0"],
            "bias_ok_asserted": any(r["v0"] <= p["v0"] + 1e-3 for r in bok),
            "propagates_to_resetn": prop,
        })
    res["pulses"] = out
    first_rst = rst[0] if rst else None
    res["resetn_early_v"] = (first_rst["v0"] if first_rst and genuine and first_rst["t0"] < genuine["t0"] else None)
    na = w["na"]
    i_ok = next((i for i in range(hi + 1) if vdd[i] >= (res["bias_ok_up_v"] or 1e9)), None)
    res["na_at_bias_ok_v"] = na[i_ok] if i_ok is not None else None
    res["por_raw_up_peak_ok"] = genuine is not None
    return res


def verdict_class(r: dict) -> str:
    """clean | pulse_absorbed | pulse_propagates | no_release | no_data"""
    if r.get("status") != "ok":
        return "no_data"
    if r["por_up_v"] is None:
        return "no_release"
    if r["pulse_count"] == 0:
        return "clean"
    return "pulse_propagates" if any(p["propagates_to_resetn"] for p in r["pulses"]) else "pulse_absorbed"
