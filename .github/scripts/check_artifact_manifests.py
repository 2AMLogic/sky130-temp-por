#!/usr/bin/env python3
"""CI: artifact-store manifests are well-formed, artifact-only, and byte-free.

Checks every manifests/artifacts/*.manifest.json (klt artifact manifest,
schema_version 1):
  schema      exact field set per entry (sha256, size, kind, producer{tool,
              version,loom.repo,commit}, uri, optional name/media_type)
  uri         must start with 'artifact:'; any '://' or 'arn:aws:' anywhere in
              the manifest (s3:// URIs, broker URLs, account ARNs) fails
  bytes       fails if a git-tracked file outside manifests/artifacts/ has the
              sha256 of a stored object (the bytes were committed as well)
Each manifest needs its '.summary.md' twin. Stdlib only; no klt, no broker
(`klt artifact verify` needs the broker and runs from fleet workers).

Usage: check_artifact_manifests.py [--selftest]
Exit: 0 pass, 1 violation (listed), 2 unusable invocation.
"""
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ART_DIR = "manifests/artifacts"
ENTRY_KEYS = {"sha256", "size", "kind", "producer", "uri"}
OPTIONAL = {"name", "media_type"}
PRODUCER_KEYS = {"tool", "version", "loom.repo", "commit"}
SHA = re.compile(r"^[0-9a-f]{64}$")


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def check_manifest(path, text):
    errs = []
    for bad in ("://", "arn:aws:"):
        if bad in text:
            errs.append(f"contains '{bad}' (storage URIs, broker URLs and account ARNs never belong in a manifest)")
    try:
        doc = json.loads(text)
    except ValueError as exc:
        return errs + [f"invalid JSON: {exc}"], []
    if not isinstance(doc, dict) or set(doc) != {"schema_version", "entries"} or doc["schema_version"] != 1:
        return errs + ["top level must be exactly {schema_version: 1, entries: [...]}"], []
    entries = doc["entries"]
    if not isinstance(entries, list) or not entries:
        return errs + ["entries must be a non-empty list"], []
    shas = []
    for i, e in enumerate(entries):
        where = f"entries[{i}]"
        if not isinstance(e, dict):
            errs.append(f"{where}: not an object")
            continue
        keys = set(e)
        if not ENTRY_KEYS <= keys or keys - ENTRY_KEYS - OPTIONAL:
            errs.append(f"{where}: fields {sorted(keys)} != required {sorted(ENTRY_KEYS)} + optional {sorted(OPTIONAL)}")
            continue
        if not (isinstance(e["sha256"], str) and SHA.match(e["sha256"])):
            errs.append(f"{where}: sha256 must be 64 lowercase hex")
        else:
            shas.append((e["sha256"], e["size"]))
        if not (isinstance(e["size"], int) and not isinstance(e["size"], bool) and e["size"] >= 0):
            errs.append(f"{where}: size must be a non-negative integer")
        if e["kind"] != "evidence":
            errs.append(f"{where}: kind must be 'evidence'")
        if not (isinstance(e["uri"], str) and e["uri"].startswith("artifact:") and len(e["uri"]) > 9):
            errs.append(f"{where}: uri must start with 'artifact:'")
        p = e["producer"]
        if not isinstance(p, dict) or set(p) != PRODUCER_KEYS:
            errs.append(f"{where}: producer fields must be exactly {sorted(PRODUCER_KEYS)}")
        name = e.get("name")
        if name is not None and (not isinstance(name, str) or name.startswith("/") or ".." in Path(name).parts):
            errs.append(f"{where}: name must be a relative path")
    return errs, shas


def run(repo):
    tracked = [p for p in git(repo, "ls-files", "-z").decode().split("\0") if p]
    manifests = sorted(p for p in tracked if re.fullmatch(re.escape(ART_DIR) + r"/[^/]+\.manifest\.json", p))
    problems = []
    stored = {}
    for m in manifests:
        errs, shas = check_manifest(m, (repo / m).read_text())
        problems += [f"{m}: {e}" for e in errs]
        if not m.endswith(".manifest.json") or (m[: -len(".manifest.json")] + ".summary.md") not in tracked:
            problems.append(f"{m}: missing .summary.md twin")
        for sha, size in shas:
            stored[sha] = (size, m)
    sizes = {s for s, _ in stored.values()}
    if stored:
        for p in tracked:
            if p.startswith(ART_DIR + "/") or not (repo / p).is_file():
                continue
            f = repo / p
            if f.stat().st_size in sizes and hashlib.sha256(f.read_bytes()).hexdigest() in stored:
                problems.append(f"{p}: bytes of a stored object are also committed ({stored[hashlib.sha256(f.read_bytes()).hexdigest()][1]})")
    # any other tracked file under manifests/ must not name storage either
    for p in tracked:
        if p.startswith("manifests/") and not p.startswith(ART_DIR + "/") and p.endswith((".json", ".md", ".yml")):
            t = (repo / p).read_text(errors="replace")
            if re.search(r"s3://|arn:aws:", t):
                problems.append(f"{p}: names a storage bucket or ARN")
    return problems, len(manifests)


def selftest():
    fails = []
    good = {"schema_version": 1, "entries": [{
        "sha256": hashlib.sha256(b"payload\n").hexdigest(), "size": 8, "kind": "evidence",
        "producer": {"tool": "klt", "version": "1", "loom.repo": "o/n", "commit": None},
        "uri": "artifact:evidence/o__n/ab/abc", "name": "tt.log"}]}

    def case(name, mutate, want_ok, extra=None):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            d = json.loads(json.dumps(good))
            mutate(d)
            a = repo / ART_DIR
            a.mkdir(parents=True)
            (a / "b-r1.manifest.json").write_text(json.dumps(d))
            (a / "b-r1.summary.md").write_text("# s\n")
            if extra:
                extra(repo)
            git(repo, "add", "-A")
            problems, _ = run(repo)
            ok = not problems
            print(f"  {'ok' if ok == want_ok else 'FAILED'}: {name}")
            if ok != want_ok:
                fails.append(name)

    case("valid manifest passes", lambda d: None, True)
    case("s3 uri fails", lambda d: d["entries"][0].update(uri="s3://bkt/k"), False)
    case("bare http uri fails", lambda d: d["entries"][0].update(uri="https://x/y"), False)
    case("unknown field fails", lambda d: d["entries"][0].update(extra=1), False)
    case("bad sha fails", lambda d: d["entries"][0].update(sha256="zz"), False)
    case("empty entries fails", lambda d: d.update(entries=[]), False)
    case("absolute name fails", lambda d: d["entries"][0].update(name="/etc/x"), False)
    case("arn in manifest fails", lambda d: d["entries"][0].update(name="arn:aws:x"), False)
    case("tracked bytes of stored object fail", lambda d: None, False,
         lambda r: (r / "sim").mkdir() or (r / "sim" / "tt.log").write_bytes(b"payload\n"))
    case("unrelated tracked file passes", lambda d: None, True,
         lambda r: (r / "sim").mkdir() or (r / "sim" / "o.log").write_bytes(b"other!!\n"))

    def no_twin(r):
        (r / ART_DIR / "b-r1.summary.md").unlink()
    case("missing summary twin fails", lambda d: None, False, no_twin)
    if fails:
        print(f"selftest FAILED: {fails}", file=sys.stderr)
        return 1
    print("selftest ok")
    return 0


def main(argv):
    if "--selftest" in argv:
        return selftest()
    try:
        repo = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], check=True, capture_output=True, text=True).stdout.strip())
    except Exception as exc:
        print(f"not in a git checkout: {exc}", file=sys.stderr)
        return 2
    problems, n = run(repo)
    for p in problems:
        print(f"::error::{p}", file=sys.stderr)
    if problems:
        print(f"artifact manifest check FAILED: {len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(f"artifact manifests ok: {n} manifest(s)")
    return 0


sys.exit(main(sys.argv[1:]))
