#!/usr/bin/env python3
"""CI: sim/ measurement records (sim/*/records/*) are append-only against Git.

sim/README.md's "Append-only rule" says records are never edited or deleted
after creation — corrections mint a new record with a Supersedes link. This
check diffs the protected record blobs (JSON and Markdown twins alike)
between a Git baseline and HEAD with rename detection disabled, and fails on
any modification, deletion or rename of an existing record, even when the
edited JSON is still well-formed. Added record paths are allowed, so a
correction can append a new record referring to the old one. Runner scripts,
experiment manifests and documentation stay editable.

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
  check_records_append_only.py --selftest   temp-git-repo fixtures: add,
                                            modify, delete, rename, twin
                                            edit, runner/manifest edit,
                                            correction append, missing
                                            baseline, initial push, push
                                            before-commit, PR merge base

Exit codes: 0 pass, 1 append-only violation (paths listed), 2 unusable
invocation or unresolvable baseline.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROTECTED = "sim/*/records/*"


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


def record_changes(repo, baseline, head="HEAD"):
    """[(status, path)] for protected paths diffed baseline..head, renames off."""
    proc = git(
        repo, "diff", "--no-renames", "--name-status", "-z", baseline, head, "--", PROTECTED
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

    if bad:
        verbs = {"D": "deleted", "M": "modified", "T": "type-changed"}
        for status, path in bad:
            verb = verbs.get(status, f"changed ({status})")
            print(
                f"::error file={path}::append-only violation: record {verb} — sim "
                f'records are never edited or deleted; mint a new record with a '
                f'Supersedes link (sim/README.md "Append-only rule")',
                file=sys.stderr,
            )
        print(
            f"append-only check FAILED vs baseline {label}: {len(bad)} protected "
            f"record path(s) edited or deleted, {added} new record path(s) allowed",
            file=sys.stderr,
        )
        return 1

    print(
        f"append-only ok vs baseline {label}: no protected record edited or "
        f"deleted; {added} new record path(s) allowed"
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

    if failures:
        print(f"selftest FAILED: {len(failures)} case(s): {', '.join(failures)}", file=sys.stderr)
        return 1
    print("selftest ok: add/modify/delete/rename/twin/runner/correction/baseline fixtures all behave")
    return 0


sys.exit(main(sys.argv[1:]))
