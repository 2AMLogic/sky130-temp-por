#!/usr/bin/env python3
"""Full-grid solver-sensitivity replicate of the natural-release iq-total state (issue #160).

DR-006 requires a solver-sensitivity replicate before the 17 non-physical iq-total points of
record 20261009-191705-df85523 can support an Iq recommendation.  This driver re-runs the WHOLE
45-point iq-total grid (never only the 17 exclusions: a solver change can move the failure set)
under three solver settings -- the unchanged control and two documented integration/tolerance
variants (experiment.json ``solver_sensitivity``) -- as ONE ``klt sim --backend batch`` corner
request per variant.  It never launches ngspice over the grid and has no local fallback: a
fleet refusal is recorded as an explicit unknown.

Only the testbench ``.options`` line differs between variants; the DUT, analysis card, measurement
windows, guards and the grading code (iq_checker.grade on the full-resolution waveform, via
run_iq_campaign.analyze_state) are shared with the original campaign.

Stages:  run | record | selftest-free unit tests live in test_solver_sensitivity.py
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import gzip
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import run_iq_campaign as rc  # noqa: E402

sim_common, cr, qc = rc.sim_common, rc.cr, rc.qc
STATE = "iq-total"
ORIGINAL_RECORD = HERE / "records" / "20261009-191705-df85523.json"
SLUG_SUFFIX = "solver-sensitivity"
BUILD = rc.BUILD / "sensitivity"


def sens(man: dict) -> dict:
    return man["solver_sensitivity"]


def variant_names(man: dict) -> list[str]:
    return list(sens(man)["variants"])


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# --------------------------------------------------------------------------
# deck / request generation (variant selection must reach both)
# --------------------------------------------------------------------------


def variant_head(head: str, variant: str, man: dict) -> str:
    """Apply a solver variant to the testbench part of the deck: replace the one options line.

    ``baseline`` has ``options: null`` and returns the head untouched (byte-identical control).
    The expected original line must occur exactly once, so a testbench edit cannot silently turn a
    variant into a no-op.
    """
    s = sens(man)
    if variant not in s["variants"]:
        raise SystemExit(f"unknown solver variant {variant!r}")
    opts = s["variants"][variant]["options"]
    find = s["options_line_in_testbench"]
    if head.count(find) != 1:
        raise SystemExit(f"testbench options line {find!r} must occur exactly once in the generated head (found {head.count(find)})")
    if opts is None:
        return head
    return head.replace(find, f".options {opts}")


def build_variant_netlist(head: str, variant: str, man: dict) -> str:
    return rc.build_netlist(variant_head(head, variant, man), STATE, man)


def build_variant_request(man: dict, capacity_wait_s: float = 0, process: str | None = None) -> dict:
    """The request is identical for every variant: the solver setting lives in the deck.

    ``process`` restricts the corner axes to one MOS corner (9 of the 45 points): used only to fit a
    variant under the fleet's per-job wall-clock ceiling by SPLITTING the grid into several fleet
    requests; the deck, analysis card and every other request field are unchanged.
    """
    req = rc.build_request("netlist.spice", man, "batch", capacity_wait_s)
    if process is not None:
        if process not in req["corners"]["process"]:
            raise SystemExit(f"unknown process corner {process!r}")
        req["corners"]["process"] = [process]
    return req


# --------------------------------------------------------------------------
# comparison (criterion predeclared in experiment.json, not tuned to results)
# --------------------------------------------------------------------------


def rel_diff(a: float, b: float) -> float:
    return abs(a - b) / min(abs(a), abs(b))


def usable(pt: dict | None) -> bool:
    """A measurement is usable only if graded `ok` AND carries a finite current; invalid input never is."""
    return bool(pt) and pt.get("status") == "ok" and not pt.get("invalid_input") and isinstance(pt.get("i_total_a"), (int, float)) and pt["i_total_a"] > 0


def agreement(currents: dict[str, float], tol: float) -> dict:
    """Pairwise agreement among the usable currents of one corner."""
    names = sorted(currents)
    if len(names) < 2:
        return {"n_ok": len(names), "agree": None, "max_rel": None}
    worst = max(rel_diff(currents[a], currents[b]) for i, a in enumerate(names) for b in names[i + 1:])
    return {"n_ok": len(names), "agree": worst <= tol, "max_rel": worst}


def classify_exclusion(runs: dict[str, dict | None], tol: float) -> tuple[str, str]:
    """Classify one originally excluded point from the statuses of all runs (rules: experiment.json, in order)."""
    got = {v: p for v, p in runs.items() if p and p.get("status") in ("ok", "non-physical-branch", "unsettled") and not p.get("invalid_input")}
    ok = {v: p["i_total_a"] for v, p in got.items() if usable(p)}
    missing = [v for v in runs if v not in got]
    if not ok and missing:
        return "unresolved", f"no run is ok and no graded result from: {', '.join(missing)}"
    if len(ok) >= 2:
        ag = agreement(ok, tol)
        if not ag["agree"]:
            return "unresolved", f"physical disagreement between ok runs (max relative difference {ag['max_rel']:.3%} > {tol:.0%})"
    if ok:
        others = {v: p["status"] for v, p in got.items() if v not in ok}
        extra = f"; not ok: {others}" if others else ""
        extra += f"; no result: {missing}" if missing else ""
        return "recovered-solver-sensitive", f"physical settled landing in {sorted(ok)}{extra} (existence only; cause of the original artifact not established)"
    sts = {p["status"] for p in got.values()}
    if sts == {"non-physical-branch"}:
        return "reproduced-non-physical", "non-physical-branch in every run"
    if "non-physical-branch" not in sts and "ok" not in sts:
        return "physical-failure", f"physical landing failing the unchanged settling/state checks ({', '.join(sorted(sts))}) in every run"
    return "unresolved", f"mixed non-ok statuses across runs: {', '.join(f'{v}={p['status']}' for v, p in sorted(got.items()))}"


def compare(per: dict[str, dict], original: dict | None, man: dict) -> dict:
    """Per-corner table + exclusion classification.  per: variant -> {"points": {cid: point}}; original: cid -> point."""
    tol = sens(man)["comparison_criterion"]["agreement_rel_tol"]
    names = variant_names(man)
    rows, classes, new_fail = [], {}, []
    for p, t, v in rc.grid(man):
        cid = rc.corner_id(p, t, v)
        runs = {n: per[n]["points"].get(cid) for n in names}
        orig = (original or {}).get(cid)
        cur = {n: runs[n]["i_total_a"] for n in names if usable(runs[n])}
        ag = agreement(cur, tol)
        orig_excl = bool(orig) and orig["status"] != "ok"
        row = {"id": cid, "original_status": orig["status"] if orig else None, "original_i_a": orig.get("i_total_a") if orig else None,
               "original_excluded": orig_excl,
               "runs": {n: {"status": (runs[n] or {}).get("status", "no-result"), "i_a": (runs[n] or {}).get("i_total_a"), "invalid_input": bool((runs[n] or {}).get("invalid_input")),
                            "reason": "; ".join((runs[n] or {}).get("nonphysical_reasons", []) + (runs[n] or {}).get("unsettled_reasons", []) + ([runs[n]["reason"]] if (runs[n] or {}).get("reason") else []))}
                        for n in names},
               "agreement": ag}
        if "baseline" in cur and orig and usable(orig):
            row["baseline_vs_original_rel"] = rel_diff(cur["baseline"], orig["i_total_a"])
        for n in names:
            if n != "baseline" and n in cur and "baseline" in cur:
                row.setdefault("vs_baseline_rel", {})[n] = rel_diff(cur[n], cur["baseline"])
        if orig and orig["status"] == "ok":
            bad = {n: row["runs"][n]["status"] for n in names if not usable(runs[n])}
            if bad:
                new_fail.append({"id": cid, "runs": bad})
            row["newly_failing_in"] = sorted(bad)
        if orig_excl:
            cls, why = classify_exclusion(runs, tol)
            classes[cid] = {"class": cls, "why": why}
            row["classification"] = cls
        rows.append(row)
    return {"tolerance": tol, "rows": rows, "classes": classes, "newly_failing": new_fail, "summary": summarize(rows, per, names, classes)}


def summarize(rows: list[dict], per: dict, names: list[str], classes: dict) -> dict:
    out: dict = {"per_variant_counts": {}, "classes": {}}
    for n in names:
        c: dict[str, int] = {}
        for r in rows:
            c[r["runs"][n]["status"]] = c.get(r["runs"][n]["status"], 0) + 1
        out["per_variant_counts"][n] = c
    for v in classes.values():
        out["classes"][v["class"]] = out["classes"].get(v["class"], 0) + 1
    multi = [r for r in rows if r["agreement"]["n_ok"] >= 2]
    out["corners_with_ge2_ok"] = len(multi)
    out["corners_agree"] = sum(1 for r in multi if r["agreement"]["agree"])
    out["corners_disagree"] = [r["id"] for r in multi if not r["agreement"]["agree"]]
    out["corners_all_variants_ok"] = sum(1 for r in rows if r["agreement"]["n_ok"] == len(names))
    out["status_differs_between_runs"] = [r["id"] for r in rows if len({r["runs"][n]["status"] for n in names}) > 1]
    return out


# --------------------------------------------------------------------------
# run / record
# --------------------------------------------------------------------------


def head_for_run(run_dir: Path, pdk) -> str:
    return rc.tb_netlist_head(STATE, run_dir, pdk)


def cmd_run(args) -> int:
    man = sim_common.load_manifest(rc.MANIFEST)
    pdk = cr.resolve_pdk(cr.load_pin())
    gi = cr.git_state()
    if gi["dirty"] and not args.allow_dirty:
        raise SystemExit("working tree is dirty: commit first so the record carries a clean resolvable source revision (or pass --allow-dirty, which the record will flag)")
    if subprocess.run(["git", "rev-parse", "--verify", "--quiet", gi["sha"] + "^{commit}"], capture_output=True, cwd=rc.REPO_ROOT).returncode != 0:
        raise SystemExit(f"source revision {gi['sha']} does not resolve")
    now = datetime.now(timezone.utc)
    run_id = args.run_id or f"{now:%Y%m%d-%H%M%S}-{gi['sha']}"
    run_dir = BUILD / run_id
    names = args.variant or variant_names(man)
    if args.retry_failed:
        if not run_dir.exists():
            raise SystemExit(f"{run_dir} does not exist")
        work = [n for n in names if args.split_process or not sim_common.report_usable(run_dir / n / STATE / sim_common.rate_tag(man["measurement"]["rate_v_per_s"]) / "report.json")]
        say = sim_common.say
        say(f"retrying {len(work)} variant request(s) without a usable report, capacity_wait_s={args.capacity_wait}")
    else:
        if run_dir.exists():
            raise SystemExit(f"{run_dir} exists; refusing to reuse a run id")
        run_dir.mkdir(parents=True)
        work = list(names)
    head = head_for_run(run_dir if not args.retry_failed else run_dir / "retry", pdk)
    rate = man["measurement"]["rate_v_per_s"]
    hashes = {}
    decks = {n: build_variant_netlist(head, n, man) for n in work}
    procs = (list(args.process or man["corners"]["process"])) if args.split_process else [None]
    for n in work:
        for pr in procs:
            req = build_variant_request(man, args.capacity_wait, pr)
            hashes[n if pr is None else f"{n}/split-{pr}"] = {"deck_sha256": sha256(decks[n]), "request_sha256": sha256(json.dumps(req, indent=2, sort_keys=True))}
    meta_path = run_dir / "run.json"
    meta = json.loads(meta_path.read_text()) if args.retry_failed else {
        "run_id": run_id, "started_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "variants": names, "klt_client": sim_common.klt_version(),
        "klt_sim_backend_env": os.environ.get("KLT_SIM_BACKEND"), "git": gi, "dut_sha256": sha256(rc.DUT_NETLIST.read_text()),
        "testbench_sha256": sha256((rc.HERE / "testbench" / "tb_temp_por_iq_total.sch").read_text()), "manifest_sha256": sha256(rc.MANIFEST.read_text())}
    meta.setdefault("hashes", {}).update(hashes)
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    def one(item):
        n, pr = item
        if pr is None:
            return sim_common.submit_request(f"{n}/{STATE}", rate, run_dir, decks[n], build_variant_request(man, args.capacity_wait), f" [{n}]", len(rc.grid(man)))
        npts = len(man["corners"]["temperature_c"]) * len(man["corners"]["supply_v"])
        return sim_common.submit_request(f"{n}/split-{pr}/{STATE}", rate, run_dir, decks[n], build_variant_request(man, args.capacity_wait, pr), f" [{n} process {pr}]", npts)

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(2, args.jobs)) as ex:
        futs = {(n if pr is None else f"{n}/split-{pr}"): ex.submit(one, (n, pr)) for n in work for pr in procs}
        for n, f in futs.items():
            try:
                results.append({"variant": n, **f.result()})
            except Exception as err:  # noqa: BLE001 -- recorded, never swallowed
                results.append({"variant": n, "error": repr(err)})
                sim_common.say(f"[error] submit {n} raised: {err!r}")
    meta = json.loads(meta_path.read_text())
    key = "retries" if args.retry_failed else "submit_results"
    if args.retry_failed:
        meta.setdefault(key, []).append({"at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "capacity_wait_s": args.capacity_wait, "results": results})
    else:
        meta[key] = results
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f"raw outputs: {run_dir}")
    return 0


def analyze_variant(n: str, run_dir: Path, man: dict, traces: dict) -> dict:
    """Same grading as the original campaign: run_iq_campaign.analyze_state over this variant's subtree.

    If the variant was resubmitted split by MOS corner (``<variant>/split-<proc>/``), each split is
    graded with the same code and the points are merged back into the full 45-point grid; the earlier
    whole-grid attempt (if any) is kept in the request's ``failed_earlier_attempts``.
    """
    splits = {pr: run_dir / n / f"split-{pr}" for pr in man["corners"]["process"] if (run_dir / n / f"split-{pr}").is_dir()}
    tr = traces.setdefault(n, {})
    if not splits:
        return rc.analyze_state(STATE, run_dir / n, man, tr)
    whole = rc.analyze_state(STATE, run_dir / n, man, {})
    pts, reqs = {}, {}
    for pr in man["corners"]["process"]:
        if pr not in splits:
            continue
        sub = copy.deepcopy(man)
        sub["corners"]["process"] = [pr]
        res = rc.analyze_state(STATE, splits[pr], sub, tr)
        pts.update(res["points"])
        reqs[pr] = res["requests"]
    full = {}
    for p, t, v in rc.grid(man):
        cid = rc.corner_id(p, t, v)
        full[cid] = pts.get(cid) or {"id": cid, "process": p, "temperature_c": t, "supply_v": v, "status": "nonconverged", "reason": "NOT SUBMITTED in the split resubmission"}
    outcomes = {pr: r.get("outcome") for pr, r in reqs.items()}
    first_diag = next((p["diagnostics"][0] for p in whole["points"].values() if p.get("diagnostics")), "")
    whole["requests"]["first_attempt_diagnostic"] = first_diag
    req = {"split_by_process": reqs, "outcome": outcomes, "job_id": {pr: r.get("job_id") for pr, r in reqs.items()},
           "instance_type": sorted({r.get("instance_type") for r in reqs.values() if r.get("instance_type")}),
           "runner_klt_version": next((r.get("runner_klt_version") for r in reqs.values() if r.get("runner_klt_version")), None),
           "first_whole_grid_attempt": whole["requests"]}
    return {"requests": req, "points": full}


def f_ua(x):
    return "-" if x is None else f"{x * 1e6:.3f}"


def render_md(rec: dict) -> str:
    man = rec["manifest_sensitivity"]
    S = rec["comparison"]["summary"]
    names = rec["variants"]
    L = [f"# Record {rec['record_id']}", ""]
    L += sim_common.render_record_id_experiment(rec["record_id"], rc.SLUG, "Solver-sensitivity replicate of the natural-release iq-total state (45-point grid, 3 solver settings)")
    L += ["- **Claim**: EVIDENCE ONLY, NOT a spec claim and NOT a proposed ceiling. Issue #160 / DR-006: re-run the whole 45-point iq-total grid under the control and two solver variants and compare physical settled landings; no Iq ceiling is proposed and no ratified row is changed.",
          f"- **Netlist provenance**: schematic (`sim/iq-top/testbench/tb_temp_por_iq_total.sch`; DUT `design/netlist/temp_por_top.spice`, sha256 `{rec['provenance']['dut_sha256']}`)"]
    L += sim_common.render_pdk_tools_repo_state(rec)
    L += [f"- **Source revision of the first submissions**: `{rec['run_git']['sha']}` on `{rec['run_git']['branch']}` (working tree dirty at submit time: {rec['run_git']['dirty']}); record written at `{rec['git']['sha']}` (dirty: {rec['git']['dirty']}). Split resubmissions ran from later commits of the same branch that changed only `run_iq_sensitivity.py` (the `--split-process` / `--process` options); each deck/request is identified by the sha256 values below.",
          f"- **Fleet PDK commit**: {rec['fleet_pdk_note']}",
          f"- **Fleet**: {rec['fleet_note']}",
          "- **Statistical convention**: N/A (corner-matrix measurement)", ""]
    L += ["## Variants (only the testbench `.options` line differs)", "| variant | `.options` | deck sha256 | request sha256 | outcome | job id |", "|---|---|---|---|---|---|"]
    for n in names:
        r = rec["requests"][n]
        h = rec["provenance"]["hashes"].get(n, {})
        outcome, job = r.get("outcome"), r.get("job_id")
        if "split_by_process" in r:
            first = r.get("first_whole_grid_attempt", {})
            outcome = f"whole-grid attempt: {first.get('outcome')} ({(first.get('first_attempt_diagnostic') or '')[:200]}); resubmitted split by MOS corner: {r['outcome']}"
            job = f"whole-grid {first.get('job_id')}; split {r['job_id']}"
        L.append(f"| {n} | `{rec['variant_options'][n] or 'method=gear trtol=50 (unchanged control)'}` | `{h.get('deck_sha256', '-')}` | `{h.get('request_sha256', '-')}` | {outcome} | {job} |")
        for k, hh in sorted(rec["provenance"]["hashes"].items()):
            if k.startswith(n + "/"):
                L.append(f"|  | {k} (45-point grid split into one request per MOS corner) | `{hh['deck_sha256']}` | `{hh['request_sha256']}` | | |")
        for a in r.get("failed_earlier_attempts", []):
            L.append(f"|  | earlier attempt: {a} | | | | |")
    L += ["", f"Unchanged across variants: {man['unchanged_across_variants']}", ""]
    L += ["## Predeclared comparison criterion (fixed before any result; see `experiment.json` `solver_sensitivity`)",
          f"- {man['comparison_criterion']['rule']}", f"- Rationale: {man['comparison_criterion']['rationale']}", ""]
    L += ["## Accounting (all 45 points per variant)", "| variant | status counts |", "|---|---|"]
    for n in names:
        L.append(f"| {n} | {S['per_variant_counts'][n]} |")
    L += ["", f"- Corners with >= 2 `ok` landings: {S['corners_with_ge2_ok']}; of those agree within {rec['comparison']['tolerance']:.0%}: {S['corners_agree']}; disagree: {S['corners_disagree'] or 'none'}.",
          f"- Corners `ok` in all {len(names)} runs: {S['corners_all_variants_ok']}.",
          f"- Corners whose status differs between runs: {len(S['status_differs_between_runs'])} ({', '.join(S['status_differs_between_runs']) or 'none'}).",
          f"- Newly failing (`ok` in the original record, not `ok` in some run here): {len(rec['comparison']['newly_failing'])}" + ("".join(f"; `{x['id']}` {x['runs']}" for x in rec["comparison"]["newly_failing"])) + ".", ""]
    L += ["## Classification of the original iq-total exclusions", f"Counts: {S['classes'] or 'none (no original exclusions found)'}", "",
          "A `recovered` label records that a physical settled landing exists under a solver setting; it does not prove the original artifact's cause. Unknowns and physical disagreements are preserved.", "",
          "| point | class | why |", "|---|---|---|"]
    for cid, c in rec["comparison"]["classes"].items():
        L.append(f"| {cid} | **{c['class']}** | {c['why']} |")
    L += ["", "## Per-corner baseline-versus-variant table (uA; * = originally excluded)", "| point | original | " + " | ".join(names) + " | ok-landings agree | max rel diff | " + " | ".join(f"{n} vs baseline" for n in names if n != "baseline") + " |",
          "|---|---|" + "---|" * (len(names) + 2 + len(names) - 1)]
    for r in rec["comparison"]["rows"]:
        cells = [f"{r['id']}{'*' if r['original_excluded'] else ''}", f"{r['original_status']} {f_ua(r['original_i_a'])}"]
        for n in names:
            x = r["runs"][n]
            cells.append(f"{x['status']} {f_ua(x['i_a'])}" + (" (invalid input)" if x["invalid_input"] else ""))
        ag = r["agreement"]
        cells += ["n/a (<2 ok)" if ag["agree"] is None else ("agree" if ag["agree"] else "**DISAGREE**"), "-" if ag["max_rel"] is None else f"{ag['max_rel']:.2e}"]
        cells += [f"{r.get('vs_baseline_rel', {}).get(n, float('nan')):.2e}" if n in r.get("vs_baseline_rel", {}) else "-" for n in names if n != "baseline"]
        L.append("| " + " | ".join(cells) + " |")
    L += ["", "## Baseline replicate vs original record", f"- {rec['baseline_vs_original_text']}", "", "## Limitations (stated, not hidden)"]
    L += [f"- {a}" for a in rec["limitations"]]
    L += ["", "## Links"] + [f"- {k}: `{v}`" for k, v in rec["links"].items()]
    L += [f"- **Timestamp / author**: {rec['timestamp']}, {rec['author']}", f"- **Supersedes**: {rec['supersedes'] or '(none; the original records are untouched)'}", "",
          "Written by `sim/iq-top/run_iq_sensitivity.py record`. Append-only: never edit this file.", ""]
    return "\n".join(L)


def cmd_record(args) -> int:
    man = sim_common.load_manifest(rc.MANIFEST)
    run_dir = BUILD / args.run_id
    meta = json.loads((run_dir / "run.json").read_text())
    pin = cr.load_pin()
    pdk = cr.resolve_pdk(pin)
    gi = cr.git_state()
    now = datetime.now(timezone.utc)
    record_id = f"{now:%Y%m%d}-{now:%H%M%S}-{meta['git']['sha']}-{SLUG_SUFFIX}"
    rec_dir, cdir, sdir = HERE / "records", HERE / "corners" / record_id, HERE / "netlist-snapshots" / record_id
    sim_common.refuse_existing((rec_dir / f"{record_id}.md", rec_dir / f"{record_id}.json", cdir, sdir))
    names = variant_names(man)
    traces: dict = {}
    per = {n: analyze_variant(n, run_dir, man, traces) for n in names}
    orig = json.loads(ORIGINAL_RECORD.read_text())["points"][STATE]
    cmp_ = compare(per, orig, man)
    cdir.mkdir(parents=True)
    sdir.mkdir(parents=True)
    rate = man["measurement"]["rate_v_per_s"]
    for n in names:
        d = run_dir / n / STATE / sim_common.rate_tag(rate)
        for name in ("netlist.spice", "request.json"):
            if (d / name).is_file():
                (sdir / f"{n}.{name}").write_text(rc.scrub((d / name).read_text(), run_dir))
        if (d / "report.json").is_file():
            (cdir / f"{n}.klt-report.json").write_text(rc.scrub((d / "report.json").read_text(), run_dir))
        if (d / "klt.stderr").is_file() and (d / "klt.stderr").read_text().strip():
            (cdir / f"{n}.klt.stderr").write_text(rc.scrub((d / "klt.stderr").read_text(), run_dir))
        if traces.get(n):
            with gzip.open(cdir / f"{n}.traces.json.gz", "wt") as fh:
                json.dump(traces[n], fh)
    allp = [p for n in names for p in per[n]["points"].values()]
    ngs = sorted({p["ngspice"] for p in allp if p.get("ngspice")})
    bo = [r["baseline_vs_original_rel"] for r in cmp_["rows"] if "baseline_vs_original_rel" in r]
    both_ok = [r["id"] for r in cmp_["rows"] if "baseline_vs_original_rel" in r]
    flips = [r["id"] for r in cmp_["rows"] if r["original_status"] and r["runs"]["baseline"]["status"] != r["original_status"]]
    bvo = (f"{len(both_ok)} corners are `ok` in both; max relative current difference {max(bo):.3e}" if bo else "no corner is `ok` in both") + \
          f"; status differs from the original record at {len(flips)} corner(s): {', '.join(flips) or 'none'}."
    n_total = len(allp)
    n_res = sum(1 for p in allp if p.get("i_total_a") is not None)
    limits = [
        "Natural-release iq-total only; forced-low por-iq contention and the definition of incremental temp-iq (DR-006 blockers) are not addressed.",
        "Three solver settings are a bounded sample, not an exhaustive sweep; a point that is non-physical in all three is `reproduced-non-physical` for THESE settings only.",
        "A passing variant shows that a physical settled landing exists under that setting; it does not by itself prove the cause of the original artifact.",
        "The fleet runner does not report the PDK commit; the host pin is recorded, and the fleet library is assumed to match it (disclosed, not verified here).",
        "Constant-VDD settled current only (supply-ramp behavior is out of scope); no mismatch Monte Carlo; no ll/hh axis; no ceiling is proposed.",
        f"{n_total - n_res} of {n_total} point-runs produced no settled-window value (see the table; these are explicit unknowns).",
    ]
    reqs = {n: per[n]["requests"] for n in names}
    record = {
        "record_id": record_id, "kind": "solver-sensitivity replicate (issue #160)", "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "author": args.author or cr.default_author(), "supersedes": args.supersedes,
        "variants": names, "variant_options": {n: sens(man)["variants"][n]["options"] for n in names}, "manifest_sensitivity": sens(man),
        "pdk": {"variant": pdk.variant, "installed_commit": pdk.installed_commit, "pinned_commit": pin["open_pdks_commit"], "matches_pin": pdk.matches_pin, "lib_file": rc.MODEL_LIB + " (resolved on the runner as /opt/pdk/sky130A/...)"},
        "tools": {"ngspice": f"{cr.first_line(['ngspice', '-v'])} (host; the grid ran on the fleet)", "xschem": cr.first_line(["xschem", "--version"]), "platform": cr.tool_versions()["platform"], "python": cr.tool_versions()["python"], "klt_client": meta["klt_client"]},
        "git": gi, "run_git": meta["git"],
        "provenance": {"dut_sha256": meta["dut_sha256"], "testbench_sha256": meta["testbench_sha256"], "manifest_sha256": meta["manifest_sha256"], "hashes": meta.get("hashes", {})},
        "fleet_pdk_note": "the fleet runner does not report its PDK commit; the host pin is " + pin["open_pdks_commit"] + " and the runner resolves the library under /opt/pdk/sky130A (commit unavailable, not verified)",
        "fleet_note": f"jobs { {n: reqs[n].get('job_id') for n in names} }; runner klt {', '.join(sorted({reqs[n].get('runner_klt_version') for n in names if reqs[n].get('runner_klt_version')})) or 'unknown'}; fleet ngspice {', '.join(ngs) or 'unknown'}; client {meta['klt_client']}; batch.runner_version_check=warn",
        "requests": reqs, "points": {n: per[n]["points"] for n in names}, "comparison": cmp_, "baseline_vs_original_text": bvo, "limitations": limits,
        "original_record": "sim/iq-top/records/20261009-191705-df85523.json",
        "links": {"record": f"sim/iq-top/records/{record_id}.md", "json": f"sim/iq-top/records/{record_id}.json", "corners_dir": f"sim/iq-top/corners/{record_id}/", "netlist_snapshots": f"sim/iq-top/netlist-snapshots/{record_id}/",
                  "driver": "sim/iq-top/run_iq_sensitivity.py", "manifest": "sim/iq-top/experiment.json", "original_record": "sim/iq-top/records/20261009-191705-df85523.md"},
    }
    rec_dir.mkdir(parents=True, exist_ok=True)
    (rec_dir / f"{record_id}.json").write_text(json.dumps(record, indent=1, sort_keys=True, default=float) + "\n")
    (rec_dir / f"{record_id}.md").write_text(render_md(record))
    print(f"record {record_id}: {cmp_['summary']['per_variant_counts']}; classes {cmp_['summary']['classes']}; dirty={gi['dirty']}")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--variant", action="append")
    r.add_argument("--jobs", type=int, default=2)
    r.add_argument("--run-id")
    r.add_argument("--retry-failed", action="store_true")
    r.add_argument("--capacity-wait", type=float, default=0)
    r.add_argument("--allow-dirty", action="store_true")
    r.add_argument("--process", action="append", help="with --split-process: resubmit only these MOS corners (e.g. after a fleet capacity refusal)")
    r.add_argument("--split-process", action="store_true", help="one fleet request per MOS corner (9 points each) for a variant whose single 45-corner job exceeds the fleet wall-clock ceiling")
    c = sub.add_parser("record")
    c.add_argument("--run-id", required=True)
    c.add_argument("--author")
    c.add_argument("--supersedes")
    args = ap.parse_args(argv)
    return {"run": cmd_run, "record": cmd_record}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
