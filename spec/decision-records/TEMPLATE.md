# DR-000: <short title>

<!--
Copy this file to spec/decision-records/DR-NNN-<slug>.md and fill it in.
Use the next unused NNN. Before taking a number, check for in-flight
records — open PRs touching spec/decision-records/ — so two concurrent
filers don't collide on the same NNN. One decision per record; keep it
to one page. A decision record is required for every spec change (see
CLAUDE.md). Do not delete or rewrite a ratified record — supersede it
with a new one.

Structure ported from gf180-temp-por's spec/decision-records/TEMPLATE.md
(see spec/porting-plan.md §0), with the "Spec lines affected" section
added to match the convention already in use across this PDK's sibling
canary repos (sky130-bandgap's own TEMPLATE.md).
-->

- **Status**: proposed | ratified | superseded by DR-NNN
- **Date**: YYYY-MM-DD
- **Decided by**: <name / role>

## Context

What forced this decision? One short paragraph: the constraint, the
measurement, or the conflict that made the current spec inadequate. Link to
the issue, the simulation evidence in `sim/`, or the prior record it revises.

## Decision

The decision, stated as a change to the spec — the parameter and its new
value, or the approach now ratified. Be specific enough that design work can
lock to it without further interpretation.

## Alternatives considered

- **<alternative>** — why it was not chosen.
- **<alternative>** — why it was not chosen.

## Spec lines affected

Which row(s) of the target-spec table (once `spec/target-spec.md` exists —
see `spec/porting-plan.md` §4), or which `spec/` file/line, does this
decision change. Name them explicitly so a reader can tell what's ratified
without re-deriving it from the prose above.

## Consequences

What follows from this: what becomes possible, what becomes harder, which
testbenches or corner sets change, what work is invalidated or must be
re-run. Include the bad consequences, not just the good ones.
