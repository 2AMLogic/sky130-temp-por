#!/usr/bin/env python3
"""CI: spec/README.md's decision-record table must index every DR-*.md with its own status.

Stdlib only. The README states the convention itself ("The table below is the
index of every `DR-*.md` file; the status is copied from each file's own
`Status` line"); this makes it mechanical. For every
spec/decision-records/DR-*.md except TEMPLATE.md (whose Status line is the
literal value menu, not a decision):

  1. spec/README.md must contain a decision-record table row whose FIRST CELL
     names the record's DR-00N stem. A stem mentioned in prose elsewhere does
     not count — a bare presence grep passes even with the row deleted.
  2. That row's status word (the leading backticked word of its third cell)
     must equal the status word on the record's own `- **Status**:` bullet,
     over the vocabulary proposed / ratified / superseded.

The reverse direction is checked too: a table row naming a DR-00N with no
corresponding file fails (a rename or deletion left the index behind).

Usage:
  check_decision_record_index.py              check the real tree
  check_decision_record_index.py --selftest   prove the check fails on each seeded violation, passes on a good tree
"""
import re
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

DR_DIR = "spec/decision-records"
README = "spec/README.md"
STEM_RE = re.compile(r"DR-(\d{3})")
FILE_STATUS_RE = re.compile(r"^\s*-\s*\*\*Status\*\*:\s*(\w+)")
ROW_STATUS_RE = re.compile(r"^`(\w+)`")
VOCABULARY = {"proposed", "ratified", "superseded"}


def file_status(path):
    """Return (status_word, line_number) from the record's `- **Status**:` bullet, or (None, None)."""
    for lineno, line in enumerate(path.read_text().splitlines(), start=1):
        m = FILE_STATUS_RE.match(line)
        if m:
            return m.group(1), lineno
    return None, None


def index_rows(readme_text):
    """Parse the README's table. Returns (rows, malformed): rows are
    (stem, status_word_or_None, line_number) for every row whose first cell
    names a DR-00N; malformed is (line_number, line) for every pipe row that
    does not split into exactly four cells."""
    rows, malformed = [], []
    for lineno, line in enumerate(readme_text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 4:
            malformed.append((lineno, stripped))
            continue
        m = STEM_RE.search(cells[0])
        if not m:
            continue  # header and separator rows skip naturally
        sm = ROW_STATUS_RE.match(cells[2])
        rows.append((m.group(0), sm.group(1) if sm else None, lineno))
    return rows, malformed


def check(records_dir, readme_path):
    """Return a list of (file_for_annotation, message) violations."""
    violations = []
    records = sorted(p for p in records_dir.glob("DR-*.md") if p.name != "TEMPLATE.md")
    if not records:
        violations.append((README, f"no DR-*.md records found under {DR_DIR}/ (fail-closed)"))
        return violations

    rows, malformed = index_rows(readme_path.read_text())
    for lineno, line in malformed:
        violations.append((README, f"line {lineno}: table row does not split into four cells: {line}"))
    indexed = {}
    for stem, status, lineno in rows:
        if stem in indexed:
            violations.append((README, f"line {lineno}: duplicate index row for {stem}"))
        else:
            indexed[stem] = (status, lineno)

    file_stems = set()
    for path in records:
        stem = STEM_RE.match(path.name).group(0)
        file_stems.add(stem)
        status, lineno = file_status(path)
        if status is None:
            violations.append((str(path.relative_to(records_dir.parents[2])), f"{stem}: no `- **Status**:` bullet found (fail-closed)"))
        elif status not in VOCABULARY:
            violations.append((str(path.relative_to(records_dir.parents[2])), f"{stem}: line {lineno}: status word '{status}' is outside the vocabulary {sorted(VOCABULARY)}"))
        if stem not in indexed:
            violations.append((README, f"no index table row names {stem} ({path.name}); a prose mention does not count"))
            continue
        row_status, row_lineno = indexed[stem]
        if row_status is None:
            violations.append((README, f"line {row_lineno}: index row for {stem} has no leading backticked status word"))
        elif status is not None and row_status != status:
            violations.append((README, f"line {row_lineno}: index status '{row_status}' does not match {stem}'s own status '{status}'"))

    for stem, (status, lineno) in sorted(indexed.items()):
        if stem not in file_stems:
            violations.append((README, f"line {lineno}: index row names {stem} but no {DR_DIR}/{stem}-*.md file exists"))
    return violations


def write_record(dr_dir, name, status=None):
    lines = [f"# {name[:-3]}: subject", ""]
    if status:
        lines.append(f"- **Status**: {status} (prose)")
    lines += ["- **Date**: 2026-01-01", ""]
    (dr_dir / name).write_text("\n".join(lines))


def write_readme(root, rows, prose=""):
    lines = ["# spec", "", prose, "", "  | Decision | Subject | Status | README target row(s) addressed |", "  |---|---|---|---|"]
    lines += rows
    (root / "spec" / "README.md").write_text("\n".join(lines) + "\n")


def row(stem, status):
    return f"  | [`{stem}`]({DR_DIR}/{stem}-x.md) | subject | `{status}` (prose) | none |"


def selftest():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        dr_dir = root / "spec" / "decision-records"
        dr_dir.mkdir(parents=True)
        readme = root / "spec" / "README.md"

        # Good tree: every record indexed with a matching status; TEMPLATE.md
        # carries the menu status line and no row and must not fail the check.
        (dr_dir / "TEMPLATE.md").write_text("- **Status**: proposed | ratified | superseded by DR-NNN\n")
        write_record(dr_dir, "DR-001-a.md", "proposed")
        write_record(dr_dir, "DR-002-b.md", "ratified")
        write_readme(root, [row("DR-001", "proposed"), row("DR-002", "ratified")])
        got = check(dr_dir, readme)
        if got:
            print(f"selftest FAILED: good tree reported {got}", file=sys.stderr)
            return 1

        def expect_failure(label, needle):
            got = check(dr_dir, readme)
            if not any(needle in msg for _, msg in got):
                print(f"selftest FAILED: {label} not detected (got {got})", file=sys.stderr)
                return 1
            return 0

        # (a) Unindexed record: DR-003 exists, no row anywhere.
        write_record(dr_dir, "DR-003-c.md", "proposed")
        rc = expect_failure("unindexed record", "no index table row names DR-003")
        dr_dir.joinpath("DR-003-c.md").unlink()

        # (c) Prose-only mention: the #375 false negative a bare grep passes.
        write_record(dr_dir, "DR-003-c.md", "proposed")
        write_readme(root, [row("DR-001", "proposed"), row("DR-002", "ratified")],
                     prose="`DR-001` through `DR-003` are all `proposed` recommendations")
        rc |= expect_failure("prose-only mention", "no index table row names DR-003")
        dr_dir.joinpath("DR-003-c.md").unlink()

        # (b) Index status disagrees with the record's own status.
        write_readme(root, [row("DR-001", "ratified"), row("DR-002", "ratified")])
        rc |= expect_failure("status mismatch", "index status 'ratified' does not match DR-001's own status 'proposed'")

        # Reverse direction: an index row with no file (a rename or deletion).
        write_readme(root, [row("DR-001", "proposed"), row("DR-002", "ratified"), row("DR-009", "proposed")])
        rc |= expect_failure("orphan index row", "index row names DR-009 but no")

        # Fail-closed shapes.
        write_record(dr_dir, "DR-003-c.md", None)
        write_readme(root, [row("DR-001", "proposed"), row("DR-002", "ratified"), row("DR-003", "proposed")])
        rc |= expect_failure("missing Status bullet", "no `- **Status**:` bullet found")

        write_record(dr_dir, "DR-003-c.md", "draft")
        rc |= expect_failure("out-of-vocabulary status", "outside the vocabulary")

        write_record(dr_dir, "DR-003-c.md", "proposed")
        write_readme(root, [row("DR-001", "proposed"), row("DR-002", "ratified"), row("DR-003", "proposed") + " extra |"])
        rc |= expect_failure("malformed row", "does not split into four cells")

        # Fail-closed: no records discovered at all.
        for p in dr_dir.glob("DR-*.md"):
            p.unlink()
        write_readme(root, [])
        got = check(dr_dir, readme)
        if not any("no DR-*.md records found" in msg for _, msg in got):
            print(f"selftest FAILED: empty records dir not fail-closed (got {got})", file=sys.stderr)
            rc = 1
        if rc:
            return 1
    print("selftest ok: each seeded violation detected, good tree passes")
    return 0


def main():
    if "--selftest" in sys.argv[1:]:
        return selftest()
    violations = check(REPO / DR_DIR, REPO / README)
    for path, msg in violations:
        print(f"::error file={path}::{msg}", file=sys.stderr)
    if violations:
        print(f"{len(violations)} decision-record index violation(s)", file=sys.stderr)
        return 1
    records = [p for p in (REPO / DR_DIR).glob("DR-*.md") if p.name != "TEMPLATE.md"]
    print(f"{len(records)}/{len(records)} decision records indexed with matching status")
    return 0


sys.exit(main())
