#!/usr/bin/env python3
"""CI: docs/characterization-report.md must cite every sim/ experiment that has records.

Stdlib only. An experiment is a directory sim/<name>/ whose records/ subdirectory
holds at least one file. It is "cited" when the report contains the path
fragment "sim/<name>/" (markdown links such as ../sim/<name>/records/x.md count).
This checks citation coverage only, not the numbers in the report.

Usage:
  check_characterization_coverage.py              check the real tree
  check_characterization_coverage.py --selftest   prove the check fails on an uncited directory
"""
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def experiments_with_records(sim):
    return sorted(
        d.name
        for d in sim.iterdir()
        if d.is_dir() and (d / "records").is_dir() and any(p.is_file() for p in (d / "records").iterdir())
    )


def uncited(sim, report):
    text = report.read_text()
    return [n for n in experiments_with_records(sim) if f"sim/{n}/" not in text]


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sim = root / "sim"
        for name in ("cited-exp", "uncited-exp"):
            (sim / name / "records").mkdir(parents=True)
            (sim / name / "records" / "r.md").write_text("x")
        (sim / "empty-exp" / "records").mkdir(parents=True)  # no records: never required
        (sim / "bin").mkdir()  # no records dir: never required
        report = root / "report.md"
        report.write_text("see [r](../sim/cited-exp/records/r.md)\n")
        got = uncited(sim, report)
        if got != ["uncited-exp"]:
            print(f"selftest FAILED: expected ['uncited-exp'], got {got}", file=sys.stderr)
            return 1
        report.write_text("../sim/cited-exp/ ../sim/uncited-exp/records/r.md\n")
        if uncited(sim, report):
            print("selftest FAILED: fully cited tree reported uncited", file=sys.stderr)
            return 1
    print("selftest ok: uncited directory detected, cited tree passes")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    sim = REPO / "sim"
    report = REPO / "docs" / "characterization-report.md"
    exps = experiments_with_records(sim)
    if not exps:
        print("no sim experiments with records found", file=sys.stderr)
        return 1
    missing = uncited(sim, report)
    for n in missing:
        print(f"::error file=docs/characterization-report.md::sim/{n}/ has records but is not cited", file=sys.stderr)
    print(f"{len(exps) - len(missing)}/{len(exps)} sim experiments with records cited by the report")
    return 1 if missing else 0


sys.exit(main())
