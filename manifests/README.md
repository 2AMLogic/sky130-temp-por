# manifests

The `klt signoff` block manifest for this canary, and the committed
tier-verdict report it renders. This is the **verdict of record** for the
block's gap to **T1 sim-validated / bronze** on the klayout-tools
design-evidence ladder — the machine-graded replacement for the
hand-maintained checklist that used to live in the gap-to-T1 tracker issue
(#4), which now points here.

## Files

- `sky130-temp-por.json` — the **block manifest**. `klt signoff --manifest`
  reads it; the fleet roll-up (2AMLogic/2am#956) consumes exactly this
  file to grade this block's row fleet-wide.
- `signoff-report.json` — the **committed evidence record**:
  the full `klt signoff --manifest sky130-temp-por.json --format json`
  tier-verdict report as of the last re-render. CI re-runs the command and
  byte-compares against this file (see below), so a manifest citing an
  artifact that has since changed fails instead of silently rotting.

## Regenerate

From the repo root (evidence paths in the manifest are repo-root-relative
and the command resolves them against the process cwd):

```sh
klt signoff --manifest manifests/sky130-temp-por.json --format json \
  > manifests/signoff-report.json
```

The block is mid-progress, so the command exits `3` by design ("rendered,
some items unmet" — see `docs/cli/signoff.md`'s "Exit codes"). Exit `0`
(all items met) is the normal, eventual goal; exit `1`/`2` is a broken
manifest or usage error and is always a failure.

## Kind: `analog`

The block is a temperature-sensor + power-on-reset pair — PTAT/CTAT sensing,
a bandgap-style bias core, a POR comparator with hysteresis, and a
reset-driver output chain. All four leaf cells plus `temp_por_top` are
SPICE/xschem analog circuits; there is no RTL, no synthesis step, and no
digital partition anywhere in `design/`. The README's "digital out via SAR
pairing" sensor-output stretch goal does not exist in this repo today, so
the block declares `kind: "analog"` — it is held to the ladder's Analog
column only (`docs/design-evidence-tiers.md` → "Block kind"). If a SAR
pairing ever lands, the kind becomes `mixed-signal` and the manifest must
declare the partition boundary and per-partition evidence.

## What each row does and does not claim

Per the grader contract (`klayout-tools`'s
[`docs/cli/signoff.md`](https://github.com/2AMLogic/klayout-tools/blob/main/docs/cli/signoff.md)
→ "Items 1, 2, 9, and 10: `klt signoff` cannot check topical relevance"),
the tool grades four of these items on "some passing envelope was cited",
never on topical relevance. Citing honestly is this repo's responsibility —
each citation below is the envelope that genuinely backs the claim, and its
blind spots are stated here (coverage honesty: a verdict's blind spots are
part of the claim and travel with it):

- **Item 1 — Design sources: `met`** via
  `layout/bias_core_mirror_amp/lvs.json` (an LVS **match**: 15/15 devices,
  13/13 nets, 0 mismatches). The block's schematic sources and the netlist
  derived from them are committed (`design/` — leaf cells plus the
  assembled `temp_por_top`; netlists exported by committed
  netlist.py tooling) and that closes tracker sub-item #5. The citation
  mechanically exercises exactly the derived netlist: the LVS reference is
  rewritten ("subckt-call" converter) from `design/netlist/bias_core.spice`'s
  own device cards, so a match is a passing check against the design's
  committed netlist. **Not proven by this envelope:** that the netlist gets
  *regenerated* on design change (that is discipline the committed export
  tooling and the composition harness own) — freshness of this exact
  citation is asserted in CI by re-hashing the committed compare netlists
  against the envelope's recorded `environment` hashes, since `klt lvs`'s
  envelope shape carries no `provenance.input.content_hash` a manifest pin
  could bind to.
- **Item 2 — Layout: `unmet` (`no_evidence`)**, truthfully: the block has
  no `temp_por_top` (or `temp_core` / `por_comparator` /
  `por_output_chain`) layout yet, so no envelope can honestly back a
  block-level layout claim. Partial progress exists — six `bias_core`
  device-group sub-blocks and the `bias_core` full-cell assembly are
  committed under `layout/` (see `layout/README.md`) — but that is a
  sub-block increment, not the block's layout, and no citation is made.
- **Item 3 — DRC clean: `met`** via `layout/bias_core/drc.json` (`status:
  clean`, 0 violations), pinned to
  `content_hash sha256:ff4feb96…e3772` — the sha256 of the committed
  `layout/bias_core/bias_core.gds` the run executed on, so the citation is
  provably fresh against the current artifact (CI re-asserts this). **Scope
  disclosure, per item 3's own claimant-enforced rule:** the cited report
  covers the `bias_core` full-cell assembly — the most complete committed
  layout artifact, 50 devices — *not* a block-level GDS. Its graded
  coverage gaps are quoted verbatim in the committed report's
  `citation.coverage` block (10 rule-free drawn layers incl. `65/44` and
  `94/20`; 11 skipped rules, all `capm2`/`met4`/`met5`/`via4`;
  `deck_scope` listing the 17 deck chapters the run was measured inside).
  A `met` verdict here does not assert those gaps were acceptable — it
  asserts the run was clean inside the coverage it had, and this README is
  where the gaps are disclosed.
- **Item 4 — LVS clean: `unmet` (`check_failed`)**, truthfully: the same
  `bias_core` full-cell composition's LVS run reports `status: mismatch`
  (21/50 devices, 13/27 nets matched) — the full-cell assembly's remaining
  cross-block nets are unrouted this increment, tracked by #64 with
  upstream `klt` gaps filed generically. Three device-group sub-blocks
  (`bias_core_settle_flag`, `bias_core_startup`, `bias_core_mirror_amp`)
  reach full LVS matches and one of those matches is the item-1 citation
  above; the full-cell LVS is cited here instead because item 4's claim is
  block LVS cleanliness, and the honest citation is the check that ran at
  the widest available scope and its true verdict. The cited envelope
  carries no `power_connectivity` verdict (analog SPICE-reference compare —
  that sub-check does not arise for this `reference.form`), and no
  warnings-only mismatches are reported in the matching sub-block runs.
- **Items 5, 6, 7, 8 — `unmet` (`no_evidence`)**, each for a real reason:
  the target spec is **not ratified** (`spec/decision-records/DR-003` is
  `proposed`; no `target-spec.md` exists), so item 5's "vs a ratified spec"
  has nothing to verify against yet, and this repo's PVT-corner and
  mismatch Monte-Carlo records live under `sim/` as the sim harness's own
  JSON records — which are not `klt sim`/`klt yield` envelopes, so no
  passing envelope backs items 5/6; no `klt pex` report exists (item 7
  rejects every other evidence kind, and none is cited pretend-adjacent);
  no aggregated block-level characterization artifact exists yet (item 8 —
  tracked by #31, blocked on spec ratification).
- **Items 9, 10 — `unmet` (`no_evidence`)** despite genuinely committed
  testbenches (`sim/` harnesses with recorded PVT-corner results, pinned
  PDK) and repo hygiene (README + LICENSE): no *passing klt envelope*
  topically backs either claim, and citing an unrelated one just to turn
  the rows green is exactly the failure mode the contract names. These
  rows are the machine-honest statement "no check backs this claim", not
  statements that the testbenches or hygiene are absent.
- **Item 11 — Power delivery (structural): `unmet` (`check_failed`)** —
  the evidence half of this compound item now exists and is cited; the
  row stays unmet on the LVS half. Cited: the `klt erc` supply spec and
  report added by #66 — `layout/bias_core/erc-supply-spec.json` (layer
  numbers resolved from the sky130A `.lyp` and cross-checked against
  klayout-tools' curated sky130 deck; `stackup[0]` gate role plus
  `active_layer` for the `poly ∩ diff` antenna denominator) and
  `layout/bias_core/erc.json`, pinned to the committed GDS's
  `sha256:ff4feb…e3772` exactly like item 3's DRC citation, with every
  field of the committed GDS's supplies graded per the item's own rules.
  **What the ERC run does establish:** with `VDD`/`VSS` declared
  `kind: "supply"` (the `.subckt bias_core` interface spellings), the
  run reports `erc_status: "clean"` — zero `erc.unconnected_net`, zero
  `erc.supply_short` — i.e. each declared supply resolves to exactly
  **one** continuous electrical island under the declared stackup. The
  run deliberately omits `--pdk`, so the report's top-level `status` is
  `not_checked` (the antenna question was never asked) and the command
  exits `4`; the structural read the item grades is `erc_status`, not
  the exit code. **What it does not establish — read before citing this
  row as a pass:**
  1. `erc.missing_tie` is **not computed**: the spec deliberately
     declares no `ties[]`. sky130's native p-type substrate has no drawn
     well layer, so a substrate (VSS) tie is structurally undeclarable
     in `klt erc` today (klayout-tools#2186's documented remaining
     limitation), and a blanket `nwell → VDD` tie was probed on this
     exact GDS before committing: 18/18 merged n-well polygons report
     `erc.missing_tie`, because this analog block's wells include
     design-legitimate non-VDD tubs (the PNP collector/base regions tie
     to their own nodes), so the blanket check conflates by-design state
     with the assembly's known partial-wiring — it is non-actionable
     noise here, not evidence. The historical reason in #66's body
     (the upstream tie-collapse bug, klayout-tools#2169) is fixed in
     the pinned klt build and is no longer the operative reason.
     Standing-in well-tie/supply evidence that does exist: PG pin labels
     in the committed GDS, taps drawn on `65/44` inside all 18 merged
     n-well polygons, and the three device-group sub-block LVS matches
     (`bias_core_mirror_amp`, `bias_core_settle_flag`, `bias_core_startup`)
     whose `net_correspondence` pairs layout-side `VDD`/`VSS` to
     reference-side supply pins — the supplies were part of a passing
     device-level compare at sub-block scope. Zero `erc.missing_tie` in
     the committed report is an **absence of evidence, not evidence of
     absence**.
  2. **The one-island-per-supply verdict is about the assembly-level
     rail routes, not about power actually reaching the blocks.** The
     ERC connectivity census run for #66 found the supply rails are
     continuous single islands — but each block's real supply pad sits
     in a *separate* island: the composed legs land on promo pins at
     doubly-translated positions displaced from each block's placed
     geometry, so the rails currently touch none of
     `mirror_amp`/`startup`/`settle_flag`'s internal supply networks
     (**#69** tracks the landing-frame fix; the upstream coordinate-trust
     gap is klayout-tools#2210). The structural power-delivery question
     at full-assembly scope is therefore *not yet verifiable-clean*
     however clean this ERC run's findings read.
  3. **The `/lvs` half fails:** the compound item cites item 4's own LVS
     report, and the full-cell LVS is `status: mismatch` (#64) — the
     direct cause of the row's rendered `check_failed` reason, and the
     first thing to change when #64/#69 land (re-render this manifest
     and report together then: `Regenerate` above).

A nearly-all-`unmet` manifest is a correct result — "the honest
machine-readable statement of the gap" — and that is what these rows are.
No envelope is cited that does not support the item it backs, and no row
goes green on evidence it does not actually have.

## CI: freshness is enforced, not remembered

`.github/workflows/signoff-manifest.yml` re-runs the graded report on every
push/PR:

1. installs the **same pinned `klt` build** the committed report was
   rendered with (a `pip install` of the klayout-tools git rev — the
   tier skeleton is bundled inside the installed package, so a checklist
   change like the 2026-09-17 item-11 addition only reaches this repo
   through a deliberate pin bump),
2. re-runs `klt signoff --manifest manifests/sky130-temp-por.json --format
   json`, accepting exit `3` (rendered with unmet items — the block is
   mid-progress) as success and failing on `1`/`2`,
3. byte-compares the fresh output against `manifests/signoff-report.json` —
   any drift (a cited envelope's status changed, a report was regenerated
   against a new artifact, a stale pinned hash, a bumped `klt` with a new
   checklist) fails the build, and
4. re-hashes the committed artifact behind each `content_hash` pin
   (`layout/bias_core/bias_core.gds`) and the compare netlists behind each
   unpinned LVS citation (checked against the envelope's recorded
   `environment.layout_sha256` / `reference_sha256`) — so a layout change
   that lands without re-rendering the manifest and report together fails
   instead of rotting.

When the layout or design evidence moves, regenerate the report
(`Regenerate` above), update any affected citation or pin in the manifest,
and commit them together — the workflow revision pin and the report move in
the same PR by construction.

Provenance hygiene per `docs/design-evidence-tiers.md` ("Provenance hygiene
in evidence records"): the committed report cites repo-relative paths only
and embeds content hashes, never host or author identifiers.
