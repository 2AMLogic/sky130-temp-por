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

## Artifact manifests (`manifests/artifacts/`)

`manifests/artifacts/<slug>-<record-id>.manifest.json` and `.summary.md` are the
committed half of every new simulation run: the raw logs, traces and fleet
reports live in the fleet artifact store, and the manifest lists them as
`artifact:<key>` URIs with a size and sha256 each. Manifests are public-safe (no
bucket, account or broker URL, and no storage-scheme URI; CI greps for them). They are written only by `sim/bin/evidence_store.py`, which fails
closed: with no `$KLT_ARTIFACT_BROKER`, no `klt artifact put`/`verify`, or an
unreachable broker, the run exits nonzero and nothing is committed. They are
append-only like the rest of the evidence, and
`.github/scripts/check_artifact_manifests.py` checks them in CI. Verify one from
a fleet worker with `klt artifact verify <manifest>`. They are separate from
the signoff report and attestations below. Flow and rationale: `sim/README.md`,
"New evidence goes to the artifact store".

## Attestation inventories (items 1, 9, 10)

`manifests/inventories/item-{1,9,10}.json` are `klt signoff --attest`
inventories (schema in klayout-tools `docs/cli/signoff.md` → "Attesting items
1, 9 and 10"). Regenerate a passing envelope after changing anything it
lists (a whitespace edit changes a hash):

```sh
klt signoff --attest 10 --inventory manifests/inventories/item-10.json \
  -o manifests/attestations/item-10.json
```

then cite its `provenance.input.content_hash` in the manifest and re-render
the report. Item 10's inventory lists `.github/workflows/signoff-manifest.yml`,
so that workflow is self-hashed: make every workflow edit first, regenerate
the item-10 envelope last, and confirm `--check` returns `match` before the
final commit. `-o` writes only a passing envelope.

A command spec may carry `"local_only": true` (item 1's five `derived[].check`
entries and item 9's `cold_start` do, because they need xschem and the sky130
PDK). The field is an *inventory* field, not a CLI flag, so it does not appear
in `klt signoff --help`. It changes nothing about which files are hashed: a
re-attestation (`-o`) runs the command as usual, and a `--check` skips it on
**every** host — not only one lacking the toolchain — reporting
`[SKIP] … (local_only, not run; committed outcome: …)` and carrying the
attest-time outcome into `fresh_status`, so a committed failure still fails the
gate. Marking a command `local_only` therefore makes `--check` runnable
unconditionally in CI; it never makes a skipped command look like a passing
one. See "CI: freshness is enforced, not remembered" below.

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

- **Item 1 — Design sources: `met`** via the artifact-anchored attestation
  `item-1.json` (22/22 checks, #220), pinned to its inventory by content hash
  like items 9 and 10. (Since klayout-tools#2718 items 1, 2, 9 and 10 accept
  only an artifact-anchored envelope, so the old native LVS envelope no longer
  satisfies it.) The inventory (`inventories/item-1.json`) lists the 10 xschem
  sources (`design/*.sch`, `*.sym`), the export tool and `design/xschemrc`,
  and the 5 committed netlists. Each netlist carries the freshness check
  `python3 design/netlist.py --check`, which passed on all 5 (netlists
  reproduce byte-for-byte). **Route and version:** run locally with the
  worker's PATH xschem, XSCHEM V3.4.7 (>= 3.4.5 is required; 3.4.4 does not
  evaluate `expr()`), against the sky130 PDK; no `--xschem-binary` pin and no
  `--backend batch`. **Limits:** it shows the committed netlists are what the
  committed schematics export, not that the circuit is right. The five
  `python3 design/netlist.py --check` freshness commands need xschem and the
  PDK, so they are marked `"local_only": true` in the inventory and are
  **never run under `--check` on any host** — including a worker that has
  xschem (see "CI: freshness is enforced" below). A schematic edit that stops
  reproducing its netlist is therefore caught only by re-attesting, or by
  running `python3 design/netlist.py --check` directly. What `--check` *does*
  enforce, on a stock runner and since #303 unconditionally: all 17 files
  this envelope recorded a `content_hash` for are re-hashed, and the
  inventory pin, the check count and every committed outcome are diffed, so
  an edited source turns the `signoff` job red. That is the gap that let
  `design/netlist.py` sit stale in this envelope from `6d11c6ec` until #298
  with every job green — the manifest pins the envelope to its *inventory*
  file's hash, never to the sources, so nothing in the graded chain noticed.
  After editing anything in the inventory, re-run `klt signoff --attest 1
  --inventory manifests/inventories/item-1.json -o
  manifests/attestations/item-1.json` locally (that run *does* execute the
  five freshness checks), then re-cite and re-render.
- **Item 2 — Layout: `met`** via the hand-written artifact-anchored
  envelope `attestations/item-2.json` (#240; `klt signoff --attest` does not
  cover item 2, so `layout/bin/attest-layout.py` writes it). It binds, as a set
  (`provenance.input.paths`), the committed `layout/temp_por_top/temp_por_top.gds`
  and its recipe `layout/temp_por_top/cell.json`, and carries a regeneration
  claim: the script rebuilds the stream from the recipe and refuses to write
  the envelope unless the rebuild is byte-identical. Any edit to either file
  (or to a leaf stream the top embeds) turns the row `stale_evidence`.
  **What it does not claim:** presence and reproducibility only. The top's
  recorded checks are *not* clean and are not cited — DRC is
  clean (0 violations, #243: leaf streams regenerated at the pinned klt), ERC
  clean (#260), and an LVS `match` (152/152
  devices, 71/71 nets) that excludes the native-Vt `XMASSIST` (#97). See
  `layout/temp_por_top/README.md`.
- **Item 3 — DRC clean: `met`** via `layout/temp_por_top/drc.json` (`status:
  clean`, 0 violations), pinned to
  `content_hash sha256:1af73f5f…ca40539`, the sha256 of the committed
  `layout/temp_por_top/temp_por_top.gds` the run executed on, so the
  citation is provably fresh against the current artifact (CI re-asserts
  this). T1 is block-scoped (#259), so this grades the block's own layout,
  not a sub-block. **Scope disclosure, per item 3's own claimant-enforced
  rule:** the graded coverage gaps are quoted verbatim in the committed
  report's `citation.coverage` block: 9 drawn layers with no rule (the
  pin-text purposes `67/5`…`72/5`, plus `66/13` `poly.res` and `82/44`,
  `83/20`); the skipped rules are `angle`/`ongrid` checks for layers this
  stream does not draw plus the `capm2.*`/`met4.enclosing.capm2.1`
  second-MiM rules; and `deck_scope` lists the deck chapters the run was
  measured inside. A `met` verdict here does not assert those gaps were
  acceptable — it asserts the run was clean inside the coverage it had, and
  this README is where the gaps are disclosed.
- **Item 4 — LVS clean: `met`** via `layout/temp_por_top/lvs.json`. The
  block-level `temp_por_top` LVS reports `status: match`, **152/152
  devices and 71/71 nets**. **Not proven by this envelope:** it is not a
  full-block compare. The native-Vt `XMASSIST` device is excluded via
  `lvs.drop_prefixes` because klt cannot draw or compare it
  (klayout-tools#2912, #97); see `layout/temp_por_top/README.md`. It also
  carries disclosed warnings: the `PNP` compare is scoped to `NE`, so `AE`
  is not verified; the reference has `R=0`/`C=0` placeholders on the
  `res_xhigh_po` and MiM caps, so their values are not compared; and the
  reference is flattened. The match is a topology match. The envelope
  carries no `power_connectivity` verdict, because that sub-check does not
  arise for an analog SPICE-reference compare. The `bias_core` sub-block
  LVS (50/50 devices, 27/27 nets) is sub-block evidence and is no longer
  cited.
- **Items 5, 6, 7, 8 — `unmet` (`no_evidence`)**, each for a real reason:
  the target spec is only **partially ratified** (DR-003 is `ratified`, scoped,
  issue #78: operating temperature and supply are final; six rows, including
  POR thresholds, hysteresis, Iq and supply-ramp coverage, stay `[TBD]`;
  no `target-spec.md` exists), so item 5's "vs a ratified spec" has nothing
  complete to verify against, and this repo's PVT-corner and mismatch
  Monte-Carlo records live under `sim/` as the sim harness's own JSON
  records — which are not `klt sim`/`klt yield` envelopes, so no passing
  envelope backs items 5/6; no `klt pex` report exists (item 7 rejects every
  other evidence kind, and none is cited pretend-adjacent); the aggregated
  block-level characterization artifact for item 8 exists
  (`docs/characterization-report.md`, #31, refreshed in #122 and guarded by
  `.github/scripts/check_characterization_coverage.py` so every `sim/`
  experiment with records is cited), but it is a hand-aggregated report that
  states FAILs and gaps as such, not a passing check, so item 8 stays
  `unmet`.
- **Items 9, 10 — `met`** via artifact-anchored attestations (#186), each
  pinned to its inventory by content hash. The inventories live in
  `manifests/inventories/`; the passing envelopes `klt signoff --attest N
  --inventory ... -o` produced live in `manifests/attestations/`.
  - **Item 9** (`item-9.json`, 43/43 checks): 40 files present (every
    `sim/*/experiment.json`, testbench schematic or `.spice`, campaign
    runner, the corner runner, `sim/pdk.json`, `spiceinit`, `xschemrc`), the
    cold start, and the PDK/tool pins. `sim/pdk.json` is inventoried, so a PDK
    re-pin (#188) changes its hash and the next `--check` drifts until the
    envelope is regenerated. **Limits:** the cold start is
    `python3 sim/bin/corner-run.py sim/bias-core-smoke --dry-run`. It netlists
    the testbench with xschem and prints the corner list and one deck. It does
    **not** run ngspice, so it shows the harness starts cold, not that any
    result is right (the PVT-corner results are in `sim/*/records/`, graded by
    no klt check). The `pins` block (PDK `c6d73a35…`, ngspice 46, xschem
    3.4.7, klt) is recorded as claimed; klt checks it is non-empty, not that
    the installed tools match. The cold start needs xschem and the PDK, so it is
    marked `"local_only": true` and is **never run under `--check` on any
    host**; re-attesting runs it, as does `python3 sim/bin/corner-run.py
    sim/bias-core-smoke --dry-run` on its own. CI does re-attest the rest of
    the envelope unconditionally (since #303): all 40 files this envelope
    recorded a hash for are re-hashed — which is how 8 of them were found
    stale on `main` — and the inventory pin, the check count and every
    committed outcome are diffed.
  - **Item 10** (`item-10.json`, 10/10 checks): `README.md`, `LICENSE` and
    both workflows present, plus six stdlib-only audit commands
    `self-checks.yml` also runs (netlist pinout invariants, JSON
    well-formedness, characterization coverage, append-only checker
    selftest, ramp and brown-out checker selftests). **Limits:** it does not
    run the SPICE campaigns, layout composition, DRC/LVS or the
    `unittest` suites, and "CI passed" is not a check (a `gh run view`
    query would need credentials and a network). Hygiene here means the
    files exist and the cheap audits run clean.
- **Item 11 — Power delivery (structural): `met`**
  (#259, #260). It cites the block-level
  `layout/temp_por_top/erc.json` (pinned to the GDS
  `sha256:1af73f5f…ca40539`, the same pin as item 3) and item 4's
  `layout/temp_por_top/lvs.json`. The ERC run uses the block-specific supply
  spec (`layout/temp_por_top/erc-supply-spec.json`, with the `NT` well tie
  for the `temp_core` nwells of `XMI1`/`XMI2`) and reports
  `erc_status: clean`. VDD and VSS are each one island at the top. The LVS
  half carries the same `XMASSIST` exclusion as item 4. Until #259 this row
  cited `layout/bias_core/`, which overclaimed: T1 is block-scoped, and the
  `bias_core` evidence (`layout/bias_core/erc.json`,
  `pad-island-census.json`) is sub-block evidence only and is not cited.

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
4. re-attests items 10, 9 and 1 against their committed envelopes
   (`klt signoff --attest N ... --check`), **unconditionally — no toolchain
   guard, no skipped step**. Each `--check` re-hashes every file that item's
   inventory lists (4 + 40 + 17 = 61 today) and diffs the whole envelope:
   the inventory pin, the check count, and every committed check outcome. So
   an edit to any attested design source, testbench or hygiene file that
   lands without a re-attestation turns this job red.

   **What `--check` does not run, and on no host:** item 1's five `python3
   design/netlist.py --check` freshness commands and item 9's cold start are
   marked `"local_only": true` in their inventories. klt skips *every*
   `local_only` command whenever `--check` is given — this is not
   conditional on the toolchain being absent, so a local `--check` on a
   worker that *has* xschem does not run them either (#303). Each is
   reported as

   ```
   [SKIP] cold_start cold_start: python3 sim/bin/corner-run.py sim/bias-core-smoke --dry-run (local_only, not run; committed outcome: pass)
   ```

   carrying the attest-time outcome, never counted as passed by that run. A
   check that cannot run must never look like one that passed
   (`.loom/docs/ci-principles.md`), and this is what that looks like in the
   job log.

   **Re-verify the skipped commands locally** after changing `design/` or
   `sim/`, by either route:
   - re-attest, which does run them (and refuses to write a failing
     envelope): `klt signoff --attest 1 --inventory
     manifests/inventories/item-1.json -o manifests/attestations/item-1.json`
     (likewise `--attest 9`); or
   - run them directly: `python3 design/netlist.py --check` and
     `python3 sim/bin/corner-run.py sim/bias-core-smoke --dry-run`.

   Both need xschem >= 3.4.5 and the sky130 PDK. And
5. re-hashes every committed file a *citation* envelope recorded a hash for,
   via `manifests/check-citations.py`:
   - the artifact behind each `content_hash` pin
     (`layout/temp_por_top/temp_por_top.gds`), resolved against the
     envelope's own directory; and
   - the two compare netlists behind each unpinned LVS citation, against the
     envelope's recorded `environment.layout_sha256` /
     `reference_sha256`.

   This closes the same class of gap for the citation shapes that step 4's
   `--check` closes for the attestation shapes: `klt signoff --manifest`
   grades a citation against the hash the envelope *recorded*, never against
   the file on disk, so a redrawn GDS would otherwise leave the pin, the
   re-rendered report and the byte-compare all agreeing with an artifact
   that no longer exists.
   `manifests/test_check_citations.py` covers the checker in
   `self-checks.yml`.

   **Decision (#303): `check-citations.py` does not re-hash
   `attestation.checks[]`.** #299 gave it a second branch that did, because
   items 1 and 9 could not be re-attested in CI at all. Marking their
   toolchain-bound commands `local_only` removed that premise: step 4 now
   re-hashes the same 61 files on the same runner, and more besides. Keeping
   both would be two mechanisms for one behaviour, and the repo-owned one
   hides the pinned tool's feature this canary exists to exercise, so the
   attestation branch was removed and the script narrowed back to the
   citation shapes. The one thing lost is klt's drift diff naming the
   drifted file by index (`attestation.checks.17.content_hash`) rather than
   by path, where the repo-owned checker printed a `STALE <path>` line; that
   is a diagnostics gap in the tool, filed as klayout-tools#5460 per the
   friction protocol, not worked around here.

When the layout or design evidence moves, regenerate the report
(`Regenerate` above), update any affected citation or pin in the manifest,
and commit them together — the workflow revision pin and the report move in
the same PR by construction.

Provenance hygiene per `docs/design-evidence-tiers.md` ("Provenance hygiene
in evidence records"): the committed report cites repo-relative paths only
and embeds content hashes, never host or author identifiers.

## What CI covers (and does not)

Two workflows run on every push to `main` and every PR:

- `signoff-manifest.yml` -- the signoff freshness gate described above.
- `self-checks.yml` -- fast, deterministic, stdlib-only checks (no SPICE, no
  layout composition, no klt, no xschem):
  - `python3 -m unittest layout/bin/test_pad_island_census.py` (the three
    `klayout.db`-dependent cases skip in CI; they need klt's interpreter);
  - `python3 sim/supply-ramp-top/ramp_checker.py` (transition-checker selftest
    fixtures; exits non-zero on any MISMATCH);
  - `python3 -I sim/brownout-top/brownout_checker.py` (brown-out waveform
    checker's 16 synthetic verdict cases; exits non-zero on any expected
    verdict or required failure-code MISMATCH; run directly, not via the
    campaign runner's selftest, so it writes no append-only record);
  - `python3 design/check_committed_netlists.py` (pinout / cross-cell
    invariants from `design/netlist.py` applied to the committed
    `design/netlist/*.spice`);
  - `python3 .github/scripts/check_json.py` (every `sim/*/experiment.json` and
    `sim/*/records/*.json` parses);
  - `python3 -I .github/scripts/check_characterization_coverage.py --selftest`
    and the real run (every `sim/<experiment>/` directory with records is cited
    by `docs/characterization-report.md`; citation coverage only, the numbers
    stay human-curated and are not checked).

Not covered: `python3 design/netlist.py --check` (committed netlists match the
schematics) and item 9's cold start need xschem and the sky130 PDK, so they are
not runnable on a stock runner -- they are marked `local_only` in their
inventories and are skipped by every `klt signoff --attest ... --check`, on this
or any host. Run them locally after schematic or `sim/` edits (or re-attest,
which runs them). Also not covered: any SPICE
campaign, `layout/bin/compose-cell.py --check` / layout composition, DRC/LVS,
and JSON schema validation (only well-formedness is checked).
