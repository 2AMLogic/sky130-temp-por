#!/usr/bin/env python3
"""Compare the per-rail PEX ramp grid (issue #521) with the fixed-2.64 V baseline.

Pure standard library.  Reads the three committed ``klt pex`` reports of
record ``20261126-122246-6640c3df`` (one per supply rail, each grading release
at its own literal ``0.8 x rail`` RESETn crossing) and the baseline 5x3x3
report of record ``20261124-092216-9307a231`` (every rail graded at 2.64 V),
joins their ramp rows on (corner, measurement), and writes beside itself:

* ``group-a-recovery.tsv`` -- the baseline group-A error rows (no 2.64 V
  crossing in 30 ms), one line per (corner, measurement), with the baseline
  and new delta status, both leg statuses on each run, and the new values.
* ``ramp-grid-comparison.tsv`` -- every ramp row (45 corners x 2 measurements).
* ``summary.json`` -- the counts the record's README quotes.

Fail closed: the coverage checks run before anything is written.  A report with
a backend failure, a rail whose rows do not match its committed request, a
missing or duplicated (corner, measurement) pair, or a new key set that differs
from the baseline's exits 1 and writes nothing.

Usage:
  compare_ramp_grid.py            derive the three files beside this script
  compare_ramp_grid.py --check    re-derive and byte-compare with the committed
                                  files; exit 1 on drift
  compare_ramp_grid.py --selftest synthetic reports; no repo files are read or written
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import csv
import hashlib
import io
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

MEASUREMENTS = ("t_release_v_ih", "vdd_at_release")
SIDES = ("schematic", "extracted")
RAILS = {"2p970": "2.970V", "3p300": "3.300V", "3p630": "3.630V"}
COMBOS_PER_RAIL = 15
GROUP_A_ROWS = 24
BASELINE_RECORD = "20261124-092216-9307a231"
REQUEST_RECORD = "20261126-073411-84645d06"
EXPECTED_REQUESTS = {
    "baseline": f"layout/temp_por_top/pex/records/{BASELINE_RECORD}/pextb-grid/request-ramp.json",
    **{rail: f"layout/temp_por_top/pex/records/{REQUEST_RECORD}/pextb-grid/request-ramp-{rail}.json" for rail in RAILS},
}
DEFAULTS = {
    "baseline_report": f"../../{BASELINE_RECORD}/grid/klt-pex.report.json",
    "baseline_groups": f"../../{BASELINE_RECORD}/diagnosis-454/error-rows.tsv",
    "reports": {rail: f"../grid-{rail}/klt-pex.report.json" for rail in RAILS},
}
OUTPUTS = ("group-a-recovery.tsv", "ramp-grid-comparison.tsv", "summary.json")
PROC_ORDER = {"tt": 0, "ss": 1, "ff": 2, "sf": 3, "fs": 4}
TEMP_ORDER = {"-40C": 0, "27C": 1, "125C": 2}
STATUS_COLUMNS = (
    "status",
    "schematic_status",
    "extracted_status",
    "schematic_value",
    "extracted_value",
)
LEG_COLUMNS = ("schematic_leg", "extracted_leg")
GROUP_A_COLUMNS = (
    "corner",
    "measurement",
    "rail",
    *(f"baseline_{c}" for c in STATUS_COLUMNS),
    *(f"new_{c}" for c in STATUS_COLUMNS),
    "new_schematic_codes",
    "new_extracted_codes",
    "new_error_side",
    "new_error_code",
    "change",
    *LEG_COLUMNS,
)
GRID_COLUMNS = ("corner", "measurement", "rail", "baseline_group", *GROUP_A_COLUMNS[3:])


def measurement_of(spec_row: str) -> str:
    """`request-ramp.t_release_v_ih` (several testbenches) or bare `t_release_v_ih`."""
    return spec_row.split(".", 1)[1] if "." in spec_row else spec_row


def row_key(row: dict) -> tuple[str, str]:
    return (row["corner_id"], measurement_of(row["spec_row"]))


def ramp_rows(delta: list[dict]) -> list[dict]:
    return [row for row in delta if measurement_of(row["spec_row"]) in MEASUREMENTS]


def split_corner(corner: str) -> tuple[str, str, str]:
    """`sf/2.970V/-40C` -> (`sf`, `2.970V`, `-40C`); an unparsable id is its own supply."""
    parts = corner.split("/")
    return (parts[0], parts[1], parts[2]) if len(parts) == 3 else ("", corner, "")


def order_key(key: tuple[str, str]) -> tuple[int, int, int, int]:
    proc, volt, temp = split_corner(key[0])
    volts = list(RAILS.values())
    return (
        volts.index(volt) if volt in volts else len(volts),
        PROC_ORDER.get(proc, len(PROC_ORDER)),
        TEMP_ORDER.get(temp, len(TEMP_ORDER)),
        MEASUREMENTS.index(key[1]) if key[1] in MEASUREMENTS else len(MEASUREMENTS),
    )


def status_change(before: str, after: str) -> str:
    if before == after:
        return "unchanged"
    if after == "pass":
        return "recovered"
    if before == "pass":
        return "regressed"
    return f"changed:{before}->{after}"


def ramp_testbench(report: dict) -> dict:
    for testbench in report.get("testbenches", []):
        if set(MEASUREMENTS) <= set(testbench.get("measurement_names", [])):
            return testbench
    return {}


def side_codes(testbench: dict) -> dict[tuple[str, str], str]:
    """(corner, side) -> `+`-joined diagnostic codes of that leg's corner."""
    codes: dict[tuple[str, str], str] = {}
    for side in SIDES:
        for corner in testbench.get("sides", {}).get(side, {}).get("corners", []):
            codes[(corner["corner_id"], side)] = "+".join(d.get("code", "") for d in corner.get("diagnostics", []))
    return codes


def check_request(
    testbench: dict,
    expected_path: str,
    expected_sha256: str | None,
    label: str,
) -> list[str]:
    """Verify the report's recorded request path, scope, and sha256 against the expected request."""
    errs: list[str] = []
    req = testbench.get("request")
    if not isinstance(req, dict):
        errs.append(f"{label}: missing request metadata")
    else:
        rec_path = req.get("path")
        if not isinstance(rec_path, str) or not rec_path:
            errs.append(f"{label}: missing request.path")
        elif rec_path != expected_path:
            errs.append(f"{label}: request.path is {rec_path!r}, expected {expected_path!r}")
        if req.get("scope") != "repo":
            errs.append(f"{label}: request.scope is {req.get('scope')!r}, expected 'repo'")
    raw_digest = testbench.get("request_sha256")
    recorded = raw_digest.removeprefix("sha256:") if isinstance(raw_digest, str) else ""
    if len(recorded) != 64 or any(ch not in "0123456789abcdef" for ch in recorded):
        errs.append(f"{label}: missing or invalid request_sha256")
        recorded = ""
    if not expected_sha256 or len(expected_sha256) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha256):
        errs.append(f"{label}: expected request_sha256 unavailable")
    elif recorded and recorded != expected_sha256:
        errs.append(f"{label}: request_sha256 differs from the committed request")
    return errs


def check_report(report: dict, rail: str, request_sha256: str | None, label: str) -> list[str]:
    """Coverage and live-run checks for one single-rail report; [] when it passes."""
    if rail not in RAILS:
        return [f"{label}: unknown rail {rail!r}"]
    volt = RAILS[rail]
    errs: list[str] = []
    if report.get("backend_failure") is not None:
        errs.append(f"{label}: backend_failure is set, so this is not a live run")
    unfinished = report.get("unfinished") or []
    if unfinished:
        errs.append(f"{label}: {len(unfinished)} unfinished row(s)")
    rows = ramp_rows(report.get("delta", []))
    seen = Counter(row_key(r) for r in rows)
    dup = sorted(k for k, n in seen.items() if n > 1)
    if dup:
        errs.append(f"{label}: duplicated (corner, measurement) pairs {dup}")
    keys = set(seen)
    volts = sorted({split_corner(k[0])[1] for k in keys})
    if volts != [volt]:
        errs.append(f"{label}: supply column(s) {volts}, expected [{volt}]")
    combos = {(split_corner(k[0])[0], split_corner(k[0])[2]) for k in keys}
    if len(combos) != COMBOS_PER_RAIL or len(keys) != 2 * COMBOS_PER_RAIL:
        errs.append(
            f"{label}: {len(combos)} process/temperature combinations and {len(keys)} "
            f"(corner, measurement) pairs, expected {COMBOS_PER_RAIL} and {2 * COMBOS_PER_RAIL}"
        )
    ramp_tbs = [tb for tb in report.get("testbenches", []) if set(MEASUREMENTS) <= set(tb.get("measurement_names", []))]
    if len(ramp_tbs) != 1 or len(report.get("testbenches", [])) != 1:
        errs.append(f"{label}: expected exactly one ramp testbench")
        return errs
    testbench = ramp_tbs[0]
    if testbench.get("measurement_names") != list(MEASUREMENTS):
        errs.append(f"{label}: measurement_names {testbench.get('measurement_names')}")
    errs += check_request(testbench, EXPECTED_REQUESTS[rail], request_sha256, label)
    corners = sorted({k[0] for k in keys})
    for side in SIDES:
        leg = testbench.get("sides", {}).get(side, {})
        if sorted(c["corner_id"] for c in leg.get("corners", [])) != corners:
            errs.append(f"{label}: {side} leg does not report the same {len(corners)} corners")
        remote = leg.get("environment", {}).get("remote", {})
        fleet = remote.get("fleet", [])
        job_ids = remote.get("job_ids", [])
        if not job_ids or sorted(f.get("job_id", "") for f in fleet) != sorted(job_ids):
            errs.append(f"{label}: {side} leg fleet[] and job_ids disagree or are empty")
        if any(not f.get("client_collected_at") for f in fleet):
            errs.append(f"{label}: {side} leg has an uncollected fleet job")
    return errs


def check_baseline(report: dict, request_sha256: str | None) -> list[str]:
    errs: list[str] = []
    if report.get("backend_failure") is not None:
        errs.append("baseline: backend_failure is set")
    unfinished = report.get("unfinished") or []
    if unfinished:
        errs.append(f"baseline: {len(unfinished)} unfinished row(s)")
    rows = ramp_rows(report.get("delta", []))
    seen = Counter(row_key(r) for r in rows)
    dup = sorted(k for k, n in seen.items() if n > 1)
    if dup:
        errs.append(f"baseline: duplicated (corner, measurement) pairs {dup}")
    if len(seen) != 3 * COMBOS_PER_RAIL * len(MEASUREMENTS):
        errs.append(f"baseline: {len(seen)} unique ramp pairs, expected 90")
    ramp_tbs = [tb for tb in report.get("testbenches", []) if set(MEASUREMENTS) <= set(tb.get("measurement_names", []))]
    if len(ramp_tbs) != 1:
        errs.append("baseline: expected exactly one ramp testbench")
        return errs
    testbench = ramp_tbs[0]
    if testbench.get("measurement_names") != list(MEASUREMENTS):
        errs.append(f"baseline: measurement_names {testbench.get('measurement_names')}")
    errs += check_request(testbench, EXPECTED_REQUESTS["baseline"], request_sha256, "baseline")
    corners = sorted({k[0] for k in seen})
    for side in SIDES:
        leg = testbench.get("sides", {}).get(side, {})
        if sorted(c["corner_id"] for c in leg.get("corners", [])) != corners:
            errs.append(f"baseline: {side} leg does not report the same {len(corners)} corners")
    return errs


def read_groups(lines) -> dict[tuple[str, str], str]:
    """(corner, measurement) -> group letter, for every row of an error-rows.tsv stream.

    Rows of other testbenches are kept and ignored by `analyze`, as the baseline
    diagnosis lists the Iq rows beside the ramp ones.  Raises ValueError on a
    duplicated (corner, measurement) key.
    """
    groups: dict[tuple[str, str], str] = {}
    for row in csv.DictReader(lines, delimiter="\t"):
        key = (row["corner"], row["measurement"])
        if key in groups:
            raise ValueError(f"baseline_groups: duplicated (corner, measurement) pair {key}")
        groups[key] = row["group"].split(" ", 1)[0]
    return groups


def analyze(baseline: dict, groups: dict[tuple[str, str], str], new: dict[str, dict]) -> dict:
    """Join the baseline ramp rows with the per-rail rows; never raises for a gap."""
    old_rows = ramp_rows(baseline.get("delta", []))
    old_seen = Counter(row_key(r) for r in old_rows)
    old_dup = sorted(k for k, n in old_seen.items() if n > 1)
    old = {row_key(r): r for r in old_rows if old_seen[row_key(r)] == 1}

    fresh_rows = [(rail, row) for rail in RAILS for row in ramp_rows(new[rail].get("delta", []))]
    fresh_seen = Counter(row_key(row) for _, row in fresh_rows)
    fresh_dup = sorted(k for k, n in fresh_seen.items() if n > 1)
    fresh = {row_key(row): (rail, row) for rail, row in fresh_rows if fresh_seen[row_key(row)] == 1}

    new_codes = {rail: side_codes(ramp_testbench(report)) for rail, report in new.items()}
    ramp_groups = {k: g for k, g in groups.items() if k[1] in MEASUREMENTS}
    errors: list[str] = []
    if old_dup:
        errors.append(f"baseline: duplicated (corner, measurement) pairs {old_dup}")
    if fresh_dup:
        errors.append(f"new: duplicated (corner, measurement) pairs {fresh_dup}")
    old_keys = set(old_seen)
    fresh_keys = set(fresh_seen)
    errors += [f"baseline ramp row {k} is absent from the new reports" for k in sorted(old_keys - fresh_keys)]
    errors += [f"new ramp row {k} is absent from the baseline report" for k in sorted(fresh_keys - old_keys)]
    errors += [
        f"group-{ramp_groups[k]} row {k} is not an error row of the baseline report"
        for k in sorted(ramp_groups)
        if k in old and old[k].get("status", "pass") == "pass"
    ]

    def entry(key: tuple[str, str]) -> dict:
        before = old[key]
        rail, after = fresh[key]
        error = after.get("error") or {}
        row = {"corner": key[0], "measurement": key[1], "rail": rail}
        for run, source in (("baseline", before), ("new", after)):
            for column in STATUS_COLUMNS:
                row[f"{run}_{column}"] = source.get(column)
        row["new_schematic_codes"] = new_codes[rail].get((key[0], "schematic"), "")
        row["new_extracted_codes"] = new_codes[rail].get((key[0], "extracted"), "")
        row["new_error_side"] = error.get("side", "")
        row["new_error_code"] = error.get("code", "")
        row["change"] = status_change(before["status"], after["status"])
        for side in SIDES:
            row[f"{side}_leg"] = status_change(before[f"{side}_status"], after[f"{side}_status"])
        return row

    ordered = sorted(old, key=order_key)
    joined = [k for k in ordered if k in fresh]
    group_a = [entry(k) | {"baseline_group": "A"} for k in joined if groups.get(k) == "A"]
    grid = [entry(k) | {"baseline_group": groups.get(k, "pass")} for k in joined]
    summary = summarize(grid, group_a, baseline, new)
    summary["coverage"] = {
        "baseline_ramp_rows": len(old_rows),
        "new_rows": len(fresh_rows),
        "new_unique_pairs": len(fresh_keys),
        "keys_equal": not old_dup and not fresh_dup and old_keys == fresh_keys,
        "per_rail": summary["coverage"]["per_rail"],
    }
    return {"grid": grid, "group_a": group_a, "errors": errors, "summary": summary}


def summarize(grid: list[dict], group_a: list[dict], baseline: dict, new: dict[str, dict]) -> dict:
    """Counts over delta rows (90) and over each leg's corners (45); every map is key-sorted."""

    def tally(values) -> dict:
        return dict(sorted(Counter(values).items()))

    def leg_corners(report: dict, side: str) -> Counter:
        corners = ramp_testbench(report).get("sides", {}).get(side, {}).get("corners", [])
        return Counter(c["status"] for c in corners)

    non_pass = [r for r in group_a if r["new_status"] != "pass"]
    regressed = [r for r in grid if r["change"] == "regressed"]
    baseline_pass = [r for r in grid if r["baseline_status"] == "pass"]

    def leg_shift(row: dict, side: str) -> str:
        before, after = row[f"baseline_{side}_value"], row[f"new_{side}_value"]
        if before == after:
            return "legs_identical"
        return "legs_new_lower" if after < before else "legs_new_higher"

    value_shift = {}
    for rail in RAILS:
        rows = [r for r in grid if r["rail"] == rail and r["baseline_status"] == "pass" and r["new_status"] == "pass"]
        shifts = Counter(leg_shift(r, side) for r in rows for side in SIDES)
        value_shift[rail] = {
            "rows_pass_in_both_runs": len(rows),
            **{k: shifts.get(k, 0) for k in ("legs_identical", "legs_new_lower", "legs_new_higher")},
        }
    per_rail = {}
    for rail, report in new.items():
        legs = ramp_testbench(report).get("sides", {})
        per_rail[rail] = {
            "volt": RAILS[rail],
            "rows": len(ramp_rows(report.get("delta", []))),
            "passed": report.get("passed"),
            "failed": report.get("failed"),
            "errored": report.get("errored"),
            "job_ids": {
                side: legs.get(side, {}).get("environment", {}).get("remote", {}).get("job_ids", []) for side in SIDES
            },
        }
    corner_leg_status = {}
    for side in SIDES:
        corner_leg_status[f"baseline_{side}"] = tally(leg_corners(baseline, side).elements())
        merged = sum((leg_corners(report, side) for report in new.values()), Counter())
        corner_leg_status[f"new_{side}"] = tally(merged.elements())
    return {
        "schema_version": 1,
        "inputs": {
            "baseline_report": DEFAULTS["baseline_report"],
            "baseline_groups": DEFAULTS["baseline_groups"],
            "new_reports": DEFAULTS["reports"],
        },
        "coverage": {
            "per_rail": per_rail,
        },
        "group_a": {
            "rows": len(group_a),
            "corners": len({r["corner"] for r in group_a}),
            "recovered": sum(r["new_status"] == "pass" for r in group_a),
            "non_pass": len(non_pass),
            "non_pass_new_schematic_status": tally(r["new_schematic_status"] for r in non_pass),
            "non_pass_new_extracted_status": tally(r["new_extracted_status"] for r in non_pass),
            "non_pass_new_extracted_codes": tally(r["new_extracted_codes"] for r in non_pass),
            "legs_recovered": [
                [r["corner"], r["measurement"], side]
                for r in group_a
                for side in SIDES
                if r[f"{side}_leg"] == "recovered"
            ],
            "legs_regressed": [
                [r["corner"], r["measurement"], side]
                for r in group_a
                for side in SIDES
                if r[f"{side}_leg"] == "regressed"
            ],
        },
        "regressions": {
            "baseline_pass_rows": len(baseline_pass),
            "regressed": len(regressed),
            "rows": [
                [
                    r["corner"],
                    r["measurement"],
                    r["new_schematic_status"],
                    r["new_extracted_status"],
                ]
                for r in regressed
            ],
        },
        "row_status": {
            "baseline": tally(r["baseline_status"] for r in grid),
            "new": tally(r["new_status"] for r in grid),
        },
        "corner_leg_status": corner_leg_status,
        "value_shift": value_shift,
        "changes": tally(r["change"] for r in grid),
    }


def _tsv(columns: tuple[str, ...], rows: list[dict]) -> str:
    lines = ["\t".join(columns)]
    lines += ["\t".join("" if row[c] is None else str(row[c]) for c in columns) for row in rows]
    return "\n".join(lines) + "\n"


def render_group_a(result: dict) -> str:
    return _tsv(GROUP_A_COLUMNS, result["group_a"])


def render_grid(result: dict) -> str:
    return _tsv(GRID_COLUMNS, result["grid"])


def derive(result: dict) -> dict[str, str]:
    """The three output files as text, keyed by file name."""
    return {
        "group-a-recovery.tsv": render_group_a(result),
        "ramp-grid-comparison.tsv": render_grid(result),
        "summary.json": json.dumps(result["summary"], indent=2) + "\n",
    }


def repo_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    raise SystemExit(f"no git checkout root above {start}")


def expected_request_digest(root: Path, rel_path: str, label: str) -> tuple[str | None, list[str]]:
    """sha256 of the expected committed request under ``root``; returns ``(None, [err])`` on read failure."""
    path = root / rel_path
    try:
        data = path.read_bytes()
    except OSError as exc:
        return None, [f"{label}: expected request {path} cannot be read: {exc.strerror}"]
    return hashlib.sha256(data).hexdigest(), []


def selftest() -> int:
    """Synthetic reports: a recovered, a leg-only recovered, an unchanged-error and regressed corners."""
    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if not cond:
            fails.append(name + (": " + detail if detail else ""))

    check("prefixed spec_row", measurement_of("request-ramp.t_release_v_ih") == "t_release_v_ih")
    check("bare spec_row", measurement_of("vdd_at_release") == "vdd_at_release")
    sample = {
        "delta": [
            {"spec_row": "request-ramp.vdd_at_release", "corner_id": "tt/2.970V/27C"},
            {"spec_row": "request-iq-por.iq_por_settled", "corner_id": "tt/2.970V/27C"},
        ]
    }
    check(
        "ramp filter",
        [r["spec_row"] for r in ramp_rows(sample["delta"])] == ["request-ramp.vdd_at_release"],
    )
    check("row key", row_key(sample["delta"][0]) == ("tt/2.970V/27C", "vdd_at_release"))
    check(
        "corner order",
        sorted(
            ["ff/3.300V/27C", "sf/2.970V/-40C", "tt/3.300V/-40C", "sf/2.970V/27C"],
            key=lambda c: order_key((c, MEASUREMENTS[0])),
        )
        == ["sf/2.970V/-40C", "sf/2.970V/27C", "tt/3.300V/-40C", "ff/3.300V/27C"],
    )
    pairs = [
        ("pass", "pass"),
        ("error", "pass"),
        ("pass", "error"),
        ("error", "error"),
        ("fail", "error"),
    ]
    want = ["unchanged", "recovered", "regressed", "unchanged", "changed:fail->error"]
    check("status_change", [status_change(*p) for p in pairs] == want)
    tsv = (
        "group\ttestbench\tmeasurement\tcorner\tfailing_side\n"
        "A no 2.64 V crossing in 30 ms\tramp\tt_release_v_ih\tff/3.300V/125C\textracted\n"
        "B ss op/transient abort (extracted only)\tiq-por\tiq_por_settled\tss/2.970V/-40C\textracted\n"
    )
    parsed = read_groups(io.StringIO(tsv))
    check(
        "read_groups",
        parsed == {("ff/3.300V/125C", "t_release_v_ih"): "A", ("ss/2.970V/-40C", "iq_por_settled"): "B"},
        str(parsed),
    )
    dup_tsv = tsv + "B conflict\tramp\tt_release_v_ih\tff/3.300V/125C\textracted\n"
    try:
        read_groups(io.StringIO(dup_tsv))
        check("read_groups duplicate refused", False, "did not raise ValueError")
    except ValueError as exc:
        check("read_groups duplicate refused", "duplicated" in str(exc), str(exc))

    def side(corners: list[str]) -> dict:
        return {
            "environment": {
                "remote": {
                    "job_ids": ["klt-sim-0"],
                    "fleet": [
                        {"job_id": "klt-sim-0", "state": "done", "client_collected_at": "t"},
                    ],
                }
            },
            "corners": [{"corner_id": c, "status": "pass", "diagnostics": []} for c in corners],
        }

    volt_to_rail = {v: k for k, v in RAILS.items()}

    def report(volt: str, request_sha: str = "0" * 64, request_path: str | None = None) -> dict:
        corners = [f"{p}/{volt}/{t}" for p in ("tt", "ss", "ff", "sf", "fs") for t in ("-40C", "27C", "125C")]
        one = side(corners)
        req_path = request_path if request_path is not None else EXPECTED_REQUESTS[volt_to_rail[volt]]
        return {
            "backend_failure": None,
            "unfinished": [],
            "delta": [
                {
                    "spec_row": m,
                    "corner_id": c,
                    "status": "pass",
                    "schematic_status": "pass",
                    "extracted_status": "pass",
                    "schematic_value": 1.0,
                    "extracted_value": 1.0,
                    "delta_pct": 0.0,
                    "error": None,
                }
                for c in corners
                for m in MEASUREMENTS
            ],
            "testbenches": [
                {
                    "measurement_names": list(MEASUREMENTS),
                    "request": {"path": req_path, "scope": "repo"},
                    "request_sha256": "sha256:" + request_sha,
                    "sides": {"schematic": one, "extracted": copy.deepcopy(one)},
                }
            ],
        }

    def refused(name: str, mutated: dict, needle: str, rail: str = "2p970", digest: str | None = "0" * 64) -> None:
        errs = check_report(mutated, rail, digest, "r")
        check(name, any(needle in e for e in errs), "; ".join(errs))

    good = check_report(report("2.970V"), "2p970", "0" * 64, "r")
    check("valid report", good == [], "; ".join(good))
    bad = report("2.970V")
    bad["backend_failure"] = {"message": "upload failed"}
    refused("backend failure refused", bad, "backend_failure")
    refused("wrong rail refused", report("3.300V"), "expected [2.970V]")
    refused("request digest refused", report("2.970V", "1" * 64), "request_sha256")
    swapped_req = report("2.970V", "1" * 64, request_path=EXPECTED_REQUESTS["3p630"])
    refused(
        "wrong request path refused even when digest matches wrong request",
        swapped_req,
        "request.path",
        digest="1" * 64,
    )
    refused("wrong request path and digest refused", swapped_req, "request_sha256", digest="0" * 64)
    bad_scope = report("2.970V")
    bad_scope["testbenches"][0]["request"]["scope"] = "external"
    refused("wrong request scope refused", bad_scope, "request.scope")
    missing_both = report("2.970V")
    del missing_both["testbenches"][0]["request_sha256"]
    missing_both["testbenches"][0]["request"]["path"] = "missing.json"
    refused(
        "missing recorded and expected digest refused", missing_both, "missing or invalid request_sha256", digest=None
    )
    refused("unavailable expected digest refused", report("2.970V"), "expected request_sha256 unavailable", digest="")
    dup = report("2.970V")
    dup["delta"].append(copy.deepcopy(dup["delta"][0]))
    refused("duplicated pair refused", dup, "duplicated")
    short = report("2.970V")
    short["delta"].pop()
    refused("missing pair refused", short, "expected 15 and 30")
    noside = report("2.970V")
    noside["testbenches"][0]["sides"]["extracted"]["corners"].pop()
    refused("side corner set refused", noside, "extracted leg does not report")
    nojobs = report("2.970V")
    nojobs["testbenches"][0]["sides"]["schematic"]["environment"]["remote"]["fleet"] = []
    refused("empty fleet refused", nojobs, "fleet[] and job_ids disagree")
    late = report("2.970V")
    del late["testbenches"][0]["sides"]["extracted"]["environment"]["remote"]["fleet"][0]["client_collected_at"]
    refused("uncollected job refused", late, "uncollected")
    twotb = report("2.970V")
    twotb["testbenches"].append(copy.deepcopy(twotb["testbenches"][0]))
    refused("two testbenches refused", twotb, "exactly one ramp testbench")
    unfinished = report("2.970V")
    unfinished["unfinished"] = ["x"]
    refused("unfinished refused", unfinished, "unfinished")

    all_corners = [
        f"{p}/{volt}/{t}"
        for volt in RAILS.values()
        for p in ("tt", "ss", "ff", "sf", "fs")
        for t in ("-40C", "27C", "125C")
    ]
    base_tb = copy.deepcopy(report("2.970V", request_path=EXPECTED_REQUESTS["baseline"])["testbenches"][0])
    base_tb["sides"] = {"schematic": side(all_corners), "extracted": side(all_corners)}
    base_rep = {
        "backend_failure": None,
        "unfinished": [],
        "delta": [],
        "testbenches": [base_tb],
    }
    for volt in RAILS.values():
        base_rep["delta"] += report(volt)["delta"]
    check("baseline valid", check_baseline(base_rep, "0" * 64) == [], "; ".join(check_baseline(base_rep, "0" * 64)))
    base_bf = copy.deepcopy(base_rep)
    base_bf["backend_failure"] = {"message": "upload failed"}
    check(
        "baseline failure refused",
        any("backend_failure" in e for e in check_baseline(base_bf, "0" * 64)),
    )
    check(
        "baseline digest refused",
        any("request_sha256" in e for e in check_baseline(base_rep, "1" * 64)),
    )
    base_bad_path = copy.deepcopy(base_rep)
    base_bad_path["testbenches"][0]["request"]["path"] = EXPECTED_REQUESTS["2p970"]
    check(
        "baseline wrong request path refused",
        any("request.path" in e for e in check_baseline(base_bad_path, "0" * 64)),
    )
    base_no_sha = copy.deepcopy(base_rep)
    del base_no_sha["testbenches"][0]["request_sha256"]
    base_no_sha["testbenches"][0]["request"]["path"] = "missing.json"
    base_no_sha_errs = check_baseline(base_no_sha, None)
    check(
        "baseline missing digest and unreadable request refused",
        any("missing or invalid request_sha256" in e for e in base_no_sha_errs)
        and any("expected request_sha256 unavailable" in e for e in base_no_sha_errs),
        "; ".join(base_no_sha_errs),
    )
    base_dup_before = copy.deepcopy(base_rep)
    conflicting = copy.deepcopy(base_dup_before["delta"][0])
    conflicting["status"] = "error"
    base_dup_before["delta"].insert(0, conflicting)
    check(
        "baseline duplicate before original refused",
        any("duplicated" in e for e in check_baseline(base_dup_before, "0" * 64)),
    )
    base_short = copy.deepcopy(base_rep)
    base_short["delta"].pop()
    check(
        "baseline pair count refused",
        any("unique ramp pairs" in e for e in check_baseline(base_short, "0" * 64)),
    )

    a1, a2, a3, a4 = "ff/3.300V/27C", "sf/2.970V/-40C", "tt/3.300V/-40C", "fs/2.970V/125C"
    reg, reg2 = "tt/3.630V/27C", "fs/3.630V/125C"

    def statuses(corner: str, special: dict[str, tuple[str, str]]) -> tuple[str, str]:
        if corner in special:
            return special[corner]
        return ("pass", "error") if corner.startswith("ss/") else ("pass", "pass")

    old_special = {
        a1: ("pass", "error"),
        a2: ("error", "error"),
        a3: ("pass", "error"),
        a4: ("error", "pass"),
    }
    new_special = {
        a1: ("pass", "pass"),
        a2: ("pass", "error"),
        a3: ("pass", "error"),
        a4: ("pass", "error"),
        reg: ("error", "pass"),
        reg2: ("pass", "error"),
    }

    def row(corner: str, meas: str, legs: tuple[str, str], prefix: str = "", shift: float = 0.0) -> dict:
        sch, ext = legs
        status = "pass" if sch == "pass" and ext == "pass" else "error"
        error = None
        if status != "pass":
            failing = "schematic" if sch != "pass" else "extracted"
            error = {"side": failing, "code": "measurement", "message": "synthetic"}
        return {
            "spec_row": f"{prefix}.{meas}" if prefix else meas,
            "corner_id": corner,
            "status": status,
            "schematic_status": sch,
            "extracted_status": ext,
            "schematic_value": round(0.0025 + shift, 6) if sch == "pass" else None,
            "extracted_value": round(0.003 + shift, 6) if ext == "pass" else None,
            "delta_pct": 20.0 if status == "pass" else None,
            "error": error,
        }

    def leg(statuses_by_corner: dict[str, str], corners: list[str]) -> list[dict]:
        return [
            {
                "corner_id": c,
                "status": statuses_by_corner[c],
                "diagnostics": [] if statuses_by_corner[c] == "pass" else [{"code": "measurement"}] * 2,
            }
            for c in corners
        ]

    baseline = {
        "delta": [],
        "testbenches": [{"measurement_names": list(MEASUREMENTS), "sides": {s: side([]) for s in SIDES}}],
    }
    new = {
        rail: {
            "delta": [],
            "testbenches": [{"measurement_names": list(MEASUREMENTS), "sides": {s: side([]) for s in SIDES}}],
        }
        for rail in RAILS
    }
    groups: dict[tuple[str, str], str] = {}
    for rail, volt in RAILS.items():
        corners = [f"{p}/{volt}/{t}" for p in ("tt", "ss", "ff", "sf", "fs") for t in ("-40C", "27C", "125C")]
        old_st = {c: statuses(c, old_special) for c in corners}
        new_st = {c: statuses(c, new_special) for c in corners}
        for i, side_name in enumerate(SIDES):
            old_leg = baseline["testbenches"][0]["sides"][side_name]["corners"]
            new_leg = new[rail]["testbenches"][0]["sides"][side_name]["corners"]
            old_leg += leg({c: old_st[c][i] for c in corners}, corners)
            new_leg += leg({c: new_st[c][i] for c in corners}, corners)
        for c in corners:
            for m in MEASUREMENTS:
                if c in (a1, a2, a3, a4):
                    groups[(c, m)] = "A"
                elif c.startswith("ss/"):
                    groups[(c, m)] = "B"
                baseline["delta"].append(row(c, m, old_st[c], prefix="request-ramp"))
                new[rail]["delta"].append(
                    row(c, m, new_st[c], shift={"2p970": -0.0001, "3p630": 0.0001}.get(rail, 0.0))
                )

    result = analyze(baseline, groups, new)
    s = result["summary"]

    def grid_row(corner: str, meas: str) -> dict:
        return next(r for r in result["grid"] if (r["corner"], r["measurement"]) == (corner, meas))

    check("no errors", result["errors"] == [], str(result["errors"]))
    check("grid rows", len(result["grid"]) == 90)
    r1 = grid_row(a1, "t_release_v_ih")
    check(
        "recovered row",
        (r1["change"], r1["schematic_leg"], r1["extracted_leg"], r1["baseline_group"])
        == ("recovered", "unchanged", "recovered", "A"),
        str(r1),
    )
    r2 = grid_row(a2, "vdd_at_release")
    check(
        "leg-only recovery row",
        (
            r2["change"],
            r2["schematic_leg"],
            r2["extracted_leg"],
            r2["new_schematic_codes"],
            r2["new_extracted_codes"],
            r2["new_error_side"],
            r2["new_error_code"],
        )
        == (
            "unchanged",
            "recovered",
            "unchanged",
            "",
            "measurement+measurement",
            "extracted",
            "measurement",
        ),
        str(r2),
    )
    r4 = grid_row(a4, "t_release_v_ih")
    check(
        "crossed legs row",
        (r4["change"], r4["schematic_leg"], r4["extracted_leg"]) == ("unchanged", "recovered", "regressed"),
        str(r4),
    )
    rr = grid_row(reg, "t_release_v_ih")
    check(
        "regressed row",
        (
            rr["change"],
            rr["schematic_leg"],
            rr["extracted_leg"],
            rr["new_schematic_codes"],
            rr["new_error_side"],
            rr["baseline_group"],
        )
        == ("regressed", "regressed", "unchanged", "measurement+measurement", "schematic", "pass"),
        str(rr),
    )
    plain = grid_row("tt/2.970V/27C", "t_release_v_ih")
    check(
        "plain row",
        (
            plain["baseline_group"],
            plain["change"],
            plain["rail"],
            plain["baseline_schematic_value"],
            plain["new_extracted_value"],
        )
        == ("pass", "unchanged", "2p970", 0.0025, 0.0029),
        str(plain),
    )
    check("group-b label", grid_row("ss/3.630V/125C", "vdd_at_release")["baseline_group"] == "B")
    check(
        "group-a membership",
        {(r["corner"], r["measurement"]) for r in result["group_a"]}
        == {(c, m) for c in (a1, a2, a3, a4) for m in MEASUREMENTS},
    )
    check(
        "group-a rows",
        s["group_a"]["rows"] == 8 and s["group_a"]["corners"] == 4,
        str(s["group_a"]),
    )
    check("group-a recovered", s["group_a"]["recovered"] == 2, str(s["group_a"]))
    check("group-a non-pass", s["group_a"]["non_pass"] == 6, str(s["group_a"]))
    check(
        "group-a non-pass legs",
        s["group_a"]["non_pass_new_schematic_status"] == {"pass": 6}
        and s["group_a"]["non_pass_new_extracted_status"] == {"error": 6}
        and s["group_a"]["non_pass_new_extracted_codes"] == {"measurement+measurement": 6},
        str(s["group_a"]),
    )
    check(
        "group-a legs recovered",
        s["group_a"]["legs_recovered"]
        == [
            [a2, "t_release_v_ih", "schematic"],
            [a2, "vdd_at_release", "schematic"],
            [a4, "t_release_v_ih", "schematic"],
            [a4, "vdd_at_release", "schematic"],
            [a1, "t_release_v_ih", "extracted"],
            [a1, "vdd_at_release", "extracted"],
        ],
        str(s["group_a"]["legs_recovered"]),
    )
    check(
        "group-a legs regressed",
        s["group_a"]["legs_regressed"]
        == [
            [a4, "t_release_v_ih", "extracted"],
            [a4, "vdd_at_release", "extracted"],
        ],
        str(s["group_a"]["legs_regressed"]),
    )
    check(
        "regressions",
        s["regressions"]["baseline_pass_rows"] == 64
        and s["regressions"]["regressed"] == 4
        and s["regressions"]["rows"]
        == [
            [reg, "t_release_v_ih", "error", "pass"],
            [reg, "vdd_at_release", "error", "pass"],
            [reg2, "t_release_v_ih", "pass", "error"],
            [reg2, "vdd_at_release", "pass", "error"],
        ],
        str(s["regressions"]),
    )
    check(
        "changes",
        s["changes"] == {"unchanged": 84, "recovered": 2, "regressed": 4},
        str(s["changes"]),
    )
    check(
        "row status",
        s["row_status"] == {"baseline": {"pass": 64, "error": 26}, "new": {"pass": 62, "error": 28}},
        str(s["row_status"]),
    )
    check(
        "corner leg status",
        s["corner_leg_status"]
        == {
            "baseline_schematic": {"pass": 43, "error": 2},
            "new_schematic": {"pass": 44, "error": 1},
            "baseline_extracted": {"pass": 33, "error": 12},
            "new_extracted": {"pass": 32, "error": 13},
        },
        str(s["corner_leg_status"]),
    )
    check(
        "coverage",
        s["coverage"]["baseline_ramp_rows"] == 90
        and s["coverage"]["new_rows"] == 90
        and s["coverage"]["new_unique_pairs"] == 90
        and s["coverage"]["keys_equal"],
        str(s["coverage"]),
    )
    check(
        "job ids",
        s["coverage"]["per_rail"]["2p970"]["job_ids"] == {"schematic": ["klt-sim-0"], "extracted": ["klt-sim-0"]},
        str(s["coverage"]["per_rail"]),
    )
    check(
        "value shift",
        s.get("value_shift")
        == {
            "2p970": {"rows_pass_in_both_runs": 20, "legs_identical": 0, "legs_new_lower": 40, "legs_new_higher": 0},
            "3p300": {"rows_pass_in_both_runs": 20, "legs_identical": 40, "legs_new_lower": 0, "legs_new_higher": 0},
            "3p630": {"rows_pass_in_both_runs": 20, "legs_identical": 0, "legs_new_lower": 0, "legs_new_higher": 40},
        },
        str(s.get("value_shift")),
    )

    def tsv_row(table: list[list[str]], corner: str, meas: str) -> dict[str, str]:
        header = table[0]
        lines = [r for r in table[1:] if (r[0], r[1]) == (corner, meas)]
        return dict(zip(header, lines[0])) if lines else {}

    ga = list(csv.reader(io.StringIO(render_group_a(result)), delimiter="\t"))
    check(
        "group-a tsv",
        len(ga) == 9 and ga[0] == list(GROUP_A_COLUMNS) and all(len(l) == len(ga[0]) for l in ga),
        str(ga[:2]),
    )
    g2 = tsv_row(ga, a2, "vdd_at_release")
    check(
        "group-a tsv values",
        g2["new_schematic_value"] == "0.0024"
        and g2["new_extracted_value"] == ""
        and g2["change"] == "unchanged"
        and g2["schematic_leg"] == "recovered",
        str(g2),
    )
    gd = list(csv.reader(io.StringIO(render_grid(result)), delimiter="\t"))
    check(
        "grid tsv",
        len(gd) == 91 and gd[0] == list(GRID_COLUMNS) and all(len(l) == len(gd[0]) for l in gd),
        str(gd[:2]),
    )
    check(
        "grid tsv order",
        [(r[0], r[1]) for r in gd[1:3]] == [("tt/2.970V/-40C", "t_release_v_ih"), ("tt/2.970V/-40C", "vdd_at_release")]
        and gd[-1][0] == "fs/3.630V/125C",
        str(gd[1:3]),
    )
    g0 = tsv_row(gd, "tt/2.970V/27C", "vdd_at_release")
    check(
        "grid tsv values",
        g0["baseline_extracted_value"] == "0.003" and g0["new_extracted_value"] == "0.0029",
        str(g0),
    )
    files = derive(result)
    check(
        "outputs",
        sorted(files) == sorted(OUTPUTS) and json.loads(files["summary.json"])["group_a"]["recovered"] == 2,
    )

    gapped = copy.deepcopy(new)
    gapped["3p300"]["delta"].pop()
    gapped["2p970"]["delta"] = [r for r in gapped["2p970"]["delta"] if r["corner_id"] != a2]
    gapped_result = analyze(baseline, groups, gapped)
    check(
        "gap reported, not raised",
        any("absent" in e for e in gapped_result["errors"])
        and len(gapped_result["errors"]) == 3
        and len(gapped_result["grid"]) == 87
        and len(gapped_result["group_a"]) == 6
        and gapped_result["summary"]["coverage"]["keys_equal"] is False,
        str(gapped_result["errors"]),
    )
    misgrouped = dict(groups)
    misgrouped[(reg, "t_release_v_ih")] = "A"
    check(
        "pass row in group A reported",
        any("not an error row" in e for e in analyze(baseline, misgrouped, new)["errors"]),
    )
    with_iq = dict(groups)
    with_iq[("ss/2.970V/27C", "iq_por_settled")] = "B"
    check(
        "non-ramp group row ignored",
        analyze(baseline, with_iq, new)["errors"] == [] and analyze(baseline, with_iq, new)["summary"] == s,
    )
    extra = copy.deepcopy(new)
    extra["3p300"]["delta"].append(row("xx/3.300V/27C", "t_release_v_ih", ("pass", "pass")))
    extra_result = analyze(baseline, groups, extra)
    check(
        "extra new row reported",
        any("absent from the baseline report" in e for e in extra_result["errors"])
        and extra_result["summary"]["coverage"]["keys_equal"] is False
        and extra_result["summary"]["coverage"]["new_unique_pairs"] == 91,
        str(extra_result["errors"]),
    )

    dup_before = copy.deepcopy(baseline)
    dup_after = copy.deepcopy(baseline)
    conflict_row = row("tt/2.970V/27C", "t_release_v_ih", ("error", "error"), prefix="request-ramp")
    dup_before["delta"].insert(0, conflict_row)
    dup_after["delta"].append(copy.deepcopy(conflict_row))
    res_before = analyze(dup_before, groups, new)
    res_after = analyze(dup_after, groups, new)
    check(
        "analyze baseline duplicate order-independent and unjoined",
        any("baseline: duplicated" in e for e in res_before["errors"])
        and res_before["errors"] == res_after["errors"]
        and res_before["grid"] == res_after["grid"]
        and len(res_before["grid"]) == 89
        and res_before["summary"]["coverage"]["keys_equal"] is False,
        f"before={res_before['errors']} after={res_after['errors']}",
    )
    new_dup = copy.deepcopy(new)
    new_dup["3p300"]["delta"].append(row("tt/2.970V/27C", "t_release_v_ih", ("error", "error")))
    res_new_dup = analyze(baseline, groups, new_dup)
    check(
        "analyze cross-rail duplicate reported and unjoined",
        any("new: duplicated" in e for e in res_new_dup["errors"])
        and len(res_new_dup["grid"]) == 89
        and res_new_dup["summary"]["coverage"]["keys_equal"] is False,
        str(res_new_dup["errors"]),
    )

    def quiet_run(comp_dir: Path, root_dir: Path, *, check_mode: bool) -> tuple[int, str, str]:
        out_buf, err_buf = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
            rc = run(comp_dir, root_dir, check=check_mode)
        return rc, out_buf.getvalue(), err_buf.getvalue()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        (tmp_root / ".git").mkdir()
        req_shas: dict[str, str] = {}
        for key, rel_req in EXPECTED_REQUESTS.items():
            req_file = tmp_root / rel_req
            req_file.parent.mkdir(parents=True, exist_ok=True)
            payload = f'{{"id": "{key}"}}\n'.encode()
            req_file.write_bytes(payload)
            req_shas[key] = hashlib.sha256(payload).hexdigest()

        comp_dir = tmp_root / "layout/temp_por_top/pex/records/20261126-122246-6640c3df/comparison"
        comp_dir.mkdir(parents=True, exist_ok=True)

        full_base = copy.deepcopy(baseline)
        full_base["backend_failure"] = None
        full_base["unfinished"] = []
        full_base["testbenches"][0]["request"] = {"path": EXPECTED_REQUESTS["baseline"], "scope": "repo"}
        full_base["testbenches"][0]["request_sha256"] = "sha256:" + req_shas["baseline"]

        full_new: dict[str, dict] = {}
        for rail in RAILS:
            rep = copy.deepcopy(new[rail])
            rep["backend_failure"] = None
            rep["unfinished"] = []
            rep["testbenches"][0]["request"] = {"path": EXPECTED_REQUESTS[rail], "scope": "repo"}
            rep["testbenches"][0]["request_sha256"] = "sha256:" + req_shas[rail]
            full_new[rail] = rep

        ga_corners = [a1, a2, a3, a4] + [c for c in all_corners if c.startswith("ss/")][:8]
        gb_corners = [c for c in all_corners if c.startswith("ss/")][8:]
        err_lines = ["group\ttestbench\tmeasurement\tcorner\tfailing_side"]
        for c in ga_corners:
            for m in MEASUREMENTS:
                err_lines.append(f"A synthetic\tramp\t{m}\t{c}\textracted")
        for c in gb_corners:
            for m in MEASUREMENTS:
                err_lines.append(f"B synthetic\tramp\t{m}\t{c}\textracted")
        groups_text = "\n".join(err_lines) + "\n"

        def reset_tree() -> tuple[Path, Path, dict[str, Path]]:
            for key, rel_req in EXPECTED_REQUESTS.items():
                (tmp_root / rel_req).write_bytes(f'{{"id": "{key}"}}\n'.encode())
            base_path = (comp_dir / DEFAULTS["baseline_report"]).resolve()
            base_path.parent.mkdir(parents=True, exist_ok=True)
            base_path.write_text(json.dumps(full_base), encoding="utf-8")
            groups_path = (comp_dir / DEFAULTS["baseline_groups"]).resolve()
            groups_path.parent.mkdir(parents=True, exist_ok=True)
            groups_path.write_text(groups_text, encoding="utf-8")
            rail_paths: dict[str, Path] = {}
            for rail, rel in DEFAULTS["reports"].items():
                rp = (comp_dir / rel).resolve()
                rp.parent.mkdir(parents=True, exist_ok=True)
                rp.write_text(json.dumps(full_new[rail]), encoding="utf-8")
                rail_paths[rail] = rp
            return base_path, groups_path, rail_paths

        base_path, _, rail_paths = reset_tree()
        rc_write, _, err_write = quiet_run(comp_dir, tmp_root, check_mode=False)
        check("e2e write ok", rc_write == 0, err_write)
        rc_check, out_check, err_check = quiet_run(comp_dir, tmp_root, check_mode=True)
        check("e2e check ok", rc_check == 0 and "match the reports" in out_check, err_check)
        saved_outputs = {name: (comp_dir / name).read_bytes() for name in OUTPUTS}

        # Regression 1a: copy request + request_sha256 from 3.630V report into 2.970V report.
        reset_tree()
        swapped_low = copy.deepcopy(full_new["2p970"])
        swapped_low["testbenches"][0]["request"] = copy.deepcopy(full_new["3p630"]["testbenches"][0]["request"])
        swapped_low["testbenches"][0]["request_sha256"] = full_new["3p630"]["testbenches"][0]["request_sha256"]
        rail_paths["2p970"].write_text(json.dumps(swapped_low), encoding="utf-8")
        rc, _, err = quiet_run(comp_dir, tmp_root, check_mode=True)
        check("e2e cross-rail request swap refused", rc == 1 and "grid-2p970" in err, err)

        # Regression 1b: remove recorded digest and make request unreadable (per-rail and baseline).
        reset_tree()
        no_digest_low = copy.deepcopy(full_new["2p970"])
        del no_digest_low["testbenches"][0]["request_sha256"]
        no_digest_low["testbenches"][0]["request"]["path"] = "layout/missing.json"
        rail_paths["2p970"].write_text(json.dumps(no_digest_low), encoding="utf-8")
        (tmp_root / EXPECTED_REQUESTS["2p970"]).unlink()
        rc, _, err = quiet_run(comp_dir, tmp_root, check_mode=True)
        check("e2e per-rail missing digest and missing file refused", rc == 1 and "grid-2p970" in err, err)

        reset_tree()
        no_digest_base = copy.deepcopy(full_base)
        del no_digest_base["testbenches"][0]["request_sha256"]
        no_digest_base["testbenches"][0]["request"]["path"] = "layout/missing.json"
        base_path.write_text(json.dumps(no_digest_base), encoding="utf-8")
        (tmp_root / EXPECTED_REQUESTS["baseline"]).unlink()
        rc, _, err = quiet_run(comp_dir, tmp_root, check_mode=True)
        check("e2e baseline missing digest and missing file refused", rc == 1 and "baseline:" in err, err)

        # Regression 2: duplicate baseline ramp row with conflicting status before original.
        reset_tree()
        dup_base = copy.deepcopy(full_base)
        bad_copy = copy.deepcopy(dup_base["delta"][0])
        bad_copy["status"] = "error" if bad_copy["status"] == "pass" else "pass"
        dup_base["delta"].insert(0, bad_copy)
        base_path.write_text(json.dumps(dup_base), encoding="utf-8")
        rc, _, err = quiet_run(comp_dir, tmp_root, check_mode=True)
        check("e2e duplicate baseline pair before original refused", rc == 1 and "duplicated" in err, err)
        rc_w, _, _ = quiet_run(comp_dir, tmp_root, check_mode=False)
        check(
            "e2e failed write leaves outputs untouched",
            rc_w == 1 and all((comp_dir / name).read_bytes() == saved_outputs[name] for name in OUTPUTS),
        )

        # Regression 3: CRLF line endings in committed TSVs and JSON caught by byte comparison.
        reset_tree()
        for name in OUTPUTS:
            for other in OUTPUTS:
                (comp_dir / other).write_bytes(saved_outputs[other])
            (comp_dir / name).write_bytes(saved_outputs[name].replace(b"\n", b"\r\n"))
            rc, _, err = quiet_run(comp_dir, tmp_root, check_mode=True)
            check(f"e2e CRLF in {name} refused", rc == 1 and name in err, err)

    if fails:
        print(f"selftest: {len(fails)} FAILED")
        for f in fails:
            print("  -", f)
        return 1
    print("selftest: ok")
    return 0


def run(here: Path, root: Path, *, check: bool) -> int:
    errs: list[str] = []
    try:
        baseline = json.loads((here / DEFAULTS["baseline_report"]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"compare_ramp_grid: baseline report cannot be read: {exc}", file=sys.stderr)
        return 1
    try:
        with (here / DEFAULTS["baseline_groups"]).open(encoding="utf-8", newline="") as handle:
            groups = read_groups(handle)
    except (OSError, ValueError) as exc:
        errs.append(str(exc))
        groups = {}
    new: dict[str, dict] = {}
    for rail, rel in DEFAULTS["reports"].items():
        try:
            new[rail] = json.loads((here / rel).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"compare_ramp_grid: grid-{rail} report cannot be read: {exc}", file=sys.stderr)
            return 1

    base_sha, req_errs = expected_request_digest(root, EXPECTED_REQUESTS["baseline"], "baseline")
    errs += req_errs
    errs += check_baseline(baseline, base_sha)
    for rail, report in new.items():
        label = f"grid-{rail}"
        rail_sha, req_errs = expected_request_digest(root, EXPECTED_REQUESTS[rail], label)
        errs += req_errs
        errs += check_report(report, rail, rail_sha, label)
    listed = [k for k, g in groups.items() if k[1] in MEASUREMENTS and g == "A"]
    if len(listed) != GROUP_A_ROWS:
        errs.append(f"{len(listed)} group-A rows listed, expected {GROUP_A_ROWS}")
    if errs:
        for err in errs:
            print(f"compare_ramp_grid: {err}", file=sys.stderr)
        return 1

    result = analyze(baseline, groups, new)
    summary = result["summary"]
    errs += result["errors"]
    if summary["group_a"]["rows"] != GROUP_A_ROWS:
        errs.append(f"{summary['group_a']['rows']} group-A rows matched, expected {GROUP_A_ROWS}")
    if not summary["coverage"]["keys_equal"]:
        errs.append("the new (corner, measurement) key set differs from the baseline ramp grid")
    if errs:
        for err in errs:
            print(f"compare_ramp_grid: {err}", file=sys.stderr)
        return 1

    files = derive(result)
    if check:
        drift: list[str] = []
        for name, text in files.items():
            target = here / name
            try:
                stored = target.read_bytes()
            except OSError:
                drift.append(name)
                continue
            if stored != text.encode("utf-8"):
                drift.append(name)
        if drift:
            print(
                f"compare_ramp_grid: committed file(s) differ from the reports: {drift}",
                file=sys.stderr,
            )
            return 1
        print("check: committed tables and summary match the reports")
        return 0

    for name, text in files.items():
        (here / name).write_bytes(text.encode("utf-8"))
    ga, rg = summary["group_a"], summary["regressions"]
    print(
        f"group A: {ga['recovered']} of {ga['rows']} delta rows pass; {ga['non_pass']} non-pass rows "
        f"(schematic {ga['non_pass_new_schematic_status']}, extracted {ga['non_pass_new_extracted_status']})"
    )
    print(f"regressions: {rg['regressed']} of {rg['baseline_pass_rows']} baseline pass rows now fail or error")
    print(f"status: baseline rows {summary['row_status']['baseline']}, new rows {summary['row_status']['new']}")
    print("wrote " + ", ".join(OUTPUTS))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--selftest", action="store_true", help="synthetic reports only")
    parser.add_argument("--check", action="store_true", help="compare with the committed files")
    parser.add_argument("--repo-root", type=Path, help="checkout the reports' request paths resolve against")
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    here = Path(__file__).resolve().parent
    root = args.repo_root or repo_root(here)
    return run(here, root, check=args.check)


if __name__ == "__main__":
    sys.exit(main())
