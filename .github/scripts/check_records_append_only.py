#!/usr/bin/env python3
"""CI: committed sim/ evidence is append-only against Git.

Protected evidence (Git pathspecs; Git's * crosses '/', so flat and nested
layouts are both covered):
  sim/*/records/*            result records (JSON and Markdown twins)
  sim/*/netlist-snapshots/*  frozen decks and batch request files
  sim/*/corners/*            raw per-corner logs, summaries, waveforms (.gz)
  manifests/artifacts/*      artifact-store manifests and summaries of new runs

sim/README.md's "Append-only rule" says this evidence is never edited,
deleted or moved after creation -- corrections preserve the old bytes and
append a new run ID (with a Supersedes link in its record). This check diffs
the protected blobs between a Git baseline and HEAD with rename detection
disabled, so a move shows as a deletion of the old path (even a move out of
the protected directories) and fails. Any modification, deletion, rename or
type change of an existing evidence blob fails, even when the edited file is
still well-formed; the affected paths are listed. Added paths are allowed.
Live testbenches, campaign drivers, experiment manifests and READMEs are not
protected and stay editable.

Closed directory (added paths also fail):
  sim/*/corners/*            historical raw bytes only

sim/README.md's "New evidence goes to the artifact store" says new runs do not
commit raw bytes -- every runner stages them in git-ignored scratch and stores
them with `klt artifact put`, committing only
manifests/artifacts/<slug>-<record-id>.{manifest.json,summary.md}. That rule was
documented but unenforceable: a runner that never writes a manifest is invisible
to check_artifact_manifests.py, and commit cf3404f added 1 MB of raw corner bytes
fifteen days after the store path landed. So an *added* file under
sim/*/corners/ fails here (issue #325); the directory is closed, historical
evidence, and nothing in it is edited, deleted, moved -- or added to.

Baseline resolution (first match wins):
  --baseline REV        use REV verbatim (must resolve to a commit)
  pull_request(_target) merge-base of HEAD and origin/$GITHUB_BASE_REF
                        (falls back to the local branch of that name)
  push                  $GITHUB_EVENT_BEFORE; an all-zeros value means an
                        initial push, checked against the empty tree
                        (explicit pass: no prior commit, nothing to protect)
  anything else         exit 2: pass --baseline explicitly

Missing history is an error, not a skip: an unresolvable baseline exits 2
with the fetch needed to fix it.

Usage:
  check_records_append_only.py              check the current checkout
  check_records_append_only.py --selftest   temp-git-repo fixtures: records
                                            (add, modify, delete, rename,
                                            twin edit, correction), flat and
                                            nested snapshot/corner evidence
                                            (modify, delete, move), additions
                                            under the closed corners/ (flat
                                            and nested), fresh store-era run,
                                            live-file edits, and baseline
                                            resolution (missing, initial push,
                                            push before-commit, PR merge base)

Exit codes: 0 pass, 1 append-only violation (paths listed), 2 unusable
invocation or unresolvable baseline.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROTECTED = (
    "sim/*/records/*",
    "sim/*/netlist-snapshots/*",
    "sim/*/corners/*",
    "manifests/artifacts/*",
)

# Closed to additions as well: raw bytes of a new run belong in the artifact
# store, never in the tree (sim/README.md, sim/bin/evidence_store.py).
CLOSED_TO_ADDITIONS = ("sim/*/corners/*",)


class BaselineError(Exception):
    """Baseline cannot be resolved; the message is the actionable CI output."""


def git(repo, *args, check=True, input=None):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        input=input,
    )


def rev_exists(repo, rev):
    return git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False).returncode == 0


def commit_sha(repo, rev):
    return git(repo, "rev-parse", "--verify", f"{rev}^{{commit}}").stdout.strip()


def empty_tree(repo):
    return git(repo, "mktree", input="").stdout.strip()


def is_zero_sha(sha):
    return bool(sha) and set(sha) == {"0"}


def resolve_baseline(repo, env, explicit):
    """Return (baseline_rev, human_label) or raise BaselineError."""
    if explicit is not None:
        if not rev_exists(repo, explicit):
            raise BaselineError(
                f"baseline '{explicit}' is not a commit present in this checkout. "
                f"Fetch it first, e.g. git fetch --no-tags origin '{explicit}', "
                f"or pass a resolvable merge-base / branch name."
            )
        return commit_sha(repo, explicit), explicit

    event = env.get("GITHUB_EVENT_NAME", "")
    if event in ("pull_request", "pull_request_target"):
        base = env.get("GITHUB_BASE_REF", "")
        if not base:
            raise BaselineError(
                "GITHUB_BASE_REF is not set for a pull_request event; pass --baseline explicitly."
            )
        for cand in (f"refs/remotes/origin/{base}", base):
            proc = git(repo, "merge-base", "HEAD", cand, check=False)
            if proc.returncode == 0:
                sha = proc.stdout.strip()
                return sha, f"merge-base with {base} ({sha})"
        raise BaselineError(
            f"cannot resolve the pull_request merge base against '{base}'. Fetch the "
            f"base branch first: git fetch --no-tags origin "
            f"refs/heads/{base}:refs/remotes/origin/{base} (a depth-1 checkout "
            f"cannot compute a merge base)."
        )

    if event == "push":
        before = env.get("GITHUB_EVENT_BEFORE", "")
        if not before:
            raise BaselineError(
                "GITHUB_EVENT_BEFORE is not set for a push event; pass --baseline explicitly."
            )
        if is_zero_sha(before):
            tree = empty_tree(repo)
            return tree, "empty tree (initial push, no prior commit)"
        if not rev_exists(repo, before):
            raise BaselineError(
                f"push baseline {before} is not present in this checkout (force push "
                f"or shallow clone). Fetch it explicitly: "
                f"git fetch --no-tags --force origin '{before}'."
            )
        return commit_sha(repo, before), f"pushed-from commit {before}"

    raise BaselineError(
        f"no baseline source: GITHUB_EVENT_NAME is '{event or 'unset'}'. Pass "
        f"--baseline <rev> (the CI workflow resolves the PR merge base or the "
        f"push's before commit automatically)."
    )


def record_changes(repo, baseline, head="HEAD", pathspecs=PROTECTED):
    """[(status, path)] for `pathspecs` diffed baseline..head, renames off."""
    proc = git(
        repo, "diff", "--no-renames", "--name-status", "-z", baseline, head, "--", *pathspecs
    )
    # With -z the fields themselves are NUL-separated: STATUS\0PATH\0... per entry.
    tokens = proc.stdout.split("\0")
    if tokens and tokens[-1] == "":
        tokens.pop()
    if len(tokens) % 2:
        raise RuntimeError(f"unexpected git diff --name-status -z output: {tokens!r}")
    out = []
    for i in range(0, len(tokens), 2):
        out.append((tokens[i], tokens[i + 1]))
    return out


def main(argv):
    if "--selftest" in argv:
        return selftest()

    baseline_arg = None
    if "--baseline" in argv:
        i = argv.index("--baseline")
        if i + 1 >= len(argv):
            print("--baseline requires a revision argument", file=sys.stderr)
            return 2
        baseline_arg = argv[i + 1]

    try:
        repo = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").stdout.strip())
        baseline, label = resolve_baseline(repo, os.environ, baseline_arg)
    except BaselineError as exc:
        print(f"append-only check could not run: {exc}", file=sys.stderr)
        return 2

    changes = record_changes(repo, baseline)
    bad = [(s, p) for s, p in changes if s != "A"]
    added = sum(1 for s, _ in changes if s == "A")
    # The closed directory: additions are violations too, not "new evidence".
    closed_added = [
        p for s, p in record_changes(repo, baseline, pathspecs=CLOSED_TO_ADDITIONS) if s == "A"
    ]

    for path in closed_added:
        print(
            f"::error file={path}::new raw evidence bytes committed in-tree: "
            f"sim/*/corners/ is closed, historical evidence only. New runs stage their "
            f"bytes in sim/.work/.stage/ and store them with `klt artifact put` via "
            f"sim/bin/evidence_store.py, committing only "
            f"manifests/artifacts/<slug>-<record-id>.manifest.json and its .summary.md "
            f'twin (sim/README.md "New evidence goes to the artifact store"). There is '
            f"no flag that commits bytes instead.",
            file=sys.stderr,
        )

    if bad or closed_added:
        verbs = {"D": "deleted", "M": "modified", "T": "type-changed"}
        for status, path in bad:
            verb = verbs.get(status, f"changed ({status})")
            print(
                f"::error file={path}::append-only violation: evidence {verb} (a move counts "
                f"as a deletion) — committed sim evidence is never edited, "
                f"deleted or moved; preserve it and append a new run ID with a "
                f'Supersedes link (sim/README.md "Append-only rule")',
                file=sys.stderr,
            )
        print(
            f"append-only check FAILED vs baseline {label}: {len(bad)} protected "
            f"evidence path(s) edited, deleted or moved, {len(closed_added)} raw byte(s) "
            f"added under the closed sim/*/corners/, "
            f"{added - len(closed_added)} new path(s) allowed",
            file=sys.stderr,
        )
        return 1

    print(
        f"append-only ok vs baseline {label}: no protected evidence edited, "
        f"deleted or moved and nothing added under the closed sim/*/corners/; "
        f"{added} new path(s) allowed"
    )
    return 0


def selftest():
    failures = []

    def check(name, cond, detail=""):
        if cond:
            print(f"  ok: {name}")
        else:
            failures.append(name)
            print(f"  FAILED: {name}: {detail}", file=sys.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "repo"
        subprocess.run(
            ["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True
        )
        git(repo, "config", "user.email", "selftest@example.com")
        git(repo, "config", "user.name", "selftest")

        exp = repo / "sim" / "exp"
        rec = exp / "records"
        rec.mkdir(parents=True)
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 1}\n')
        (rec / "r1.md").write_text("# record r1\n")
        (exp / "run.py").write_text("print('runner')\n")
        (exp / "experiment.json").write_text('{"slug": "exp"}\n')

        def commit_all(msg):
            git(repo, "add", "-A")
            git(repo, "commit", "-qm", msg)

        commit_all("baseline commit")
        base_sha = commit_sha(repo, "HEAD")

        def run(*args, env_extra=None):
            env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
            if env_extra:
                env.update(env_extra)
            return subprocess.run(
                [sys.executable, "-I", str(Path(__file__).resolve()), *args],
                cwd=repo,
                env=env,
                capture_output=True,
                text=True,
            )

        def plain(*args):
            return run("--baseline", base_sha, *args)

        # 1. adding a new record passes
        (rec / "r2.json").write_text('{"verdict": "PASS", "supersedes": null}\n')
        (rec / "r2.md").write_text("# record r2\n")
        commit_all("add record r2")
        p = plain()
        check("adding a new record passes", p.returncode == 0, p.stderr)

        # 2. modifying an existing record fails even with well-formed JSON
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 999}\n')
        commit_all("tamper with r1.json (still well-formed JSON)")
        p = plain()
        check(
            "modifying an existing record fails",
            p.returncode == 1,
            f"rc={p.returncode} {p.stdout}{p.stderr}",
        )
        check("offending path is listed", "sim/exp/records/r1.json" in p.stderr, p.stderr)

        # 3. editing only the Markdown twin fails
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 1}\n')
        (rec / "r1.md").write_text("# record r1, typos fixed in place\n")
        commit_all("tamper with r1.md")
        p = plain()
        check(
            "editing the Markdown twin fails",
            p.returncode == 1 and "sim/exp/records/r1.md" in p.stderr,
            f"rc={p.returncode} {p.stderr}",
        )
        (rec / "r1.md").write_text("# record r1\n")
        commit_all("restore r1.md")

        # 4. deleting an existing record (present in the baseline) fails
        (rec / "r1.md").unlink()
        commit_all("delete r1.md")
        p = plain()
        check(
            "deleting an existing record fails",
            p.returncode == 1 and "sim/exp/records/r1.md" in p.stderr,
            f"rc={p.returncode} {p.stderr}",
        )
        (rec / "r1.md").write_text("# record r1\n")
        commit_all("restore r1.md")

        # 5. renaming an existing record fails (rename detection disabled)
        git(repo, "mv", "sim/exp/records/r1.json", "sim/exp/records/r1-renamed.json")
        commit_all("rename r1.json")
        p = plain()
        check(
            "renaming an existing record fails",
            p.returncode == 1,
            f"rc={p.returncode} {p.stderr}",
        )
        check(
            "renamed-away path is reported as deleted",
            "sim/exp/records/r1.json" in p.stderr,
            p.stderr,
        )
        git(repo, "mv", "sim/exp/records/r1-renamed.json", "sim/exp/records/r1.json")
        commit_all("rename r1.json back")

        # 6. runner and manifest edits pass
        (exp / "run.py").write_text("print('runner v2')\n")
        (exp / "experiment.json").write_text('{"slug": "exp", "notes": "edited"}\n')
        commit_all("edit runner and manifest")
        p = plain()
        check("editing a runner or manifest passes", p.returncode == 0, p.stderr)

        # 7. a correction appends a new record referring to the old one
        (rec / "r3.md").write_text("# record r3 — supersedes r1\n")
        (rec / "r3.json").write_text('{"supersedes": "r1"}\n')
        commit_all("add correction record r3")
        p = plain()
        check("correction appending a new record passes", p.returncode == 0, p.stderr)

        # 8. a missing baseline fails with an actionable message
        p = run("--baseline", "1234567890abcdef1234567890abcdef12345678")
        check(
            "missing baseline fails with exit 2",
            p.returncode == 2,
            f"rc={p.returncode} {p.stderr}",
        )
        check("missing baseline message names the fetch", "fetch" in p.stderr, p.stderr)

        # 9. an initial push (all-zeros before) passes explicitly
        p = run(env_extra={"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_BEFORE": "0" * 40})
        check("initial push (all-zeros before) passes", p.returncode == 0, p.stderr)

        # 10. a push event diffs against the pushed-from commit
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 42}\n')
        commit_all("tamper r1.json (push-event case)")
        p = run(env_extra={"GITHUB_EVENT_NAME": "push", "GITHUB_EVENT_BEFORE": base_sha})
        check(
            "push event with a real before commit catches edits",
            p.returncode == 1,
            f"rc={p.returncode} {p.stderr}",
        )
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 1}\n')
        commit_all("restore r1.json (push-event case)")

        # 11. a pull_request resolves the merge base with the target branch:
        # the tamper is buried under a later unrelated commit, so a HEAD~1
        # baseline would miss it — only the merge base catches it.
        git(repo, "checkout", "-q", "-b", "feature", "main")
        (rec / "r1.json").write_text('{"verdict": "PASS", "v": 7}\n')
        commit_all("feature: tamper r1.json")
        (exp / "run.py").write_text("print('runner v3')\n")
        commit_all("feature: unrelated runner edit")
        p = run(env_extra={"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"})
        check(
            "pull_request merge base catches a buried tamper",
            p.returncode == 1,
            f"rc={p.returncode} {p.stderr}",
        )

        # 12. a pull_request that only adds a record passes via the merge base
        git(repo, "checkout", "-q", "-b", "pr-ok", "main")
        (rec / "r4.json").write_text('{"new": true}\n')
        (rec / "r4.md").write_text("# record r4\n")
        commit_all("add r4")
        p = run(env_extra={"GITHUB_EVENT_NAME": "pull_request", "GITHUB_BASE_REF": "main"})
        check("pull_request adding a record passes", p.returncode == 0, p.stderr)

        # 13. no baseline source at all errors with guidance, no silent skip
        p = run()
        check(
            "no baseline source errors with guidance",
            p.returncode == 2 and "--baseline" in p.stderr,
            f"rc={p.returncode} {p.stderr}",
        )

        # 14. evidence fixtures: flat + nested snapshots/corners
        git(repo, "checkout", "-q", "main")
        snap = exp / "netlist-snapshots"
        cor = exp / "corners"
        (snap / "r1" / "sub").mkdir(parents=True)
        (cor / "r1" / "control").mkdir(parents=True)
        (snap / "r0.spice").write_text("* flat deck\n")
        (snap / "r1" / "deck.spice").write_text("* nested deck\n")
        (snap / "r1" / "sub" / "b.request.json").write_text('{"req": 1}\n')
        (cor / "r1" / "tt.log").write_bytes(b"log\n")
        (cor / "r1" / "control" / "tt.trace.csv.gz").write_bytes(b"\x1f\x8bfake")
        (exp / "testbench").mkdir()
        (exp / "testbench" / "tb.spice").write_text("* tb\n")
        (exp / "README.md").write_text("readme\n")
        commit_all("add historical evidence")
        ev_base = commit_sha(repo, "HEAD")

        def ev(*args):
            return run("--baseline", ev_base, *args)

        def expect_fail(name, path):
            p = ev()
            check(
                name,
                p.returncode == 1 and path in p.stderr,
                f"rc={p.returncode} {p.stderr}",
            )
            git(repo, "reset", "-q", "--hard", ev_base)

        flat = "sim/exp/netlist-snapshots/r0.spice"
        (snap / "r0.spice").write_text("* flat deck edited\n")
        commit_all("edit flat snapshot")
        expect_fail("modifying a flat snapshot fails", flat)

        (snap / "r0.spice").unlink()
        commit_all("delete flat snapshot")
        expect_fail("deleting a flat snapshot fails", flat)

        (snap / "r1" / "sub" / "b.request.json").write_text('{"req": 2}\n')
        commit_all("edit nested request")
        expect_fail(
            "modifying a nested batch request fails",
            "sim/exp/netlist-snapshots/r1/sub/b.request.json",
        )

        (cor / "r1" / "tt.log").write_bytes(b"log edited\n")
        commit_all("edit corner log")
        expect_fail("modifying a corner log fails", "sim/exp/corners/r1/tt.log")

        gz = "sim/exp/corners/r1/control/tt.trace.csv.gz"
        (cor / "r1" / "control" / "tt.trace.csv.gz").write_bytes(b"other")
        commit_all("edit waveform")
        expect_fail("modifying a nested waveform fails", gz)

        (cor / "r1" / "control" / "tt.trace.csv.gz").unlink()
        commit_all("delete waveform")
        expect_fail("deleting a nested waveform fails", gz)

        (exp / "archive").mkdir()
        git(repo, "mv", "sim/exp/corners/r1/tt.log", "sim/exp/archive/tt.log")
        commit_all("move corner log out of protected dir")
        expect_fail("moving evidence outside protected dirs fails", "sim/exp/corners/r1/tt.log")

        git(repo, "mv", "sim/exp/netlist-snapshots/r0.spice", "sim/exp/netlist-snapshots/r0b.spice")
        commit_all("rename snapshot within protected dir")
        expect_fail("renaming a snapshot fails", flat)

        # artifact manifests are protected too; adding one passes
        art = repo / "manifests" / "artifacts"
        art.mkdir(parents=True)
        (art / "exp-r0.manifest.json").write_text("{}\n")
        commit_all("add artifact manifest")
        ev_base = commit_sha(repo, "HEAD")
        (art / "exp-r1.manifest.json").write_text("{}\n")
        commit_all("add second artifact manifest")
        p = ev()
        check("adding an artifact manifest passes", p.returncode == 0, p.stderr)
        (art / "exp-r0.manifest.json").write_text('{"x": 1}\n')
        commit_all("edit artifact manifest")
        expect_fail("modifying an artifact manifest fails", "manifests/artifacts/exp-r0.manifest.json")

        # fresh store-era run: records + flat/nested snapshots + an artifact
        # manifest pair, and NO new bytes under corners/
        (snap / "r9.spice").write_text("* new flat\n")
        (snap / "r9-x").mkdir()
        (snap / "r9-x" / "deck.spice").write_text("* new nested\n")
        (rec / "r9.md").write_text("# r9\n")
        (rec / "r9.json").write_text("{}\n")
        (art / "exp-r9.manifest.json").write_text("{}\n")
        (art / "exp-r9.summary.md").write_text("# stored\n")
        commit_all("fresh run")
        p = ev()
        check("adding a fresh store-era run's evidence passes", p.returncode == 0, p.stderr)
        git(repo, "reset", "-q", "--hard", ev_base)

        # corners/ is closed to ADDITIONS too: new raw bytes in-tree fail (issue #325)
        (cor / "r9").mkdir()
        (cor / "r9" / "tt.log").write_text("new raw bytes\n")
        commit_all("new run commits a raw corner log in-tree")
        p = ev()
        check(
            "adding a new corner log under corners/ fails",
            p.returncode == 1 and "sim/exp/corners/r9/tt.log" in p.stderr,
            f"rc={p.returncode} {p.stderr}",
        )
        check(
            "the closed-directory error names the artifact store",
            "klt artifact put" in p.stderr and "sim/.work/.stage/" in p.stderr,
            p.stderr,
        )
        git(repo, "reset", "-q", "--hard", ev_base)

        # a nested addition (a non-.log object, e.g. a per-sample CSV) fails too
        (cor / "r9" / "baseline").mkdir(parents=True)
        (cor / "r9" / "baseline" / "samples-mirror.csv").write_text("a,b\n1,2\n")
        commit_all("new run commits per-sample CSVs in-tree")
        p = ev()
        check(
            "adding a nested non-log object under corners/ fails",
            p.returncode == 1
            and "sim/exp/corners/r9/baseline/samples-mirror.csv" in p.stderr,
            f"rc={p.returncode} {p.stderr}",
        )
        git(repo, "reset", "-q", "--hard", ev_base)

        # a records/ or netlist-snapshots/ addition is still allowed
        (rec / "r10.md").write_text("# r10\n")
        (snap / "r10.spice").write_text("* r10 deck\n")
        commit_all("add a record and a snapshot only")
        p = ev()
        check(
            "records/ and netlist-snapshots/ additions are still allowed",
            p.returncode == 0,
            p.stderr,
        )
        git(repo, "reset", "-q", "--hard", ev_base)

        # live files stay editable
        (exp / "testbench" / "tb.spice").write_text("* tb v2\n")
        (exp / "run.py").write_text("print('driver v9')\n")
        (exp / "experiment.json").write_text('{"slug": "exp", "v": 2}\n')
        (exp / "README.md").write_text("readme v2\n")
        commit_all("edit live files")
        p = ev()
        check("editing testbench/driver/manifest/README passes", p.returncode == 0, p.stderr)

    if failures:
        print(f"selftest FAILED: {len(failures)} case(s): {', '.join(failures)}", file=sys.stderr)
        return 1
    print("selftest ok: record and evidence (flat/nested) add/modify/delete/move, live-file and baseline fixtures all behave")
    return 0


sys.exit(main(sys.argv[1:]))
