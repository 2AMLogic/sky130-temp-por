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
trailer checked against the helper.  Nothing is written, and no record is rewritten.

Stdlib only: no SPICE, no PDK, no fleet, no records written.

Run: python3 -I sim/bin/test_record_footer.py
"""

from __future__ import annotations

import copy
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

# A record whose `links` carry no artifact-store entries at all.  The seven committed
# `corner-run.py` records predate that store, and `corner-run.py`'s footer resolves
# `artifact_manifest` / `artifact_summary` by hard key, so it cannot re-render any of
# them -- true before this consolidation and after it, since the lookups are unchanged.
# It is therefore the one renderer the corpus cannot drive, and these two keys are
# supplied (paths only, no measurement invented) so its trailer is covered at all.
CORNER_RUN_LINK_BACKFILL = {
    "artifact_manifest": "sim/bias-core-smoke/artifacts/manifest.json",
    "artifact_summary": "sim/bias-core-smoke/artifacts/summary.md",
}

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

    Self-test records are excluded: their trailer is `selftest_footer_lines()`'s, and the
    three hand-written records (a fleet timeout, a local probe, a fleet refusal) have no
    `.json` twin and no renderer at all.
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
        doc = json.loads(js.read_text())
        if name == "sim/bin/corner-run.py":
            doc = copy.deepcopy(doc)
            doc["links"] = {**doc["links"], **CORNER_RUN_LINK_BACKFILL}
        out.append((name, md, doc))
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
        `after_links` / `after_supersedes`; it may not re-emit these two."""
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

    Re-rendered from each record's own `.json` twin; nothing is written and no committed
    record is touched (`.github/scripts/check_records_append_only.py` enforces that
    independently).
    """

    def rendered(self) -> list[tuple[str, Path, str]]:
        """Every committed record its renderer can still re-render.

        A record predating a schema field its renderer now resolves by hard key cannot be
        re-rendered -- unrelated to the trailer, and it fails identically with or without
        this consolidation -- so those are reported by
        `test_the_corpus_covers_every_renderer_in_the_table` rather than silently dropped.
        """
        out = []
        for name, md, doc in committed_records():
            try:
                out.append((name, md, RENDERERS[name](doc)))
            except KeyError:
                continue
        return out

    def test_the_corpus_is_not_empty(self):
        """A ratchet, not a count: records are only ever added, so this floor may rise
        and must never fall.  It drops if a renderer stops being able to re-render its
        own committed evidence, which is itself the regression worth failing on.

        Two of the 31 evidence records -- `sim/bias-core-op-branch`'s and
        `sim/pnp-mismatch`'s first, both from 2026-08-25/26 -- predate the batch backend
        and raise on a `batch` key in the record BODY, above the trailer; that is
        unrelated to this contract and identical before and after the consolidation.
        """
        self.assertGreaterEqual(len(self.rendered()), 29)

    def test_the_corpus_covers_every_renderer_in_the_table(self):
        """Each of the ten renderers is driven by at least one real record, so none of
        them is covered by source grep alone."""
        covered = {name for name, _, _ in self.rendered()}
        self.assertEqual(set(RENDERERS) - covered, set(),
                         "no committed record exercises this renderer's trailer")

    def test_every_record_closes_with_the_one_canonical_sentence(self):
        for name, md, text in self.rendered():
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
        docs = {p: d for _, p, d in committed_records()}
        for name, md, text in self.rendered():
            doc = docs[md]
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
        for name, md, text in self.rendered():
            with self.subTest(md.relative_to(REPO_ROOT).as_posix()):
                line = next(ln for ln in trailer(text).splitlines()
                            if ln.startswith("- **Supersedes**: "))
                value = line.removeprefix("- **Supersedes**: ")
                self.assertTrue(value == "(none)" or not value.startswith("(none"), value)


if __name__ == "__main__":
    unittest.main()
