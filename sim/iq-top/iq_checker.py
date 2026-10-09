#!/usr/bin/env python3
"""Settling / physicality grading of one assembled-Iq transient (issue #107).

Pure functions over a ``{name: samples}`` waveform dict (the shape
``load_wave`` returns for a klt waveform JSON).  Used by run_iq_campaign.py for
every grid point and by its ``selftest`` on synthetic constant / drifting
currents.  Nothing here is a spec limit: every threshold comes from
experiment.json ``measurement`` and is an exploratory measurement definition.

Statuses: ok | non-physical-branch | unsettled | nonconverged.  Structurally or
numerically invalid input (NaN/inf, unequal columns, non-increasing time) is
reported as ``nonconverged`` with ``invalid_input: True`` and a ``reason``; it
can never be graded ``ok``.
"""

from __future__ import annotations

import gzip
import json
import math
import sys
from pathlib import Path

SUBCELLS = {
    "bias_core": "i(v.xdut.vsbias)",
    "por_comparator": "i(v.xdut.vscmp)",
    "por_output_chain": "i(v.xdut.vspor)",
    "temp_core": "i(v.xdut.vstemp)",
}
TOTAL_VEC = "i(bvdd)"  # supply current = -i(BVDD)
FORCE_VEC = "i(vrst)"  # por-iq only: current into the RESETn forcing source


def load_wave(path: Path) -> dict[str, list[float]]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt") as fh:
        doc = json.load(fh)
    try:
        names = [v["name"].lower() for v in doc["variables"]]
        rows = doc["points"]
    except (KeyError, TypeError, AttributeError) as e:
        raise ValueError(f"malformed waveform document: {e!r}") from e
    if not names or not isinstance(rows, list):
        raise ValueError("malformed waveform document: no variables or points not a list")
    cols: dict[str, list[float]] = {n: [] for n in names}
    for i, row in enumerate(rows):
        if not isinstance(row, (list, tuple)) or len(row) != len(names):
            raise ValueError(f"malformed waveform row {i}: expected {len(names)} values, got {len(row) if isinstance(row, (list, tuple)) else type(row).__name__}")
        for n, x in zip(names, row):
            try:
                cols[n].append(float(x))
            except (TypeError, ValueError) as e:
                raise ValueError(f"malformed waveform row {i}: non-numeric value {x!r} for {n}") from e
    return cols


def validate_wave(wave: dict) -> str | None:
    """Return a reason string if the waveform is structurally/numerically invalid, else None."""
    t = wave.get("time")
    if not isinstance(t, (list, tuple)):
        return "invalid input: no time vector"
    for name, y in wave.items():
        if not isinstance(y, (list, tuple)) or len(y) != len(t):
            return f"invalid input: column {name} has {len(y) if isinstance(y, (list, tuple)) else 'non-list'} samples, time has {len(t)}"
        for k, x in enumerate(y):
            if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
                return f"invalid input: non-finite or non-numeric sample {x!r} in {name} at index {k}"
    for k in range(len(t) - 1):
        if not t[k + 1] > t[k]:
            return f"invalid input: time not strictly increasing at index {k + 1} ({t[k]!r} -> {t[k + 1]!r})"
    return None


def window(t, y, lo, hi):
    """Samples with lo <= t <= hi (inclusive)."""
    pairs = [(a, b) for a, b in zip(t, y) if lo <= a <= hi]
    return [p[0] for p in pairs], [p[1] for p in pairs]


def tmean(t, y):
    """Time-weighted (trapezoid) mean; the sample grid is non-uniform."""
    if len(t) < 2:
        return y[0] if y else float("nan")
    area = sum((t[i + 1] - t[i]) * (y[i + 1] + y[i]) / 2 for i in range(len(t) - 1))
    return area / (t[-1] - t[0])


def wstats(t, y, w):
    tt, yy = window(t, y, w[0], w[1])
    if len(tt) < 3:
        return None
    return {"mean": tmean(tt, yy), "min": min(yy), "max": max(yy), "n": len(tt), "max_gap_s": max(tt[i + 1] - tt[i] for i in range(len(tt) - 1))}


def grade(wave: dict[str, list[float]], state: str, vf: float, cfg: dict) -> dict:
    """Grade one point's waveform.  Returns a dict with ``status`` and the evidence."""
    m = cfg["measurement"]
    bad_input = validate_wave(wave)
    if bad_input:
        return {"status": "nonconverged", "invalid_input": True, "reason": bad_input}
    t = wave.get("time", [])
    need = [TOTAL_VEC, "v(vdd)", "v(resetn)", *SUBCELLS.values()] + ([FORCE_VEC] if state == "por-iq" else [])
    missing = [n for n in need if n not in wave]
    if len(t) < 10 or missing:
        return {"status": "nonconverged", "reason": f"waveform missing/short (samples={len(t)}, missing vectors={missing})"}
    if t[-1] < m["trail_window_s"][1] * 0.999:
        return {"status": "nonconverged", "reason": f"simulation ended at {t[-1]:.6g} s, before the trailing window end {m['trail_window_s'][1]} s"}
    tw, pw = m["trail_window_s"], m["prev_window_s"]
    itot = [-x for x in wave[TOTAL_VEC]]
    sub = {k: wave[v] for k, v in SUBCELLS.items()}
    out: dict = {"status": None, "reasons": []}
    s_t, s_p = wstats(t, itot, tw), wstats(t, itot, pw)
    if s_t is None or s_p is None:
        return {"status": "nonconverged", "reason": "too few samples in the settling windows"}
    mean_t = s_t["mean"]
    out["i_total_a"] = mean_t
    out["prev_window_mean_a"] = s_p["mean"]
    out["drift_rel"] = abs(mean_t - s_p["mean"]) / abs(mean_t) if mean_t else float("inf")
    out["pk_pk_rel"] = (s_t["max"] - s_t["min"]) / abs(mean_t) if mean_t else float("inf")
    out["trail_samples"] = s_t["n"]
    out["trail_max_gap_s"] = s_t["max_gap_s"]
    attrib = {}
    for k, y in sub.items():
        st = wstats(t, y, tw)
        attrib[k] = st["mean"] if st else float("nan")
    out["subcell_a"] = attrib
    out["subcell_sum_a"] = sum(attrib.values())
    out["sum_minus_direct_rel"] = (out["subcell_sum_a"] - mean_t) / abs(mean_t) if mean_t else float("inf")
    vdd = wstats(t, wave["v(vdd)"], tw)
    rst = wstats(t, wave["v(resetn)"], tw)
    out["vdd_trail_v"] = vdd["mean"]
    out["resetn_trail_v"] = rst["mean"]
    out["resetn_trail_max_v"] = rst["max"]
    if state == "por-iq":
        f = wstats(t, wave[FORCE_VEC], tw)
        out["contention_a"] = f["mean"]  # current the DUT pushes into the forcing source
        out["i_total_less_contention_a"] = mean_t - f["mean"]
    # ---- physicality (non-physical-branch signature)
    lo, hi = m["non_physical_branch"]["range_v"][0], vf + m["non_physical_branch"]["range_v"][1]
    bad = []
    for name, y in wave.items():
        if name.startswith("v(") or name == "v(vdd)":
            st = wstats(t, y, tw)
            if st and (st["min"] < lo or st["max"] > hi):
                bad.append(f"{name} in [{st['min']:.4g}, {st['max']:.4g}] V outside [{lo:.2f}, {hi:.2f}]")
    if mean_t <= 0:
        bad.append(f"settled total supply current {mean_t:.4g} A <= 0")
    floor = m["non_physical_branch"]["min_subcell_current_a"]
    for k, v in attrib.items():
        if v < floor:
            bad.append(f"sub-cell {k} settled supply current {v:.4g} A < {floor:g}")
    out["nonphysical_reasons"] = bad
    # ---- settling / state checks
    s = m["settling"]
    un = []
    if out["drift_rel"] > s["max_window_to_window_drift"]:
        un.append(f"window-to-window drift {out['drift_rel']:.3%} > {s['max_window_to_window_drift']:.0%}")
    if out["pk_pk_rel"] > s["max_trailing_window_pk_pk"]:
        un.append(f"trailing pk-pk {out['pk_pk_rel']:.3%} > {s['max_trailing_window_pk_pk']:.0%}")
    if abs(out["vdd_trail_v"] - vf) > s["vdd_tolerance_v"]:
        un.append(f"VDD {out['vdd_trail_v']:.4f} V not within {s['vdd_tolerance_v']} V of {vf}")
    if state == "iq-total" and not out["resetn_trail_v"] > 0.8 * vf:
        un.append(f"RESETn not released (trailing mean {out['resetn_trail_v']:.3f} V <= 0.8*VDD)")
    if state == "por-iq" and out["resetn_trail_max_v"] > 0.05:
        un.append(f"RESETn not held low (max {out['resetn_trail_max_v']:.3f} V)")
    out["unsettled_reasons"] = un
    out["status"] = "non-physical-branch" if bad else ("unsettled" if un else "ok")
    return out


# --------------------------------------------------------------------------
# selftest: synthetic constant / drifting currents (no simulation involved)
# --------------------------------------------------------------------------


def synth(state: str, vf: float = 3.3, *, i0=20e-6, drift=0.0, ripple=0.0, released=True, neg=False, tstop=0.03, n=3001, ptat=1.4):
    t = [tstop * k / (n - 1) for k in range(n)]

    def cur(base):
        sgn = -1.0 if neg else 1.0
        return [sgn * base * (1 + drift * (x / tstop) + ripple * (1 if k % 2 else -1)) for k, x in enumerate(t)]

    fr = {"bias_core": 0.1, "por_comparator": 0.2, "por_output_chain": 0.3, "temp_core": 0.4 if state == "iq-total" else 0.0}
    tot = sum(fr.values())
    w = {"time": t, "v(vdd)": [vf] * n, "v(ptat)": [ptat] * n, "v(ctat)": [0.6] * n}
    w["v(resetn)"] = [(vf if (state == "iq-total" and released) else 0.0)] * n
    w["i(bvdd)"] = [-x for x in cur(i0)]
    for k, v in SUBCELLS.items():
        w[v] = cur(i0 * fr[k] / tot)
    if state == "por-iq":
        w["i(vrst)"] = [0.0] * n
    return w


def selftest_cases(cfg: dict):
    """(name, waveform, state, vf, expected_status)"""
    cases = [
        ("settled_constant_por", synth("por-iq"), "por-iq", 3.3, "ok"),
        ("settled_constant_total", synth("iq-total"), "iq-total", 3.3, "ok"),
        ("drifting_total", synth("iq-total", drift=0.5), "iq-total", 3.3, "unsettled"),
        ("drifting_por", synth("por-iq", drift=0.5), "por-iq", 3.3, "unsettled"),
        ("ripple_5pct_total", synth("iq-total", ripple=0.05), "iq-total", 3.3, "unsettled"),
        ("not_released_total", synth("iq-total", released=False), "iq-total", 3.3, "unsettled"),
        ("negative_supply_current", synth("iq-total", neg=True), "iq-total", 3.3, "non-physical-branch"),
        ("railed_ptat", synth("iq-total", ptat=5.0), "iq-total", 3.3, "non-physical-branch"),
    ]
    short = synth("iq-total")
    cut = {k: v[:1500] for k, v in short.items()}
    cases.append(("ended_before_trailing_window", cut, "iq-total", 3.3, "nonconverged"))
    return cases + invalid_cases()


def _with(w, key, idx, val):
    w = {k: list(v) for k, v in w.items()}
    w[key][idx] = val
    return w


def invalid_cases():
    """Malformed / non-finite waveforms: must never grade ``ok``."""
    nan, inf = float("nan"), float("inf")
    base = synth("iq-total")
    n = len(base["time"])
    c = []
    allnan = {k: list(v) for k, v in base.items()}
    allnan["i(bvdd)"] = [nan] * n
    c.append(("invalid_nan_all_current", allnan, "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_nan_one_current", _with(base, "i(bvdd)", n - 5, nan), "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_inf_current", _with(base, "i(bvdd)", n - 5, inf), "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_nan_voltage", _with(base, "v(vdd)", n - 5, nan), "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_inf_voltage", _with(base, "v(resetn)", n - 5, -inf), "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_nan_time", _with(base, "time", n // 2, nan), "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_inf_time", _with(base, "time", n - 1, inf), "iq-total", 3.3, "nonconverged"))
    short = {k: list(v) for k, v in base.items()}
    short["i(bvdd)"] = short["i(bvdd)"][:-1]
    c.append(("invalid_unequal_columns", short, "iq-total", 3.3, "nonconverged"))
    c.append(("invalid_duplicate_time", _with(base, "time", n // 2, base["time"][n // 2 - 1]), "iq-total", 3.3, "nonconverged"))
    rev = _with(base, "time", n // 2, base["time"][n // 2 - 1] - 1e-6)
    c.append(("invalid_reversed_time", rev, "iq-total", 3.3, "nonconverged"))
    return c


def irregular_wave(state="iq-total"):
    """Valid non-uniform grid (dense then sparse); constant current, so mean is exact."""
    w = synth(state, n=3001)
    keep = sorted(set(list(range(0, 3001, 7)) + list(range(2000, 3001, 1)) + [3000]))
    return {k: [v[i] for i in keep] for k, v in w.items()}


def weighted_wave(cfg: dict, state="iq-total", vf=3.3, i0=20e-6, a=0.012):
    """Non-constant current on a non-uniform grid with an exactly known time-weighted mean.

    Grid: 10 us spacing everywhere, plus 0.5 us spacing in [25.0, 27.5] ms (dense where the
    current ramps).  Current: I0 up to 25.0 ms, a linear ramp to I0*(1+a) at 27.5 ms, then
    constant to 30 ms.  Both breakpoints are grid points and the window edges are hit exactly,
    so the trapezoid integral over the trailing window [25, 30] ms is exact:
        mean = I0 * (1 + a * (0.5*0.5 + 0.5)) = I0 * (1 + 0.75*a).
    The dense ramp samples pull a plain arithmetic mean of the window samples well below that
    (~I0*(1 + 0.53*a)), so the fixture discriminates time weighting from sample averaging.
    Returns (wave, exact_trailing_mean_a, arithmetic_trailing_mean_a).
    """
    tw = cfg["measurement"]["trail_window_s"]
    # integer grid in units of 0.5 us; k / 2e6 is the correctly rounded value, so it equals the
    # float literals 0.025 / 0.0275 / 0.03 used for the window edges exactly
    k0, k1, kend = round(tw[0] * 2e6), round((tw[0] + tw[1]) / 2 * 2e6), round(tw[1] * 2e6)
    ks = sorted(set(range(0, kend + 1, 20)) | set(range(k0, k1 + 1)))
    t = [k / 2e6 for k in ks]
    assert t[0] == 0.0 and tw[0] in t and tw[1] == t[-1]

    def shape(k):
        return 1.0 if k <= k0 else (1.0 + a * (k - k0) / (k1 - k0) if k <= k1 else 1.0 + a)

    n = len(t)
    fr = {"bias_core": 0.1, "por_comparator": 0.2, "por_output_chain": 0.3, "temp_core": 0.4 if state == "iq-total" else 0.0}
    tot = sum(fr.values())
    w = {"time": t, "v(vdd)": [vf] * n, "v(ptat)": [1.4] * n, "v(ctat)": [0.6] * n,
         "v(resetn)": [(vf if state == "iq-total" else 0.0)] * n, "i(bvdd)": [-i0 * shape(k) for k in ks]}
    for name, vec in SUBCELLS.items():
        w[vec] = [i0 * fr[name] / tot * shape(k) for k in ks]
    if state == "por-iq":
        w["i(vrst)"] = [0.0] * n
    exact = i0 * (1 + 0.75 * a)
    _, yy = window(t, [-x for x in w["i(bvdd)"]], tw[0], tw[1])
    return w, exact, sum(yy) / len(yy)


def run_selftest(cfg: dict, fixture_dir: Path | None = None):
    rows = []
    for name, wave, state, vf, want in selftest_cases(cfg):
        g = grade(wave, state, vf, cfg)
        rows.append({"case": name, "state": state, "expected": want, "got": g["status"], "ok": g["status"] == want,
                     "drift_rel": g.get("drift_rel"), "pk_pk_rel": g.get("pk_pk_rel"), "i_total_a": g.get("i_total_a"),
                     "sum_minus_direct_rel": g.get("sum_minus_direct_rel"), "reasons": g.get("unsettled_reasons", []) + g.get("nonphysical_reasons", []) + ([g["reason"]] if "reason" in g else [])})
        if fixture_dir is not None and name in ("settled_constant_total", "drifting_total"):
            names = list(wave)
            doc = {"variables": [{"name": n} for n in names], "points": [[wave[n][i] for n in names] for i in range(0, len(wave["time"]), 10)]}
            (fixture_dir / f"{name}.wave.json").write_text(json.dumps(doc) + "\n")
    return rows


def selftest_load_wave_cases() -> list[tuple[str, bool]]:
    """load_wave must reject malformed documents (ValueError) and accept a valid one."""
    import tempfile

    docs = {
        "ragged_row_short": {"variables": [{"name": "time"}, {"name": "v(a)"}], "points": [[0, 1], [1]]},
        "ragged_row_long": {"variables": [{"name": "time"}, {"name": "v(a)"}], "points": [[0, 1], [1, 2, 3]]},
        "row_not_list": {"variables": [{"name": "time"}], "points": [5]},
        "non_numeric": {"variables": [{"name": "time"}], "points": [["abc"]]},
        "missing_points": {"variables": [{"name": "time"}]},
    }
    res = []
    with tempfile.TemporaryDirectory() as td:
        for name, doc in docs.items():
            p = Path(td) / f"{name}.json"
            p.write_text(json.dumps(doc))
            try:
                load_wave(p)
                res.append((f"load_wave_rejects_{name}", False))
            except ValueError:
                res.append((f"load_wave_rejects_{name}", True))
        good = Path(td) / "good.json"
        good.write_text(json.dumps({"variables": [{"name": "Time"}, {"name": "V(a)"}], "points": [[0, 1], [1, 2]]}))
        res.append(("load_wave_accepts_valid", load_wave(good) == {"time": [0.0, 1.0], "v(a)": [1.0, 2.0]}))
    return res


def main() -> int:
    """Stdlib CI selftest: no simulation, no records written."""
    cfg = json.loads((Path(__file__).resolve().parent / "experiment.json").read_text())
    fails = []
    for r in run_selftest(cfg):
        print(f"{'PASS' if r['ok'] else 'FAIL'} {r['case']}: expected {r['expected']}, got {r['got']}")
        if not r["ok"]:
            fails.append(r["case"])
    for name, wave, state, vf, _ in invalid_cases():
        g = grade(wave, state, vf, cfg)
        if g["status"] == "ok" or not g.get("invalid_input") or not g.get("reason"):
            fails.append(name + ":invalid-not-flagged")
    w = irregular_wave()
    g = grade(w, "iq-total", 3.3, cfg)
    ref = grade(synth("iq-total"), "iq-total", 3.3, cfg)
    good = g["status"] == "ok" and not g.get("invalid_input") and abs(g["i_total_a"] - ref["i_total_a"]) <= 1e-12 * abs(ref["i_total_a"])
    print(f"{'PASS' if good else 'FAIL'} irregular_sampling_time_weighted: {g['status']} i={g.get('i_total_a')} ref={ref['i_total_a']}")
    if not good:
        fails.append("irregular_sampling")
    # non-constant current on a non-uniform grid: must equal the exact trapezoid mean, which is
    # chosen to differ from the arithmetic sample mean (otherwise the check is not discriminating)
    ww, exact, arith = weighted_wave(cfg)
    gw = grade(ww, "iq-total", 3.3, cfg)
    discriminating = abs(exact - arith) > 1e-3 * abs(exact)
    good = (gw["status"] == "ok" and not gw.get("invalid_input") and discriminating
            and abs(gw["i_total_a"] - exact) <= 1e-9 * abs(exact) and abs(gw["i_total_a"] - arith) > 1e-3 * abs(exact))
    print(f"{'PASS' if good else 'FAIL'} irregular_nonconstant_time_weighted: {gw['status']} i={gw.get('i_total_a')} exact={exact} arith_mean={arith}")
    if not good:
        fails.append("irregular_nonconstant_time_weighted")
    # drifting irregular grid: time-weighting must still detect the drift
    wd = synth("iq-total", drift=0.5)
    keep = sorted(set(list(range(0, 3001, 7)) + list(range(2000, 3001)) + [3000]))
    gd = grade({k: [v[i] for i in keep] for k, v in wd.items()}, "iq-total", 3.3, cfg)
    if gd["status"] != "unsettled":
        fails.append("irregular_drift")
    for name, ok in selftest_load_wave_cases():
        print(f"{'PASS' if ok else 'FAIL'} {name}")
        if not ok:
            fails.append(name)
    print("FAILED: " + ", ".join(fails) if fails else "all iq_checker selftests passed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
