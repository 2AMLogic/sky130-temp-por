#!/usr/bin/env python3
"""Every evidence record carries ONE canonical append-only trailer (issue #337).

A record's closing block -- the `Links` list, `Timestamp / author`, `Supersedes`, and
the sentence that restates `sim/README.md`'s own append-only rule -- was re-emitted by
hand in ten renderers.  `sim_common.selftest_footer_lines()` had long owned the
*self-test* record's trailer; the evidence record's was the half that never got the
same treatment, and it had drifted into four texts:

  * five copies carried the majority text,
  * three wrote an em dash where the others write `--`,
  * `sim/supply-ramp-top/run_reassert_diagnosis.py` dropped the `(see sim/README.md)`
    pointer, and
  * `sim/iq-top/run_iq_sensitivity.py` truncated it to `Append-only: never edit this
    file.`

So two of ten record classes asserted the append-only policy without pointing a reader
at it, and three had grown their own `Supersedes` fallback wording where
`sim/README.md`'s field table says plainly: "prior `<record-id>` this corrects or
re-runs; `(none)` otherwise".  A committed record can never be corrected in place -- only
superseded -- which is exactly why the sentence stating that rule must not be maintained
in ten places.

This file is the cross-renderer contract, in the shape `test_runner_fleet_pdk.py`
established: ONE table of the renderers that write an evidence record, so an eleventh
cannot quietly reintroduce a private copy, plus source guards that make the
consolidation a mechanism rather than a convention -- every renderer must go through
`sim_common.record_footer_lines()`, none may restate the append-only sentence, and none
may hand-write the `Timestamp / author` or `Supersedes` bullet.

The committed records under `sim/*/records/` are the end-to-end corpus: each one that
its renderer can still re-render is re-rendered from its own `.json` twin and its
trailer checked against the helper.  A record whose renderer resolves a later-added
key by hard subscript cannot re-render at all; those stay valid committed evidence and
are pinned -- missing key and reason -- in `RENDER_EXCLUSIONS` below, a registry
guarded in both directions so the next retroactive breakage (a renderer gaining a
hard subscript, which breaks records already committed) is named rather than absorbed.
Renderers the registry strips of all their records keep trailer coverage through a
synthetic fixture doc built in this file.  Nothing is written, and no record is
rewritten.

Stdlib only: no SPICE, no PDK, no fleet, no records written.

Run: python3 -I sim/bin/test_record_footer.py
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
for _d in ("sim/bias-core-op-branch", "sim/brownout-top", "sim/glitch-top", "sim/iq-top",
           "sim/pnp-mismatch", "sim/por-comparator-thresholds", "sim/supply-ramp-top",
           "sim/bin"):
    sys.path.insert(0, str(REPO_ROOT / _d))

import sim_common  # noqa: E402
import run_brownout_campaign as rb  # noqa: E402
import run_glitch_campaign as rg  # noqa: E402
import run_iq_campaign as riq  # noqa: E402
import run_iq_sensitivity as ris  # noqa: E402
import run_op_branch as rob  # noqa: E402
import run_pnp_mismatch as rpnp  # noqa: E402
import run_ramp_campaign as rr  # noqa: E402
import run_reassert_diagnosis as rrd  # noqa: E402
import run_thresholds_campaign as rth  # noqa: E402

cr = sim_common.load_corner_run()

# The renderers that close an evidence record, keyed by the script path each one names in
# its own `Written by` line -- which is also how a committed record identifies the
# renderer that wrote it, so the corpus below maps onto this table by reading the record.
#
# `run_thresholds_campaign.py` interpolates its own `SLUG`, and `run_iq_sensitivity.py`
# names the `record` subcommand, so both keys are derived rather than written out.
RENDERERS = {
    "sim/bin/corner-run.py": cr.render_record,
    "sim/bias-core-op-branch/run_op_branch.py": rob.render_record,
    "sim/brownout-top/run_brownout_campaign.py": rb.render_md,
    "sim/glitch-top/run_glitch_campaign.py": rg.render_md,
    "sim/iq-top/run_iq_campaign.py": riq.render_md,
    "sim/iq-top/run_iq_sensitivity.py": ris.render_md,
    "sim/pnp-mismatch/run_pnp_mismatch.py": rpnp.render_record,
    f"sim/{rth.SLUG}/run_thresholds_campaign.py": rth.render_md,
    "sim/supply-ramp-top/run_ramp_campaign.py": rr.render_md,
    "sim/supply-ramp-top/run_reassert_diagnosis.py": rrd.render_md,
}

# Where each renderer's source lives, for the source guards (same keys as above).
SOURCES = {name: REPO_ROOT / name for name in RENDERERS}

WRITTEN_BY = re.compile(r"^Written by `([^` ]+)(?: (\w+))?`\. ", re.M)
LINKS_HEAD = re.compile(r"^(## Links|- \*\*Links\*\*:)$", re.M)
LINK_BULLET = re.compile(r"^ {0,2}- [^*]")

# Records that cannot be re-rendered from their own raw `.json` twin: the renderer
# that wrote them resolves a `links` or record key by hard subscript, and the record
# predates that key.  Each one is still valid committed evidence -- append-only means
# nothing here repairs it -- so it is excluded from the round-trip walk below, and the
# exclusion is pinned with the missing key and the reason.  The registry is guarded in
# both directions by `test_the_exclusion_registry_matches_the_corpus_exactly`, so it
# can neither silently grow nor rot:
#
#   * a record that raises and is NOT listed fails the test, naming the record and
#     the key (the old mechanism here was an absorbed `except KeyError: continue`);
#   * an entry that no longer raises fails as a stale allowlist entry; and
#   * the corpus floor is derived from this table's length, so a renderer change that
#     breaks one record cannot net out against another that was fixed.
#
# The set is OPEN, and that is the point: growth comes from a RENDERER gaining a hard
# subscript, which retroactively breaks records already committed -- exactly how the
# two 20261113-160939 entries joined (commit 7023a693, PR #336, added the trailer's
# artifact-store prose the day after those records were committed, and PR #366's
# review absorbed the breakage by widening a backfill while its floor never moved).
# Re-measure before editing: run this file and read the failure, never copy a count.
RENDER_EXCLUSIONS: dict[str, tuple[str, str]] = {
    # record path: (missing key, why the record lacks it)

    # Predating the batch backend: the record body has no `batch` block, and the
    # renderer resolves it by hard key while building the deck-list clause.
    "sim/bias-core-op-branch/records/20260826-001526-f4f73a5.md": (
        "batch", "predates the batch backend; run_op_branch.py resolves r['batch'] by hard key"),
    "sim/pnp-mismatch/records/20260825-220116-a9cac4b.md": (
        "batch", "predates the batch backend; run_pnp_mismatch.py resolves r['batch'] by hard key"),

    # Committed 2026-11-13 by the pre-artifact-store renderer vintage (links carry
    # klt_report / points_dir, not artifact_manifest / artifact_summary); 7023a693
    # added the trailer's artifact-store prose -- with its hard subscript -- the next
    # day, retroactively breaking them.
    "sim/bias-core-op-branch/records/20261113-160939-9211b20a.md": (
        "artifact_manifest",
        "committed by the pre-artifact-store renderer vintage; 7023a693 (PR #336) added "
        "the hard subscript in the trailer's artifact-store prose the day after"),
    "sim/pnp-mismatch/records/20261113-160939-9211b20a.md": (
        "artifact_manifest",
        "committed by the pre-artifact-store renderer vintage; 7023a693 (PR #336) added "
        "the hard subscript in the trailer's artifact-store prose the day after"),

    # Pre-artifact-store `corner-run.py` records: `links` carry `corners_dir`/`manifest`
    # instead, and corner-run.py resolves `links['artifact_manifest']` (and its summary
    # twin) by hard key since the artifact store landed (1285ef82).  One of these was
    # committed 38 minutes AFTER that commit by a worktree branched before it -- a
    # record's schema vintage is not derivable from its own timestamp, which is why
    # these are pinned by path rather than inferred by date.
    "sim/bias-core-smoke/records/20260825-214036-a9cac4b.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/bias-core-smoke/records/20261023-171642-e69f5b2e.md": (
        "artifact_manifest",
        "written by a pre-artifact-store renderer vintage; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/bias-core-startup/records/20260825-235846-f4f73a5.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/bias-core-startup/records/20260826-005156-f4f73a5.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/native-device-characterization/records/20260909-232337-c7b9b94.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/temp-core-startup/records/20260826-053032-ee63b45.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
    "sim/temp-core-startup-en-delayed/records/20260826-054047-ee63b45.md": (
        "artifact_manifest",
        "links predate the artifact store; corner-run.py resolves links['artifact_manifest'] by hard key"),
}

# Renderers whose committed records are ALL in RENDER_EXCLUSIONS, mapped to a record
# whose raw `.json` twin seeds a synthetic fixture doc for them.  The fixture is
# trailer-coverage tooling, not a repair: `fixture_doc()` adds ONLY the missing
# hard-subscript keys, with paths derived from that record's own experiment directory
# and merged so any real value wins.  The committed record on disk stays byte-for-byte
# as committed and still cannot re-render from its raw twin.
FIXTURE_SEEDS: dict[str, str] = {
    "sim/bias-core-op-branch/run_op_branch.py":
        "sim/bias-core-op-branch/records/20261113-160939-9211b20a.md",
}


def fixture_doc(seed: str) -> dict:
    """The seeded record's raw `.json` twin with the artifact-store link keys added.

    The added paths are clearly synthetic (no such bytes are committed) and name the
    record's OWN experiment, so the no-foreign-path contract below holds; the merge
    order means a real value in the record's own `links` always wins.
    """
    md = REPO_ROOT / seed
    doc = json.loads(md.with_suffix(".json").read_text())
    experiment, record_id = seed.split("/")[1], md.stem
    fixture_links = {
        "artifact_manifest": f"sim/{experiment}/corners/{record_id}/batch/manifest.json",
        "artifact_summary": f"sim/{experiment}/corners/{record_id}/batch/summary.md",
    }
    return {**doc, "links": {**fixture_links, **doc["links"]}}

# The only bullets a call site may add to the trailer, both genuinely per-record:
# `sim/glitch-top`'s "no bytes were stored because nothing was graded", and
# `sim/brownout-top`'s "this solver-variant record sits beside, and does not replace,
# the default-deck one".  Anything else in the trailer is a field that belongs in the
# shared helper (or in the record body above it).
ALLOWED_EXTRA_BULLETS = ("- **Evidence bytes**: ", "- **Companion of**: ")

STUB = {
    "links": {"testbench": "sim/x/testbench/tb.sch", "json": "sim/x/records/r.json"},
    "timestamp": "2026-11-14T00:00:00Z",
    "author": "ci@loom.test",
    "supersedes": "",
}


def trailer(text: str) -> str:
    """A record's markdown from its last `Links` heading to the end of the file."""
    heads = list(LINKS_HEAD.finditer(text))
    assert heads, "record has no Links block"
    return text[heads[-1].start():]


def unlinked(lines: list[str]) -> list[str]:
    """`lines` minus the link bullets, whose ORDER follows the `links` dict and so
    follows whether the record's `.json` was written sorted -- not this contract."""
    return [ln for ln in lines if not LINK_BULLET.match(ln)]


def committed_records() -> list[tuple[str, Path, dict]]:
    """`(renderer, md path, record document)` for every committed evidence record.

    The document is the raw `.json` twin, exactly as committed -- no key is injected
    into it anywhere downstream.  Self-test records are excluded: their trailer is
    `selftest_footer_lines()`'s, and the three hand-written records (a fleet timeout, a
    local probe, a fleet refusal) have no `.json` twin and no renderer at all.
    """
    out = []
    for md in sorted(REPO_ROOT.glob("sim/*/records/*.md")):
        js = md.with_suffix(".json")
        if not js.exists():
            continue
        m = WRITTEN_BY.search(md.read_text())
        if not m or m.group(2) == "selftest":
            continue
        name = m.group(1) if m.group(2) is None else f"{m.group(1)} {m.group(2)}"
        name = name.removesuffix(" record")           # run_iq_sensitivity.py record
        if name not in RENDERERS:
            continue
        out.append((name, md, json.loads(js.read_text())))
    return out


def probe_broken(renderer_map: dict) -> dict[str, str]:
    """`{record path: missing key}` for every committed record that raises KeyError
    when its renderer is given the raw `.json` twin.  Any other exception propagates:
    loud, the way a record-level failure should be.
    """
    broken = {}
    for name, md, doc in committed_records():
        render = renderer_map.get(name)
        if render is None:
            continue
        try:
            render(doc)
        except KeyError as e:
            broken[md.relative_to(REPO_ROOT).as_posix()] = e.args[0]
    return broken


def doc_strings(value) -> set[str]:
    """Every string the record document itself carries, at any depth -- the paths a
    trailer may legitimately name because the record itself says so."""
    out: set[str] = set()
    if isinstance(value, str):
        out.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            out |= doc_strings(v)
    elif isinstance(value, list):
        for v in value:
            out |= doc_strings(v)
    return out


class CanonicalTrailerTest(unittest.TestCase):
    """One sentence, one `Supersedes` fallback, and the layout knobs that stay knobs."""

    def test_the_sentence_restates_the_rule_and_points_at_the_normative_source(self):
        s = sim_common.RECORD_APPEND_ONLY
        self.assertIn("never edit this file", s)
        self.assertIn("`Supersedes` field", s)
        self.assertIn("(see `sim/README.md`)", s,
                      "a record that asserts the append-only policy must point at it")
        self.assertNotIn("—", s, "the majority text writes `--`, not an em dash")

    def test_the_readme_pointer_is_not_a_dangling_reference(self):
        """The whole value of the pointer is that it resolves."""
        readme = (REPO_ROOT / "sim" / "README.md").read_text()
        self.assertIn("### Append-only rule", readme)
        self.assertIn("`(none)` otherwise", readme,
                      "the `Supersedes` fallback below is quoted from this table")

    def test_supersedes_falls_back_to_the_word_the_readme_ratifies(self):
        """Three renderers had grown their own fallback; `sim/README.md`'s field table
        defines exactly one, and a record is evidence against that table."""
        self.assertIn("- **Supersedes**: (none)",
                      sim_common.record_footer_lines(STUB, "s.py"))
        prior = {**STUB, "supersedes": "20260825-214036-a9cac4b"}
        self.assertIn("- **Supersedes**: 20260825-214036-a9cac4b",
                      sim_common.record_footer_lines(prior, "s.py"))

    def test_the_trailer_ends_with_the_sentence_and_a_final_blank_line(self):
        got = sim_common.record_footer_lines(STUB, "sim/x/run_x.py")
        self.assertEqual(got[-1], "")
        self.assertEqual(got[-2], f"Written by `sim/x/run_x.py`. {sim_common.RECORD_APPEND_ONLY}")
        self.assertEqual(got[-3], "", "a blank line separates the trailer from the fields")

    def test_flat_and_nested_differ_in_layout_only(self):
        """`nested=True` is the three renderers that fold the block into the bullet list
        above it.  Layout is not policy, so it is preserved -- but it may not change one
        word of what the trailer says."""
        flat = sim_common.record_footer_lines(STUB, "s.py")
        nest = sim_common.record_footer_lines(STUB, "s.py", nested=True)
        self.assertEqual(flat[0], "## Links")
        self.assertEqual(nest[0], "- **Links**:")
        self.assertEqual(unlinked(flat)[1:], unlinked(nest)[1:])
        self.assertEqual([ln.strip() for ln in flat[1:3]], [ln.strip() for ln in nest[1:3]])
        self.assertTrue(all(ln.startswith("  - ") for ln in nest[1:3]), nest[1:3])

    def test_prose_labels_replace_the_json_keys_without_touching_the_rest(self):
        """Two renderers label their links in prose (`Testbench:`) rather than by JSON
        key, which is why `links` is an override and not a second trailer."""
        got = sim_common.record_footer_lines(
            STUB, "s.py", nested=True,
            links=[("Testbench", "sim/x/testbench/tb.sch"), ("Machine-readable record", "r.json")])
        self.assertIn("  - Testbench: `sim/x/testbench/tb.sch`", got)
        self.assertIn("  - Machine-readable record: `r.json`", got)
        self.assertEqual(unlinked(got),
                         unlinked(sim_common.record_footer_lines(STUB, "s.py", nested=True)))

    def test_a_bare_string_link_is_one_pre_written_bullet_at_its_position(self):
        """`run_op_branch.py`'s artifact-store link is a sentence covering several
        stored objects, not a `label: value` pair; it passes through with the same
        bullet the pairs get and holds its place in the list order."""
        got = sim_common.record_footer_lines(
            STUB, "s.py", nested=True,
            links=[("Testbench", "tb.sch"),
                   "the raw logs and the deck report are stored objects",
                   ("Machine-readable record", "r.json")])
        self.assertEqual(got[2], "  - the raw logs and the deck report are stored objects")
        self.assertEqual(got[3], "  - Machine-readable record: `r.json`")
        self.assertEqual(unlinked(got),
                         unlinked(sim_common.record_footer_lines(STUB, "s.py", nested=True)))

    def test_an_empty_link_value_is_stated_not_rendered_as_empty_backticks(self):
        """A link the run could not produce (nothing graded, so no artifacts stored) says
        so; `` `` `` would read as a path the reader simply cannot see."""
        rec = {**STUB, "links": {"artifact_manifest": "", "json": "sim/x/records/r.json"}}
        got = sim_common.record_footer_lines(rec, "s.py")
        self.assertIn("- artifact_manifest: none", got)
        self.assertNotIn("- artifact_manifest: ``", got)

    def test_the_two_extra_hooks_land_at_their_own_positions(self):
        """`after_links` qualifies the links; `after_supersedes` qualifies `Supersedes`.
        A record's field ORDER is part of its format, so one hook cannot serve both."""
        got = sim_common.record_footer_lines(
            STUB, "s.py", after_links=["- **Evidence bytes**: none stored"],
            after_supersedes=["- **Companion of**: `x`"])
        self.assertLess(got.index("- **Evidence bytes**: none stored"),
                        next(i for i, ln in enumerate(got) if ln.startswith("- **Timestamp")))
        self.assertGreater(got.index("- **Companion of**: `x`"),
                           next(i for i, ln in enumerate(got) if ln.startswith("- **Supersedes")))

    def test_no_hook_can_displace_the_closing_sentence(self):
        got = sim_common.record_footer_lines(
            STUB, "s.py", after_links=["- a"], after_supersedes=["- b"])
        self.assertIn(sim_common.RECORD_APPEND_ONLY, got[-2])


class EveryRendererGoesThroughTheHelperTest(unittest.TestCase):
    """Mechanism, not documentation: the greps that stop an eleventh private copy."""

    # The drifted sentence in every variant that was live, plus the shapes a new copy
    # would most plausibly take.
    RESTATES_THE_RULE = re.compile(r"(?i)never edit this file|append-only: never edit")
    HAND_WRITTEN_BULLET = re.compile(r"\*\*(Supersedes|Timestamp / author)\*\*:")

    def renderer_sources(self) -> dict[str, str]:
        found = {name: path.read_text() for name, path in SOURCES.items()}
        self.assertEqual(len(found), 10, "the table must name all ten renderers")
        return found

    def record_writers(self) -> dict[str, str]:
        """Every `sim/` script that closes an evidence record, found by the call itself."""
        cand = sorted((REPO_ROOT / "sim").glob("*/run_*.py")) + [REPO_ROOT / "sim/bin/corner-run.py"]
        return {p.relative_to(REPO_ROOT).as_posix(): p.read_text() for p in cand
                if "record_footer_lines(" in p.read_text()}

    def test_every_renderer_in_the_table_calls_the_shared_helper(self):
        for name, src in self.renderer_sources().items():
            with self.subTest(name):
                self.assertIn("sim_common.record_footer_lines(", src)

    def test_an_eleventh_record_writer_must_join_this_file_s_table(self):
        """Otherwise the contract silently stops covering the repo -- the failure mode
        `test_runner_fleet_pdk.py` guards the same way."""
        writers = set(self.record_writers())
        table = {Path(name).as_posix() for name in SOURCES}
        self.assertEqual(writers - table, set(),
                         "a script closes an evidence record but is not in RENDERERS")
        self.assertEqual(table - writers, set(),
                         "RENDERERS names a script that no longer closes an evidence record")

    def test_no_renderer_restates_the_append_only_rule_itself(self):
        """The ten copies this file exists to collapse.  The sentence belongs to
        `sim_common.RECORD_APPEND_ONLY`, so it cannot drift from `sim/README.md` in nine
        places at once -- and a drifted copy lands in append-only evidence, where it can
        never be corrected."""
        offenders = [f"{name}:{n}: {line.strip()}"
                     for name, src in self.renderer_sources().items()
                     for n, line in enumerate(src.splitlines(), start=1)
                     if self.RESTATES_THE_RULE.search(line)]
        self.assertEqual(offenders, [], "a renderer restates the append-only sentence:\n  "
                         + "\n  ".join(offenders))

    def test_no_renderer_hand_writes_the_timestamp_or_supersedes_bullet(self):
        """`Supersedes`' fallback drifted three ways precisely because each renderer
        emitted the bullet itself.  A renderer may still PASS extra bullets through
        `after_links` / `after_supersedes`; it may not re-emit these two.

        Scoped to the ten renderers in the table, NOT to every `sim/*/run_*.py`:
        `run_accuracy_mc.py` and `run_solver_sweep.py` write a differently shaped
        record with no append-only trailer; their `supersedes` handling (the falsy
        contract: `null` in the JSON, `(none)` only in rendered markdown) is pinned by
        `test_supersedes_contract.py` (issue #353).  Widening this grep would mix the two
        contracts.
        """
        offenders = [f"{name}:{n}: {line.strip()}"
                     for name, src in self.renderer_sources().items()
                     for n, line in enumerate(src.splitlines(), start=1)
                     if self.HAND_WRITTEN_BULLET.search(line)]
        self.assertEqual(offenders, [], "a renderer hand-writes a trailer bullet:\n  "
                         + "\n  ".join(offenders))

    def test_the_selftest_trailer_stays_its_own_helper(self):
        """The two trailers are siblings, not one function with a mode: a self-test
        record carries an `Overall` verdict and no `Links` block, and says `Append-only.`
        without the correction clause because it is not evidence for a spec claim."""
        doc = {"timestamp": STUB["timestamp"], "author": STUB["author"], "supersedes": ""}
        st = sim_common.selftest_footer_lines(doc, True, "s.py selftest")
        self.assertNotIn("## Links", st)
        self.assertNotIn(sim_common.RECORD_APPEND_ONLY, "\n".join(st))


class CommittedRecordsTest(unittest.TestCase):
    """End to end over the committed corpus: the trailer still reaches the record.

    Every committed record is re-rendered from its own raw `.json` twin -- no
    backfill, no key injected into a committed document.  A record whose renderer
    resolves a later-added key by hard subscript cannot re-render; those are pinned
    in `RENDER_EXCLUSIONS` with the missing key and the reason, and the registry is
    guarded in both directions so the next retroactive breakage is named rather than
    absorbed.  Nothing is written and no committed record is touched
    (`.github/scripts/check_records_append_only.py` enforces that independently).
    """

    SIM_PATH = re.compile(r"sim/[A-Za-z0-9][\w./-]*")

    def test_the_exclusion_registry_matches_the_corpus_exactly(self):
        """The ratchet, in both directions: the registry can neither silently grow
        nor rot.

        Growth: a renderer gaining a hard subscript retroactively breaks
        already-committed records (7023a693 did it to two of these), and the old
        mechanism here absorbed that silently.  Rot: an entry whose record re-renders
        again is a stale allowlist entry; a changed key is an entry whose failure
        mode moved; a path the corpus no longer has is a registry pointing nowhere.
        """
        corpus_paths = {md.relative_to(REPO_ROOT).as_posix()
                        for _, md, _ in committed_records()}
        broken = probe_broken(RENDERERS)
        unregistered = {p: k for p, k in broken.items() if p not in RENDER_EXCLUSIONS}
        self.assertEqual(
            unregistered, {},
            "a committed record raises KeyError and is not in RENDER_EXCLUSIONS -- a "
            "renderer change retroactively broke it; pin it there with the key and the "
            "reason, or fix the renderer:\n"
            + "\n".join(f"  {p}: missing key {k!r}" for p, k in sorted(unregistered.items())))
        stale = sorted(p for p in RENDER_EXCLUSIONS if p not in broken)
        self.assertEqual(
            stale, [],
            "a RENDER_EXCLUSIONS entry no longer raises from its raw twin -- remove the "
            "stale entry so the registry stays an exclusion list:\n"
            + "\n".join(f"  {p}" for p in stale))
        moved = {p: (RENDER_EXCLUSIONS[p][0], k) for p, k in broken.items()
                 if p in RENDER_EXCLUSIONS and RENDER_EXCLUSIONS[p][0] != k}
        self.assertEqual(
            moved, {},
            "a RENDER_EXCLUSIONS entry raises on a different key than pinned -- update "
            "the entry:\n"
            + "\n".join(f"  {p}: pinned {a!r}, raises {b!r}"
                        for p, (a, b) in sorted(moved.items())))
        gone = sorted(p for p in RENDER_EXCLUSIONS if p not in corpus_paths)
        self.assertEqual(
            gone, [],
            "a RENDER_EXCLUSIONS entry names a record the corpus no longer has "
            "(records are append-only; investigate before removing):\n"
            + "\n".join(f"  {p}" for p in gone))

    def test_a_renderer_gaining_a_hard_subscript_fails_loudly_not_silently(self):
        """The regression the registry exists to catch, simulated on a stub wrapper
        over the real corpus (no real renderer is edited).

        This is the #336-shaped change: a renderer gains a hard subscript for a key
        its committed records lack.  The probe must report it as named, per-record
        breakage -- record path plus missing key -- which is what
        `test_the_exclusion_registry_matches_the_corpus_exactly` turns into a failure.
        The absorbed version of history: PR #366's review widened a backfill for
        exactly such a breakage and the corpus floor never moved.
        """
        future_key = "simulated_retroactive_subscript"
        real = RENDERERS["sim/iq-top/run_iq_campaign.py"]

        def upgraded(doc):
            doc["links"][future_key]                    # the hard subscript, "added today"
            return real(doc)

        broken = probe_broken({**RENDERERS, "sim/iq-top/run_iq_campaign.py": upgraded})
        newly = {p: k for p, k in broken.items() if k == future_key}
        self.assertTrue(newly, "the retroactive breakage was absorbed silently")
        affected = {md.relative_to(REPO_ROOT).as_posix()
                    for name, md, _ in committed_records()
                    if name == "sim/iq-top/run_iq_campaign.py"}
        self.assertEqual(set(newly), affected,
                         "the newly broken records must be named one-for-one")

    def fixture_records(self) -> list[tuple[str, Path, dict, str]]:
        """The synthetic fixture docs, rendered through their real renderer."""
        out = []
        for name, seed in sorted(FIXTURE_SEEDS.items()):
            doc = fixture_doc(seed)
            out.append((name, REPO_ROOT / seed, doc, RENDERERS[name](doc)))
        return out

    def rendered_records(self) -> list[tuple[str, Path, dict, str]]:
        """`(renderer, md path, record document, rendered text)` for every trailer
        check: re-renderable corpus records from their raw twin, plus -- for a
        renderer whose committed records are all registry-excluded -- the synthetic
        fixture doc, so the trailer contract never loses a renderer to the registry.
        """
        out = []
        for name, md, doc in committed_records():
            rel = md.relative_to(REPO_ROOT).as_posix()
            if rel in RENDER_EXCLUSIONS:
                continue
            try:
                text = RENDERERS[name](doc)
            except KeyError as e:
                self.fail(
                    f"{rel} raises KeyError on {e.args[0]!r} and is not in "
                    "RENDER_EXCLUSIONS -- a renderer change retroactively broke a "
                    "committed record. Pin it in the registry with the key and the "
                    "reason (or fix the renderer); do not absorb it.")
            out.append((name, md, doc, text))
        out.extend(self.fixture_records())
        return out

    def rendered(self) -> list[tuple[str, Path, str]]:
        """The re-renderable corpus records only: `(renderer, md path, text)`."""
        fixture_md = {REPO_ROOT / seed for seed in FIXTURE_SEEDS.values()}
        return [(name, md, text) for name, md, _, text in self.rendered_records()
                if md not in fixture_md]

    def test_the_corpus_is_not_empty(self):
        """A derived ratchet, not a bare literal: adding a record raises the floor
        automatically, and a renderer change that breaks an existing record cannot
        net out against another that was fixed -- the registry-exactness test names
        such a breakage before this count is reached.
        """
        floor = len(committed_records()) - len(RENDER_EXCLUSIONS)
        self.assertEqual(len(self.rendered()), floor)

    def test_the_corpus_covers_every_renderer_in_the_table(self):
        """Each of the ten renderers is driven by at least one real record or, where
        the registry excludes all of a renderer's records, by the synthetic fixture --
        so none of them is covered by source grep alone.  The fixture table is pinned
        to exactly the renderers the real corpus no longer reaches: a renderer that
        regains real coverage cannot keep a stale fixture, and one that loses real
        coverage cannot lose its trailer check silently.
        """
        real = {name for name, md, _ in committed_records()
                if md.relative_to(REPO_ROOT).as_posix() not in RENDER_EXCLUSIONS}
        self.assertEqual(
            set(FIXTURE_SEEDS), set(RENDERERS) - real,
            "the fixture table must name exactly the renderers whose committed records "
            "are all registry-excluded")
        self.assertEqual(set(RENDERERS) - (real | set(FIXTURE_SEEDS)), set(),
                         "no committed record or fixture exercises this renderer's trailer")

    def test_no_rendered_trailer_names_a_path_outside_the_record_s_own_evidence(self):
        """A trailer must not send a reader to another experiment's evidence.

        The absorbed #366 backfill injected
        `sim/bias-core-smoke/artifacts/manifest.json` -- a directory belonging to a
        different experiment, and nonexistent -- into the re-rendered trailers of
        eleven records across nine experiment directories, twice inside prose telling
        the reader to `klt artifact verify` it.  Allowed instead: the record's own
        experiment, the renderer's own `Written by` path, a path the canonical
        append-only sentence itself names (`sim/README.md` -- the normative source the
        trailer must point at), and a path the record's own raw document genuinely
        carries (bias-core records borrow a bias-core-smoke testbench and say so).
        Anything else is an injected path.
        """
        for name, md, _, text in self.rendered_records():
            rel = md.relative_to(REPO_ROOT).as_posix()
            own = rel.split("/")[1]
            carried = doc_strings(json.loads(md.with_suffix(".json").read_text()))
            foreign = sorted(
                {p for raw in self.SIM_PATH.findall(trailer(text))
                 for p in {raw, raw.rstrip(".")}
                 if not p.startswith(f"sim/{own}/") and p != name
                 and p not in carried and p not in sim_common.RECORD_APPEND_ONLY})
            with self.subTest(rel):
                self.assertEqual(
                    foreign, [],
                    "the re-rendered trailer names a path outside this record's own "
                    "experiment and its own document -- an injected path, not record "
                    "content")

    def test_every_record_closes_with_the_one_canonical_sentence(self):
        for name, md, _, text in self.rendered_records():
            with self.subTest(md.relative_to(REPO_ROOT).as_posix()):
                self.assertEqual(text.count(sim_common.RECORD_APPEND_ONLY), 1)
                self.assertTrue(text.endswith(
                    f"{sim_common.RECORD_APPEND_ONLY}\n"), text[-200:])
                self.assertNotIn("— a correction is a new record", text)

    def test_every_record_s_trailer_fields_come_from_the_record_document(self):
        """Asserted against each record's own `.json`, not against the helper's output --
        comparing the helper with itself would pass however it drifts.  The link bullets
        are excluded because their order follows the `links` dict, not this contract.

        These are the exact three lines the four drifted texts lived on, plus a check
        that no renderer smuggles a fourth field in beside them.
        """
        for name, md, doc, text in self.rendered_records():
            with self.subTest(md.relative_to(REPO_ROOT).as_posix()):
                got = unlinked(trailer(text).split("\n"))
                self.assertIn(got[0], ("## Links", "- **Links**:"))
                self.assertEqual(got[-3], "")
                self.assertEqual(got[-1], "")
                self.assertIn(sim_common.RECORD_APPEND_ONLY, got[-2])
                self.assertTrue(got[-2].startswith(f"Written by `{name}"), got[-2])
                fields = got[1:-3]
                self.assertIn(f"- **Timestamp / author**: {doc['timestamp']}, {doc['author']}",
                              fields)
                self.assertIn(f"- **Supersedes**: {doc['supersedes'] or '(none)'}", fields)
                extra = [ln for ln in fields
                         if not ln.startswith(("- **Timestamp / author**: ",
                                               "- **Supersedes**: "))]
                self.assertTrue(all(ln.startswith(ALLOWED_EXTRA_BULLETS) for ln in extra),
                                f"unexpected trailer field(s): {extra}")

    def test_no_record_states_a_supersedes_fallback_of_its_own(self):
        """`(none; cites ...)`, `(none - first record for this claim)` and `(none; the
        original records are untouched)` were three renderers' private wordings of
        `sim/README.md`'s one word."""
        for name, md, _, text in self.rendered_records():
            with self.subTest(md.relative_to(REPO_ROOT).as_posix()):
                line = next(ln for ln in trailer(text).splitlines()
                            if ln.startswith("- **Supersedes**: "))
                value = line.removeprefix("- **Supersedes**: ")
                self.assertTrue(value == "(none)" or not value.startswith("(none"), value)


if __name__ == "__main__":
    unittest.main()
