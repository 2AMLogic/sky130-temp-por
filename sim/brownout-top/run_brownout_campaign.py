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
  cost       (issue #153) project the tightened-solver rerun's per-job fleet time
             from pilot reports already in a run directory; no submission.

Solver variants (issue #153): ``run/probe/record --variant <key>`` select a
variant declared in experiment.json ``solver_variants``; only the declared
extra ``.options`` are appended to the testbench's options line.  A tightened
run is restricted to ``tightened_rerun.rerun_tags`` and its record carries a
per-point default-vs-tightened comparison against the source record.

Append-only: ``record`` and ``selftest`` refuse to overwrite any existing path.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import functools
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SIM_DIR = HERE.parent
REPO_ROOT = SIM_DIR.parent
sys.path.insert(0, str(SIM_DIR / "bin"))
sys.path.insert(0, str(HERE))

import brownout_checker as bc  # noqa: E402
import evidence_store  # noqa: E402
import sim_common  # noqa: E402

cr = sim_common.load_corner_run()

SLUG = "brownout-top"
MANIFEST = HERE / "experiment.json"
TB_SCH = HERE / "testbench" / "tb_temp_por_brownout.sch"
DUT_NETLIST = sim_common.DUT_NETLIST
BUILD = REPO_ROOT / "sim" / "build" / SLUG
MODEL_LIB = sim_common.MODEL_LIB

say = sim_common.say
fmt = sim_common.fmt
corner_id = sim_common.corner_id
scrub = functools.partial(sim_common.scrub, repo_root=REPO_ROOT)


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


# --------------------------------------------------------------------------
# declared solver variants (experiment.json solver_variants)
# --------------------------------------------------------------------------


def variant_of(man: dict, key: str | None) -> dict:
    """Resolve a declared solver variant; an undeclared key is refused (predeclaration is enforced here)."""
    variants = man.get("solver_variants") or {}
    key = key or "default"
    if key not in variants:
        raise SystemExit(f"solver variant '{key}' is not declared in {MANIFEST.name} solver_variants (declared: {sorted(variants)})")
    return {"key": key, **variants[key]}


def selected_rerun_tags(man: dict) -> list[str]:
    """The predeclared tightened-rerun request set (experiment.json tightened_rerun.rerun_tags), validated against the matrix."""
    rr = man.get("tightened_rerun") or {}
    tags = list(rr.get("rerun_tags") or [])
    declared = [r["tag"] for r in plan_requests(man)]
    unknown = [t for t in tags if t not in declared]
    if not tags or unknown or len(set(tags)) != len(tags):
        raise SystemExit(f"tightened_rerun.rerun_tags must be a non-empty, duplicate-free list of declared request tags (unknown: {unknown})")
    return [t for t in declared if t in set(tags)]


def apply_variant(head: str, variant: dict) -> str:
    """Append the declared extra options to the testbench's single declared .options line.  Nothing else may change."""
    extra = list(variant.get("options_extra") or [])
    if not extra:
        return head
    marker = ".options method=gear trtol=50"
    if head.count(marker) != 1:
        raise SystemExit(f"solver variant {variant['key']}: expected exactly one '{marker}' line in the netlisted testbench head")
    return head.replace(marker, marker + " " + " ".join(extra), 1)


def tb_netlist_head(run_dir: Path, pdk) -> str:
    """Netlist the testbench with xschem; keep only the testbench part (DUT comes from the committed export)."""
    return sim_common.netlist_tb_head(TB_SCH, run_dir / "tb", pdk)


def build_netlist(head: str, req: dict, man: dict | None = None, variant_key: str | None = None) -> str:
    dut = sim_common.load_dut_netlist(DUT_NETLIST)
    banner = (
        f"* {SLUG}: generated by sim/brownout-top/run_brownout_campaign.py -- do not edit\n"
        f"* request {req['tag']} ({req['kind']}): unchanged committed design/netlist/temp_por_top.spice, PTAT/CTAT open\n"
        f".param rup={req['rup']:g} t0={req['t0']:g} vlow={req['vlow']:g} th={req['th']:g} sf={req['sf']:g} sr={req['sr']:g}\n"
        "* ng_nomodcheck: same setting as sim/spiceinit; carried in the netlist because the fleet runner\n"
        "* ignores options.ngspice_init (see experiment.json fleet.ngspice_note)\n"
        + sim_common.NOMODCHECK_CONTROL
    )
    if variant_key:
        if man is None:
            raise SystemExit("a solver variant needs the manifest")
        v = variant_of(man, variant_key)
        head = apply_variant(head, v)
        if v["key"] != "default":
            banner += (f"* solver variant {v['key']}: {v.get('label', '')}\n"
                       f"* .options {' '.join(v.get('options_extra') or [])} appended to the declared default line "
                       "(experiment.json solver_variants); circuit, stimulus, windows and checker unchanged\n")
    return banner + head + "\n" + dut


def build_request(req: dict, man: dict, backend: str, capacity_wait_s: float = 0) -> dict:
    tstop, tmax = tstop_of(req, man), tmax_of(req, man)
    c = man["corners"]
    return sim_common.base_request(
        "netlist.spice", backend,
        {"process": c["process"], "supply_v": {"vset": c["supply_v"]}, "temperature_c": c["temperature_c"]},
        {"kind": "tran", "args": f"{min(1e-6, tmax):.3g} {tstop:.9g} 0 {tmax:.3g}"},
        [
            {"name": "vdd_min", "spice": ".meas tran vdd_min MIN v(vdd)", "unit": "V"},
            {"name": "resetn_end", "spice": f".meas tran resetn_end FIND v(resetn) AT={(tstop - 0.1e-3):.9g}", "unit": "V"},
            {"name": "resetn_min_after_t0", "spice": f".meas tran resetn_min_after_t0 MIN v(resetn) FROM={req['t0']:g} TO={tstop:.9g}", "unit": "V"},
        ],
        7200, capacity_wait_s,
    )


CONCURRENCY_CAP_MARKER = "BATCH_MAX_CONCURRENT_INSTANCES"


def concurrency_capped(report_text: str) -> bool:
    """True when klt's error envelope is the shared fleet's concurrent-instance cap refusal.

    klt's capacity_wait_s only waits out Spot capacity refusals, not this cap
    (2AMLogic/klayout-tools#2917), so ``run --slot-wait`` waits for it here.  The refusal
    creates no instance and runs no corner; it is archived as an earlier attempt.
    """
    try:
        body = json.loads(report_text)
    except (json.JSONDecodeError, TypeError):
        return False
    return "corners" not in body and CONCURRENCY_CAP_MARKER in str((body.get("error") or {}).get("message", ""))


def submit_one(req: dict, head: str, man: dict, run_dir: Path, capacity_wait_s: float = 0, variant_key: str | None = None,
               slot_wait_s: float = 0, slot_poll_s: float = 300, _sleep=None, _clock=None) -> dict:
    """Submit one request; on a fleet concurrency-cap refusal, retry every ``slot_poll_s`` until ``slot_wait_s`` is spent.

    Every refused attempt is archived (attemptN/), never overwritten or hidden.
    """
    import time
    sleep, clock = _sleep or time.sleep, _clock or time.monotonic
    start = clock()
    while True:
        res = _submit_once(req, head, man, run_dir, capacity_wait_s, variant_key)
        d = run_dir / req["tag"]
        # klt writes its --format json error envelope to stderr, not stdout: check both
        capped = any(concurrency_capped((d / n).read_text()) for n in ("report.json", "klt.stderr") if (d / n).is_file())
        if not (slot_wait_s > 0 and capped and clock() - start + slot_poll_s <= slot_wait_s):
            return res
        say(f"[wait]   {req['tag']}: fleet concurrency cap reached; resubmitting in {slot_poll_s:.0f} s")
        sleep(slot_poll_s)


def _submit_once(req: dict, head: str, man: dict, run_dir: Path, capacity_wait_s: float = 0, variant_key: str | None = None) -> dict:
    """Write netlist + request and run ``klt sim --backend batch``; an earlier attempt is archived, never overwritten."""
    res = sim_common.submit_prepared(
        run_dir / req["tag"], build_netlist(head, req, man, variant_key), build_request(req, man, "batch", capacity_wait_s),
        f"{req['tag']}: {declared_counts(man)['points_per_request']} points -> batch fleet", req["tag"])
    return {"tag": req["tag"], **res}


# --------------------------------------------------------------------------
# provenance
# --------------------------------------------------------------------------


def file_sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


# Inputs that shape the simulated deck.  If any of them differs between the
# commit the grid was SUBMITTED from and the commit that GRADES it, the record
# would mis-attribute the evidence, so ``record`` refuses.
DECK_INPUTS = ("design/netlist", "sim/brownout-top/testbench", "sim/spiceinit", "sim/pdk.json")


deck_drift = functools.partial(sim_common.deck_drift, REPO_ROOT, DECK_INPUTS)


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
    evidence_store.preflight_or_exit()  # fail closed before anything is submitted
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    gi = source_state()
    if (gi["dirty"] or not gi["pushed_to_remote"]) and not args.allow_dirty:
        raise SystemExit(f"refusing to submit: dirty={gi['dirty']} pushed={gi['pushed_to_remote']} (commit + push first, or --allow-dirty; the state is recorded either way)")
    variant_key = args.variant or "default"
    variant_of(man, variant_key)  # refuse an undeclared variant before anything is submitted
    now = datetime.now(timezone.utc)
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{gi['sha']}"
    run_dir = BUILD / run_id
    meta = None
    if args.retry_failed:
        if not run_dir.exists():
            raise SystemExit(f"{run_dir} does not exist")
        meta = json.loads((run_dir / "run.json").read_text())
        prev = meta.get("solver_variant", "default")
        if prev != variant_key:
            raise SystemExit(f"run {run_id} was submitted with solver variant '{prev}'; refusing to mix variants in one run")
        drift = deck_drift((meta.get("source") or {}).get("sha_full"), gi.get("sha_full"))
        if drift is None or drift:
            raise SystemExit(f"refusing to continue run {run_id}: deck inputs differ from (or cannot be compared with) its first submit commit: {drift}")
    else:
        if run_dir.exists():
            raise SystemExit(f"{run_dir} exists; refusing to reuse a run id")
    reqs = plan_requests(man)
    rerun = man.get("tightened_rerun") or {}
    if variant_key != "default" and rerun.get("variant") == variant_key:
        allowed = set(selected_rerun_tags(man))
        if args.only and set(args.only) - allowed:
            raise SystemExit(f"--only names request(s) outside the predeclared tightened_rerun.rerun_tags: {sorted(set(args.only) - allowed)}")
        reqs = [r for r in reqs if r["tag"] in allowed]
    if args.only:
        reqs = [r for r in reqs if r["tag"] in args.only]
        if not reqs:
            raise SystemExit("--only matched no declared request")
    if not args.retry_failed:
        run_dir.mkdir(parents=True)
    if args.retry_failed:
        reqs = [r for r in reqs if not sim_common.report_usable(run_dir / r["tag"] / "report.json")]
        say(f"retrying {len(reqs)} request(s) without a usable report (variant {variant_key}), capacity_wait_s={args.capacity_wait}")
    head = tb_netlist_head(run_dir / ("retry" if args.retry_failed else "."), pdk)
    if meta is None:
        meta = {"run_id": run_id, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": gi, "klt_client": sim_common.klt_version(),
                "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "declared": declared_counts(man), "solver_variant": variant_key, "capacity_wait_s": args.capacity_wait, "slot_wait_s": args.slot_wait,
                "submitted_tags": [r["tag"] for r in reqs]}
        (run_dir / "run.json").write_text(json.dumps(meta, indent=2) + "\n")
    say(f"run id {run_id}: {len(reqs)} request(s), solver variant {variant_key}")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, args.jobs)) as ex:
        futs = [ex.submit(submit_one, r, head, man, run_dir, args.capacity_wait, variant_key, args.slot_wait, args.slot_poll) for r in reqs]
        for f in futs:
            try:
                results.append(f.result())
            except Exception as err:  # noqa: BLE001 -- recorded, never swallowed
                results.append({"error": repr(err)})
                say(f"[error] submit raised: {err!r}")
    old = json.loads((run_dir / "run.json").read_text()) if args.retry_failed else meta
    if args.retry_failed:
        old.setdefault("retries", []).append({"at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "capacity_wait_s": args.capacity_wait,
                                             "slot_wait_s": args.slot_wait,
                                             "source": gi, "klt_client": sim_common.klt_version(), "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"),
                                             "submitted_tags": [r["tag"] for r in reqs], "results": results})
    else:
        old["submit_results"] = results
    (run_dir / "run.json").write_text(json.dumps(old, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def project_cost(src_rec: dict, pilots: dict, tags: list[str], limit_s: float) -> dict:
    """Project every selected request's tightened fleet elapsed time from pilot jobs.

    ``pilots`` maps tag -> {"elapsed_s", "corner_runtime_sum_s", "timed_out"} measured on the tightened
    deck.  The ratio is taken per pilot against the same request in the source (default-deck) record,
    both on the fleet's whole-job elapsed time and on the summed per-corner runtime; the projection uses
    the LARGEST observed ratio (conservative) and flags any request whose projection exceeds ``limit_s``.
    A pilot that hit the job limit gives only a LOWER bound on its ratio (its corner runtimes are lost),
    so its corner-sum ratio is not used and the whole projection is marked ``lower_bound``.
    """
    src_req = {q["tag"]: q for q in src_rec.get("requests", [])}
    src_sum: dict = {}
    for p in src_rec.get("points", []):
        src_sum[p["tag"]] = src_sum.get(p["tag"], 0.0) + (p.get("runtime_s") or 0.0)
    pil = []
    for tag, m in pilots.items():
        d_el = (src_req.get(tag) or {}).get("elapsed_seconds")
        timed_out = bool(m.get("timed_out"))
        pil.append({"tag": tag, "tightened_elapsed_s": m.get("elapsed_s"), "default_elapsed_s": d_el, "timed_out": timed_out,
                    "elapsed_ratio": (m["elapsed_s"] / d_el) if m.get("elapsed_s") and d_el else None,
                    "tightened_corner_sum_s": m.get("corner_runtime_sum_s"), "default_corner_sum_s": src_sum.get(tag),
                    "corner_sum_ratio": (m["corner_runtime_sum_s"] / src_sum[tag]) if m.get("corner_runtime_sum_s") and src_sum.get(tag) and not timed_out else None})
    ratios = [x for p in pil for x in (p["elapsed_ratio"], p["corner_sum_ratio"]) if x]
    worst = max(ratios) if ratios else None
    proj = []
    for tag in tags:
        d_el = (src_req.get(tag) or {}).get("elapsed_seconds")
        est = d_el * worst if (d_el and worst) else None
        proj.append({"tag": tag, "default_elapsed_s": d_el, "projected_tightened_elapsed_s": est, "pilot": tag in pilots,
                     "over_limit": None if est is None else est > limit_s})
    return {"limit_s": limit_s, "pilots": pil, "worst_ratio": worst, "lower_bound": any(p["timed_out"] for p in pil), "projection": proj,
            "n_over_limit": sum(1 for p in proj if p["over_limit"]), "n_unprojected": sum(1 for p in proj if p["over_limit"] is None)}


def cmd_cost(args) -> int:
    """Pilot-based runtime projection for the tightened rerun (no submission; reads pilot reports of an existing run)."""
    man = sim_common.load_manifest(MANIFEST)
    rr = man.get("tightened_rerun") or {}
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    src_rec = json.loads((REPO_ROOT / rr["source_record"]).read_text())
    pilots = {}
    for tag in selected_rerun_tags(man):
        rp = run_dir / tag / "report.json"
        if not sim_common.report_usable(rp):
            continue
        rep = json.loads(rp.read_text())
        remote = (rep.get("environment") or {}).get("remote") or {}
        timed_out = remote.get("state") == "timeout" or any(dg.get("code") == "batch_job_timeout" for c in rep.get("corners", []) for dg in c.get("diagnostics", []))
        pilots[tag] = {"elapsed_s": remote.get("elapsed_seconds"), "corner_runtime_sum_s": sum((c.get("runtime_s") or 0.0) for c in rep.get("corners", [])),
                       "timed_out": timed_out, "job_id": remote.get("job_id"), "instance_type": remote.get("instance_type"), "state": remote.get("state")}
    if not pilots:
        raise SystemExit(f"no usable pilot report under {run_dir}")
    limit = float(args.limit_s) if args.limit_s else float(rr.get("job_limit_s", 7200))
    res = project_cost(src_rec, pilots, selected_rerun_tags(man), limit)
    res["limit_source"] = f"--limit-s {args.limit_s:g} ({args.limit_note or 'no note given'})" if args.limit_s else "experiment.json tightened_rerun.job_limit_s"
    for p in res["pilots"]:
        p.update({k: pilots[p["tag"]][k] for k in ("job_id", "instance_type", "state")})
    now = datetime.now(timezone.utc)
    res.update({"at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "run_id": args.run_id, "solver_variant": meta.get("solver_variant"), "source_record": rr["source_record"]})
    out = run_dir / f"cost-projection-{now:%Y%m%d-%H%M%S}.json"
    out.write_text(json.dumps(res, indent=2) + "\n")
    for p in res["pilots"]:
        print(f"pilot {p['tag']:<36} job {p['job_id']} ({p['state']}) elapsed {fmt(p['default_elapsed_s'], '.0f')} -> {fmt(p['tightened_elapsed_s'], '.0f')} s "
              f"(x{'>=' if p['timed_out'] else ''}{fmt(p['elapsed_ratio'], '.2f')}); corner-sum x{fmt(p['corner_sum_ratio'], '.2f')}")
    print(f"worst ratio x{'>=' if res['lower_bound'] else ''}{fmt(res['worst_ratio'], '.2f')}{' (LOWER BOUND: a pilot hit the job limit)' if res['lower_bound'] else ''}; limit {res['limit_s']:.0f} s")
    for p in res["projection"]:
        print(f"  {p['tag']:<36} default {fmt(p['default_elapsed_s'], '.0f'):>6} s -> projected {fmt(p['projected_tightened_elapsed_s'], '.0f'):>6} s"
              f"{'  OVER LIMIT' if p['over_limit'] else ''}{'  (pilot)' if p['pilot'] else ''}")
    print(f"{res['n_over_limit']} request(s) projected over the limit; written {out}")
    return 0


def cmd_probe(args) -> int:
    """ONE single-corner local request for netlist/channel validation.  Never a grid."""
    man = sim_common.load_manifest(MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    reqs = {r["tag"]: r for r in plan_requests(man)}
    if args.tag not in reqs:
        raise SystemExit(f"unknown request tag {args.tag}")
    req = reqs[args.tag]
    proc, temp, vf = args.process or "tt", 27.0 if args.temp is None else args.temp, 3.3 if args.supply is None else args.supply
    if (proc, temp, vf) not in corners_of(man):
        raise SystemExit(f"probe corner {proc}/{temp:g}C/{vf:g}V is not in the declared corner matrix")
    d = BUILD / "probe" / f"{args.tag}{'-' + args.variant if args.variant else ''}-{corner_id(proc, temp, vf)}{'-fleeteq' if args.fleet_equivalent else ''}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "netlist.spice").write_text(build_netlist(tb_netlist_head(d, pdk), req, man, args.variant))
    r = build_request(req, man, "local")
    r["corners"] = {"process": [proc], "supply_v": {"vset": [vf]}, "temperature_c": [temp]}
    if args.tstop:  # channel/netlist validation only: a truncated record is never graded or recorded
        r["analysis"]["args"] = f"1e-6 {args.tstop:g} 0 5e-6"
        r["measurements"] = []
    if not args.fleet_equivalent:
        r["options"]["ngspice_init"] = sim_common.spiceinit_lines(SIM_DIR)
    # --fleet-equivalent: no ngspice_init, exactly as the fleet runner executes the deck (it ignores
    # options.ngspice_init, so ngspice falls back to its default SPARSE solver) -- for like-for-like timing
    (d / "request.json").write_text(json.dumps(r, indent=2) + "\n")
    say(f"[probe] one LOCAL corner {corner_id(proc, temp, vf)} for {args.tag} (variant {args.variant or 'default'})")
    p = sim_common.run_local_probe(d)
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


def attempt_message(ad: Path) -> str:
    """One archived attempt's outcome: the report's error/status, else klt's stderr error envelope."""
    for name in ("report.json", "klt.stderr"):
        f = ad / name
        if not f.is_file():
            continue
        try:
            body = json.loads(f.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict) and (body.get("error") or body.get("status")):
            return (body.get("error") or {}).get("message") or ("report status " + str(body.get("status")))
    tail = (ad / "klt.stderr").read_text()[-300:].strip() if (ad / "klt.stderr").is_file() else ""
    return "unparseable report" + (f": {tail}" if tail else "")


def analyze_request(req: dict, run_dir: Path, man: dict, corners_dir: Path, write: bool) -> dict:
    """All 45 declared points of one request.  Every declared point appears, covered or not."""
    d = run_dir / req["tag"]
    st = stim_of(req)
    declared = corners_of(man)
    info = {"tag": req["tag"], "kind": req["kind"], "stimulus": st, "tstop_s": tstop_of(req, man), "tmax_s": tmax_of(req, man)}
    attempts = []
    for ad in sorted(d.glob("attempt*"), key=lambda x: int(x.name[7:]) if x.name[7:].isdigit() else 0):
        attempts.append(scrub(attempt_message(ad), run_dir)[:400])
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
    info["netlist_sha256_submitted"] = file_sha256(d / "netlist.spice")
    info["netlist_sha256_reported"] = (rep.get("environment") or {}).get("netlist_sha256")
    info["netlist_matches_report"] = info["netlist_sha256_submitted"] is not None and info["netlist_sha256_submitted"] == info["netlist_sha256_reported"]
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
              "ngspice": ngv[0] if ngv else None,
              "netlist_klu_announced": True if "Using KLU as Direct Linear Solver" in log_text else (False if log_text else None), "measurements": {m["name"]: m.get("value") for m in c.get("measurements", [])},
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
    nonphys = {"pre-dip node violation": 0, "post-dip node violation": 0, "supply current reversed at end": 0, "supply current reversed at baseline": 0, "NONPHYSICAL total": 0}
    for p in points:
        ph = (p.get("check") or {}).get("physical")
        if p["outcome"] == "NONPHYSICAL" and ph:
            nonphys["NONPHYSICAL total"] += 1
            if ph.get("node_violation_phase") == "pre-dip":
                nonphys["pre-dip node violation"] += 1
            elif ph.get("node_violation_phase") == "post-dip":
                nonphys["post-dip node violation"] += 1
            nonphys["supply current reversed at end"] += bool(ph.get("supply_current_reversed_at_end"))
            nonphys["supply current reversed at baseline"] += bool(ph.get("supply_current_reversed_at_baseline"))
    for p in points:
        for c in (p.get("check") or {}).get("fail_codes", []):
            codes[c] = codes.get(c, 0) + 1
    return {"by_request": by_req, "total": total, "fail_codes": codes, "nonphysical_breakdown": nonphys}


def _cmp_note(p: dict) -> str:
    c = p.get("check") or {}
    if p.get("outcome") == "NOT_COVERED":
        return (p.get("reason") or "")[:90]
    if p.get("outcome") == "ERROR":
        return f"{c.get('error_class', '')} {c.get('detail', '')[:70]}".strip()
    if c.get("fail_codes"):
        return ",".join(c["fail_codes"])
    if c.get("unresolved_reasons"):
        return "; ".join(c["unresolved_reasons"])[:90]
    ph = c.get("physical") or {}
    if p.get("outcome") == "NONPHYSICAL":
        return ("NONPHYSICAL " + (ph.get("node_violation_phase") or "no node violation")
                + (f" [{','.join(sorted(ph.get('violations_after_t0') or []))}]" if ph.get("violations_after_t0") else ""))[:120]
    return ""


def _physical_flag(p: dict):
    """True/False from the checker's physicality block; None when the point was never graded (NOT_COVERED / ERROR)."""
    if p.get("outcome") in ("NOT_COVERED", "ERROR"):
        return None
    return ((p.get("check") or {}).get("physical") or {}).get("ok")


def build_comparison(src_rec: dict, points: list[dict], requests: list[dict] | None = None, variant: dict | None = None,
                     selected_tags: list[str] | None = None) -> dict:
    """Join the source (default-deck) record with this run's tightened points on (request tag, corner id).

    Refuses a broken join in either direction: every declared point must appear exactly once on
    each side, so the comparison accounts for every selected point, including refusals and
    NOT_COVERED rows (kept, never dropped).  ``selected_tags`` is the predeclared rerun set (request
    tags); a point outside it is still listed, with ``selected`` False, so nothing disappears.
    Roles: a source-NONPHYSICAL point is a ``target``, a source-physical point a ``control``.
    """
    src: dict = {}
    for p in src_rec.get("points", []):
        k = (p.get("tag"), p.get("id"))
        if k in src:
            raise SystemExit(f"source record lists {k[0]}/{k[1]} twice -- refusing a broken join")
        src[k] = p
    src_jobs = {q.get("tag"): q for q in src_rec.get("requests", [])}
    new_jobs = {q.get("tag"): q for q in (requests or [])}
    sel = None if selected_tags is None else set(selected_tags)
    rows, missing = [], []
    for p in points:
        s = src.pop((p.get("tag"), p.get("id")), None)
        if s is None:
            missing.append(f"{p.get('tag')}/{p.get('id')}")
            continue
        outcome = p.get("outcome")
        rows.append({"tag": p["tag"], "id": p["id"], "process": p.get("process"), "temperature_c": p.get("temperature_c"), "supply_v": p.get("supply_v"),
                     "role": "target" if s.get("outcome") == "NONPHYSICAL" else "control",
                     "selected": True if sel is None else p["tag"] in sel,
                     "default_outcome": s.get("outcome"), "tightened_outcome": outcome,
                     "default_physical": _physical_flag(s), "tightened_physical": _physical_flag(p),
                     "default_job_id": (src_jobs.get(p["tag"]) or {}).get("job_id"), "tightened_job_id": (new_jobs.get(p["tag"]) or {}).get("job_id"),
                     "default_runtime_s": s.get("runtime_s"), "tightened_runtime_s": p.get("runtime_s"),
                     "default_fail_codes": list((s.get("check") or {}).get("fail_codes") or []),
                     "tightened_fail_codes": list((p.get("check") or {}).get("fail_codes") or []),
                     "default_note": _cmp_note(s), "tightened_note": _cmp_note(p)})
    if missing:
        raise SystemExit(f"rerun point(s) absent from the source record ({len(missing)}, first: {missing[:3]}) -- refusing a broken join")
    if src:
        first = [f"{k[0]}/{k[1]}" for k in list(src)[:3]]
        raise SystemExit(f"source point(s) with no rerun row ({len(src)}, first: {first}) -- the rerun set must cover every selected point")
    matrix: dict = {}
    for r in rows:
        matrix.setdefault(r["default_outcome"], {}).setdefault(r["tightened_outcome"], 0)
        matrix[r["default_outcome"]][r["tightened_outcome"]] += 1
    targets = [r for r in rows if r["role"] == "target"]
    controls = [r for r in rows if r["role"] == "control"]
    # an uncovered or ERROR control (no waveform: never graded) is not a changed verdict: it is counted
    # separately, never as agreement either
    changed = [r for r in controls if r["tightened_outcome"] not in (r["default_outcome"], "NOT_COVERED", "ERROR")]
    ctl_uncovered = sum(1 for r in controls if r["tightened_outcome"] == "NOT_COVERED")
    ctl_error = sum(1 for r in controls if r["tightened_outcome"] == "ERROR")
    tgt: dict = {}
    for r in targets:
        tgt[r["tightened_outcome"]] = tgt.get(r["tightened_outcome"], 0) + 1
    ratios = sorted(r["tightened_runtime_s"] / r["default_runtime_s"] for r in rows
                    if r.get("default_runtime_s") and r.get("tightened_runtime_s"))
    runtime = {"n": len(ratios), "median_ratio": ratios[len(ratios) // 2] if ratios else None,
               "min_ratio": ratios[0] if ratios else None, "max_ratio": ratios[-1] if ratios else None}
    req_rows = []
    for tag in dict.fromkeys(r["tag"] for r in rows):
        sq, nq = src_jobs.get(tag) or {}, new_jobs.get(tag) or {}
        mine = [r for r in rows if r["tag"] == tag]
        req_rows.append({"tag": tag, "selected": mine[0]["selected"], "n_points": len(mine),
                         "n_targets": sum(r["role"] == "target" for r in mine), "n_controls": sum(r["role"] == "control" for r in mine),
                         "default_job_id": sq.get("job_id"), "default_elapsed_s": sq.get("elapsed_seconds"),
                         "tightened_job_id": nq.get("job_id"), "tightened_elapsed_s": nq.get("elapsed_seconds"),
                         "tightened_fleet_outcome": nq.get("outcome"), "tightened_earlier_attempts": nq.get("failed_earlier_attempts") or [],
                         "tightened_not_covered": sum(r["tightened_outcome"] == "NOT_COVERED" for r in mine),
                         "tightened_error": sum(r["tightened_outcome"] == "ERROR" for r in mine)})
    sel_rows = [r for r in rows if r["selected"]]
    accounting = {"selected_points": len(sel_rows), "selected_targets": sum(r["role"] == "target" for r in sel_rows),
                  "excluded_points": len(rows) - len(sel_rows),
                  "unselected_targets": sum(1 for r in rows if r["role"] == "target" and not r["selected"]),
                  "tightened_not_covered": sum(r["tightened_outcome"] == "NOT_COVERED" for r in rows),
                  "tightened_error": sum(r["tightened_outcome"] == "ERROR" for r in rows),
                  "requests_without_job": [q["tag"] for q in req_rows if q["selected"] and not q["tightened_job_id"]]}
    solver = None
    if variant is not None:
        solver = {"default": {"key": "default", "options_extra": []},
                  "tightened": {"key": variant.get("key"), "options_extra": list(variant.get("options_extra") or [])}}
    return {"source_record": src_rec.get("record_id"), "solver": solver, "points_compared": len(rows), "transition_matrix": matrix,
            "targets": {"n": len(targets), "transitions": tgt},
            "controls": {"n": len(controls), "n_changed": len(changed), "n_not_covered": ctl_uncovered, "n_error": ctl_error, "changed": changed},
            "accounting": accounting, "requests": req_rows,
            "runtime_ratio": runtime, "rows": rows}


def render_comparison_md(cmp: dict) -> list[str]:
    L = [f"## Tightened-vs-default comparison (source record `{cmp['source_record']}`)", "",
         "Every declared point appears exactly once: the **default** verdict is the source record's outcome for that point, the **tightened** verdict is this record's. Same circuit, stimulus, windows, checker and physicality bounds; only the declared solver options differ.", ""]
    L.append("### Transition matrix (default -> tightened)")
    L.append("")
    L.append("| default \\ tightened | " + " | ".join(OUTCOMES) + " |")
    L.append("|---|" + "---|" * len(OUTCOMES))
    for d in OUTCOMES:
        row = cmp["transition_matrix"].get(d, {})
        L.append(f"| {d} | " + " | ".join(str(row.get(t, 0)) for t in OUTCOMES) + " |")
    L.append("")
    t, c = cmp["targets"], cmp["controls"]
    L.append(f"- **Targets (source NONPHYSICAL, {t['n']} points)**: " + (", ".join(f"{o} {n}" for o, n in sorted(t["transitions"].items())) or "none") + ".")
    L.append(f"- **Controls (source PASS/FAIL, {c['n']} points)**: {c['n'] - c['n_changed'] - c.get('n_not_covered', 0) - c.get('n_error', 0)} unchanged, {c['n_changed']} changed, {c.get('n_error', 0)} ERROR and {c.get('n_not_covered', 0)} NOT_COVERED in the tightened run (not graded, so neither agreement nor change). Changed control verdicts are retained below as evidence, not discarded; control agreement is not a precondition for this record.")
    a = cmp.get("accounting") or {}
    if a:
        L.append(f"- **Accounting**: {a['selected_points']} selected point(s) ({a['selected_targets']} source-NONPHYSICAL targets), {a['excluded_points']} excluded "
                 f"({a['unselected_targets']} of them targets); tightened NOT_COVERED {a['tightened_not_covered']}, ERROR {a['tightened_error']}; "
                 f"selected requests with no tightened fleet job: {', '.join(a['requests_without_job']) or 'none'}.")
    if cmp.get("solver"):
        sv = cmp["solver"]["tightened"]
        L.append(f"- **Solver settings**: default = the testbench's declared `.options method=gear trtol=50`; tightened `{sv['key']}` = the same line + `{' '.join(sv['options_extra'])}`.")
    rt = cmp["runtime_ratio"]
    if rt["n"]:
        L.append(f"- **Runtime, tightened vs default** (per corner, {rt['n']} points with both measured): median x{rt['median_ratio']:.2f}, range x{rt['min_ratio']:.2f} - x{rt['max_ratio']:.2f}.")
    L.append("")
    if cmp.get("requests"):
        L.append("### Per-request fleet jobs (default -> tightened)")
        L.append("")
        L.append("| request | selected | targets / controls | default job | default elapsed (s) | tightened job | tightened elapsed (s) | tightened fleet outcome | NOT_COVERED | ERROR | earlier attempts |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|")
        for q in cmp["requests"]:
            L.append(f"| {q['tag']} | {'yes' if q['selected'] else 'no'} | {q['n_targets']} / {q['n_controls']} | {q['default_job_id']} | {fmt(q['default_elapsed_s'], '.0f')} | "
                     f"{q['tightened_job_id']} | {fmt(q['tightened_elapsed_s'], '.0f')} | {str(q['tightened_fleet_outcome'])[:60]} | {q['tightened_not_covered']} | {q['tightened_error']} | {len(q['tightened_earlier_attempts'])} |")
        L.append("")
    if c["changed"]:
        L.append("### Changed control points (source physical)")
        L.append("")
        L.append("| request | point | default | tightened | tightened physical | default note | tightened note |")
        L.append("|---|---|---|---|---|---|---|")
        for r in c["changed"]:
            L.append(f"| {r['tag']} | {r['id']} | {r['default_outcome']} | {r['tightened_outcome']} | {r['tightened_physical']} | {r.get('default_note', '')} | {r['tightened_note']} |")
        L.append("")
    L.append("### Per-point comparison")
    L.append("")
    L.append("Physical = the checker's physicality flag under the unchanged bounds (None = not graded: NOT_COVERED or ERROR).")
    L.append("")
    L.append("| request | point | role | default | tightened | physical default -> tightened | runtime default -> tightened (s) | tightened note |")
    L.append("|---|---|---|---|---|---|---|---|")
    for r in cmp["rows"]:
        rt_s = f"{fmt(r['default_runtime_s'], '.0f')} -> {fmt(r['tightened_runtime_s'], '.0f')}" if r.get("tightened_runtime_s") else fmt(r["default_runtime_s"], ".0f")
        role = r.get("role", "") + ("" if r.get("selected", True) else " (excluded)")
        L.append(f"| {r['tag']} | {r['id']} | {role} | {r['default_outcome']} | {r['tightened_outcome']} | {r.get('default_physical')} -> {r['tightened_physical']} | {rt_s} | {r['tightened_note']} |")
    L.append("")
    return L


def render_md(rec: dict) -> str:
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], rec["experiment"]["slug"], rec["experiment"]["title"])
    L.append(f"- **Claim**: {rec['experiment']['claim']}")
    L.append(f"- **Netlist provenance**: {rec['experiment']['provenance']} (`{rec['experiment']['provenance_source']}`)")
    L += sim_common.render_pdk_tools_repo_state(rec)
    t, g = rec["tools"], rec["git"]
    rs = rec["run_source"]
    L.append(f"- **Simulation source commit** (grid submitted from): `{rs.get('sha_full')}` (dirty at submit: {rs.get('dirty')}; pushed to a remote branch at submit: {rs.get('pushed_to_remote')})")
    later = [(x.get("at_utc"), x.get("source") or {}, x.get("submitted_tags") or []) for x in (rec.get("run_meta") or {}).get("retries") or [] if x.get("source")]
    if later:
        L.append("- **Later submit batches into this run** (each refused deck drift since the first submit): "
                 + "; ".join(f"{at} from `{s.get('sha_full')}` (dirty {s.get('dirty')}, pushed {s.get('pushed_to_remote')}), {len(tags)} request(s)" for at, s, tags in later))
    L.append(f"- **Grading source commit** (checker/record written from): `{g['sha_full']}` (dirty at grading: {g['dirty']}; pushed: {g['pushed_to_remote']})")
    dd = rec["deck_drift"]
    L.append("- **Deck inputs between the two commits** (" + ", ".join(f"`{x}`" for x in DECK_INPUTS) + "): "
             + ("identical (the submitted decks are the ones a checkout of either commit regenerates)" if dd == [] else f"CHANGED {dd}" if dd else "not determinable"))
    nm = [q["tag"] for q in rec["requests"] if q.get("job_id") and not q.get("netlist_matches_report")]
    L.append(f"- **Submitted netlist vs fleet report sha256**: " + ("all match" if not nm else f"MISMATCH for {nm}"))
    L.append(f"- **Fleet runner**: klt `{t['fleet_runner_klt']}` / `{t['fleet_ngspice']}` (client klt `{t['klt_client']}`); {t['fleet_note']}")
    klu_n = t.get("fleet_klu_points")
    if klu_n is not None and (klu_n or "klu" in (rec.get("solver_variant") or {}).get("options_extra", [])):
        L.append(f"- **Netlist-carried KLU on the runner**: ngspice announced `Using KLU as Direct Linear Solver` in {klu_n} of {rec['matrix']['n_points_graded']} graded point log(s); absence on a graded point means the SPARSE default solver ran there.")
    L.append(f"- **Host tool caveat**: {t['xschem_note']}")
    m = rec["matrix"]
    L.append("- **Corner matrix**: process " + ", ".join(m["process"]) + "; temperature " + ", ".join(f"{cr.fmt_temp(x)} C" for x in m["temperature_c"]) + "; starting supply " + ", ".join(f"{v:.2f} V" for v in m["supply_v"]))
    L.append(f"- **Declared**: {m['n_requests']} request(s) x {m['points_per_request']} = {m['n_points']} points; {m['n_requests_submitted']} request(s) with a usable report; {m['n_points_graded']} points graded, {m['n_points_not_covered']} NOT_COVERED (never counted as covered).")
    sv = rec.get("solver_variant") or {}
    if sv.get("key", "default") != "default":
        L.append(f"- **Solver variant**: `{sv['key']}` -- `.options {' '.join(sv.get('options_extra') or [])}` appended to the testbench's declared default options line (experiment.json `solver_variants`); circuit, stimulus, windows, tmax, checker and physicality bounds unchanged. {sv.get('label', '')}")
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
    L.append(f"\nNONPHYSICAL breakdown (a point may count in several rows): {s['nonphysical_breakdown']}")
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
            if p["outcome"] == "NONPHYSICAL":
                ph = c["physical"]
                note = (f"NONPHYSICAL {ph['node_violation_phase'] or 'no node violation'}"
                        + (f" [{','.join(sorted(ph['violations_after_t0']))}]" if ph["violations_after_t0"] else "")
                        + (" supply-current-reversed(end)" if ph["supply_current_reversed_at_end"] else "")
                        + (" delivered-bias-sign" if not ph["delivered_bias_sign_ok"] else ""))[:140]
            u = lambda x: "n/a" if x is None else f"{x * 1e6:.3g}"  # noqa: E731
            ms = lambda x: "n/a" if x is None else f"{x * 1e3:.5g}"  # noqa: E731
            L.append(f"| {p['id']} | {p['outcome']} | {rs['n_assert']} | {'y' if c['detectability']['required_to_assert'] else 'n'} | {fmt(rs['vdd_at_assert_v'], '.3f')}{'*' if rs['assertion_rail_limited'] else ''} | {ms(rs['t_assert_s'])} | {ms(rs['t_release_s'])} | "
                     f"{'ok' if c['baseline']['ok'] else 'UNREADY'} | {u(db['baseline_a'])}/{u(db['min_after_t0_a'])}/{u(db['end_a'])} | {fmt(ibn['baseline_v'], '.3f')}/{fmt(ibn['min_after_t0_v'], '.3f')} | {rz['max_dt_dip_window_s'] * 1e6:.3g}/{rz['required_max_dt_s'] * 1e6:.3g} | {note} |")
    L.append("")
    L.append("`*` = assertion was rail-limited (VDD <= V_IL at the crossing): RESETn could not stay high regardless of the comparator.")
    L.append("")
    if rec.get("cost_projections"):
        L.append("## Pilot runtime projection (made before the remaining requests were submitted)")
        L.append("")
        for cp in rec["cost_projections"]:
            L.append(f"- {cp.get('at_utc')}: pilots " + ", ".join(f"`{p['tag']}` job {p.get('job_id')} {fmt(p['default_elapsed_s'], '.0f')} -> {fmt(p['tightened_elapsed_s'], '.0f')} s ({p.get('state') or 'done'}; elapsed x{'>=' if p.get('timed_out') else ''}{fmt(p['elapsed_ratio'], '.2f')}, corner-sum x{fmt(p['corner_sum_ratio'], '.2f')})" for p in cp["pilots"])
                     + (f"; limit from {cp['limit_source']}" if cp.get("limit_source") else "") + f"; worst ratio x{'>=' if cp.get('lower_bound') else ''}{fmt(cp['worst_ratio'], '.2f')}{' (lower bound: a pilot hit the job limit, its corner runtimes were lost)' if cp.get('lower_bound') else ''} against the {cp['limit_s']:.0f} s per-job limit; {cp['n_over_limit']} request(s) projected over it. "
                     + "Projected max: " + fmt(max((p["projected_tightened_elapsed_s"] or 0) for p in cp["projection"]), ".0f") + " s.")
        L.append("")
    if rec.get("comparison"):
        L += render_comparison_md(rec["comparison"])
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
    if rec.get("companion_of"):
        L.append(f"- **Companion of**: `{rec['companion_of']}` -- the default-deck record stays as evidence; this solver-variant record is reported beside it and does not replace it.")
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
    evidence_store.preflight_or_exit()
    man = sim_common.load_manifest(MANIFEST)
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    run_variant = meta.get("solver_variant", "default")
    variant_key = args.variant or run_variant or "default"
    if variant_key != run_variant:
        raise SystemExit(f"run {args.run_id} was submitted with solver variant '{run_variant}', not '{variant_key}'")
    variant = variant_of(man, variant_key)
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    gi = source_state()
    drift = deck_drift((meta.get("source") or {}).get("sha_full"), gi.get("sha_full"))
    sim_common.refuse_unrecordable(gi, drift, args.allow_dirty, args.allow_deck_drift)
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{gi['sha']}"
    rec_dir = HERE / "records"
    corners_dir = evidence_store.stage_dir_for(HERE.name, record_id)  # git-ignored scratch; stored below
    snap_dir = HERE / "netlist-snapshots" / record_id
    sim_common.refuse_existing((rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", corners_dir, snap_dir, evidence_store.manifest_path(HERE.name, record_id)))
    reqs = plan_requests(man)
    points, requests, fleet_pdk = [], [], {}
    for r in reqs:
        res = analyze_request(r, run_dir, man, corners_dir, write=True)
        points += res["points"]
        requests.append(res["info"])
        fleet_pdk = res["pdk_report"] or fleet_pdk
        src = run_dir / r["tag"]
        sim_common.snapshot_request_artifacts(src, r["tag"], snap_dir, corners_dir, run_dir, REPO_ROOT)
    snap_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "run.json").is_file():
        shutil.copyfile(run_dir / "run.json", snap_dir / "run.json")
    cost_files = sorted(run_dir.glob("cost-projection-*.json"))
    for cf in cost_files:
        shutil.copyfile(cf, snap_dir / cf.name)
    cost_projections = [json.loads(cf.read_text()) for cf in cost_files]
    fails = sim_common.submit_failures(requests)
    ngs = sorted({p["ngspice"] for p in points if p.get("ngspice")})
    runners = sorted({q.get("runner_klt_version") for q in requests if q.get("runner_klt_version")})
    cnt = declared_counts(man)
    n_graded = sum(1 for p in points if p["outcome"] != "NOT_COVERED")
    comparison = None
    rerun = man.get("tightened_rerun") or {}
    compare_source = args.compare_source
    if not compare_source and variant["key"] != "default" and rerun.get("variant") == variant["key"]:
        compare_source = str(REPO_ROOT / rerun["source_record"])  # a tightened-variant record is always a comparison
    if compare_source:
        src_path = Path(compare_source)
        if not src_path.is_file():
            raise SystemExit(f"--compare-source {src_path} does not exist")
        src_rec = json.loads(src_path.read_text())
        comparison = build_comparison(src_rec, points, requests, variant, selected_rerun_tags(man) if rerun.get("variant") == variant["key"] else None)
        t, c = comparison["targets"], comparison["controls"]
        say(f"comparison vs {comparison['source_record']}: {comparison['points_compared']} points; targets {t['n']} -> {t['transitions']}; controls {c['n']} with {c['n_changed']} changed, {c.get('n_error', 0)} ERROR, {c.get('n_not_covered', 0)} NOT_COVERED")
    art_manifest, art_summary = evidence_store.store_or_exit(HERE.name, record_id, corners_dir)
    ph = man["grading"]
    record = {
        "record_id": record_id, "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
        "solver_variant": variant, "comparison": comparison, "cost_projections": cost_projections,
        "companion_of": (comparison or {}).get("source_record"),
        "experiment": {k: man[k] for k in ("slug", "title", "claim", "provenance", "provenance_source", "statistical_convention")},
        "pdk": {"root": "<host $PDK_ROOT>", "variant": pdk.variant, "installed_commit": pdk.installed_commit, "pinned_commit": pin["open_pdks_commit"], "matches_pin": pdk.matches_pin,
                "lib_file": MODEL_LIB + " (resolved on the runner as /opt/pdk/sky130A/...)", "fleet_pdk_report": fleet_pdk},
        "tools": {"ngspice": f"{cr.first_line(['ngspice', '-v'])} (host; the grid ran on the fleet)", "xschem": cr.first_line(["xschem", "--version"]),
                  "platform": cr.tool_versions()["platform"], "python": cr.tool_versions()["python"], "klt_client": meta.get("klt_client"),
                  "fleet_runner_klt": ", ".join(runners) or "unknown", "fleet_ngspice": ", ".join(ngs) or "unknown",
                  "fleet_note": sim_common.FLEET_NOTE,
                  "fleet_klu_points": sum(1 for p in points if p.get("netlist_klu_announced")),
                  "xschem_note": sim_common.XSCHEM_NOTE},
        "git": gi, "run_source": meta.get("source", {}), "deck_drift": drift, "run_meta": {k: meta.get(k) for k in ("run_id", "started_utc", "submitted_tags", "retries")},
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
                  "netlist_snapshots": f"sim/brownout-top/netlist-snapshots/{record_id}/", "artifact_manifest": str(art_manifest.relative_to(REPO_ROOT)), "artifact_summary": str(art_summary.relative_to(REPO_ROOT)),
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
    r.add_argument("--variant", help="declared solver variant key (experiment.json solver_variants); default deck if omitted")
    r.add_argument("--only", action="append", help="submit only this declared request tag (repeatable); the rest stay NOT_COVERED")
    r.add_argument("--retry-failed", action="store_true")
    r.add_argument("--capacity-wait", type=float, default=0)
    r.add_argument("--slot-wait", type=float, default=0, help="seconds to keep resubmitting a request the fleet refused at its concurrent-instance cap (klayout-tools#2917); each refusal is archived")
    r.add_argument("--slot-poll", type=float, default=300, help="seconds between concurrency-cap resubmissions")
    r.add_argument("--allow-dirty", action="store_true")
    x = sub.add_parser("probe")
    x.add_argument("--tag", required=True)
    x.add_argument("--variant", help="declared solver variant key (experiment.json solver_variants); default deck if omitted")
    x.add_argument("--process", help="one declared process corner (default tt)")
    x.add_argument("--fleet-equivalent", action="store_true", help="omit ngspice_init, as the fleet runner does (default SPARSE solver), for like-for-like single-corner timing")
    x.add_argument("--temp", type=float, help="one declared temperature in C (default 27)")
    x.add_argument("--supply", type=float, help="one declared starting supply in V (default 3.3)")
    x.add_argument("--tstop", type=float, help="shortened stop time (s) for a quick channel-name validation; such a probe is never graded")
    c = sub.add_parser("record")
    c.add_argument("--run-id", required=True)
    c.add_argument("--variant", help="must match the solver variant the run was submitted with (run.json solver_variant)")
    c.add_argument("--compare-source", help="path to the source (default-deck) record .json; writes a per-point default-vs-tightened comparison into this record")
    c.add_argument("--notes-file")
    c.add_argument("--author")
    c.add_argument("--supersedes")
    c.add_argument("--allow-dirty", action="store_true")
    c.add_argument("--allow-deck-drift", action="store_true", help="record even though deck inputs changed since the submit commit (stated in the record)")
    s = sub.add_parser("selftest")
    s.add_argument("--author")
    s.add_argument("--supersedes")
    k = sub.add_parser("cost")
    k.add_argument("--run-id", required=True, help="run holding the tightened pilot reports; projects every predeclared rerun request against tightened_rerun.job_limit_s")
    k.add_argument("--limit-s", type=float, help="project against this per-job limit instead (e.g. the limit the fleet harness actually enforced); recorded with --limit-note")
    k.add_argument("--limit-note", help="where the --limit-s value comes from")
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "run": cmd_run, "probe": cmd_probe, "record": cmd_record, "selftest": cmd_selftest, "cost": cmd_cost}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
