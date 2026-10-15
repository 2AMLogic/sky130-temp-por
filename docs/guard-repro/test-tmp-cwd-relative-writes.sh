#!/usr/bin/env bash
# Reproducer + regression controls for issue #88: the Bash-tool write-
# confinement guard (worktree-write-confinement-unresolved-var) denies
# variable-derived RELATIVE write targets even after a literal `cd /tmp/...`.
#
# Scope (operator ruling 2026-10-15): reproduction and proof only. This does
# NOT patch the Loom-managed hook; any guard change belongs upstream
# (rjwalters/loom defaults/hooks/guard-destructive-generic.sh).
#
# Usage: docs/guard-repro/test-tmp-cwd-relative-writes.sh   (from a repo with a
# managed worktree; the guard is a no-op otherwise, which the script detects)
#
# Sections:
#   CONTROLS  must be denied today AND after any future refinement. Failure => exit 1.
#   REPRO     the false positive: safe scratch writes the guard denies today.
#             Reported as KNOWN-GAP; once a refinement lands they should flip
#             to allow and be promoted to asserted cases (exit 1 on a flip so
#             the promotion is not forgotten).
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/.loom/hooks/guard-destructive-generic.sh"
[[ -f "$HOOK" ]] || { echo "SKIP: $HOOK missing"; exit 0; }

verdict() {  # prints deny|allow for a Bash command
  local out
  out=$(jq -n --arg c "$1" --arg cwd "$ROOT" \
    '{tool_name:"Bash",tool_input:{command:$c},cwd:$cwd,hook_event_name:"PreToolUse"}' \
    | env -u LOOM_FORCE_SCOPE -u LOOM_GUARD_DECISION_LOG bash "$HOOK" 2>/dev/null \
    | jq -r '.hookSpecificOutput.permissionDecision // empty' 2>/dev/null)
  [[ "$out" == deny ]] && echo deny || echo allow
}

# The guard only confines when a managed worktree exists; prove it is live.
if [[ "$(verdict 'echo x > "$UNSET_VAR/f"')" != deny ]]; then
  echo "SKIP: confinement not in play (no managed worktree for $ROOT)"; exit 0
fi

fail=0
control() {
  local v; v=$(verdict "$2")
  if [[ "$v" == deny ]]; then echo "PASS control  [$1]"
  else echo "FAIL control  [$1] expected deny, got $v: $2"; fail=1; fi
}
repro() {
  local v; v=$(verdict "$2")
  if [[ "$v" == deny ]]; then echo "KNOWN-GAP     [$1] still denied: $2"
  else echo "FLIPPED       [$1] now allowed - promote to an asserted case: $2"; fail=1; fi
}

echo "== CONTROLS (must stay denied) =="
control unknown-arg-var     'cd /tmp/p && echo x > "$1.gds"'
control unset-cwd-var       'cd $D && echo x > a'
control abs-loop-value      'cd /tmp/p && for n in /abs; do echo x > "$n.gds"; done'
control traversal-loop-val  'cd /tmp/p && for n in ../x; do echo x > "$n.gds"; done'
control traversal-literal   'cd /tmp/p && for n in a; do echo x > "/$n/../a"; done'
control var-dir-component   'cd /tmp/p && for n in a; do echo x > "$n/f"; done'
control fn-unknown-arg      'cd /tmp/p && g(){ echo x > "$1.gds"; }; g a'
control no-cwd-var-root     'for n in a; do echo x > "$n.gds"; done'

echo "== REPRO (#88 false positives, safe scratch work) =="
repro loop-literal-tmp-cwd  'mkdir -p /tmp/klt_probe && cd /tmp/klt_probe && for name in a b; do echo x > "$name.gds"; echo y > "$name.json"; done'
repro loop-tmp-cwd-only     'cd /tmp/klt_probe && for name in a b; do echo x > "$name.gds"; done'

echo "NOTE: guard is lexical; symlink escapes (ln -s <repo> /tmp/p/l; > l/x) are invisible to it."
echo "      A refinement must either reject any command creating symlinks or prove none exist."
exit $fail
