#!/usr/bin/env python3
"""Driver for the assembled temp_por_top glitch campaign (issue #117).

Two glitch classes are planned, submitted, graded and RECORDED SEPARATELY:

  por_raw_inject  POR_RAW-domain finite-impedance pulse injection (instrumented
                  assembly: two instrument lines spliced into the DUT subckt).
  vdd_level       symmetric-edge VDD glitch on the unmodified assembly.

Each glitch point is ONE ``klt sim`` request whose corner axes are process x
supply x temperature (45 points); the request goes to the Spot batch fleet.
This script never launches ngspice over a grid.

Subcommands
  plan       print the declared request/point counts per class (no simulation).
  run        build netlists + requests and submit to the fleet (``--backend
             batch``).  Refuses a dirty tree or an unpushed source SHA unless
             ``--allow-dirty``.  A submit failure is kept as evidence -- there is
             NO local fallback.
  probe      ONE single-corner LOCAL request (``--backend local``): netlist /
             channel-name validation only, never a grid.
  record     grade every retrieved waveform with glitch_checker.py and write the
             append-only evidence, ONE record (md + json) PER CLASS.  Unsubmitted
             / refused / missing points are NOT_COVERED.
  selftest   run the checker's synthetic cases and write a self-test record.

Append-only: ``record`` and ``selftest`` refuse to overwrite any existing path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SIM_DIR / "brownout-top"))

import evidence_store  # noqa: E402
import glitch_checker as gc  # noqa: E402
import run_brownout_campaign as rb  # noqa: E402  (generic helpers: provenance, per-point logs, error classes)
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()
say = sim_common.say
fmt = sim_common.fmt
scrub = rb.scrub

SLUG = "glitch-top"
MANIFEST = HERE / "experiment.json"
TB_SCH = HERE / "testbench" / "tb_temp_por_glitch.sch"
DUT_NETLIST = sim_common.DUT_NETLIST
BUILD = REPO_ROOT / "sim" / "build" / SLUG
MODEL_LIB = rb.MODEL_LIB
CLASSES = (gc.CLASS_A, gc.CLASS_B)
OUTCOMES = rb.OUTCOMES
DECK_INPUTS = ("design/netlist", "sim/glitch-top/testbench", "sim/spiceinit", "sim/pdk.json")

corner_id, corners_of = rb.corner_id, rb.corners_of
file_sha256, source_state = rb.file_sha256, rb.source_state

# the two instrument lines (exact text; the selftest and the deck attribution check compare against these)
INJ_MARK = "* GLITCH-TOP INSTRUMENT (not part of the design): POR_RAW injection"
INJ_B = "BINJ INJD VSS V=v(POR_RAW)*(1-v(ginj))"
INJ_R = "RINJ INJD POR_RAW {rinj:g}"
INJ_SAVE = ".save @r.xdut.rinj[i]"


def _g(x: float) -> str:
    return f"{x:g}".replace("+", "").replace("-", "m")


# --------------------------------------------------------------------------
# the declared matrix
# --------------------------------------------------------------------------


def plan_requests(man: dict, cls: str | None = None) -> list[dict]:
    """Declared glitch points.  Every axis is a separate parameter; class A and B never share a request."""
    g, s = man["grid"], man["stimulus"]
    out: list[dict] = []
    # defaults for parameters a class does not use (inert: vlow=99 -> no dip, gen=0 -> no injection)
    inert = {"vlow": 99.0, "th": 0.0, "sf": 1e5, "gen": 0, "tw": 1e-5, "te": 1e-5, "rinj": 1e3}
    base = {"rup": s["power_up_rate_v_per_s"], "t0": s["t0_s"]}

    if cls in (None, gc.CLASS_A):
        a = g["por_raw_inject"]

        def add_a(kind, rinj, tw, te, gen=1):
            tag = "por_raw_control" if kind == "control" else f"por_raw_{kind}_r{_g(rinj)}_w{_g(tw)}_e{_g(te)}"
            out.append({"cls": gc.CLASS_A, "tag": tag, "kind": kind, **base, **inert, "gen": gen, "rinj": rinj, "tw": tw, "te": te})

        for rinj in a["rinj_ohm"]:
            for tw in a["flat_widths_s"]:
                add_a("cube", rinj, tw, a["edge_default_s"])
        c = a["edge_variant_center"]
        for te in a["edge_variants_s"]:
            add_a("edge", c["rinj"], c["tw"], te)
        add_a("control", a["rinj_ohm"][0], a["flat_widths_s"][0], a["edge_default_s"], gen=0)

    if cls in (None, gc.CLASS_B):
        b = g["vdd_level"]

        def add_b(kind, vlow, th, sf):
            tag = "vdd_control" if kind == "control" else f"vdd_{kind}_v{_g(vlow)}_h{_g(th)}_s{_g(sf)}"
            out.append({"cls": gc.CLASS_B, "tag": tag, "kind": kind, **base, **inert, "vlow": vlow, "th": th, "sf": sf})

        for vlow in b["floors_v"]:
            for th in b["holds_s"]:
                add_b("cube", vlow, th, b["slew_default_v_per_s"])
        c = b["slew_variant_center"]
        for sf in b["slew_variants_v_per_s"]:
            add_b("slew", c["vlow"], c["th"], sf)
        add_b("control", 99.0, b["holds_s"][0], b["slew_default_v_per_s"])

    tags = [r["tag"] for r in out]
    if len(set(tags)) != len(tags):
        raise SystemExit("request tag collision in the declared matrix")
    return out


def declared_counts(man: dict, cls: str | None = None) -> dict:
    reqs = plan_requests(man, cls)
    n_corner = len(corners_of(man))
    return {"requests": len(reqs), "points_per_request": n_corner, "points": len(reqs) * n_corner}


def stim_of(req: dict) -> dict:
    if req["cls"] == gc.CLASS_A:
        return {k: req[k] for k in ("rup", "t0", "te", "tw", "rinj", "gen")}
    return {k: req[k] for k in ("rup", "t0", "vlow", "th", "sf")}


def tstop_of(req: dict, man: dict) -> float:
    t_obs = man["stimulus"]["observation_after_recovery_s"]
    if req["cls"] == gc.CLASS_A:
        return gc.tstop_a(stim_of(req), t_obs)
    return gc.tstop_b(max(man["corners"]["supply_v"]), stim_of(req), t_obs)


def tmax_of(req: dict, man: dict) -> float:
    if req["cls"] == gc.CLASS_A:
        return gc.tmax_a(stim_of(req))
    return gc.tmax_b(stim_of(req), min(man["corners"]["supply_v"]))


# --------------------------------------------------------------------------
# netlists and requests
# --------------------------------------------------------------------------


def tb_netlist_head(run_dir: Path, pdk) -> str:
    return sim_common.netlist_tb_head(TB_SCH, run_dir / "tb", pdk)


def splice_injection(dut: str, rinj: float) -> str:
    """Insert the two instrument lines at the end of the temp_por_top subckt (before its .ends).  Nothing else changes."""
    lines = dut.splitlines()
    out, inside, done = [], False, False
    for ln in lines:
        low = ln.strip().lower()
        if low.startswith(".subckt temp_por_top"):
            inside = True
        if inside and not done and low.startswith(".ends"):
            out += [INJ_MARK, INJ_B, INJ_R.format(rinj=rinj)]
            done = True
            inside = False
        out.append(ln)
    if not done:
        raise SystemExit("could not find the temp_por_top subckt end in the committed netlist")
    return "\n".join(out) + "\n"


def build_netlist(head: str, req: dict) -> str:
    dut = sim_common.load_dut_netlist(DUT_NETLIST)
    A = req["cls"] == gc.CLASS_A
    sr = req["sf"]  # symmetric edges: the testbench sr is the class's sf
    params = (f".param rup={req['rup']:g} t0={req['t0']:g} vlow={req['vlow']:g} th={req['th']:g} sf={req['sf']:g} sr={sr:g} "
              f"gen={req['gen']:g} tw={req['tw']:g} te={req['te']:g} rinj={req['rinj']:g}")
    banner = (
        f"* {SLUG}: generated by sim/glitch-top/run_glitch_campaign.py -- do not edit\n"
        f"* request {req['tag']} (class {req['cls']}, {req['kind']}): "
        + ("committed design/netlist/temp_por_top.spice + two POR_RAW injection instrument lines (INSTRUMENTED assembly), PTAT/CTAT open\n"
           if A else "unchanged committed design/netlist/temp_por_top.spice (UNMODIFIED assembly), PTAT/CTAT open\n")
        + params + "\n"
        "* ng_nomodcheck: same setting as sim/spiceinit; carried in the netlist because the fleet runner\n"
        "* ignores options.ngspice_init (see experiment.json fleet.ngspice_note)\n"
        + sim_common.NOMODCHECK_CONTROL
    )
    if A:
        # GINJ must be global so the drive inside the DUT subckt is the testbench's GINJ node
        banner += ".global GINJ\n" + INJ_SAVE + "\n"
        dut = splice_injection(dut, req["rinj"])
    return banner + head + "\n" + dut


def build_request(req: dict, man: dict, backend: str, capacity_wait_s: float = 0) -> dict:
    tstop, tmax = tstop_of(req, man), tmax_of(req, man)
    c = man["corners"]
    t0 = req["t0"]
    r = {
        "netlist": "netlist.spice",
        "backend": backend,
        "models": {"pdk": "sky130A", "lib": MODEL_LIB},
        "corners": {"process": c["process"], "supply_v": {"vset": c["supply_v"]}, "temperature_c": c["temperature_c"]},
        "analysis": {"kind": "tran", "args": f"{min(1e-6, tmax):.3g} {tstop:.9g} 0 {tmax:.3g}"},
        "measurements": [
            {"name": "vdd_min", "spice": ".meas tran vdd_min MIN v(vdd)", "unit": "V"},
            {"name": "resetn_end", "spice": f".meas tran resetn_end FIND v(resetn) AT={(tstop - 0.1e-3):.9g}", "unit": "V"},
            {"name": "resetn_min_after_t0", "spice": f".meas tran resetn_min_after_t0 MIN v(resetn) FROM={t0:g} TO={tstop:.9g}", "unit": "V"},
        ],
        "options": {"timeout_s": 7200, "keep_artifacts": True, "waveforms": True},
    }
    if backend == "batch":
        r["batch"] = {"runner_version_check": "warn"}
        if capacity_wait_s:
            r["batch"]["capacity_wait_s"] = capacity_wait_s
    return r


def submit_one(req: dict, head: str, man: dict, run_dir: Path, capacity_wait_s: float = 0) -> dict:
    """Write netlist + request and run ``klt sim --backend batch``; an earlier attempt is archived, never overwritten."""
    d = run_dir / req["tag"]

    def refused(p, n):
        # the fleet has a shared instance cap that klt does not wait on; a refused LAUNCH is retried later
        # (bounded; never replaced by a local grid).  Every refusal is kept as evidence.
        if "BATCH_MAX_CONCURRENT_INSTANCES" in p.stdout + p.stderr and capacity_wait_s and n <= 40:
            (d / f"launch-refused-{n}.txt").write_text(p.stdout + p.stderr)
            time.sleep(min(180, capacity_wait_s))
            return True
        return False

    res = sim_common.submit_prepared(
        d, build_netlist(head, req), build_request(req, man, "batch", capacity_wait_s),
        f"{req['tag']}: {len(corners_of(man))} points -> batch fleet", req["tag"], retry=refused)
    return {"tag": req["tag"], **res}


# --------------------------------------------------------------------------
# provenance + deck attribution
# --------------------------------------------------------------------------


def deck_drift(run_sha, grade_sha):
    if not run_sha or not grade_sha:
        return None
    p = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "--name-only", run_sha, grade_sha, "--", *DECK_INPUTS], capture_output=True, text=True)
    return None if p.returncode != 0 else [ln for ln in p.stdout.splitlines() if ln.strip()]


def deck_attribution(deck: str, req: dict) -> list[str]:
    """Problems that would let a point be credited to the wrong DUT / class (empty = attributable)."""
    bad = []
    if f"* {SLUG}: generated by" not in deck or f"request {req['tag']} (class {req['cls']}" not in deck:
        bad.append("banner/request tag missing")
    if not re.search(r"XMN1\b[^\n]*\bL=20\b[^\n]*\bW=0\.42\b", deck, re.I) and not re.search(r"XMN1\b[^\n]*\bW=0\.42\b[^\n]*\bL=20\b", deck, re.I):
        bad.append("committed XMN1 L=20 W=0.42 not found")
    if re.search(r"diag-mn1|diagnostic", deck, re.I):
        bad.append("diagnostic marker present")
    has_inj = INJ_B in deck and INJ_R.format(rinj=req["rinj"]) in deck
    if req["cls"] == gc.CLASS_A and not has_inj:
        bad.append("class por_raw_inject deck lacks the injection element")
    if req["cls"] == gc.CLASS_B and (INJ_B in deck or INJ_MARK in deck or re.search(r"^RINJ\b", deck, re.M)):
        bad.append("class vdd_level deck contains an injection element (DUT not unmodified)")
    if f"rinj={req['rinj']:g}" not in deck or f"tw={req['tw']:g}" not in deck or f"vlow={req['vlow']:g}" not in deck:
        bad.append("declared .param line differs from the request")
    return bad


def attribute_point(netlist_text: str, matches_report: bool, corner_deck: str, req: dict, proc: str, temp: float) -> list[str]:
    """Attribution of one fleet point.  The fleet's retrieved corner deck only wraps the submitted netlist (``.include``), so the exact
    DUT/class evidence is the submitted netlist, accepted only when its sha256 equals the fleet-reported netlist sha256."""
    if not netlist_text:
        return ["submitted netlist not on disk: cannot attribute the point to this experiment/class"]
    bad = [] if matches_report else ["submitted netlist sha256 differs from the fleet-reported netlist sha256"]
    bad += deck_attribution(netlist_text, req)
    if not corner_deck:
        bad.append("retrieved corner deck missing")
    else:
        if not re.search(rf"^\.lib\s+\S*sky130\.lib\.spice\s+{re.escape(proc)}\s*$", corner_deck, re.M):
            bad.append(f"corner deck does not load the {proc} process corner")
        if not re.search(rf"^\.temp\s+{re.escape(f'{temp:g}')}\s*$", corner_deck, re.M):
            bad.append(f"corner deck temperature differs from {temp:g}")
        if not re.search(r"^\.include\s+\S*netlist", corner_deck, re.M):
            bad.append("corner deck does not include the submitted netlist")
    return bad


def cmd_plan(args) -> int:
    man = sim_common.load_manifest(MANIFEST)
    for cls in CLASSES:
        cnt = declared_counts(man, cls)
        print(f"class {cls}: {cnt['requests']} requests x {cnt['points_per_request']} PVT points = {cnt['points']} points")
        for r in plan_requests(man, cls):
            print(f"  {r['tag']:<40} tstop {tstop_of(r, man) * 1e3:7.3f} ms  tmax {tmax_of(r, man) * 1e6:7.3f} us")
    tot = declared_counts(man)
    print(f"total: {tot['requests']} requests, {tot['points']} points")
    return 0


def cmd_run(args) -> int:
    evidence_store.preflight_or_exit()  # fail closed before anything is submitted
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    gi = source_state()
    if (gi["dirty"] or not gi["pushed_to_remote"]) and not args.allow_dirty:
        raise SystemExit(f"refusing to submit: dirty={gi['dirty']} pushed={gi['pushed_to_remote']} (commit + push first, or --allow-dirty; the state is recorded either way)")
    now = datetime.now(timezone.utc)
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{gi['sha']}"
    run_dir = BUILD / run_id
    if args.retry_failed:
        if not run_dir.exists():
            raise SystemExit(f"{run_dir} does not exist")
    else:
        if run_dir.exists():
            raise SystemExit(f"{run_dir} exists; refusing to reuse a run id")
        run_dir.mkdir(parents=True)
    reqs = plan_requests(man, args.only_class)
    if args.only:
        reqs = [r for r in reqs if r["tag"] in args.only]
        if not reqs:
            raise SystemExit("--only matched no declared request")
    if args.retry_failed:
        reqs = [r for r in reqs if not sim_common.report_usable(run_dir / r["tag"] / "report.json")]
        say(f"retrying {len(reqs)} request(s) without a usable report, capacity_wait_s={args.capacity_wait}")
    head = tb_netlist_head(run_dir / ("retry" if args.retry_failed else "."), pdk)
    meta = {"run_id": run_id, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": gi, "klt_client": sim_common.klt_version(),
            "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "declared": declared_counts(man), "submitted_tags": [r["tag"] for r in reqs]}
    if not args.retry_failed:
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    say(f"run id {run_id}: {len(reqs)} request(s)")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(2, args.jobs))) as ex:
        futs = [ex.submit(submit_one, r, head, man, run_dir, args.capacity_wait) for r in reqs]
        for f in futs:
            try:
                results.append(f.result())
            except Exception as err:  # noqa: BLE001 -- recorded, never swallowed
                results.append({"error": repr(err)})
                say(f"[error] submit raised: {err!r}")
    old = json.loads((run_dir / "run.json").read_text()) if args.retry_failed else meta
    if args.retry_failed:
        old.setdefault("retries", []).append({"at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "capacity_wait_s": args.capacity_wait, "results": results})
    else:
        old["submit_results"] = results
    (run_dir / "run.json").write_text(json.dumps(old, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def cmd_probe(args) -> int:
    """ONE single-corner local request for netlist/channel validation.  Never a grid."""
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    reqs = {r["tag"]: r for r in plan_requests(man)}
    if args.tag not in reqs:
        raise SystemExit(f"unknown request tag {args.tag}")
    req = reqs[args.tag]
    d = BUILD / "probe" / args.tag
    d.mkdir(parents=True, exist_ok=True)
    (d / "netlist.spice").write_text(build_netlist(tb_netlist_head(d, pdk), req))
    r = build_request(req, man, "local")
    r["corners"] = {"process": ["tt"], "supply_v": {"vset": [3.3]}, "temperature_c": [27]}
    if args.tstop:
        r["analysis"]["args"] = f"1e-6 {args.tstop:g} 0 5e-6"
        r["measurements"] = []
    r["options"]["ngspice_init"] = [ln.strip() for ln in (SIM_DIR / "spiceinit").read_text().splitlines() if ln.strip() and not ln.startswith("*")]
    (d / "request.json").write_text(json.dumps(r, indent=2) + "\n")
    say(f"[probe] one LOCAL corner tt/27C/3.30V for {args.tag}")
    p = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "local", "-o", str(d / "out"), "--format", "json"], capture_output=True, text=True, timeout=3600)
    (d / "report.json").write_text(p.stdout)
    (d / "klt.stderr").write_text(p.stderr)
    print(f"exit {p.returncode}; {d}")
    return 0


# --------------------------------------------------------------------------
# record
# --------------------------------------------------------------------------


def analyze_request(req: dict, run_dir: Path, man: dict, corners_dir: Path, write: bool) -> dict:
    """All 45 declared points of one request.  Every declared point appears, covered or not."""
    d = run_dir / req["tag"]
    st = stim_of(req)
    cls = req["cls"]
    A = cls == gc.CLASS_A
    t_obs = man["stimulus"]["observation_after_recovery_s"]
    declared = corners_of(man)
    info = {"tag": req["tag"], "class": cls, "kind": req["kind"], "stimulus": st, "tstop_s": tstop_of(req, man), "tmax_s": tmax_of(req, man)}
    attempts = []
    for ad in sorted(d.glob("attempt*")):
        try:
            body = json.loads((ad / "report.json").read_text()) if (ad / "report.json").is_file() else {}
            msg = (body.get("error") or {}).get("message") or ("report status " + str(body.get("status")))
        except json.JSONDecodeError:
            msg = "unparseable report"
        attempts.append(scrub(msg, run_dir)[:400])
    if attempts:
        info["failed_earlier_attempts"] = attempts
    rep, why = None, None
    rep_path = d / "report.json"
    if not rep_path.is_file():
        why = "NOT SUBMITTED (no report on disk)"
    else:
        try:
            rep = json.loads(rep_path.read_text())
        except json.JSONDecodeError:
            why = "NO JSON (klt failed before a report existed): " + scrub((d / "klt.stderr").read_text()[-600:], run_dir)
        else:
            if "corners" not in rep:
                why = "klt/fleet error, no corners reported: " + scrub(str((rep.get("error") or {}).get("message", rep))[:500], run_dir)
                rep = None
    pts = []
    if rep is None:
        info["outcome"] = why
        for p, t, v in declared:
            pts.append({"id": corner_id(p, t, v), "tag": req["tag"], "class": cls, "process": p, "temperature_c": t, "supply_v": v, "outcome": "NOT_COVERED", "reason": why})
        return {"info": info, "points": pts, "pdk_report": {}}
    remote = (rep.get("environment") or {}).get("remote") or {}
    info["netlist_sha256_submitted"] = file_sha256(d / "netlist.spice")
    info["netlist_sha256_reported"] = (rep.get("environment") or {}).get("netlist_sha256")
    info["netlist_matches_report"] = info["netlist_sha256_submitted"] is not None and info["netlist_sha256_submitted"] == info["netlist_sha256_reported"]
    info.update({"outcome": rep.get("status"), "job_id": remote.get("job_id"), "instance_type": remote.get("instance_type"), "lifecycle": remote.get("lifecycle"),
                 "runner_klt_version": remote.get("runner_klt_version"), "client_klt_version": remote.get("client_klt_version"),
                 "elapsed_seconds": remote.get("elapsed_seconds"), "state": remote.get("state"), "corner_count": rep.get("corner_count"),
                 "request_id": (rep.get("environment") or {}).get("request_id") or rep.get("request_id")})
    seen = set()
    for c in rep.get("corners", []):
        proc, vf, temp = c["process"], c["supply_v"]["vset"], c["temperature_c"]
        cid = corner_id(proc, temp, vf)
        seen.add(cid)
        art = c.get("artifacts") or {}
        wave_path = Path(art["waveform"]) if art.get("waveform") else None
        log_text = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else ""
        deck_text = Path(art["deck"]).read_text() if art.get("deck") and Path(art["deck"]).is_file() else ""
        ngv = re.findall(r"(ngspice-\d+) done", log_text)
        pt = {"id": cid, "tag": req["tag"], "class": cls, "process": proc, "temperature_c": temp, "supply_v": vf, "klt_status": c.get("status"), "runtime_s": c.get("runtime_s"),
              "ngspice": ngv[0] if ngv else None, "measurements": {m["name"]: m.get("value") for m in c.get("measurements", [])},
              "diagnostics": [{"severity": dg.get("severity"), "code": dg.get("code"), "message": scrub(dg.get("message", ""), run_dir)[:400]} for dg in c.get("diagnostics", [])]}
        wave, load_err = None, None
        if wave_path is not None and wave_path.is_file():
            try:
                wave = sim_common.load_wave(wave_path)
            except Exception as err:  # noqa: BLE001
                load_err = f"waveform unreadable: {err!r}"
        attr = attribute_point((d / "netlist.spice").read_text() if (d / "netlist.spice").is_file() else "", info["netlist_matches_report"], deck_text, req, proc, temp)
        res = gc.analyze(cls, wave, vf, st, t_obs)
        if attr:
            res = {"verdict": "ERROR", "fail_codes": [], "unresolved_reasons": [], "class": cls, "detail": "deck_attribution: " + "; ".join(attr), "error_class": "deck_attribution"}
        elif wave is None:
            res["detail"] = load_err or "no waveform artifact for this corner"
            res["error_class"] = rb.classify_error(c, log_text)
        pt["outcome"] = res["verdict"]
        pt["check"] = res
        if wave is not None and res["verdict"] != "ERROR":
            rows = gc.compress(wave, A and bool(st["gen"]))
            stt = gc.transitions_from_stored(rows, vf, st["t0"])
            n_as = res["resetn"]["n_assert"]
            n_rel = res["resetn"]["n_release_after_t0"]
            pt["stored_trace"] = {"rows": len(rows), "full_samples": len(wave["time"]), "n_assert": stt["n_assert"], "n_release": stt["n_release"],
                                  "agrees_with_full_resolution": stt["n_assert"] == n_as and stt["n_release"] == n_rel}
            if write:
                gc.write_trace(corners_dir / req["tag"] / f"{cid}.trace.csv.gz", rows, A and bool(st["gen"]))
        if write:
            if A:
                desc = f"rinj={st['rinj']:g}ohm flat_width={st['tw']:g}s edge={st['te']:g}s gen={st['gen']:g}"
            else:
                desc = f"vlow={st['vlow']:g}V hold={st['th']:g}s slew(sf=sr)={st['sf']:g}V/s"
            header = [f"# point: {SLUG} {cls} {req['tag']} {cid}",
                      f"# process={proc} temp={cr.fmt_temp(temp)}C start_supply={vf:.2f}V {desc} tstop={tstop_of(req, man):.6g}s",
                      f"# klt status: {c.get('status')}   runtime on runner: {c.get('runtime_s')} s   outcome: {pt['outcome']}"]
            (corners_dir / req["tag"]).mkdir(parents=True, exist_ok=True)
            (corners_dir / req["tag"] / f"{cid}.log").write_text(rb.point_log(c, header, run_dir))
        pts.append(pt)
    for p, t, v in declared:
        cid = corner_id(p, t, v)
        if cid not in seen:
            pts.append({"id": cid, "tag": req["tag"], "class": cls, "process": p, "temperature_c": t, "supply_v": v, "outcome": "NOT_COVERED",
                        "reason": "corner absent from an otherwise returned report"})
    return {"info": info, "points": pts, "pdk_report": (rep.get("provenance") or {}).get("pdk", {})}


def summarize(points: list[dict]) -> dict:
    """Per-request and per-corner (process x temperature x supply) outcome counts for ONE class."""
    by_req: dict = {}
    by_corner: dict = {}
    codes: dict = {}
    for p in points:
        by_req.setdefault(p["tag"], {o: 0 for o in OUTCOMES})[p["outcome"]] += 1
        by_corner.setdefault(p["id"], {o: 0 for o in OUTCOMES})[p["outcome"]] += 1
        for c in (p.get("check") or {}).get("fail_codes", []):
            codes[c] = codes.get(c, 0) + 1
    total = {o: sum(s[o] for s in by_req.values()) for o in OUTCOMES}
    nonphys = {"pre-glitch node violation": 0, "post-glitch node violation": 0, "supply current reversed at end": 0, "supply current reversed at baseline": 0, "NONPHYSICAL total": 0}
    for p in points:
        ph = (p.get("check") or {}).get("physical")
        if p["outcome"] == "NONPHYSICAL" and ph:
            nonphys["NONPHYSICAL total"] += 1
            nonphys["pre-glitch node violation"] += ph.get("node_violation_phase") == "pre-glitch"
            nonphys["post-glitch node violation"] += ph.get("node_violation_phase") == "post-glitch"
            nonphys["supply current reversed at end"] += bool(ph.get("supply_current_reversed_at_end"))
            nonphys["supply current reversed at baseline"] += bool(ph.get("supply_current_reversed_at_baseline"))
    return {"by_request": by_req, "by_corner": by_corner, "total": total, "fail_codes": codes, "nonphysical_breakdown": nonphys}


def _uA(x):
    return "n/a" if x is None else f"{x * 1e6:.3g}"


def _ms(x):
    return "n/a" if x is None else f"{x * 1e3:.5g}"


def point_row(p: dict, A: bool) -> str:
    c = p.get("check")
    if p["outcome"] == "NOT_COVERED":
        return f"| {p['id']} | NOT_COVERED | " + " | ".join(["-"] * 10) + f" | {p.get('reason', '')[:80]} |"
    if p["outcome"] == "ERROR":
        return f"| {p['id']} | ERROR | " + " | ".join(["-"] * 10) + f" | {c.get('error_class', '')} {c.get('detail', '')[:80]} |"
    rs, db, ibn, rz, bl = c["resetn"], c["delivered_bias"], c["ibias_node"], c["resolution"], c["baseline"]
    if A:
        ex = c["expectation"]["call"]
        det = f"dwell {c['expectation']['dwell_raw_below_vmid_s'] * 1e6:.3g} us"
        inj = f"min {fmt(c['injection']['por_raw_min_v'], '.3f')} V / peak {_uA(c['injection']['peak_injected_current_a'])} uA"
        gap = rz["max_dt_glitch_window_s"]
        assert_v = ""
    else:
        ex = c["detectability"]["call"]
        det = f"VDD dwell<V_MUST {c['detectability']['dwell_below_vmust_s'] * 1e6:.3g} us"
        inj = "rail collapse" if c.get("regime", {}).get("rail_collapse") else ("POR_RAW fell, RESETn held" if c.get("regime", {}).get("dwell_rejection_visible") else "-")
        gap = rz["max_dt_dip_window_s"]
        assert_v = f" VDD@assert {fmt(rs.get('vdd_at_assert_v'), '.3f')}{'*' if rs.get('assertion_rail_limited') else ''}"
    note = ",".join(c["fail_codes"]) or "; ".join(c["unresolved_reasons"])[:90]
    if p["outcome"] == "NONPHYSICAL":
        ph = c["physical"]
        note = (f"NONPHYSICAL {ph['node_violation_phase'] or 'no node violation'}"
                + (f" [{','.join(sorted(ph['violations_after_t0']))}]" if ph["violations_after_t0"] else "")
                + (" supply-current-reversed(end)" if ph["supply_current_reversed_at_end"] else "")
                + (" delivered-bias-sign" if not ph["delivered_bias_sign_ok"] else ""))[:140]
    sp = 1 if "premature_release" in c["fail_codes"] else rs.get("spurious_releases", 0)
    return (f"| {p['id']} | {p['outcome']} | {ex} | {det} | {rs['n_assert']}{assert_v} | {_ms(rs['t_assert_s'])}/{_ms(rs['t_release_s'])} | {sp} | "
            f"{'ok' if bl['ok'] else 'UNREADY'} | {_uA(db['baseline_a'])}/{_uA(db['min_after_t0_a'])}/{_uA(db['end_a'])} | "
            f"{fmt(ibn['baseline_v'], '.3f')}/{fmt(ibn['min_after_t0_v'], '.3f')} | {inj} | {gap * 1e6:.3g}/{rz['required_max_dt_s'] * 1e6:.3g} | {note} |")


def render_md(rec: dict) -> str:
    cls = rec["class"]
    A = cls == gc.CLASS_A
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], rec["experiment"]["slug"], rec["experiment"]["title"])
    L.append(f"- **Glitch class (this record covers ONLY this class)**: `{cls}` -- {rec['class_info']['label']}. {rec['class_info']['purpose']}")
    if A:
        L.append("- **Evidence kind**: INSTRUMENTED assembly -- two instrument lines are spliced into the DUT subckt (see Injection). This is NOT as-drawn immunity evidence.")
    else:
        L.append("- **Evidence kind**: UNMODIFIED assembly -- the DUT netlist is spliced byte-identical; only the supply stimulus differs.")
    L.append(f"- **Claim**: {rec['experiment']['claim']}")
    L.append(f"- **Netlist provenance**: {rec['experiment']['provenance']} (`{rec['experiment']['provenance_source']}`)")
    L += sim_common.render_pdk_tools_repo_state(rec)
    t, g = rec["tools"], rec["git"]
    rs = rec["run_source"]
    L.append(f"- **Simulation source commit** (grid submitted from): `{rs.get('sha_full')}` (dirty at submit: {rs.get('dirty')}; pushed to a remote branch at submit: {rs.get('pushed_to_remote')})")
    L.append(f"- **Grading source commit**: `{g['sha_full']}` (dirty at grading: {g['dirty']}; pushed: {g['pushed_to_remote']})")
    dd = rec["deck_drift"]
    L.append("- **Deck inputs between the two commits** (" + ", ".join(f"`{x}`" for x in DECK_INPUTS) + "): "
             + ("identical" if dd == [] else f"CHANGED {dd}" if dd else "not determinable"))
    nm = [q["tag"] for q in rec["requests"] if q.get("job_id") and not q.get("netlist_matches_report")]
    L.append("- **Submitted netlist vs fleet report sha256**: " + ("all match" if not nm else f"MISMATCH for {nm}"))
    L.append(f"- **Fleet runner**: klt `{t['fleet_runner_klt']}` / `{t['fleet_ngspice']}` (client klt `{t['klt_client']}`); {t['fleet_note']}")
    L.append(f"- **Host tool caveat**: {t['xschem_note']}")
    m = rec["matrix"]
    L.append("- **Corner matrix**: process " + ", ".join(m["process"]) + "; temperature " + ", ".join(f"{cr.fmt_temp(x)} C" for x in m["temperature_c"]) + "; starting supply " + ", ".join(f"{v:.2f} V" for v in m["supply_v"]))
    L.append(f"- **Declared**: {m['n_requests']} request(s) x {m['points_per_request']} = {m['n_points']} points; {m['n_requests_submitted']} request(s) with a fleet job id; {m['n_points_graded']} points graded, {m['n_points_not_covered']} NOT_COVERED (never counted as covered).")
    L.append("- **PTAT/CTAT loading**: open; RESETn unloaded; no ideal bias/sensor substitution; committed XMN1 L=20 W=0.42, no diagnostic edits.")
    L.append("")
    if A:
        inj = rec["injection"]
        L.append("## Injection (instrument, disclosed departure from the uninstrumented assembly)")
        L.append(f"- **Status**: {inj['status']}")
        L.append("- **Elements**: " + "; ".join(f"`{e}`" for e in inj["elements"]))
        L.append(f"- **Mechanism**: {inj['mechanism']}")
        L.append(f"- **Loading**: {inj['loading']}")
        L.append(f"- **Limit rule**: {inj['limit_rule']}")
        L.append(f"- **Measured per point**: {inj['measured_injection']}")
        L.append("")
    L.append("## Measurement definitions (exploratory; none is a ratified bound)")
    for k, v in rec["definitions"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    s = rec["summary"]
    L.append("## Outcome totals (this class only)")
    L.append("| " + " | ".join(OUTCOMES) + " |")
    L.append("|" + "---|" * len(OUTCOMES))
    L.append("| " + " | ".join(str(s["total"][o]) for o in OUTCOMES) + " |")
    L.append(f"\nFailure codes (graded points): {s['fail_codes'] or 'none'}")
    L.append(f"\nNONPHYSICAL breakdown (a point may count in several rows): {s['nonphysical_breakdown']}")
    L.append("")
    L.append("## Per-corner summary (all requests of this class, per PVT corner)")
    L.append("| corner | " + " | ".join(OUTCOMES) + " |")
    L.append("|---|" + "---|" * len(OUTCOMES))
    for cid, cnt in s["by_corner"].items():
        L.append(f"| {cid} | " + " | ".join(str(cnt[o]) for o in OUTCOMES) + " |")
    L.append("")
    L.append("## Per-request fleet submissions and outcome counts")
    if A:
        L.append("| request | kind | RINJ ohm | flat width s | edge s | gen | tstop ms | tmax us | fleet outcome | job id | " + " | ".join(OUTCOMES) + " |")
    else:
        L.append("| request | kind | floor V | hold s | slew V/s | - | tstop ms | tmax us | fleet outcome | job id | " + " | ".join(OUTCOMES) + " |")
    L.append("|" + "---|" * (10 + len(OUTCOMES)))
    for r in rec["requests"]:
        st, c = r["stimulus"], s["by_request"][r["tag"]]
        axes = (f"{st['rinj']:g} | {st['tw']:g} | {st['te']:g} | {st['gen']:g}" if A else f"{st['vlow']:g} | {st['th']:g} | {st['sf']:g} | -")
        L.append(f"| {r['tag']} | {r['kind']} | {axes} | {r['tstop_s'] * 1e3:.4g} | {r['tmax_s'] * 1e6:.3g} | {str(r.get('outcome'))[:60]} | {r.get('job_id')} | " + " | ".join(str(c[o]) for o in OUTCOMES) + " |")
    L.append("")
    L.append("## Per-point table")
    L.append("Columns: outcome; call = what the stimulus calls for; detectability dwell; asserts (+VDD at assertion for VDD-level; `*` rail-limited); t_assert/t_release ms; spurious releases; baseline; delivered bias (+id of XMPIB, uA) baseline/min/end; IBIAS node V baseline/min; injection or regime observation; max sample gap vs required (us); note.")
    for r in rec["requests"]:
        L.append("")
        L.append(f"### {r['tag']}")
        L.append("| point | outcome | call | detectability | asserts | t_assert/t_release (ms) | spurious rel | baseline | Ibias base/min/end (uA) | IBIAS node base/min (V) | injection / regime | gap/req (us) | note |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for p in (q for q in rec["points"] if q["tag"] == r["tag"]):
            L.append(point_row(p, A))
    L.append("")
    if rec.get("submit_failures"):
        L.append("## Fleet submit failures / refusals (recorded, no local fallback)")
        for f in rec["submit_failures"]:
            L.append(f"- `{f['tag']}`: {f['reason']}")
        L.append("")
    L.append("## Absent coverage (stated, not hidden)")
    for a in rec["absent_coverage"]:
        L.append(f"- {a}")
    L.append("")
    if rec.get("follow_on"):
        L += ["## Notes", rec["follow_on"], ""]
    L.append("## Links")
    for k, v in rec["links"].items():
        L.append(f"- {k}: `{v}`" if v else f"- {k}: none")
    if not rec["links"].get("artifact_manifest"):
        L.append("- **Evidence bytes**: none stored -- no point of this class was graded and no request was submitted (all points NOT_COVERED).")
    L.append(f"- **Timestamp / author**: {rec['timestamp']}, {rec['author']}")
    L.append(f"- **Supersedes**: {rec['supersedes'] or '(none)'}")
    L.append("")
    L.append("Written by `sim/glitch-top/run_glitch_campaign.py`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).")
    L.append("")
    return "\n".join(L)


def absent(man: dict, cls: str) -> list[str]:
    common = [
        "The initial grid is exploratory and bounded (see experiment.json grid.not_covered); no glitch-immunity envelope is claimed or ratified (DR-003 Sec8). The expansion policy is declared in the manifest.",
        "Edge/slew is varied one-factor-at-a-time around the center point only, not crossed with the full cube.",
        "ll/hh passive skew and mismatch Monte Carlo are not exercised; PTAT/CTAT are open; no post-layout parasitics; default solver settings only.",
        "temp_core startup artifacts of #86 are not presumed fixed: an affected point shows up as an UNRESOLVED baseline, a NONPHYSICAL node or an ERROR, not as a PASS.",
    ]
    if cls == gc.CLASS_A:
        return common + ["This class is INSTRUMENTED-assembly evidence: it says how the deglitch dwell reacts to a finite-impedance disturbance at POR_RAW, not that the as-drawn block tolerates any physical disturbance source.",
                         "The VDD-level class is a separate record; neither class stands in for the other."]
    return common + ["The POR_RAW-domain injection class is a separate record; a VDD-level result says nothing about the deglitch dwell in isolation."]


def cmd_record(args) -> int:
    evidence_store.preflight_or_exit()
    man = sim_common.load_manifest(MANIFEST)
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    gi = source_state()
    if gi["dirty"] and not args.allow_dirty:
        raise SystemExit("refusing to record from a dirty tree (commit first, or --allow-dirty; the state is recorded either way)")
    drift = deck_drift((meta.get("source") or {}).get("sha_full"), gi.get("sha_full"))
    if drift and not args.allow_deck_drift:
        raise SystemExit(f"deck inputs changed between the submit commit and HEAD: {drift} -- the record would mis-attribute the evidence")
    now = datetime.now(timezone.utc)
    ph = man["grading"]
    wrote = []
    for cls in CLASSES:
        record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{gi['sha']}-{cls}"
        rec_dir = HERE / "records"
        corners_dir = evidence_store.stage_dir_for(SLUG, record_id)  # git-ignored scratch; stored below
        snap_dir = HERE / "netlist-snapshots" / record_id
        for pth in (rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir, evidence_store.manifest_path(SLUG, record_id)):
            if pth.exists():
                raise SystemExit(f"{pth} exists -- sim/ is append-only")
        points, requests, fleet_pdk = [], [], {}
        for r in plan_requests(man, cls):
            res = analyze_request(r, run_dir, man, corners_dir, write=True)
            points += res["points"]
            requests.append(res["info"])
            fleet_pdk = res["pdk_report"] or fleet_pdk
            src = run_dir / r["tag"]
            for name in ("netlist.spice", "request.json"):
                if (src / name).is_file():
                    snap_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src / name, snap_dir / f"{r['tag']}.{name}")
            if (src / "report.json").is_file():
                (corners_dir / r["tag"]).mkdir(parents=True, exist_ok=True)
                (corners_dir / r["tag"] / "klt-report.json").write_text(scrub((src / "report.json").read_text(), run_dir))
        # A class with nothing submitted/graded (a --only subset run) stages no bytes: record it as NOT_COVERED
        # with null artifact links rather than tripping the store's fail-closed empty-manifest refusal.
        staged = corners_dir.is_dir() and any(corners_dir.rglob("*"))
        if staged or snap_dir.is_dir():
            snap_dir.mkdir(parents=True, exist_ok=True)
            if (run_dir / "run.json").is_file():
                shutil.copyfile(run_dir / "run.json", snap_dir / "run.json")
        fails = [{"tag": q["tag"], "reason": q["outcome"]} for q in requests if q.get("job_id") is None and q.get("outcome") and q["outcome"] not in ("ok", "OK", "PASS")]
        ngs = sorted({p["ngspice"] for p in points if p.get("ngspice")})
        runners = sorted({q.get("runner_klt_version") for q in requests if q.get("runner_klt_version")})
        cnt = declared_counts(man, cls)
        n_graded = sum(1 for p in points if p["outcome"] != "NOT_COVERED")
        art_manifest, art_summary = evidence_store.store_or_exit(SLUG, record_id, corners_dir) if staged else (None, None)
        record = {
            "record_id": record_id, "class": cls, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
            "experiment": {k: man[k] for k in ("slug", "title", "claim", "provenance", "provenance_source", "statistical_convention")},
            "class_info": man["classes"][cls],
            "injection": man["injection"] if cls == gc.CLASS_A else None,
            "pdk": {"root": "<host $PDK_ROOT>", "variant": pdk.variant, "installed_commit": pdk.installed_commit, "pinned_commit": pin["open_pdks_commit"], "matches_pin": pdk.matches_pin,
                    "lib_file": MODEL_LIB + " (resolved on the runner as /opt/pdk/sky130A/...)", "fleet_pdk_report": fleet_pdk},
            "tools": {"ngspice": f"{cr.first_line(['ngspice', '-v'])} (host; the grid ran on the fleet)", "xschem": cr.first_line(["xschem", "--version"]),
                      "platform": cr.tool_versions()["platform"], "python": cr.tool_versions()["python"], "klt_client": meta.get("klt_client"),
                      "fleet_runner_klt": ", ".join(runners) or "unknown", "fleet_ngspice": ", ".join(ngs) or "unknown",
                      "fleet_note": "client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used",
                      "xschem_note": "only the testbench is netlisted by xschem here; the DUT is spliced from the committed design/netlist/temp_por_top.spice (host xschem leaves expr() parameters unevaluated)"},
            "git": gi, "run_source": meta.get("source", {}), "deck_drift": drift, "run_meta": {k: meta.get(k) for k in ("run_id", "started_utc", "submitted_tags", "retries")},
            "matrix": {"process": man["corners"]["process"], "temperature_c": man["corners"]["temperature_c"], "supply_v": man["corners"]["supply_v"],
                       "n_requests": cnt["requests"], "points_per_request": cnt["points_per_request"], "n_points": cnt["points"],
                       "n_requests_submitted": sum(1 for q in requests if q.get("job_id")), "n_points_graded": n_graded, "n_points_not_covered": cnt["points"] - n_graded,
                       "is_subset": n_graded != cnt["points"], "subset_reason": None if n_graded == cnt["points"] else "see NOT_COVERED rows and submit failures"},
            "definitions": {"levels": ph["levels"], "assertion": ph["assertion"], "detectability": ph["detectability"], "expectation": ph["expectation"], "baseline": ph["baseline"],
                            "recovery": ph["recovery"], "delivered bias": ph["delivered_bias"], "resolution": ph["resolution"], "physicality": ph["physicality"],
                            "verdicts": ph["verdicts"], "deck attribution": ph["deck_attribution"], "stimulus": man["stimulus"]["construction"],
                            "observation": man["stimulus"]["observation_rationale"], "grid": man["grid"][cls]["rationale"], "expansion policy": man["grid"]["expansion_policy"],
                            "trace storage": ph["trace_storage"]},
            "requests": requests, "points": points, "summary": summarize(points), "submit_failures": fails,
            "absent_coverage": absent(man, cls), "follow_on": Path(args.notes_file).read_text().strip() if args.notes_file else "",
            "links": {"testbench": "sim/glitch-top/testbench/tb_temp_por_glitch.sch", "manifest": "sim/glitch-top/experiment.json",
                      "driver": "sim/glitch-top/run_glitch_campaign.py", "checker": "sim/glitch-top/glitch_checker.py",
                      "netlist_snapshots": f"sim/glitch-top/netlist-snapshots/{record_id}/" if snap_dir.is_dir() else None,
                      "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)) if art_manifest else None, "artifact_summary": str(art_summary.relative_to(REPO_ROOT)) if art_summary else None,
                      "json": f"sim/glitch-top/records/{record_id}.json", "record": f"sim/glitch-top/records/{record_id}.md"},
        }
        rec_dir.mkdir(parents=True, exist_ok=True)
        (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
        (rec_dir / f"{record_id}.md").write_text(render_md(record))
        wrote.append(record_id)
        print(f"record {record_id}: {n_graded}/{cnt['points']} graded; totals {record['summary']['total']}")
    return 0


# --------------------------------------------------------------------------
# selftest record
# --------------------------------------------------------------------------


def cmd_selftest(args) -> int:
    gi = source_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{gi['sha']}-checker-selftest"
    rec_dir = HERE / "records"
    rec_dir.mkdir(exist_ok=True)
    for ext in (".md", ".json"):
        if (rec_dir / f"{record_id}{ext}").exists():
            raise SystemExit("record exists -- append-only")
    results = gc.run_selftest(HERE / "selftest")
    ok = all(r["ok"] for r in results)
    doc = {"record_id": record_id, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
           "kind": "glitch checker self-test (synthetic behavioural stand-ins, no simulation)", "git": gi, "cases": results, "overall_pass": ok}
    (rec_dir / f"{record_id}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    L = [f"# Record {record_id}", "", f"- **Record ID**: {record_id}", "- **Experiment**: `glitch-top` -- checker self-test",
         "- **Claim**: proves `glitch_checker.py` produces PASS / FAIL / ERROR / NONPHYSICAL / UNRESOLVED with the intended precedence for both glitch classes on controlled synthetic waveforms with known answers (clean cases and controls PASS, so the checker is not vacuous). No simulation is involved.",
         f"- **Repo state**: `{gi['sha']}` on `{gi['branch']}`" + (" (working tree dirty at run time)" if gi["dirty"] else " (clean working tree)"),
         "", "| case | class | expected | got | failure codes | ok |", "|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['case']} | {r['class']} | {r['expected_verdict']} | {r['verdict']} | {', '.join(r['fail_codes']) or '-'} | {'yes' if r['ok'] else 'NO'} |")
    L += ["", f"**Overall: {'PASS' if ok else 'FAIL'}**", "", f"- **Timestamp / author**: {doc['timestamp']}, {doc['author']}", f"- **Supersedes**: {args.supersedes or '(none)'}", "",
          "Written by `sim/glitch-top/run_glitch_campaign.py selftest`. Append-only.", ""]
    (rec_dir / f"{record_id}.md").write_text("\n".join(L))
    print(f"selftest record {record_id}: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("plan")
    r = sub.add_parser("run")
    r.add_argument("--jobs", type=int, default=2, help="concurrent fleet submissions (max 2)")
    r.add_argument("--run-id")
    r.add_argument("--only", action="append", help="submit only this declared request tag (repeatable); the rest stay NOT_COVERED")
    r.add_argument("--only-class", choices=CLASSES)
    r.add_argument("--retry-failed", action="store_true")
    r.add_argument("--capacity-wait", type=float, default=0)
    r.add_argument("--allow-dirty", action="store_true")
    x = sub.add_parser("probe")
    x.add_argument("--tag", required=True)
    x.add_argument("--tstop", type=float, help="shortened stop time (s) for a quick channel-name validation; such a probe is never graded")
    c = sub.add_parser("record")
    c.add_argument("--run-id", required=True)
    c.add_argument("--notes-file")
    c.add_argument("--author")
    c.add_argument("--supersedes")
    c.add_argument("--allow-dirty", action="store_true")
    c.add_argument("--allow-deck-drift", action="store_true")
    s = sub.add_parser("selftest")
    s.add_argument("--author")
    s.add_argument("--supersedes")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "run": cmd_run, "probe": cmd_probe, "record": cmd_record, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
