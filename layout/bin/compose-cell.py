#!/usr/bin/env python3
"""Compose one layout cell from klt primitive generators and verify it.

Reads a cell descriptor (``layout/<cell>/cell.json``) and drives the whole
klayout-tools (``klt``) layout chain for that cell, end to end:

    klt gen (per device/tap block)
      -> klt gen-compose (place + route)
      -> klt drc          (rule sign-off)
      -> klt extract      (layout-derived netlist)
      -> klt lvs          (extracted vs. design/*.spice reference)

Every step's JSON response is written next to the descriptor, so the
committed contents of ``layout/<cell>/`` are the full, re-checkable evidence
trail for that cell rather than a bare GDS.

Usage
-----

    python3 layout/bin/compose-cell.py layout/temp_core/cell.json
    python3 layout/bin/compose-cell.py layout/temp_core/cell.json --check

``--check`` re-runs everything into a temporary directory and diffs the
verdict-bearing fields against what is committed, without touching the
committed files -- the layout sibling of ``design/netlist.py --check``.

Descriptor shape
----------------

See ``layout/README.md`` and ``layout/temp_core/cell.json``. In brief::

    {
      "cell": "<cell>",
      "pdk": {"variant": "sky130A", "deck": "sky130"},
      "blocks": [
        {"id": "mn", "generator": "mos_array", "cell_name": "nfet_...",
         "params": {...}, "orientation": "none"}
      ],
      "placement": {"strategy": "explicit", "order": [...],
                    "origins_um": {...}},
      "routing": {"layer_role": "metal", "width_um": 0.17},
      "connectivity": [...],
      "pins": [...],
      "lvs": {"reference": "design/<cell>.spice", "subckt": "<cell>"}
    }

Two-pass composition (``"stages"``, #27 step 2)
------------------------------------------------

Some cells have two nets that would short if both were routed on the same
metal layer in one ``klt gen-compose`` call. A cell.json may replace its
top-level ``blocks``/``placement``/``routing``/``connectivity``/``pins``
fields with a ``"stages"`` list instead, each entry shaped like those same
fields plus a ``"name"`` (required on every stage but the last, which is
always named after the cell itself and always ends up as
``compose.request.json``/``compose.response.json`` with no prefix -- so
``--check`` and the DRC/extract/LVS steps below are completely unaware
whether a cell used one stage or several). A later stage reaches an earlier
stage's composed cell through a ``blocks[].cell`` entry with ``from_stage``
(below); see ``layout/temp_core/cell.json`` for a worked example.

``blocks[].from_stage`` (a bare ``{"id": ..., "from_stage": ...}`` block that
handed a later stage the earlier stage's own ``gen-compose`` response as a
``generator_report``) is **removed** (#321). No committed cell recipe declared
it, and the technique is recorded as not routing for this repo's cells (see
``layout/README.md``). A descriptor that still carries it fails with a
``BuildError``; use ``blocks[].cell`` with ``from_stage`` instead.

Placing an already-composed sibling cell (``blocks[].cell``, #27 step 3)
-----------------------------------------------------------------------

A stage's ``blocks[]`` entry may name an *existing* committed stream instead
of a generator or an earlier stage::

    {"id": "g", "cell": {"gds_path": "../<other>/<other>.gds",
                         "cell_name": "<other>", "ports": [...]}}

``gds_path`` is relative to **the cell.json**, not to the output directory,
so it keeps the repo-relative spelling that keeps absolute home paths out of
the committed provenance. ``--check`` rebuilds into a temporary directory
where that relative path resolves to nothing, so there -- and only there --
this script substitutes the resolved absolute path.

Because a pre-existing stream never reported a ``ports[]`` list to any ``klt
gen`` response, its ports are hand-declared. Two things that costs, both
learned the hard way: the *only* authoritative source for a
two-stage cell's port geometry is its own **intermediate** stage response
(the final one reports ``"ports": []``), and a port may legitimately be
declared on a layer other than li1 -- declaring a rail port on met1, where
the leaf gate's own second stage already drew it, is what lets a later stage
route that rail on ``"metal3"`` within ``gen-compose``'s single-hop via-drop
rule.

Re-placing an earlier stage with hand-declared ports (``cell.from_stage``)
--------------------------------------------------------------------------

A later stage may tap an already-composed earlier stage's own interior
conductor at a measured coordinate that was never a ``pins[]`` entry. That is
``blocks[].cell``'s hand-declared ``ports[]`` shape, pointed at a stage rather
than at a committed sibling cell (``layout/temp_core/cell.json``)::

    {"id": "core", "cell": {"from_stage": "<earlier stage's name>", "ports": [...]}}

``cell_name`` defaults to the stage's own name (which is what
``compose_stage`` names its composed cell) and ``gds_path`` is filled in as
``<stage>.gds``, resolved against the **output** directory. That distinction
is the whole point: a committed sibling cell's ``gds_path`` is relative to
the cell.json and gets rewritten to an absolute path under ``--check``,
whereas a stage's stream is produced by the run in progress and must be read
back from wherever that run is writing -- otherwise a ``--check`` rebuild
would compose its later stages over the *committed* earlier stages and
report "matches" no matter what drifted.

The reference-netlist unit rewrite
----------------------------------

``design/*.spice`` is xschem's own export and is simulated under
``.option scale=1u`` (see any ``sim/*/testbench/*.spice``), so its device
cards carry *unitless* geometry that means micrometres: ``L=0.15 W=0.84``
is a 0.15 um x 0.84 um device.

``klt lvs``'s ``reference.form: "subckt-call"`` converter reads an unsuffixed
value as SI **metres** and rescales it, turning ``L=0.15`` into
``L=150000U`` -- a 0.15 m gate. The compare then fails with a
``device.unmatched``/``net.unmatched`` avalanche and no diagnostic pointing
at the units. Reported upstream (generically) as
2AMLogic/klayout-tools#1492.

Until that is fixed this script appends an explicit ``u`` suffix to the
``L=``/``W=`` values of the extracted reference subckt (and to the values of
any parameter substituted into them), which the converter then reads
correctly. Only the unit spelling changes -- no topology, no net names, no
device count, and the rewritten reference is written to disk
(``<cell>.ref.spice``) so a reviewer can diff it against the source subckt.

A multi-subckt reference (``lvs.dependencies``) needs more knobs, first
exercised by ``layout/temp_por_top/``:

``lvs.reference_top``
    Names the reference's top circuit. A file holding three ``.subckt``
    definitions has three *top* circuits as far as the SPICE reader is
    concerned, and ``klt lvs`` errors out rather than guessing which one to
    compare (``reference netlist has 3 top circuits (...); pass 'top' to
    select one``).
``lvs.flatten_reference``
    ``klt extract`` hands LVS a **flat** layout netlist, so a hierarchical
    reference has to be flattened to compare against it. LVS reports this
    back as a ``topology.flattened`` warning on an otherwise-matching run:
    the resulting ``match`` verifies device-for-device and net-for-net
    correspondence, but NOT that the layout's cell hierarchy mirrors the
    schematic's.
``lvs.drop_prefixes``
    Element-card name prefixes removed from the generated reference. A
    ``+`` continuation line after a removed card is removed with it. Whatever
    this removes is an *LVS exclusion* and must be disclosed in the cell's
    README (``layout/por_output_chain/`` once dropped ``XMASSIST``, a
    native-Vt NMOS, from its reference, then drew that device and retired the
    exclusion once klayout-tools grew the ``nvt`` voltage flavor -- see that
    README's blocker history; ``layout/temp_por_top/`` has since retired it
    too).
``lvs.expand_multiplier``
    Names of element cards carrying ``m=N`` that are rewritten as N
    single-instance cards (``<name>_0``..) because ``klt lvs``'s plain-element
    converter refuses multiplied devices; the layout must draw N devices.
``lvs.options.compare_mos_flavour``
    Forwarded verbatim (like every ``lvs.options`` entry) and, when set,
    switches the LVS request's layout side from the pre-extracted ``netlist``
    shape to inline extraction of the composed ``<cell>.gds``: the option
    compares MOS flavour (klayout-tools#3650 -- a reference
    ``sky130_fd_pr__nfet_05v0_nvt`` card then matches only a layout device
    carrying the native-Vt marker, class ``nfet__nvt``), and a pre-extracted
    netlist carries no flavour, so ``klt lvs`` rejects the combination. The
    standalone ``klt extract`` run of the chain still writes the committed
    ``extract.json``/``<cell>.spice`` (generic ``nfet``/``pfet`` cards -- the
    deck's flavour binning is an LVS-inline behavior, not an extract-report
    one); the ``lvs.json`` response names ``<cell>.gds`` as its layout input
    so the two stay distinguishable in the committed evidence.

``extract.top_cell_pins`` / ``extract.hierarchical_cells``
    Forwarded to ``klt extract`` as ``--top-cell-pins`` and
    ``--hierarchical-cells``. A cell that places several already-composed
    sibling streams needs them: the leaves label their internal nets
    independently, so the same label (or labels differing only by case --
    ``pb``/``PB``) recurs in more than one leaf, and a *flat* extracted netlist
    then collapses those distinct nets when ``klt lvs`` reads it back
    (``net.merged``). Naming the placed cells (spelled ``<block id>__<cell
    name>`` in the composed stream) writes one ``.SUBCKT`` per leaf, scoping
    each leaf's internal labels; pair it with ``lvs.flatten_layout`` so the
    hierarchical layout netlist is compared against the flattened reference
    (``layout/temp_por_top/``).

Compatibility note: ``lvs.dependency_variants`` (#22/#27, removed in #110),
``lvs.params`` and ``lvs.drop_kwargs`` (removed in #321) are **removed**.
``dependency_variants`` let a top subckt call one dependency at several
sizings; ``params`` substituted values for a subckt's own parameter names (and
stripped the ``.subckt`` header defaults); ``drop_kwargs`` stripped
pass-through keyword arguments from instance-call lines. No committed cell
recipe declared any of them, and the generated reference bodies of every
committed recipe are unchanged by the removals. A descriptor that still
carries one of the keys now fails with a ``BuildError`` naming it instead of
being silently ignored; an external recipe that relied on one must keep a
pre-removal copy of this script.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import BuildError, check_klt_pin, run_klt, write_json  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Verdict-bearing fields --check compares, per artifact.
CHECK_FIELDS: dict[str, tuple[str, ...]] = {
    "drc.json": ("status", "violation_count"),
    "extract.json": ("status", "device_count", "net_count", "device_counts"),
    "lvs.json": ("status", "mismatch_count", "error_count", "counts"),
    "compose.response.json": ("cell_name", "bbox_um"),
}


# --------------------------------------------------------------------------
# Reference-netlist extraction
# --------------------------------------------------------------------------

_SUBCKT_RE = r"^\.subckt\s+{name}\b"
_GEOMETRY_RE = re.compile(
    r"\b([LW])=([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)(?![0-9a-zA-Z.])"
)


def extract_subckt(netlist: Path, subckt: str) -> list[str]:
    """The ``.subckt <subckt> ... .ends`` block of ``netlist``, as lines."""
    start = re.compile(_SUBCKT_RE.format(name=re.escape(subckt)), re.IGNORECASE)
    lines = netlist.read_text().splitlines()
    for index, line in enumerate(lines):
        if start.match(line):
            for end in range(index, len(lines)):
                if lines[end].lower().startswith(".ends"):
                    return lines[index : end + 1]
            raise BuildError(f"{netlist}: .subckt {subckt} has no .ends")
    raise BuildError(f"{netlist}: no .subckt {subckt}")


def build_reference(
    lines: list[str],
    *,
    drop_prefixes: tuple[str, ...],
    expand_multiplier: tuple[str, ...] = (),
) -> list[str]:
    """Rewrite an xschem-exported subckt into a klt-lvs-ready reference.

    Four transformations, each deliberately minimal and each visible in the
    written-out result:

    1. The ``name=value`` parameter defaults are dropped from the ``.subckt``
       line.
    2. Element cards whose name starts with one of ``drop_prefixes`` are
       removed -- e.g. a lumped *simulation* load capacitor with no physical
       counterpart in the layout, not a device the layout omits.
    3. Unitless ``L=``/``W=`` values gain an explicit ``u`` suffix -- see this
       module's docstring for why (klayout-tools#1492).
    4. (``expand_multiplier``, issue #97) A named element card carrying
       ``m=N`` (N > 1) is replaced by N single-instance cards
       ``<name>_0``..``<name>_<N-1>`` with ``m=1``/``MF=1``, because ``klt
       lvs``'s plain-element converter refuses a multiplied device ("one
       device per drawn gate"). The layout draws N separate devices, so this
       is the same circuit written the way the layout draws it; the written
       reference shows the expansion.

    A ``+`` continuation line that follows a card removed by step 2 is removed
    with it (otherwise it would attach to the previous, unrelated card).
    """
    out: list[str] = []
    dropping = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("+"):
            if dropping:
                continue
        else:
            dropping = False
        if stripped.lower().startswith(".subckt"):
            # Drop `name=value` parameter defaults from the port list.
            head = [tok for tok in stripped.split() if "=" not in tok]
            out.append(" ".join(head))
            continue
        if drop_prefixes and stripped.upper().startswith(
            tuple(p.upper() for p in drop_prefixes)
        ):
            dropping = True
            continue
        toks = stripped.split()
        if toks and toks[0] in expand_multiplier:
            mm = re.search(r"\bm=(\d+)\b", stripped)
            count = int(mm.group(1)) if mm else 1
            for k in range(count):
                card = re.sub(r"\bm=\d+\b", "m=1", stripped)
                card = re.sub(r"\bMF=\d+\b", "MF=1", card)
                card = card.replace(toks[0], f"{toks[0]}_{k}", 1)
                out.append(_GEOMETRY_RE.sub(r"\1=\2u", card))
            continue
        out.append(_GEOMETRY_RE.sub(r"\1=\2u", line))
    return out


#: ``lvs`` keys retired for want of any committed recipe declaring them; a
#: descriptor still carrying one fails loudly instead of being ignored.
_RETIRED_LVS_KEYS: dict[str, str] = {
    "dependency_variants": ("#110; express each dependency through lvs.dependencies"),
    "params": "#321; no committed recipe declared it",
    "drop_kwargs": "#321; no committed recipe declared it",
}


def build_lvs_reference(reference_source: Path, lvs_spec: dict) -> list[str]:
    """Assemble a cell's whole LVS reference netlist from its ``lvs`` block.

    Returns the reference body: each ``lvs.dependencies`` subckt, then the top
    subckt, every one rewritten by :func:`build_reference`.

    ``lvs.dependency_variants`` (#110), ``lvs.params`` and ``lvs.drop_kwargs``
    (#321) were retired: no committed cell recipe declared them. A descriptor
    that still carries one is rejected with a ``BuildError`` naming the key
    rather than silently producing a reference the removed key would have
    shaped.
    """
    for key, hint in _RETIRED_LVS_KEYS.items():
        if key in lvs_spec:
            raise BuildError(f"lvs.{key} was removed ({hint})")
    drop_prefixes = tuple(lvs_spec.get("drop_prefixes", ()))
    expand_multiplier = tuple(lvs_spec.get("expand_multiplier", ()))

    def rewritten(subckt: str) -> list[str]:
        return build_reference(
            extract_subckt(reference_source, subckt),
            drop_prefixes=drop_prefixes,
            expand_multiplier=expand_multiplier,
        )

    out: list[str] = []
    for dependency in lvs_spec.get("dependencies", ()):
        out.extend(rewritten(dependency))
        out.append("")
    out.extend(rewritten(lvs_spec["subckt"]))
    return out


# --------------------------------------------------------------------------
# The chain
# --------------------------------------------------------------------------


def resolve_cell_block(
    cell_ref: dict,
    *,
    block_id: str,
    spec_dir: Path,
    out_dir: Path,
    stage_responses: dict[str, str],
) -> dict:
    """Resolve one ``blocks[].cell`` entry into a ``klt gen-compose`` block.

    Two sources, which differ *only* in what their ``gds_path`` is relative
    to -- and getting that wrong is silent, which is why this is its own
    function with its own unit coverage:

    A committed sibling cell (``gds_path``)
        A previously-composed, already-committed
        ``layout/<other-cell>/<other-cell>.gds`` this cell.json did not
        (re)generate, placed via ``klt gen-compose``'s own ``blocks[].cell``
        request shape (``{gds_path, cell_name, ports[], bbox_um}``, #1189 in
        klayout-tools). No ``klt gen`` call: there is nothing to generate,
        only an existing stream to place. This needs hand-declared
        ``ports[]`` (a pre-existing cell never reported a ``ports[]`` list to
        any ``klt gen`` response the way a fresh primitive does). Its ``gds_path`` is written relative to the
        **cell.json** (e.g. ``"../<other>/<other>.gds"``), which keeps the
        repo-relative spelling that keeps absolute home paths out of the
        committed provenance. Rebuilding in place (``out_dir`` is the cell's
        own directory) that resolves correctly as written; ``--check``
        rebuilds into a temporary directory instead, where it resolves to
        nothing -- so there, and only there, the resolved absolute path of
        the sibling cell's committed stream is substituted.

    An earlier stage of this same cell.json (``from_stage``)
        See this module's docstring, "Re-placing an earlier stage with
        hand-declared ports". That stream is written into ``out_dir`` by
        **this** run, so its path is relative to the *output* directory and
        must NOT be absolutized against ``spec_dir``: doing so would point a
        ``--check`` rebuild at the *committed* stage stream instead of the
        one it just rebuilt, quietly turning the reproducibility check into a
        no-op for every stage after the first.

    ``from_stage`` must name an **earlier** stage (one already present in
    ``stage_responses``); naming a later stage, or a typo, raises rather than
    composing against whatever stale stream happens to be on disk.
    """
    resolved = dict(cell_ref)
    from_stage = resolved.pop("from_stage", None)
    if from_stage is None:
        gds_path = resolved["gds_path"]
        if out_dir.resolve() != spec_dir.resolve():
            gds_path = str((spec_dir / gds_path).resolve())
        return {**resolved, "gds_path": gds_path}
    if from_stage not in stage_responses:
        raise BuildError(
            f"{block_id}: cell.from_stage {from_stage!r} does not name an "
            f"earlier stage (have: {sorted(stage_responses) or 'none'})"
        )
    resolved.setdefault("cell_name", from_stage)
    return {**resolved, "gds_path": f"{from_stage}.gds"}


def compose_stage(
    stage: dict,
    *,
    is_final: bool,
    cell: str,
    variant: str,
    env: dict[str, str],
    spec_dir: Path,
    out_dir: Path,
    stage_responses: dict[str, str],
) -> dict:
    """Run one stage's ``gen`` (per new block) + ``gen-compose`` (place/route).

    A stage's ``blocks[]`` entries are either freshly generated (the
    ``generator``/``params``/``cell_name`` shape) or an already-composed
    stream (``block["cell"]``, which may itself name an *earlier* stage via
    ``cell.from_stage``). See this module's docstring and ``layout/README.md``
    for why a cell ever needs more than one stage.

    The **final** stage (``is_final=True``) writes ``compose.request.json``/
    ``compose.response.json`` with no prefix, and its ``options.cell_name``
    is the cell's own name -- unprefixed, exactly as every single-stage cell
    already committed under ``layout/`` expects, so a cell.json with no
    ``"stages"`` key (wrapped by ``compose_cell`` into one implicit final
    stage) is byte-for-byte unaffected by this function's existence. A
    non-final stage's files are prefixed with its own ``name`` instead
    (``<name>.compose.request.json`` etc.), and its composed cell is named
    ``<name>``, so every stage's evidence lives in the cell's own directory
    without filename collisions.
    """
    gen_dir = out_dir / "gen"
    gen_dir.mkdir(parents=True, exist_ok=True)

    blocks_request = []
    for block in stage["blocks"]:
        if "from_stage" in block:
            raise BuildError(
                f"{block['id']}: blocks[].from_stage was removed (#321); "
                "use blocks[].cell with from_stage and hand-declared ports"
            )
        if "cell" in block:
            cell_block = resolve_cell_block(
                block["cell"],
                block_id=block["id"],
                spec_dir=spec_dir,
                out_dir=out_dir,
                stage_responses=stage_responses,
            )
            blocks_request.append(
                {
                    "id": block["id"],
                    "cell": cell_block,
                    **(
                        {"orientation": block["orientation"]}
                        if block.get("orientation", "none") != "none"
                        else {}
                    ),
                }
            )
            continue
        response = run_klt(
            [
                "gen",
                block["generator"],
                "--params",
                json.dumps(block["params"]),
                "--pdk",
                variant,
                "--cell-name",
                block["cell_name"],
                "-o",
                f"gen/{block['id']}.gds",
            ],
            env=env,
            cwd=out_dir,
        )
        write_json(gen_dir / f"{block['id']}.gen.json", response)
        blocks_request.append(
            {
                "id": block["id"],
                "generator_report": f"gen/{block['id']}.gen.json",
                **(
                    {"orientation": block["orientation"]}
                    if block.get("orientation", "none") != "none"
                    else {}
                ),
            }
        )

    name = cell if is_final else stage["name"]
    prefix = "" if is_final else f"{stage['name']}."
    request = {
        "pdk": {"variant": variant},
        "blocks": blocks_request,
        "placement": stage["placement"],
        "routing": stage["routing"],
        "connectivity": stage["connectivity"],
        "pins": stage.get("pins", []),
        "options": {"cell_name": name, "output": f"{name}.gds"},
    }
    write_json(out_dir / f"{prefix}compose.request.json", request)
    compose = run_klt(
        ["gen-compose", f"{prefix}compose.request.json"], env=env, cwd=out_dir
    )
    write_json(out_dir / f"{prefix}compose.response.json", compose)
    unrouted = [net["net"] for net in compose.get("nets", []) if not net.get("routed")]
    if unrouted:
        raise BuildError(f"{name}: nets left unrouted by gen-compose: {unrouted}")
    return compose


def compose_cell(spec: dict, spec_dir: Path, out_dir: Path) -> dict:
    """Run the full gen -> compose -> drc -> extract -> lvs chain.

    ``spec["stages"]`` is optional (#27 step 2): a list of stage dicts, each
    shaped like this function's single-stage fields
    (``blocks``/``placement``/``routing``/``connectivity``/``pins``) plus a
    ``name`` (required on every stage but the last, which is always named
    after the cell itself). When absent, ``spec`` itself is wrapped as the
    one implicit final stage -- every cell.json committed before #27 step 2
    has no ``"stages"`` key and is therefore unaffected by this branch.
    """
    cell = spec["cell"]
    variant = spec["pdk"]["variant"]
    deck = spec["pdk"]["deck"]
    env = {**os.environ, "PDK": variant}

    stages = spec.get("stages") or [
        {
            "blocks": spec["blocks"],
            "placement": spec["placement"],
            "routing": spec["routing"],
            "connectivity": spec["connectivity"],
            "pins": spec.get("pins", []),
        }
    ]

    stage_responses: dict[str, str] = {}
    compose = None
    for index, stage in enumerate(stages):
        is_final = index == len(stages) - 1
        compose = compose_stage(
            stage,
            is_final=is_final,
            cell=cell,
            variant=variant,
            env=env,
            spec_dir=spec_dir,
            out_dir=out_dir,
            stage_responses=stage_responses,
        )
        if not is_final:
            stage_responses[stage["name"]] = f"{stage['name']}.compose.response.json"
    assert compose is not None  # stages is always non-empty

    # 3. DRC.
    drc = run_klt(["drc", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "drc.json", drc)

    # 4. Extraction.
    extract_spec = spec.get("extract") or {}
    extract_args = ["extract", f"{cell}.gds", "--deck", deck]
    if extract_spec.get("top_cell_pins"):
        extract_args.append("--top-cell-pins")
    if extract_spec.get("hierarchical_cells"):
        extract_args += [
            "--hierarchical-cells",
            ",".join(extract_spec["hierarchical_cells"]),
        ]
    extract = run_klt(extract_args, env=env, cwd=out_dir)
    write_json(out_dir / "extract.json", extract)

    # 5. LVS against the design's own schematic-exported subckt.
    lvs_spec = spec["lvs"]
    reference_source = REPO_ROOT / lvs_spec["reference"]
    dependency_subckts = lvs_spec.get("dependencies", ())
    reference_lines = build_lvs_reference(reference_source, lvs_spec)
    reference_path = out_dir / f"{cell}.ref.spice"
    dependency_note = (
        f" plus dependency subckt(s) {', '.join(dependency_subckts)}"
        if dependency_subckts
        else ""
    )
    reference_path.write_text(
        "\n".join(
            [
                f"* Reference netlist for {cell} LVS -- GENERATED by "
                "layout/bin/compose-cell.py",
                f"* Source: {lvs_spec['reference']} .subckt "
                f"{lvs_spec['subckt']}{dependency_note}",
                "* Mechanically rewritten from the source by build_reference -- see",
                "* compose-cell.py's docstring for the exact transformations.",
                *reference_lines,
                "",
            ]
        )
    )
    lvs_options = {}
    if lvs_spec.get("flatten_reference"):
        lvs_options["flatten_reference"] = True
    if lvs_spec.get("flatten_layout"):
        lvs_options["flatten_layout"] = True
    # Forward the cell.json's own declared LVS options verbatim (e.g.
    # ``options.compare_parameters``, the disclosed device-parameter
    # exclusion the PNP cells use for sky130's fixed-geometry ``AE`` gap --
    # klayout-tools#2335) so a cell can scope its own comparison without a
    # compose-cell.py change per option. Explicit lvs block keys keep
    # winning over same-named forwarded keys.
    for key, value in (lvs_spec.get("options") or {}).items():
        lvs_options.setdefault(key, value)
    lvs_request = {
        # ``deck`` on the layout side lets klt lvs re-ingest the bare-mode
        # 3-terminal resistor ``X`` cards klt extract writes since
        # klayout-tools#2336 (without it they read back as unmatched
        # subcircuit stubs, not resistors).
        #
        # ``options.compare_mos_flavour`` (klayout-tools#3650) compares MOS
        # flavour, which only the *inline-extracted* layout shape carries --
        # a pre-extracted netlist has no flavour, and klt lvs application-errors
        # on the combination rather than silently comparing unflavoured. When
        # the cell opts in, hand klt lvs the composed stream instead of the
        # extracted netlist so the flavoured devices (e.g. ``mos_array``'s
        # ``voltage_flavor`` markers) take part in the compare.
        **(
            {
                "layout": {"file": f"{cell}.gds", "deck": deck},
            }
            if lvs_options.get("compare_mos_flavour")
            else {
                "layout": {
                    "netlist": str(Path(extract["netlist_path"]).name),
                    "deck": deck,
                },
            }
        ),
        "reference": {
            "netlist": reference_path.name,
            "form": "subckt-call",
            "deck": deck,
            # A multi-subckt reference (lvs.dependencies) leaves klt lvs more
            # than one candidate top circuit -- every subckt definition in
            # the file is a top circuit as far as the reader is concerned,
            # because it sees several definitions and no single root. `reference.top` names the one
            # to compare against; klt errors out rather than guessing.
            **(
                {"top": lvs_spec["reference_top"]}
                if lvs_spec.get("reference_top")
                else {}
            ),
        },
        **({"options": lvs_options} if lvs_options else {}),
    }
    write_json(out_dir / "lvs.request.json", lvs_request)
    lvs = run_klt(["lvs", "lvs.request.json"], env=env, cwd=out_dir)
    write_json(out_dir / "lvs.json", lvs)

    return {
        "cell": cell,
        "drc": f"{drc['status']} ({drc['violation_count']} violations)",
        "extract": (
            f"{extract['status']}: {extract['device_count']} devices, "
            f"{extract['net_count']} nets"
        ),
        "lvs": (
            f"{lvs['status']}: {lvs['counts']['devices']['matched']}/"
            f"{lvs['counts']['devices']['reference']} devices, "
            f"{lvs['counts']['nets']['matched']}/"
            f"{lvs['counts']['nets']['reference']} nets matched"
        ),
        "clean": (
            drc["status"] == "clean"
            and drc["violation_count"] == 0
            and extract["status"] == "extracted"
            and lvs["status"] == "match"
        ),
    }


def check_cell(spec: dict, spec_dir: Path) -> int:
    """Rebuild into a temp dir and diff verdicts against what is committed."""
    with tempfile.TemporaryDirectory(prefix="klt-compose-cell-") as tmp:
        tmp_dir = Path(tmp)
        compose_cell(spec, spec_dir, tmp_dir)
        drift: list[str] = []
        for name, fields in CHECK_FIELDS.items():
            committed_path = spec_dir / name
            if not committed_path.exists():
                drift.append(f"{name}: missing from {spec_dir}")
                continue
            committed = json.loads(committed_path.read_text())
            rebuilt = json.loads((tmp_dir / name).read_text())
            for field in fields:
                if committed.get(field) != rebuilt.get(field):
                    drift.append(
                        f"{name}.{field}: committed={committed.get(field)!r} "
                        f"rebuilt={rebuilt.get(field)!r}"
                    )
        # A multi-stage cell.json (#27 step 2) also commits each non-final
        # stage's own "<name>.compose.response.json" (see compose_stage's
        # docstring) -- diff those too, on the same verdict-bearing fields
        # as the final compose.response.json above, so drift in an earlier
        # stage's own placement/routing is caught even when it happens not
        # to move the final cell's own bbox/DRC/LVS verdict.
        for committed_path in sorted(spec_dir.glob("*.compose.response.json")):
            if committed_path.name == "compose.response.json":
                continue  # the final stage, already diffed above
            rebuilt_path = tmp_dir / committed_path.name
            if not rebuilt_path.exists():
                drift.append(f"{committed_path.name}: missing from rebuild")
                continue
            committed = json.loads(committed_path.read_text())
            rebuilt = json.loads(rebuilt_path.read_text())
            for field in CHECK_FIELDS["compose.response.json"]:
                if committed.get(field) != rebuilt.get(field):
                    drift.append(
                        f"{committed_path.name}.{field}: "
                        f"committed={committed.get(field)!r} "
                        f"rebuilt={rebuilt.get(field)!r}"
                    )
    if drift:
        print(f"DRIFT in {spec_dir}:", file=sys.stderr)
        for entry in drift:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print(f"{spec_dir}: rebuild matches committed evidence")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="path to a layout/<cell>/cell.json")
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild into a temp dir and diff verdicts against the committed "
        "evidence instead of overwriting it",
    )
    args = parser.parse_args(argv)

    check_klt_pin(REPO_ROOT / "layout" / "pdk.json", env=os.environ.copy())

    spec_path = args.spec.resolve()
    spec = json.loads(spec_path.read_text())
    spec_dir = spec_path.parent

    try:
        if args.check:
            return check_cell(spec, spec_dir)
        summary = compose_cell(spec, spec_dir, spec_dir)
    except BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"cell:    {summary['cell']}")
    print(f"drc:     {summary['drc']}")
    print(f"extract: {summary['extract']}")
    print(f"lvs:     {summary['lvs']}")
    return 0 if summary["clean"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
