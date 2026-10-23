#!/usr/bin/env python3
"""Fail-closed client for the fleet artifact store (`klt artifact`).

New sim evidence bytes go to the common artifact store; git keeps only a
manifest (`manifests/artifacts/<bench>-<run-id>.manifest.json`) and a Markdown
summary (`...summary.md`: name, size, sha256 per object). There is no flag and
no fallback that commits bytes instead.

Fail closed: `preflight()` raises StoreError -- before any simulation runs --
when $KLT_ARTIFACT_BROKER is unset or `klt artifact put` / `klt artifact
verify` is unavailable (feature probe via --help, not version parsing). If the
put itself fails (broker unreachable, refusal), the staged bytes are kept in
the git-ignored scratch directory, no manifest or summary is left behind, and
StoreError is raised.

The broker URL is never read into, logged by, or written to the repo.

Library use:  preflight(); store_run(bench, run_id, stage_dir) -> (manifest, summary)
Self-test:    evidence_store.py --selftest   (fake klt on PATH, no broker needed)
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
STAGE_ROOT = REPO_ROOT / "sim" / ".work" / ".stage"
MANIFEST_DIR = REPO_ROOT / "manifests" / "artifacts"
BROKER_ENV = "KLT_ARTIFACT_BROKER"


class StoreError(Exception):
    """Evidence cannot be stored; the message says why. Nothing was committed."""


def _klt(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["klt", *args], capture_output=True, text=True, cwd=cwd, timeout=1800
        )
    except FileNotFoundError:
        raise StoreError("`klt` is not on PATH; the artifact store client is required")
    except subprocess.TimeoutExpired:
        raise StoreError(f"`klt {' '.join(args[:2])}` timed out")


def preflight() -> None:
    """Raise StoreError unless evidence can be stored. Call before simulating."""
    if not os.environ.get(BROKER_ENV):
        raise StoreError(
            f"${BROKER_ENV} is unset; new evidence goes to the artifact store and "
            "there is no fallback to committing bytes (run on a fleet worker)"
        )
    for verb in ("put", "verify"):
        probe = _klt("artifact", verb, "--help")
        if probe.returncode != 0:
            raise StoreError(
                f"this klt lacks `klt artifact {verb}` (need klayout-tools "
                "7e3561f or later); upgrade the worker's klt"
            )


def stage_dir_for(bench: str, run_id: str) -> Path:
    return STAGE_ROOT / bench / run_id


def manifest_path(bench: str, run_id: str) -> Path:
    return MANIFEST_DIR / f"{bench}-{run_id}.manifest.json"


def summary_path(bench: str, run_id: str) -> Path:
    return MANIFEST_DIR / f"{bench}-{run_id}.summary.md"


def render_summary(bench: str, run_id: str, manifest: dict) -> str:
    lines = [
        f"# Stored evidence: {bench} / {run_id}",
        "",
        "Raw outputs are in the fleet artifact store (private); this summary and",
        f"`{manifest_path(bench, run_id).name}` are the committed record. Check the bytes",
        f"with `klt artifact verify manifests/artifacts/{manifest_path(bench, run_id).name}`.",
        "",
        "| name | size (bytes) | sha256 |",
        "|---|---:|---|",
    ]
    for e in manifest["entries"]:
        lines.append(f"| `{e.get('name', '')}` | {e['size']} | `{e['sha256']}` |")
    lines.append("")
    return "\n".join(lines)


def store_run(bench: str, run_id: str, stage_dir: Path) -> tuple[Path, Path]:
    """Put every file under stage_dir; write the manifest and summary.

    Returns (manifest, summary). On any failure raises StoreError and leaves
    no manifest or summary; the staged bytes are kept for a retry.
    """
    files = sorted(p for p in stage_dir.rglob("*") if p.is_file())
    if not files:
        raise StoreError(f"nothing staged under {stage_dir}; refusing an empty manifest")
    manifest = manifest_path(bench, run_id)
    summary = summary_path(bench, run_id)
    if manifest.exists() or summary.exists():
        raise StoreError(f"{manifest} already exists -- evidence is append-only; use a new run id")

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # Entry names are relative to the stage dir (run-local, never absolute).
        proc = _klt(
            "artifact", "put", "--manifest", str(manifest),
            *[str(f.relative_to(stage_dir)) for f in files],
            cwd=stage_dir,
        )
        if proc.returncode != 0:
            raise StoreError(
                f"`klt artifact put` failed (rc={proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()[:500]}; staged bytes kept in {stage_dir}"
            )
        try:
            data = json.loads(manifest.read_text())
        except (OSError, ValueError) as exc:
            raise StoreError(f"manifest unreadable after put: {exc}")
        bad = [e.get("uri") for e in data.get("entries", []) if not str(e.get("uri", "")).startswith("artifact:")]
        if bad or len(data.get("entries", [])) != len(files):
            raise StoreError(f"manifest has non-artifact URIs or a missing entry: {bad}")
        summary.write_text(render_summary(bench, run_id, data))
    except BaseException:
        manifest.unlink(missing_ok=True)
        summary.unlink(missing_ok=True)
        raise
    return manifest, summary


def preflight_or_exit() -> None:
    """Driver entry point: preflight(), exiting nonzero with the reason."""
    try:
        preflight()
    except StoreError as err:
        raise SystemExit(f"evidence store unavailable, refusing to run: {err}")


def store_or_exit(bench: str, run_id: str, stage_dir: Path) -> tuple[Path, Path]:
    """Driver entry point: store_run(), exiting nonzero (nothing committed) on failure."""
    try:
        return store_run(bench, run_id, stage_dir)
    except StoreError as err:
        raise SystemExit(f"evidence not stored, nothing committed: {err}")


# --------------------------------------------------------------------------
# self-test (fake klt)
# --------------------------------------------------------------------------

_FAKE_KLT = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
a = sys.argv[1:]
mode = os.environ.get("FAKE_KLT_MODE", "ok")
if a[:2] == ["artifact", "put"] and "--help" in a:
    sys.exit(1 if mode == "no-put" else 0)
if a[:2] == ["artifact", "verify"] and "--help" in a:
    sys.exit(0)
if a[:2] == ["artifact", "put"]:
    if mode == "put-fails":
        print("broker unreachable", file=sys.stderr); sys.exit(1)
    m = a[a.index("--manifest") + 1]
    files = a[a.index("--manifest") + 2:]
    ents = []
    for f in files:
        b = open(f, "rb").read(); h = hashlib.sha256(b).hexdigest()
        ents.append({"sha256": h, "size": len(b), "kind": "evidence",
                     "producer": {"tool": "klt", "version": "0", "loom.repo": "o/n", "commit": None},
                     "uri": ("s3://x/" if mode == "bad-uri" else "artifact:evidence/o__n/") + h, "name": f})
    open(m, "w").write(json.dumps({"schema_version": 1, "entries": ents}))
    sys.exit(0)
sys.exit(2)
'''


def selftest() -> int:
    global MANIFEST_DIR, STAGE_ROOT
    failures: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        if cond:
            print(f"  ok: {name}")
        else:
            failures.append(name)
            print(f"  FAILED: {name}: {detail}", file=sys.stderr)

    def raises(fn) -> str | None:
        try:
            fn()
        except StoreError as exc:
            return str(exc)
        return None

    def raises_exit(fn) -> bool:
        try:
            fn()
        except SystemExit as exc:
            return bool(exc.code)
        return False

    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        binp = tmpd / "bin"
        binp.mkdir()
        (binp / "klt").write_text(_FAKE_KLT.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        (binp / "klt").chmod(0o755)
        saved = (MANIFEST_DIR, STAGE_ROOT, dict(os.environ))
        MANIFEST_DIR = tmpd / "manifests" / "artifacts"
        STAGE_ROOT = tmpd / "stage"
        os.environ["PATH"] = f"{binp}{os.pathsep}{os.environ['PATH']}"
        try:
            os.environ[BROKER_ENV] = "http://broker.invalid"
            os.environ["FAKE_KLT_MODE"] = "ok"
            check("preflight passes with broker and verbs", raises(preflight) is None)

            del os.environ[BROKER_ENV]
            msg = raises(preflight)
            check("unset broker fails closed", msg is not None and BROKER_ENV in msg, str(msg))
            os.environ[BROKER_ENV] = "http://broker.invalid"

            os.environ["FAKE_KLT_MODE"] = "no-put"
            msg = raises(preflight)
            check("klt without `artifact put` fails closed", msg is not None and "put" in msg, str(msg))

            stage = stage_dir_for("b", "r1")
            (stage / "sub").mkdir(parents=True)
            (stage / "tt.log").write_text("log\n")
            (stage / "sub" / "x.csv").write_text("1,2\n")
            os.environ["FAKE_KLT_MODE"] = "ok"
            man, summ = store_run("b", "r1", stage)
            data = json.loads(man.read_text())
            check("manifest has every file with artifact: uris",
                  len(data["entries"]) == 2 and all(e["uri"].startswith("artifact:") for e in data["entries"]))
            check("summary lists name, size and sha256",
                  all(e["sha256"] in summ.read_text() for e in data["entries"]))
            check("re-run with an existing run id is refused",
                  raises(lambda: store_run("b", "r1", stage)) is not None)

            stage2 = stage_dir_for("b", "r2")
            stage2.mkdir(parents=True)
            (stage2 / "a.log").write_text("a\n")
            os.environ["FAKE_KLT_MODE"] = "put-fails"
            msg = raises(lambda: store_run("b", "r2", stage2))
            check("put failure raises and keeps staged bytes",
                  msg is not None and (stage2 / "a.log").exists(), str(msg))
            check("put failure leaves no manifest or summary",
                  not manifest_path("b", "r2").exists() and not summary_path("b", "r2").exists())

            os.environ["FAKE_KLT_MODE"] = "bad-uri"
            msg = raises(lambda: store_run("b", "r2", stage2))
            check("non-artifact URI from put is rejected and removed",
                  msg is not None and not manifest_path("b", "r2").exists(), str(msg))

            os.environ["FAKE_KLT_MODE"] = "no-put"
            check("preflight_or_exit exits nonzero", raises_exit(preflight_or_exit))
            stage4 = stage_dir_for("b", "r4")
            stage4.mkdir(parents=True)
            (stage4 / "a.log").write_text("a\n")
            os.environ["FAKE_KLT_MODE"] = "put-fails"
            check("store_or_exit exits nonzero and commits nothing",
                  raises_exit(lambda: store_or_exit("b", "r4", stage4))
                  and not manifest_path("b", "r4").exists())

            # Every campaign driver refuses to submit or record without the
            # broker, before touching anything (no fleet job, no files).
            env = {k: v for k, v in os.environ.items() if k != BROKER_ENV}
            for drv in sorted(REPO_ROOT.glob("sim/*/run_*_campaign.py")):
                for argv in (["run"], ["record", "--run-id", "selftest-none"]):
                    proc = subprocess.run([sys.executable, "-I", str(drv), *argv],
                                          capture_output=True, text=True, env=env, timeout=120)
                    check(f"{drv.parent.name} `{argv[0]}` fails closed without the broker",
                          proc.returncode != 0 and BROKER_ENV in (proc.stderr + proc.stdout),
                          (proc.stderr or proc.stdout)[-200:])

            empty = stage_dir_for("b", "r3")
            empty.mkdir(parents=True)
            os.environ["FAKE_KLT_MODE"] = "ok"
            check("empty stage dir is refused", raises(lambda: store_run("b", "r3", empty)) is not None)
        finally:
            MANIFEST_DIR, STAGE_ROOT = saved[0], saved[1]
            os.environ.clear()
            os.environ.update(saved[2])
    if failures:
        print(f"selftest FAILED: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("selftest ok: preflight and store_run fail closed, manifests artifact-only")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv[1:]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(0)
