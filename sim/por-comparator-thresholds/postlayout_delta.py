#!/usr/bin/env python3
"""Post-layout vs schematic delta table (issue #124).  Stdlib only; reads two record JSONs, prints markdown.

usage: postlayout_delta.py <schematic-record.json> <postlayout-record.json>
Every row is one PVT point (process x temperature); deltas = post-layout minus schematic, in mV.
Points that are not OK/rate-consistent on either side are listed with their status, never dropped.
"""
import json
import sys


def main(a, b):
    s, p = (json.load(open(x)) for x in (a, b))
    st = {r["id"]: r for r in s["table"]}
    pt = {r["id"]: r for r in p["table"]}
    print(f"Schematic record `{s['record_id']}` vs post-layout record `{p['record_id']}` (rate {p['manifest_excerpt']['primary_rate']:g} V/s; delta = post-layout - schematic)\n")
    print("| corner (process, T) | VPOR-up sch / pex (V) | dUP (mV) | VPOR-down sch / pex (V) | dDOWN (mV) | hyst sch / pex (mV) | dHYST (mV) | status sch / pex |")
    print("|---|---|---|---|---|---|---|---|")
    d = {"up": [], "dn": [], "hys": []}
    for cid in st:
        x, y = st[cid], pt.get(cid)
        if y is None:
            print(f"| {cid} | - | - | - | - | - | - | {x['status']} / MISSING |")
            continue
        ok = x["status"] == "OK" and y["status"] == "OK"
        if ok:
            du, dd, dh = (y["vup"] - x["vup"]) * 1e3, (y["vdn"] - x["vdn"]) * 1e3, (y["hys"] - x["hys"]) * 1e3
            d["up"].append((du, cid)); d["dn"].append((dd, cid)); d["hys"].append((dh, cid))
            print(f"| {cid} | {x['vup']:.4f} / {y['vup']:.4f} | {du:+.1f} | {x['vdn']:.4f} / {y['vdn']:.4f} | {dd:+.1f} | {x['hys']*1e3:.1f} / {y['hys']*1e3:.1f} | {dh:+.1f} | OK / OK |")
        else:
            print(f"| {cid} | n/a | n/a | n/a | n/a | n/a | n/a | {x['status']} / {y['status']} |")
    print()
    for k, name in (("up", "VPOR-up"), ("dn", "VPOR-down"), ("hys", "hysteresis")):
        if d[k]:
            lo, hi = min(d[k]), max(d[k])
            print(f"- {name} delta over {len(d[k])} comparable points: min {lo[0]:+.1f} mV ({lo[1]}), max {hi[0]:+.1f} mV ({hi[1]})")
    bs, bp = s.get("binding", {}), p.get("binding", {})
    if "vpor_up" in bs and "vpor_up" in bp:
        print(f"- max(VPOR-up): schematic {bs['vpor_up']['max_v']:.4f} V ({bs['vpor_up']['max_corner']}), post-layout {bp['vpor_up']['max_v']:.4f} V ({bp['vpor_up']['max_corner']})")
        if s.get("margin") and p.get("margin"):
            print(f"- margin vs 2.97 V low rail: schematic {s['margin']['margin_mv']:+.0f} mV, post-layout {p['margin']['margin_mv']:+.0f} mV")


if __name__ == "__main__":
    main(*sys.argv[1:3])
