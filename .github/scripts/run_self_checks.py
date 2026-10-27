#!/usr/bin/env python3
"""Run the `run:` steps of .github/workflows/self-checks.yml locally.

The workflow is the single source of truth: this reads its steps (stdlib
only, no YAML parser) and executes each one from the repo root, so
`npm run check:ci` cannot drift from, or pass without running, CI's checks.
Steps guarded by an `if:` (push-only baseline fetch) are skipped.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "self-checks.yml"


def steps(text):
    """Yield (name, script) for each unguarded step with a `run:` key."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = re.match(r"^(\s*)- (?:name: (.*)|(\w+):.*)$", lines[i])
        if not m:
            i += 1
            continue
        indent = len(m.group(1))
        j = i + 1
        while j < len(lines) and not re.match(rf"^\s{{{indent}}}- ", lines[j]) \
                and (not lines[j].strip() or len(lines[j]) - len(lines[j].lstrip()) > indent):
            j += 1
        block = lines[i:j]
        i = j
        name = m.group(2) or "(unnamed)"
        if any(re.match(r"^\s+(- )?if:", b) for b in block):
            continue
        for k, b in enumerate(block):
            rm = re.match(r"^(\s+)(?:- )?run:\s*(.*)$", b)
            if not rm:
                continue
            if rm.group(2) in ("|", ">", "|-"):
                body = []
                for c in block[k + 1:]:
                    body.append(c.strip())
                yield name, "\n".join(x for x in body if x)
            else:
                yield name, rm.group(2)
            break


def local_baseline():
    """Merge base with origin/main, standing in for CI's event baseline."""
    for ref in ("origin/main", "main"):
        r = subprocess.run(["git", "merge-base", "HEAD", ref], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout.strip()
    return None


def main():
    found = list(steps(WORKFLOW.read_text()))
    if not found:
        print(f"error: no run steps parsed from {WORKFLOW}", file=sys.stderr)
        return 2
    failed = []
    for name, script in found:
        if ("check_records_append_only.py" in script and "--selftest" not in script
                and not os.environ.get("GITHUB_EVENT_NAME")):
            base = local_baseline()
            if base is None:
                print(f"==> {name}\nFAILED: no origin/main or main to baseline against",
                      file=sys.stderr)
                failed.append(name)
                continue
            script += f" --baseline {base}"
        print(f"==> {name}", flush=True)
        if subprocess.run(["bash", "-e", "-c", script], cwd=ROOT).returncode:
            failed.append(name)
    print(f"\n{len(found) - len(failed)}/{len(found)} self-check steps passed")
    for n in failed:
        print(f"FAILED: {n}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
