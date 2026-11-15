#!/usr/bin/env python3
"""Unit tests for the shared deck-list record `batch` provenance block (issue #350).

The two bespoke deck-list runners (`sim/pnp-mismatch/run_pnp_mismatch.py`,
`sim/bias-core-op-branch/run_op_branch.py`) used to hand-roll this block twice: the
15-key fleet-job dict and the `**Backend**` / `**Fleet engine**` sentences that render
it, byte-identically, 45 lines each.  Every neighbouring block in the same record
already went through one builder -- `record_pdk_tools()` for `pdk`/`tools` (issue #297),
`fleet_job_fields()` for a campaign's per-corner fleet dict (issue #322) -- and this was
the one record-provenance shape in the tree with two copies and no helper.

What makes drift expensive here is that the output is committed evidence: records under
`sim/*/records` are append-only (`.github/scripts/check_records_append_only.py`), so a
key that silently changes name, or a sentence that silently changes wording, cannot be
corrected in an already-minted record -- only superseded.  So these tests use the
COMMITTED records as the oracle:

  * `deck_list_batch_clause()` must reproduce, byte for byte, the `**Backend**` and
    `**Fleet engine**` lines in every committed `.md` that carries a `batch` block.
    Those bytes were minted by the pre-refactor code, so this is a real oracle and not
    the helper checking itself.
  * `deck_list_batch_fields()` must emit exactly the key set those records carry, with
    each key routed back to the source it came from, and in the order
    `DECK_LIST_BATCH_KEYS` names.
  * neither runner may hand-roll either half again.

Stdlib only, no SPICE, no PDK, no fleet, no klt: `klt_version()` and the
`KLT_SIM_BACKEND` environment read are stubbed, so the test is hermetic.

Run: python3 -I sim/bin/test_sim_common_deck_batch.py
 or: python3 -m pytest sim/bin/
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import sim_common as sc  # noqa: E402

# The two deck-list runners and their record directories.  A third deck-list runner
# must be added here, not given a third copy of the block.
RUNNERS = {
    "pnp-mismatch": "run_pnp_mismatch.py",
    "bias-core-op-branch": "run_op_branch.py",
}

# `run_pnp_mismatch.py` adds exactly this one key at the call site: it is a claim about
# how that experiment drew its samples, not about the fleet job, so it must NOT migrate
# into the shared builder (issue #350 scope note).
CALL_SITE_KEYS = {"sampling_method"}


def committed_records() -> list[tuple[str, Path, dict]]:
    """Every committed record carrying a `batch` block, as `(slug, json path, doc)`.

    Records minted before the deck-list fleet path existed have no `batch` block at all
    and are skipped -- they are evidence of local runs and nothing here applies to them.
    """
    out = []
    for slug in RUNNERS:
        for jf in sorted((REPO_ROOT / "sim" / slug / "records").glob("*.json")):
            doc = json.loads(jf.read_text())
            if "batch" in doc:
                out.append((slug, jf, doc))
    return out


RECORDS = committed_records()


def report_from(b: dict) -> dict:
    """Rebuild the klt report shape the recorded block was derived from.

    The split is the contract under test: six keys come off the job's
    `environment.remote`, five off the report itself.  Routing one to the wrong source
    is exactly the drift a second hand-rolled copy makes possible.
    """
    return {
        "environment": {"remote": {k: b[k] for k in sc.DECK_LIST_REMOTE_KEYS}},
        "status": b["report_status"],
        "unit_count": b["unit_count"],
        "passed": b["passed"],
        "errored": b["errored"],
        "timed_out": b["timed_out"],
    }


def rebuild(b: dict) -> dict:
    """`deck_list_batch_fields()` fed the committed block's own inputs."""
    with mock.patch.dict("os.environ", {} if b["klt_sim_backend_env"] is None
                         else {"KLT_SIM_BACKEND": b["klt_sim_backend_env"]}, clear=True):
        return sc.deck_list_batch_fields(
            report_from(b),
            capacity_wait_s=b["capacity_wait_s"],
            attempts=b["failed_earlier_attempts"],
            klt_client=b["klt_client"],
        )


class CommittedRecordsExistTest(unittest.TestCase):
    """A vacuous suite is the one way these tests could silently stop guarding."""

    def test_both_runners_have_a_batch_carrying_record(self):
        slugs = {slug for slug, _, _ in RECORDS}
        self.assertEqual(slugs, set(RUNNERS), f"found batch records only for {slugs}")


class BatchFieldsTest(unittest.TestCase):
    def test_key_order_is_the_named_contract(self):
        b = rebuild(RECORDS[0][2]["batch"])
        self.assertEqual(tuple(b), sc.DECK_LIST_BATCH_KEYS)

    def test_reproduces_every_committed_block_key_for_key(self):
        for slug, jf, doc in RECORDS:
            with self.subTest(record=f"{slug}/{jf.name}"):
                committed = doc["batch"]
                got = rebuild(committed)
                extra = set(committed) - set(got)
                self.assertEqual(extra, extra & CALL_SITE_KEYS,
                                 "a key the helper must own is only at the call site")
                self.assertEqual(got, {k: v for k, v in committed.items() if k not in extra})

    def test_pnp_sampling_method_is_not_in_the_helper(self):
        """The one experiment-specific key stays at its call site."""
        b = rebuild(RECORDS[0][2]["batch"])
        for key in CALL_SITE_KEYS:
            self.assertNotIn(key, b)

    def test_absent_report_keys_are_recorded_as_none_not_dropped(self):
        """Same contract `fleet_job_fields()` keeps: one shape whatever the fleet said."""
        with mock.patch.dict("os.environ", {}, clear=True):
            b = sc.deck_list_batch_fields({}, capacity_wait_s=0, attempts=[],
                                          klt_client="klt 1.2.3")
        self.assertEqual(tuple(b), sc.DECK_LIST_BATCH_KEYS)
        for key in sc.DECK_LIST_BATCH_KEYS:
            if key in ("klt_client", "capacity_wait_s", "failed_earlier_attempts",
                       "klt_sim_backend_env"):
                continue
            self.assertIsNone(b[key], f"{key} should be None, not dropped or defaulted")
        self.assertIsNone(b["klt_sim_backend_env"])
        self.assertEqual(b["failed_earlier_attempts"], [])

    def test_klt_client_is_observed_when_not_supplied(self):
        """A record states the client klt it saw, never a literal (issue #297)."""
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch.object(sc, "klt_version", return_value="klt 9.9.9-observed") as kv:
            b = sc.deck_list_batch_fields({}, capacity_wait_s=0, attempts=[])
        self.assertEqual(b["klt_client"], "klt 9.9.9-observed")
        kv.assert_called_once_with()

    def test_backend_env_is_read_from_the_environment(self):
        with mock.patch.dict("os.environ", {"KLT_SIM_BACKEND": "batch"}, clear=True):
            b = sc.deck_list_batch_fields({}, capacity_wait_s=0, attempts=[],
                                          klt_client="klt 1.2.3")
        self.assertEqual(b["klt_sim_backend_env"], "batch")


class BatchClauseTest(unittest.TestCase):
    """The render half, checked against the bytes the pre-refactor code minted."""

    @staticmethod
    def committed_lines(md: Path) -> list[str]:
        text = md.read_text().splitlines()
        return [next(ln for ln in text if ln.startswith("- **Backend**:")),
                next(ln for ln in text if ln.startswith("- **Fleet engine**:"))]

    def test_reproduces_every_committed_record_byte_for_byte(self):
        for slug, jf, doc in RECORDS:
            with self.subTest(record=f"{slug}/{jf.name}"):
                self.assertEqual(
                    sc.deck_list_batch_clause(doc["batch"], doc["tools"]["fleet_ngspice"]),
                    self.committed_lines(jf.with_suffix(".md")),
                )

    def test_earlier_submit_attempts_are_appended_when_present(self):
        b = dict(RECORDS[0][2]["batch"], failed_earlier_attempts=["cap refusal A", "cap refusal B"])
        backend = sc.deck_list_batch_clause(b, "ngspice-47")[0]
        self.assertIn("2 earlier submit attempt(s) refused: cap refusal A; cap refusal B", backend)

    def test_no_attempt_suffix_when_the_first_submit_landed(self):
        b = dict(RECORDS[0][2]["batch"], failed_earlier_attempts=[])
        self.assertNotIn("earlier submit attempt", sc.deck_list_batch_clause(b, "ngspice-47")[0])

    def test_returns_lines_for_extend_like_its_sibling(self):
        """Mirrors `render_pdk_tools_repo_state()`: a list the caller `L.extend`s."""
        lines = sc.deck_list_batch_clause(RECORDS[0][2]["batch"], "ngspice-47")
        self.assertIsInstance(lines, list)
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(isinstance(x, str) and "\n" not in x for x in lines))


# --------------------------------------------------------------------------
# Source-level regression guard: no runner may hand-roll either half again
# --------------------------------------------------------------------------
# The helpers above make the shared shape easy to use; this makes a third copy
# detectable.  It is the same shape of guard `test_sim_common_provenance.py` applies to
# stated tool versions, and for the same reason: two copies were already enough for
# drift to go unnoticed here, and the output is append-only evidence.

class NoHandRolledCopyTest(unittest.TestCase):
    def runner_sources(self):
        for slug, name in RUNNERS.items():
            yield f"{slug}/{name}", (REPO_ROOT / "sim" / slug / name).read_text()

    def test_no_runner_assembles_the_dict_itself(self):
        for rel, src in self.runner_sources():
            with self.subTest(runner=rel):
                self.assertNotIn('"runner_request_features":', src,
                                 "build the batch dict via sim_common.deck_list_record_blocks()")

    def test_no_runner_renders_the_backend_sentence_itself(self):
        for rel, src in self.runner_sources():
            with self.subTest(runner=rel):
                self.assertNotIn("- **Backend**: `klt sim --backend batch`", src,
                                 "render it via sim_common.deck_list_batch_clause()")

    def test_every_runner_goes_through_the_helpers(self):
        for rel, src in self.runner_sources():
            with self.subTest(runner=rel):
                self.assertIn("deck_list_record_blocks(", src)
                self.assertIn("deck_list_batch_clause(", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
