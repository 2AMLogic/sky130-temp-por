#!/usr/bin/env python3
"""CI: every sim experiment.json and every sim/*/records/*.json must parse.

Stdlib only. Exits 1 (listing each offender) on any malformed or missing file.
"""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2] / "sim"
files = sorted(root.glob("*/experiment.json")) + sorted(root.glob("*/records/*.json"))
if not files:
    print("no sim JSON files found", file=sys.stderr)
    sys.exit(1)
bad = 0
for f in files:
    try:
        json.loads(f.read_text())
    except (ValueError, OSError) as exc:
        bad += 1
        print(f"::error file={f.relative_to(root.parent)}::{exc}", file=sys.stderr)
print(f"{len(files) - bad}/{len(files)} sim JSON files well-formed")
sys.exit(1 if bad else 0)
