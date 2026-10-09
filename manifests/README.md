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
  no `temp_por_top` (nor `temp_core` / `por_output_chain`) layout yet, so
  no envelope can honestly back a block-level layout claim. Partial
  progress exists — six `bias_core` device-group sub-blocks, the `bias_core` full-cell assembly and the
  `por_comparator` leaf cell (21 devices, DRC clean, LVS `match`, #82) are
  committed under `layout/` (see `layout/README.md`), as is the
  `por_output_chain` leaf cell (#97: DRC clean, LVS `match` 33/33 devices,
  but **without** its native-Vt device `XMASSIST`, which klt cannot draw or
  compare, so that cell is incomplete) — but those are sub-block increments,
  not the block's layout, and no citation is made.
- **Item 3 — DRC clean: `met`** via `layout/bias_core/drc.json` (`status:
  clean`, 0 violations), pinned to
  `content_hash sha256:9c414f91…7ab68e`, the sha256 of the committed
  `layout/bias_core/bias_core.gds` the run executed on (#81's fully
  wired composition), so the citation is provably fresh against the
  current artifact (CI re-asserts this). **Scope disclosure, per item 3's
  own claimant-enforced rule:** the cited report covers the `bias_core`
  full-cell assembly (the most complete committed layout artifact, 50
  devices), *not* a block-level GDS. Its graded coverage gaps are quoted
  verbatim in the committed report's `citation.coverage` block: 9 drawn
  layers with no rule (the pin-text purposes `67/5`…`72/5`, plus `66/13`
  `poly.res`, `79/20` `urpm`, `82/44`); 46 skipped rules, all
  `angle`/`ongrid` checks for layers this stream does not draw plus the
  `capm2.*`/`met4.enclosing.capm2.1` second-MiM rules; and `deck_scope`
  listing the 18 deck chapters the run was measured inside. At the #81 pin
  the `met5.*`, `via4.*` and `capm.*` rules are evaluated (they were
  skipped or rule-free before).
  A `met` verdict here does not assert those gaps were acceptable — it
  asserts the run was clean inside the coverage it had, and this README is
  where the gaps are disclosed.
- **Item 4 — LVS clean: `met`** via `layout/bias_core/lvs.json`. The
  `bias_core` full-cell composition's LVS against
  `design/netlist/bias_core.spice`'s `.subckt bias_core` reports `status:
  match`, **50/50 devices and 27/27 nets**, 0 errors. Issue #81 wired the
  remaining cross-block nets on the met3/met4/met5 routing roles that
  klayout-tools#2738 added (layer plan in `layout/bias_core/README.md`);
  before it, the compare stood at 21/50 devices and 14/27 nets. **Not
  proven by this envelope:** it is the `bias_core` assembly, not a
  block-level (`temp_por_top`) layout (see item 2). It also carries five
  disclosed warnings: the `PNP` compare is scoped to `NE`, so `AE` is not
  verified; the subckt-call reference has `R=0`/`C=0` placeholders on the
  4 `res_xhigh_po` and 2 MiM caps, so their values are not compared; and
  resistor `L/W/A/P` and MiM `A/P` are secondary parameters KLayout does
  not compare. The match is a topology match. The envelope carries no
  `power_connectivity` verdict, because that sub-check does not arise for
  an analog SPICE-reference compare.
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
- **Item 11 — Power delivery (structural): `unmet`
  (`supply_spec_incomplete`)**. Before #81 this row rendered
  `check_failed` because its LVS half (item 4) was a mismatch. That half
  now passes (item 4 above), and the grader stops at the ERC half
  instead. Reason `supply_spec_incomplete` here means that the cited spec
  declares no `ties[]` and no `ties_disclosure`, so `erc.missing_tie` is
  never computed (klayout-tools `docs/cli/signoff.md` reason table). The
  follow-up is tracked in #90.
  Cited: `layout/bias_core/erc-supply-spec.json` (rationale in
  `layout/bias_core/erc-supply-spec.md`, because klt at this pin rejects
  an inline `_comment`) and `layout/bias_core/erc.json`, pinned to the
  committed GDS's `sha256:9c414f91…7ab68e`, the same pin as item 3.
  **What the ERC citation establishes:** with `VDD`/`VSS` declared
  `kind: "supply"`, `erc_status: "clean"`, with zero
  `erc.unconnected_net` and zero `erc.supply_short` over 18 gate nets.
  Each supply resolves to exactly **one** island, and those islands
  contain the blocks' real supply pads. The pad-point island census
  (`layout/bin/pad-island-census.py` →
  `layout/bias_core/pad-island-census.json`, pinned to the GDS sha256)
  probes all 39 declared pads of the 15 connectivity/pin nets and finds
  each net to be exactly one island (`VDD,vdd`, `VSS,vss`, …). The spec's
  stackup now includes met5/via4 (the `pb` route), and its `devices[]`
  cuts the poly-resistor bodies (`66/13`) and the MiM top-plate via3
  (`89/44`) out of the conductor graph. Without those cuts the graph
  bridged the resistor and capacitor terminals: island names like
  `VDD,nokx` appeared, which LVS shows are not shorts. The run omits
  `--pdk` deliberately, so the top-level `status` is `not_checked` and the
  command exits `4`. The item grades `erc_status`, not the exit code.
  **What it does not establish:**
  1. `erc.missing_tie` is **not computed** (no `ties[]`). sky130's native
     p-substrate has no drawn well layer, so a VSS substrate tie is
     undeclarable in `klt erc` today (klayout-tools#2186's documented
     limitation). A blanket `nwell → VDD` probe after #69 left exactly 2
     findings, both on the PNP device-group tubs, which tie to their own
     nodes by design. That probe was **not** re-run for #81. Zero
     `erc.missing_tie` in the committed report is an **absence of
     evidence, not evidence of absence**. #90 tracks declaring the
     nwell tie with the PNP tubs excluded and disclosing the substrate
     class.
  2. The LVS half rests on item 4's topology match. The supplies
     appear in its `net_correspondence` paired to the reference's
     `VDD`/`VSS`, but device values are not compared (see item 4).

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
