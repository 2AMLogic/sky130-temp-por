#!/usr/bin/env python3
"""Driver for the assembled temp_por_top brown-out campaign (issue #116).

Each dip point (floor x hold x falling slew x recovery slew, plus the no-dip
control) is ONE ``klt sim`` request whose corner axes are process x supply x
temperature (45 points); the request goes to the Spot batch fleet.  This script
never launches ngspice over the grid.

Subcommands
  plan       print the declared request/point counts (no simulation).
  run        build netlists + requests and submit to the fleet (``--backend
             batch``).  Refuses a dirty tree or an unpushed source SHA unless
             ``--allow-dirty``; the state is recorded either way.  A submit
             failure is kept as evidence -- there is NO local fallback.
  probe      ONE single-corner LOCAL request (``--backend local``): netlist /
             channel-name validation only, never a grid.
  record     grade every retrieved waveform with brownout_checker.py and write
             the append-only evidence: exact input decks, requests, per-point
             logs, event-preserving traces, markdown + JSON record twins.
             Unsubmitted / refused / missing points are listed as NOT_COVERED.
  selftest   run the checker's synthetic cases and write a self-test record.

Append-only: ``record`` and ``selftest`` refuse to overwrite any existing path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import functools
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(HERE))

import brownout_checker as bc  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()

SLUG = "brownout-top"
MANIFEST = HERE / "experiment.json"
TB_SCH = HERE / "testbench" / "tb_temp_por_brownout.sch"
DUT_NETLIST = REPO_ROOT / "design" / "netlist" / "temp_por_top.spice"
BUILD = REPO_ROOT / "sim" / "build" / SLUG
MODEL_LIB = "libs.tech/combined/sky130.lib.spice"

say = sim_common.say
scrub = functools.partial(sim_common.scrub, repo_root=REPO_ROOT)


def corner_id(proc: str, temp: float, vf: float) -> str:
    return f"{proc}_{cr.fmt_temp(temp)}c_{vf:.2f}v"


def corners_of(man: dict) -> list[tuple[str, float, float]]:
    c = man["corners"]
    return [(p, t, v) for p in c["process"] for t in c["temperature_c"] for v in c["supply_v"]]


# --------------------------------------------------------------------------
# the declared matrix
# --------------------------------------------------------------------------


def _g(x: float) -> str:
    return f"{x:g}".replace("+", "").replace("-", "m")


def plan_requests(man: dict) -> list[dict]:
    """The declared dip points.  Axes are independent: every value is a separate parameter."""
    g, s = man["grid"], man["stimulus"]
    base = {"rup": s["power_up_rate_v_per_s"], "t0": s["t0_s"]}
    out = []

    def add(kind, vlow, th, sf, sr):
        tag = "control" if kind == "control" else f"{kind}_v{_g(vlow)}_h{_g(th)}_f{_g(sf)}_r{_g(sr)}"
        out.append({"tag": tag, "kind": kind, **base, "vlow": vlow, "th": th, "sf": sf, "sr": sr})

    for vlow in g["floors_v"]:
        for th in g["holds_s"]:
            for sf in g["fall_slews_v_per_s"]:
                add("cube", vlow, th, sf, g["recovery_slew_default_v_per_s"])
    c = g["recovery_variant_center"]
    for sr in g["recovery_variants_v_per_s"]:
        add("recovery", c["vlow"], c["th"], c["sf"], sr)
    ref = out[0]
    add("control", 99.0, ref["th"], ref["sf"], g["recovery_slew_default_v_per_s"])
    tags = [r["tag"] for r in out]
    if len(set(tags)) != len(tags):
        raise SystemExit("request tag collision in the declared matrix")
    return out


def declared_counts(man: dict) -> dict:
    reqs = plan_requests(man)
    n_corner = len(corners_of(man))
    return {"requests": len(reqs), "points_per_request": n_corner, "points": len(reqs) * n_corner}


def stim_of(req: dict) -> dict:
    return {k: req[k] for k in ("rup", "t0", "vlow", "th", "sf", "sr")}


def tstop_of(req: dict, man: dict) -> float:
    vmax = max(man["corners"]["supply_v"])
    return bc.tstop_for(vmax, stim_of(req), man["stimulus"]["observation_after_recovery_s"])


def tmax_of(req: dict, man: dict) -> float:
    return bc.tmax_for(stim_of(req), min(man["corners"]["supply_v"]))


# --------------------------------------------------------------------------
# netlists and requests
# --------------------------------------------------------------------------


def tb_netlist_head(run_dir: Path, pdk) -> str:
    """Netlist the testbench with xschem; keep only the testbench part (DUT comes from the committed export)."""
    produced = cr.netlist_with_xschem(TB_SCH, run_dir / "tb", pdk)
    text = produced.read_text().replace(str(REPO_ROOT) + os.sep, "")
    head = text.split("\n* expanding")[0]
    return "\n".join(ln for ln in head.splitlines() if ln.strip().lower() != ".end") + "\n"


def build_netlist(head: str, req: dict) -> str:
    dut = DUT_NETLIST.read_text()
    dut = "\n".join(ln for ln in dut.splitlines() if ln.strip().lower() != ".end") + "\n"
    banner = (
        f"* {SLUG}: generated by sim/brownout-top/run_brownout_campaign.py -- do not edit\n"
        f"* request {req['tag']} ({req['kind']}): unchanged committed design/netlist/temp_por_top.spice, PTAT/CTAT open\n"
        f".param rup={req['rup']:g} t0={req['t0']:g} vlow={req['vlow']:g} th={req['th']:g} sf={req['sf']:g} sr={req['sr']:g}\n"
        "* ng_nomodcheck: same setting as sim/spiceinit; carried in the netlist because the fleet runner\n"
        "* ignores options.ngspice_init (see experiment.json fleet.ngspice_note)\n"
        ".control\nset ng_nomodcheck\n.endc\n"
    )
    return banner + head + "\n" + dut


def build_request(req: dict, man: dict, backend: str, capacity_wait_s: float = 0) -> dict:
    tstop, tmax = tstop_of(req, man), tmax_of(req, man)
    c = man["corners"]
    r = {
        "netlist": "netlist.spice",
        "backend": backend,
        "models": {"pdk": "sky130A", "lib": MODEL_LIB},
        "corners": {"process": c["process"], "supply_v": {"vset": c["supply_v"]}, "temperature_c": c["temperature_c"]},
        "analysis": {"kind": "tran", "args": f"{min(1e-6, tmax):.3g} {tstop:.9g} 0 {tmax:.3g}"},
        "measurements": [
            {"name": "vdd_min", "spice": ".meas tran vdd_min MIN v(vdd)", "unit": "V"},
            {"name": "resetn_end", "spice": f".meas tran resetn_end FIND v(resetn) AT={(tstop - 0.1e-3):.9g}", "unit": "V"},
            {"name": "resetn_min_after_t0", "spice": f".meas tran resetn_min_after_t0 MIN v(resetn) FROM={req['t0']:g} TO={tstop:.9g}", "unit": "V"},
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
    d.mkdir(parents=True, exist_ok=True)
    if (d / "report.json").is_file():
        n = 1
        while (d / f"attempt{n}").exists():
            n += 1
        (d / f"attempt{n}").mkdir()
        for name in ("report.json", "klt.stderr"):
            if (d / name).is_file():
                shutil.move(str(d / name), str(d / f"attempt{n}" / name))
    (d / "netlist.spice").write_text(build_netlist(head, req))
    (d / "request.json").write_text(json.dumps(build_request(req, man, "batch", capacity_wait_s), indent=2) + "\n")
    say(f"[submit] {req['tag']}: {declared_counts(man)['points_per_request']} points -> batch fleet")
    p = subprocess.run(["klt", "sim", str(d / "request.json"), "--backend", "batch", "-o", str(d / "out"), "--format", "json"],
                       capture_output=True, text=True, timeout=4 * 3600)
    (d / "report.json").write_text(p.stdout)
    (d / "klt.stderr").write_text(p.stderr)
    try:
        status = json.loads(p.stdout).get("status", "?")
    except json.JSONDecodeError:
        status = "NO-JSON"
    say(f"[done]   {req['tag']}: exit {p.returncode}, report status {status}")
    return {"tag": req["tag"], "exit": p.returncode, "status": status}


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def source_state() -> dict:
    g = cr.git_state()
    sha_full = cr.git("rev-parse", "HEAD")
    contains = cr.git("branch", "-r", "--contains", sha_full) if sha_full else ""
    g.update({"sha_full": sha_full, "pushed_to_remote": bool(contains.strip()), "remote_branches": [b.strip() for b in contains.splitlines()][:5]})
    return g


def cmd_plan(args) -> int:
    man = sim_common.load_manifest(MANIFEST)
    cnt = declared_counts(man)
    reqs = plan_requests(man)
    print(f"declared: {cnt['requests']} requests x {cnt['points_per_request']} PVT points = {cnt['points']} points")
    for r in reqs:
        print(f"  {r['tag']:<34} tstop {tstop_of(r, man) * 1e3:7.3f} ms  tmax {tmax_of(r, man) * 1e6:7.3f} us")
    return 0


def cmd_run(args) -> int:
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
    reqs = plan_requests(man)
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, args.jobs)) as ex:
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
    if args.tstop:  # channel/netlist validation only: a truncated record is never graded or recorded
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


def classify_error(corner: dict, log_text: str) -> str:
    if "could not find a valid modelname" in log_text:
        return "model_not_found"
    codes = [d.get("code") for d in corner.get("diagnostics", [])]
    if any(c and "timeout" in c for c in codes):
        return "timeout"
    return ("error:" + ",".join(sorted({c for c in codes if c}))) if codes else "error"


def point_log(corner: dict, header: list[str], run_dir: Path) -> str:
    art = corner.get("artifacts") or {}
    deck = Path(art["deck"]).read_text() if art.get("deck") and Path(art["deck"]).is_file() else "(no deck retrieved)"
    log = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else "(no ngspice log retrieved)"
    lines = list(header) + [""]
    lines += ["# ==== klt sim deck (exact input given to ngspice on the runner) ====", *[f"| {ln}" for ln in deck.splitlines()], ""]
    lines += ["# ==== klt diagnostics ====", *[f"| {dg.get('severity')}/{dg.get('code')}: {dg.get('message')}" for dg in corner.get("diagnostics", [])], ""]
    lines += ["# ==== ngspice stdout+stderr ====", log.rstrip(), ""]
    return scrub("\n".join(lines), run_dir)


def analyze_request(req: dict, run_dir: Path, man: dict, corners_dir: Path, write: bool) -> dict:
    """All 45 declared points of one request.  Every declared point appears, covered or not."""
    d = run_dir / req["tag"]
    st = stim_of(req)
    declared = corners_of(man)
    info = {"tag": req["tag"], "kind": req["kind"], "stimulus": st, "tstop_s": tstop_of(req, man), "tmax_s": tmax_of(req, man)}
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
            pts.append({"id": corner_id(p, t, v), "tag": req["tag"], "process": p, "temperature_c": t, "supply_v": v, "outcome": "NOT_COVERED", "reason": why})
        return {"info": info, "points": pts, "pdk_report": {}}
    remote = (rep.get("environment") or {}).get("remote") or {}
    info.update({"outcome": rep.get("status"), "job_id": remote.get("job_id"), "instance_type": remote.get("instance_type"), "lifecycle": remote.get("lifecycle"),
                 "runner_klt_version": remote.get("runner_klt_version"), "client_klt_version": remote.get("client_klt_version"),
                 "elapsed_seconds": remote.get("elapsed_seconds"), "state": remote.get("state"), "corner_count": rep.get("corner_count")})
    seen = set()
    for c in rep.get("corners", []):
        proc, vf, temp = c["process"], c["supply_v"]["vset"], c["temperature_c"]
        cid = corner_id(proc, temp, vf)
        seen.add(cid)
        art = c.get("artifacts") or {}
        wave_path = Path(art["waveform"]) if art.get("waveform") else None
        log_text = Path(art["log"]).read_text() if art.get("log") and Path(art["log"]).is_file() else ""
        ngv = re.findall(r"(ngspice-\d+) done", log_text)
        pt = {"id": cid, "tag": req["tag"], "process": proc, "temperature_c": temp, "supply_v": vf, "klt_status": c.get("status"), "runtime_s": c.get("runtime_s"),
              "ngspice": ngv[0] if ngv else None, "measurements": {m["name"]: m.get("value") for m in c.get("measurements", [])},
              "diagnostics": [{"severity": dg.get("severity"), "code": dg.get("code"), "message": scrub(dg.get("message", ""), run_dir)[:400]} for dg in c.get("diagnostics", [])]}
        wave, load_err = None, None
        if wave_path is not None and wave_path.is_file():
            try:
                wave = sim_common.load_wave(wave_path)
            except Exception as err:  # noqa: BLE001
                load_err = f"waveform unreadable: {err!r}"
        res = bc.analyze(wave, vf, st, man["stimulus"]["observation_after_recovery_s"])
        if wave is None:
            res["detail"] = load_err or "no waveform artifact for this corner"
            res["error_class"] = classify_error(c, log_text)
        pt["outcome"] = res["verdict"]
        pt["check"] = res
        if wave is not None and res["verdict"] != "ERROR":
            rows = bc.compress(wave)
            stt = bc.transitions_from_stored(rows, vf, st["t0"])
            pt["stored_trace"] = {"rows": len(rows), "full_samples": len(wave["time"]), "n_assert": stt["n_assert"], "n_release": stt["n_release"],
                                  "agrees_with_full_resolution": stt["n_assert"] == res["resetn"]["n_assert"] and stt["n_release"] == res["resetn"]["n_release_after_t0"]}
            if write:
                bc.write_trace(corners_dir / req["tag"] / f"{cid}.trace.csv.gz", rows)
        if write:
            header = [f"# point: {SLUG} {req['tag']} {cid}",
                      f"# process={proc} temp={cr.fmt_temp(temp)}C start_supply={vf:.2f}V vlow={st['vlow']:g} hold={st['th']:g}s fall={st['sf']:g}V/s recovery={st['sr']:g}V/s tstop={tstop_of(req, man):.6g}s",
                      f"# klt status: {c.get('status')}   runtime on runner: {c.get('runtime_s')} s   outcome: {pt['outcome']}"]
            (corners_dir / req["tag"]).mkdir(parents=True, exist_ok=True)
            (corners_dir / req["tag"] / f"{cid}.log").write_text(point_log(c, header, run_dir))
        pts.append(pt)
    for p, t, v in declared:
        cid = corner_id(p, t, v)
        if cid not in seen:
            pts.append({"id": cid, "tag": req["tag"], "process": p, "temperature_c": t, "supply_v": v, "outcome": "NOT_COVERED", "reason": "corner absent from an otherwise returned report"})
    return {"info": info, "points": pts, "pdk_report": (rep.get("provenance") or {}).get("pdk", {})}


OUTCOMES = ("PASS", "FAIL", "ERROR", "NONPHYSICAL", "UNRESOLVED", "NOT_COVERED")


def summarize(points: list[dict]) -> dict:
    by_req: dict = {}
    for p in points:
        s = by_req.setdefault(p["tag"], {o: 0 for o in OUTCOMES})
        s[p["outcome"]] += 1
    total = {o: sum(s[o] for s in by_req.values()) for o in OUTCOMES}
    codes: dict = {}
    for p in points:
        for c in (p.get("check") or {}).get("fail_codes", []):
            codes[c] = codes.get(c, 0) + 1
    return {"by_request": by_req, "total": total, "fail_codes": codes}


def fmt(x, spec=".4g"):
    return "n/a" if x is None else f"{x:{spec}}"


def render_md(rec: dict) -> str:
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], rec["experiment"]["slug"], rec["experiment"]["title"])
    L.append(f"- **Claim**: {rec['experiment']['claim']}")
    L.append(f"- **Netlist provenance**: {rec['experiment']['provenance']} (`{rec['experiment']['provenance_source']}`)")
    L += sim_common.render_pdk_tools_repo_state(rec)
    t, g = rec["tools"], rec["git"]
    L.append(f"- **Source commit**: `{g['sha_full']}` (pushed to a remote branch: {g['pushed_to_remote']}; dirty at submit: {rec['run_source']['dirty']})")
    L.append(f"- **Fleet runner**: klt `{t['fleet_runner_klt']}` / `{t['fleet_ngspice']}` (client klt `{t['klt_client']}`); {t['fleet_note']}")
    L.append(f"- **Host tool caveat**: {t['xschem_note']}")
    m = rec["matrix"]
    L.append("- **Corner matrix**: process " + ", ".join(m["process"]) + "; temperature " + ", ".join(f"{cr.fmt_temp(x)} C" for x in m["temperature_c"]) + "; starting supply " + ", ".join(f"{v:.2f} V" for v in m["supply_v"]))
    L.append(f"- **Declared**: {m['n_requests']} request(s) x {m['points_per_request']} = {m['n_points']} points; {m['n_requests_submitted']} request(s) with a usable report; {m['n_points_graded']} points graded, {m['n_points_not_covered']} NOT_COVERED (never counted as covered).")
    L.append("- **Statistical convention**: N/A (corner-matrix check)")
    L.append("- **PTAT/CTAT loading**: open (no output buffer exists); RESETn unloaded; no ideal bias/sensor substitution; committed XMN1 L=20 W=0.42, no diagnostic edits.")
    L.append("")
    L.append("## Measurement definitions (exploratory; none is a ratified bound)")
    for k, v in rec["definitions"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    s = rec["summary"]
    L.append("## Outcome totals")
    L.append("| " + " | ".join(OUTCOMES) + " |")
    L.append("|" + "---|" * len(OUTCOMES))
    L.append("| " + " | ".join(str(s["total"][o]) for o in OUTCOMES) + " |")
    L.append(f"\nFailure codes (graded points): {s['fail_codes'] or 'none'}")
    L.append("")
    L.append("## Per-request fleet submissions and outcome counts")
    L.append("| request | kind | floor V | hold | fall V/s | recov V/s | tstop ms | tmax us | fleet outcome | job id | " + " | ".join(OUTCOMES) + " |")
    L.append("|" + "---|" * (10 + len(OUTCOMES)))
    for r in rec["requests"]:
        st, c = r["stimulus"], s["by_request"][r["tag"]]
        L.append(f"| {r['tag']} | {r['kind']} | {st['vlow']:g} | {st['th']:g} | {st['sf']:g} | {st['sr']:g} | {r['tstop_s'] * 1e3:.4g} | {r['tmax_s'] * 1e6:.3g} | {str(r.get('outcome'))[:60]} | {r.get('job_id')} | " + " | ".join(str(c[o]) for o in OUTCOMES) + " |")
    L.append("")
    L.append("## Per-corner table")
    L.append("Columns: outcome; asserts = RESETn assertions after t0; req = required-to-assert (dwell below V_MUST); VDD@assert; t_assert/t_release (ms, absolute); baseline ok; Ibias delivered baseline / min / end (uA, = +id of XMPIB); IBIAS node baseline / min (V); max sample gap vs required (us); note = failure codes, else unresolved reasons or error class.")
    for r in rec["requests"]:
        pts = [p for p in rec["points"] if p["tag"] == r["tag"]]
        L.append("")
        L.append(f"### {r['tag']}")
        L.append("| point | outcome | asserts | req | VDD@assert (V) | t_assert (ms) | t_release (ms) | baseline | Ibias base/min/end (uA) | IBIAS node base/min (V) | gap/req (us) | note |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for p in pts:
            c = p.get("check")
            if p["outcome"] == "NOT_COVERED":
                L.append(f"| {p['id']} | NOT_COVERED | - | - | - | - | - | - | - | - | - | {p.get('reason', '')[:80]} |")
                continue
            if p["outcome"] == "ERROR":
                L.append(f"| {p['id']} | ERROR | - | - | - | - | - | - | - | - | - | {c.get('error_class', '')} {c.get('detail', '')[:80]} |")
                continue
            rs, db, ibn, rz = c["resetn"], c["delivered_bias"], c["ibias_node"], c["resolution"]
            note = ",".join(c["fail_codes"]) or "; ".join(c["unresolved_reasons"])[:90] or ("NONPHYSICAL: " + ",".join(c["physical"]["violations_after_t0"]) if p["outcome"] == "NONPHYSICAL" else "")
            if p["outcome"] == "NONPHYSICAL" and not note.startswith("NONPHYS"):
                note = "NONPHYSICAL " + note
            u = lambda x: "n/a" if x is None else f"{x * 1e6:.3g}"  # noqa: E731
            ms = lambda x: "n/a" if x is None else f"{x * 1e3:.5g}"  # noqa: E731
            L.append(f"| {p['id']} | {p['outcome']} | {rs['n_assert']} | {'y' if c['detectability']['required_to_assert'] else 'n'} | {fmt(rs['vdd_at_assert_v'], '.3f')}{'*' if rs['assertion_rail_limited'] else ''} | {ms(rs['t_assert_s'])} | {ms(rs['t_release_s'])} | "
                     f"{'ok' if c['baseline']['ok'] else 'UNREADY'} | {u(db['baseline_a'])}/{u(db['min_after_t0_a'])}/{u(db['end_a'])} | {fmt(ibn['baseline_v'], '.3f')}/{fmt(ibn['min_after_t0_v'], '.3f')} | {rz['max_dt_dip_window_s'] * 1e6:.3g}/{rz['required_max_dt_s'] * 1e6:.3g} | {note} |")
    L.append("")
    L.append("`*` = assertion was rail-limited (VDD <= V_IL at the crossing): RESETn could not stay high regardless of the comparator.")
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
        L.append(f"- {k}: `{v}`")
    L.append(f"- **Timestamp / author**: {rec['timestamp']}, {rec['author']}")
    L.append(f"- **Supersedes**: {rec['supersedes'] or '(none)'}")
    L.append("")
    L.append("Written by `sim/brownout-top/run_brownout_campaign.py`. Append-only: never edit this file -- a correction is a new record with a `Supersedes` field (see `sim/README.md`).")
    L.append("")
    return "\n".join(L)


def absent(man: dict) -> list[str]:
    return [
        "The initial dip grid is exploratory and bounded (see experiment.json grid.not_covered); no brown-out envelope is claimed or ratified (DR-003 Sec8). The expansion policy is declared in the manifest.",
        "Recovery slew is varied one-factor-at-a-time around the center point only, not crossed with the full floor x hold x fall cube.",
        "The orthogonal ll/hh passive-skew axis and mismatch Monte Carlo are not exercised; PTAT/CTAT are open; no post-layout parasitics.",
        "temp_core startup artifacts of #86 are not presumed fixed: an affected point shows up as an UNRESOLVED baseline, a NONPHYSICAL node, or an ERROR in the table, not as a PASS.",
        "POR_RAW-referenced and VDD-level GLITCH characterization is the sibling child of #106 and is not exercised here.",
    ]


def cmd_record(args) -> int:
    man = sim_common.load_manifest(MANIFEST)
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    gi = source_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{gi['sha']}"
    rec_dir = HERE / "records"
    corners_dir = HERE / "corners" / record_id
    snap_dir = HERE / "netlist-snapshots" / record_id
    for pth in (rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir):
        if pth.exists():
            raise SystemExit(f"{pth} exists -- sim/ is append-only")
    reqs = plan_requests(man)
    points, requests, fleet_pdk = [], [], {}
    for r in reqs:
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
    snap_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "run.json").is_file():
        shutil.copyfile(run_dir / "run.json", snap_dir / "run.json")
    fails = [{"tag": q["tag"], "reason": q["outcome"]} for q in requests if q.get("job_id") is None and q.get("outcome") and q["outcome"] not in ("ok", "OK", "PASS")]
    ngs = sorted({p["ngspice"] for p in points if p.get("ngspice")})
    runners = sorted({q.get("runner_klt_version") for q in requests if q.get("runner_klt_version")})
    cnt = declared_counts(man)
    n_graded = sum(1 for p in points if p["outcome"] != "NOT_COVERED")
    ph = man["grading"]
    record = {
        "record_id": record_id, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
        "experiment": {k: man[k] for k in ("slug", "title", "claim", "provenance", "provenance_source", "statistical_convention")},
        "pdk": {"root": "<host $PDK_ROOT>", "variant": pdk.variant, "installed_commit": pdk.installed_commit, "pinned_commit": pin["open_pdks_commit"], "matches_pin": pdk.matches_pin,
                "lib_file": MODEL_LIB + " (resolved on the runner as /opt/pdk/sky130A/...)", "fleet_pdk_report": fleet_pdk},
        "tools": {"ngspice": f"{cr.first_line(['ngspice', '-v'])} (host; the grid ran on the fleet)", "xschem": cr.first_line(["xschem", "--version"]),
                  "platform": cr.tool_versions()["platform"], "python": cr.tool_versions()["python"], "klt_client": meta.get("klt_client"),
                  "fleet_runner_klt": ", ".join(runners) or "unknown", "fleet_ngspice": ", ".join(ngs) or "unknown",
                  "fleet_note": "client/runner klt skew accepted with batch.runner_version_check=warn; the runner ignores options.ngspice_init so a netlist-carried `set ng_nomodcheck` is used",
                  "xschem_note": "only the testbench is netlisted by xschem here; the DUT is spliced from the committed design/netlist/temp_por_top.spice (host xschem leaves expr() parameters unevaluated)"},
        "git": gi, "run_source": meta.get("source", {}),
        "matrix": {"process": man["corners"]["process"], "temperature_c": man["corners"]["temperature_c"], "supply_v": man["corners"]["supply_v"],
                   "n_requests": cnt["requests"], "points_per_request": cnt["points_per_request"], "n_points": cnt["points"],
                   "n_requests_submitted": sum(1 for q in requests if q.get("job_id")), "n_points_graded": n_graded, "n_points_not_covered": cnt["points"] - n_graded,
                   "is_subset": n_graded != cnt["points"], "subset_reason": None if n_graded == cnt["points"] else "see NOT_COVERED rows and submit failures"},
        "definitions": {"levels": ph["levels"], "assertion": ph["assertion"], "detectability": ph["detectability"], "baseline": ph["baseline"], "recovery": ph["recovery"],
                        "delivered bias": ph["delivered_bias"], "resolution": ph["resolution"], "physicality": ph["physicality"], "verdicts": ph["verdicts"],
                        "stimulus": man["stimulus"]["construction"], "observation": man["stimulus"]["observation_rationale"], "grid": man["grid"]["rationale"],
                        "expansion policy": man["grid"]["expansion_policy"], "trace storage": ph["trace_storage"]},
        "requests": requests, "points": points, "summary": summarize(points), "submit_failures": fails,
        "absent_coverage": absent(man), "follow_on": Path(args.notes_file).read_text().strip() if args.notes_file else "",
        "links": {"testbench": "sim/brownout-top/testbench/tb_temp_por_brownout.sch", "manifest": "sim/brownout-top/experiment.json",
                  "driver": "sim/brownout-top/run_brownout_campaign.py", "checker": "sim/brownout-top/brownout_checker.py",
                  "netlist_snapshots": f"sim/brownout-top/netlist-snapshots/{record_id}/", "corners_dir": f"sim/brownout-top/corners/{record_id}/",
                  "json": f"sim/brownout-top/records/{record_id}.json", "record": f"sim/brownout-top/records/{record_id}.md"},
    }
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
    (rec_dir / f"{record_id}.md").write_text(render_md(record))
    print(f"record {record_id}: {n_graded}/{cnt['points']} graded; totals {record['summary']['total']}")
    return 0


# --------------------------------------------------------------------------
# selftest
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
    results = bc.run_selftest(HERE / "selftest")
    ok = all(r["ok"] for r in results)
    doc = {"record_id": record_id, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
           "kind": "brown-out checker self-test (synthetic behavioural stand-ins, no simulation)", "git": gi, "cases": results, "overall_pass": ok}
    (rec_dir / f"{record_id}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n")
    L = [f"# Record {record_id}", "", f"- **Record ID**: {record_id}", "- **Experiment**: `brownout-top` -- checker self-test",
         "- **Claim**: proves `brownout_checker.py` produces PASS / FAIL / ERROR / NONPHYSICAL / UNRESOLVED with the intended precedence on controlled synthetic waveforms with known answers (a clean recovery and a no-dip control PASS, so the checker is not vacuous). No simulation is involved.",
         f"- **Repo state**: `{gi['sha']}` on `{gi['branch']}`" + (" (working tree dirty at run time)" if gi["dirty"] else " (clean working tree)"),
         "", "| case | expected | got | failure codes | ok |", "|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {r['case']} | {r['expected_verdict']} | {r['verdict']} | {', '.join(r['fail_codes']) or '-'} | {'yes' if r['ok'] else 'NO'} |")
    L += ["", f"**Overall: {'PASS' if ok else 'FAIL'}**", "", f"- **Timestamp / author**: {doc['timestamp']}, {doc['author']}", f"- **Supersedes**: {args.supersedes or '(none)'}", "",
          "Written by `sim/brownout-top/run_brownout_campaign.py selftest`. Append-only.", ""]
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
    s = sub.add_parser("selftest")
    s.add_argument("--author")
    s.add_argument("--supersedes")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "run": cmd_run, "probe": cmd_probe, "record": cmd_record, "selftest": cmd_selftest}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
