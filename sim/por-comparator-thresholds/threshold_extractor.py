#!/usr/bin/env python3
"""VPOR-up / VPOR-down extractor for the por_comparator threshold campaign (issue #102).

Stdlib only.  Input is a klt waveform (``time``, ``v(vdd)``, ``v(por_raw)``)
of one quasi-static VDD sweep: VDD rises at a constant dVDD/dt to a peak and then
falls at the same |dVDD/dt|.  Definitions (all measurement definitions of THIS
campaign; none is a ratified bound):

* The sweep is split at the sample of maximum VDD into an UP segment and a DOWN
  segment.
* POR_RAW is "high" when ``v(por_raw) > 0.5 * v(vdd)`` (a supply-tracking
  mid-level, so the criterion is meaningful at every VDD) and the state is only
  defined where ``v(vdd) >= V_VALID``; below that the comparator has no
  meaningful rail and samples are ignored (stated, not hidden).
* VPOR-up   = interpolated VDD at which POR_RAW changes state during the UP
  segment; VPOR-down = the same during the DOWN segment.  The direction of each
  edge is checked against the expected polarity; a wrong-direction or repeated
  crossing is reported, never silently picked.
* hysteresis = VPOR-up - VPOR-down.
* Edge resolution: the VDD distance between the two samples that bracket the
  crossing.  An edge bracketed by more than ``MAX_BRACKET_V`` is UNRESOLVED.
* A segment in which POR_RAW does not change state is reported as
  ``no_transition`` (with the state it stayed in), never omitted.
"""

from __future__ import annotations

import json
import sys

V_VALID = 1.0  # V: below this supply the POR_RAW state is not evaluated
MAX_BRACKET_V = 0.010  # V: widest sample step (in VDD) allowed around an edge
LEVEL_FRAC = 0.5  # POR_RAW state threshold as a fraction of the instantaneous VDD


def _segment_edges(t, vdd, raw, lo, hi):
    """State changes of POR_RAW in samples lo..hi (inclusive) where vdd >= V_VALID."""
    edges = []
    prev = None  # (index, state)
    state_first = state_last = None
    for i in range(lo, hi + 1):
        if vdd[i] < V_VALID:
            continue
        s = raw[i] > LEVEL_FRAC * vdd[i]
        if state_first is None:
            state_first = s
        state_last = s
        if prev is not None and s != prev[1]:
            j = prev[0]
            d0 = raw[j] - LEVEL_FRAC * vdd[j]
            d1 = raw[i] - LEVEL_FRAC * vdd[i]
            f = d0 / (d0 - d1) if d0 != d1 else 1.0
            edges.append(
                {
                    "vdd_v": vdd[j] + f * (vdd[i] - vdd[j]),
                    "t_s": t[j] + f * (t[i] - t[j]),
                    "direction": "rise" if s else "fall",
                    "bracket_v": abs(vdd[i] - vdd[j]),
                }
            )
        prev = (i, s)
    return edges, state_first, state_last


def analyze(wave: dict, expect_up: str = "rise", expect_down: str = "fall") -> dict:
    """Extract both edges from one sweep waveform. ``expect_*`` = POR_RAW direction."""
    t, vdd, raw = wave["time"], wave["v(vdd)"], wave["v(por_raw)"]
    n = len(t)
    if n < 10 or any(t[k + 1] <= t[k] for k in range(n - 1)):
        return {"verdict": "ERROR", "detail": "waveform too short or time axis not strictly increasing"}
    ipk = max(range(n), key=lambda k: vdd[k])
    out = {"n_samples": n, "vdd_peak_v": vdd[ipk], "t_peak_s": t[ipk], "vdd_end_v": vdd[-1]}
    for name, lo, hi, want in (("up", 0, ipk, expect_up), ("down", ipk, n - 1, expect_down)):
        edges, s0, s1 = _segment_edges(t, vdd, raw, lo, hi)
        seg = {"expected_direction": want, "n_edges": len(edges), "edges": edges}
        if not edges:
            seg["result"] = "no_transition"
            seg["state_throughout"] = None if s0 is None else ("high" if s0 else "low")
            seg["vdd_v"] = None
        elif len(edges) > 1:
            seg["result"] = "multiple_transitions"
            seg["vdd_v"] = None
        elif edges[0]["direction"] != want:
            seg["result"] = "wrong_direction"
            seg["vdd_v"] = None
        elif edges[0]["bracket_v"] > MAX_BRACKET_V:
            seg["result"] = "unresolved"
            seg["vdd_v"] = edges[0]["vdd_v"]
        else:
            seg["result"] = "edge"
            seg["vdd_v"] = edges[0]["vdd_v"]
            seg["bracket_v"] = edges[0]["bracket_v"]
        out[name] = seg
    up, dn = out["up"], out["down"]
    if up["result"] == "edge" and dn["result"] == "edge":
        out["hysteresis_v"] = up["vdd_v"] - dn["vdd_v"]
        out["verdict"] = "OK"
    else:
        out["hysteresis_v"] = None
        bad = [f"{k}:{out[k]['result']}" for k in ("up", "down") if out[k]["result"] != "edge"]
        out["verdict"] = "NO_RESULT (" + ", ".join(bad) + ")"
    max_step = max((vdd[k + 1] - vdd[k]) if k < ipk else (vdd[k] - vdd[k + 1]) for k in range(n - 1) if k != ipk)
    out["max_vdd_step_v"] = max_step
    return out


def compare_rates(full: dict, half: dict, tol_v: float) -> dict:
    """Quasi-static guard: edge agreement between the full-rate and half-rate sweeps."""
    rec = {"tolerance_v": tol_v}
    grades = []
    for k in ("up", "down"):
        a, b = full.get(k, {}).get("vdd_v"), half.get(k, {}).get("vdd_v")
        if full.get(k, {}).get("result") != "edge" or half.get(k, {}).get("result") != "edge":
            rec[k] = "n/a (an edge is missing in a segment)"
            grades.append("n/a")
            continue
        rec[f"{k}_delta_v"] = a - b
        g = "consistent" if abs(a - b) <= tol_v else "rate-dependent"
        rec[k] = g
        grades.append(g)
    rec["grade"] = "rate-dependent" if "rate-dependent" in grades else ("n/a" if "n/a" in grades else "consistent")
    return rec


# --------------------------------------------------------------------------
# selftest (synthetic sweeps with known answers; no simulation)
# --------------------------------------------------------------------------


def synth(vup: float, vdn: float, peak: float = 3.63, dv: float = 0.005, glitch: bool = False, flat: bool = False):
    """Synthetic sweep: POR_RAW = VDD above the high state, 0 below, with hysteresis."""
    up = [k * dv for k in range(int(peak / dv) + 1)]
    down = list(reversed(up))[1:]
    vdd = up + down
    ipk = len(up) - 1
    raw = []
    state = False
    for k, v in enumerate(vdd):
        if not flat:
            if k <= ipk and v >= vup:
                state = True
            if k > ipk and v < vdn:
                state = False
            if glitch and k <= ipk and abs(v - (vup + 0.05)) < dv / 2:
                state = False  # chatter after the first rise -> multiple transitions
        raw.append(v if state else 0.0)
    t = [k * dv / 1000.0 for k in range(len(vdd))]
    return {"time": t, "v(vdd)": vdd, "v(por_raw)": raw}


def selftest() -> list[dict]:
    cases = []

    def check(name, got, want):
        cases.append({"case": name, "want": want, "got": got, "ok": got == want})

    r = analyze(synth(2.60, 2.45))
    check("clean_edges_verdict", r["verdict"], "OK")
    check("clean_up_within_dv", abs(r["up"]["vdd_v"] - 2.60) <= 0.005, True)
    check("clean_down_within_dv", abs(r["down"]["vdd_v"] - 2.45) <= 0.005, True)
    check("clean_hysteresis_within_2dv", abs(r["hysteresis_v"] - 0.15) <= 0.010, True)
    r = analyze(synth(2.60, 2.45, flat=True))
    check("never_toggles_up", r["up"]["result"], "no_transition")
    check("never_toggles_down", r["down"]["result"], "no_transition")
    check("never_toggles_verdict_not_ok", r["verdict"].startswith("NO_RESULT"), True)
    r = analyze(synth(2.60, 2.45, glitch=True))
    check("chatter_reported", r["up"]["result"], "multiple_transitions")
    r = analyze(synth(2.60, 2.45, dv=0.05))
    check("coarse_step_unresolved", r["up"]["result"], "unresolved")
    a = analyze(synth(2.60, 2.45))
    b = analyze(synth(2.62, 2.45))
    check("rate_guard_consistent", compare_rates(a, a, 0.01)["grade"], "consistent")
    check("rate_guard_flags_shift", compare_rates(a, b, 0.01)["grade"], "rate-dependent")
    return cases


if __name__ == "__main__":
    res = selftest()
    for c in res:
        print(("ok   " if c["ok"] else "FAIL ") + c["case"], "" if c["ok"] else f"(got {c['got']!r}, want {c['want']!r})")
    ok = all(c["ok"] for c in res)
    print(json.dumps({"overall_pass": ok, "n_cases": len(res)}))
    sys.exit(0 if ok else 1)
