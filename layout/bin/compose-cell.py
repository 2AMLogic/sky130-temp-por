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

    python3 layout/bin/compose-cell.py layout/ro_buf/cell.json
    python3 layout/bin/compose-cell.py layout/ro_buf/cell.json --check

``--check`` re-runs everything into a temporary directory and diffs the
verdict-bearing fields against what is committed, without touching the
committed files -- the layout sibling of ``design/netlist.py --check``.

Descriptor shape
----------------

See ``layout/README.md`` and ``layout/ro_buf/cell.json``. In brief::

    {
      "cell": "ro_buf",
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
      "lvs": {"reference": "design/ro_array_core.spice", "subckt": "ro_buf"}
    }

Two-pass composition (``"stages"``, #27 step 2)
------------------------------------------------

Some gates have two nets that would short if both were routed on the same
metal layer in one ``klt gen-compose`` call -- ``ro_stage``/``ro_nand2``'s
always-on starve devices cross-couple their gates to the *opposite* rail
(``Mph.g = vss``, ``Mnt.g = vddr``), so wiring both crossing nets on the
base ``"metal"`` role in a single pass is not routable without one net
running through the other's block or backbone (see ``layout/README.md``'s
"Composing a gate" section). A cell.json may replace its top-level
``blocks``/``placement``/``routing``/``connectivity``/``pins`` fields with a
``"stages"`` list instead, each entry shaped like those same fields plus a
``"name"`` (required on every stage but the last, which is always named
after the cell itself and always ends up as ``compose.request.json``/
``compose.response.json`` with no prefix -- so ``--check`` and the DRC/
extract/LVS steps below are completely unaware whether a cell used one
stage or several). A later stage's ``blocks[]`` entry may reference an
earlier stage's own composed cell instead of a fresh ``klt gen`` call via
``{"id": ..., "from_stage": "<earlier stage's name>"}``, which resolves to
that stage's own ``<name>.compose.response.json`` -- a valid
``generator_report`` in its own right, since ``klt gen-compose``'s response
already carries ``generator: "gen-compose"`` plus a composed-frame
``ports[]`` promoted from that stage's own ``pins[]`` (this is what the CLI
itself calls composition "nesting"). The usual second stage routes the two
gate-crossing nets on ``"metal2"`` (sky130 met1) with an automatic via-drop
back to each pin's own base-``"metal"``-role pad, over the first stage's
already-composed cell -- see ``layout/ro_stage/cell.json`` for a worked
example and ``layout/ro_stage/README.md`` for why each net landed on the
layer it did.

Placing an already-composed sibling cell (``blocks[].cell``, #27 step 3)
-----------------------------------------------------------------------

A stage's ``blocks[]`` entry may name an *existing* committed stream instead
of a generator or an earlier stage::

    {"id": "g", "cell": {"gds_path": "../ro_nand2/ro_nand2.gds",
                         "cell_name": "ro_nand2", "ports": [...]}}

``gds_path`` is relative to **the cell.json**, not to the output directory,
so it keeps the repo-relative spelling that keeps absolute home paths out of
the committed provenance. ``--check`` rebuilds into a temporary directory
where that relative path resolves to nothing, so there -- and only there --
this script substitutes the resolved absolute path.

Because a pre-existing stream never reported a ``ports[]`` list to any ``klt
gen`` response, its ports are hand-declared. Two things that costs, both
learned building ``layout/ro_ring5/``: the *only* authoritative source for a
two-stage cell's port geometry is its own **intermediate** stage response
(the final one reports ``"ports": []``), and a port may legitimately be
declared on a layer other than li1 -- declaring a rail port on met1, where
the leaf gate's own second stage already drew it, is what lets a later stage
route that rail on ``"metal3"`` within ``gen-compose``'s single-hop via-drop
rule.

Re-placing an earlier stage with hand-declared ports (``cell.from_stage``)
--------------------------------------------------------------------------

``blocks[].from_stage`` (above) hands a later stage the earlier stage's own
``gen-compose`` *response*, whose ``ports[]`` are exactly that stage's own
``pins[]`` -- everything a leaf/ring cell's own promotion stages need. An
**array**-level stage needs the other half: to tap an already-composed
stage's own interior conductor at a measured coordinate that was never a
``pins[]`` entry (``ro_array_core``'s ``vdd``/``vss`` promotion stubs start
on each buffer's/XOR's own tap pad *inside* the composed block, and end on a
met1 tip that only exists once that stage has drawn it). That is
``blocks[].cell``'s hand-declared ``ports[]`` shape, pointed at a stage
rather than at a committed sibling cell::

    {"id": "core", "cell": {"from_stage": "vddstub", "ports": [...]}}

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

A multi-subckt reference (``lvs.dependencies``) needs two more knobs, both
first exercised by ``layout/ro_ring5/``:

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
``lvs.drop_kwargs``
    Pass-through keyword arguments to strip from instance-call lines that
    are not in ``lvs.params`` -- see ``build_reference``'s transformation 2.

A same-subckt, differently-parametrized reference (``lvs.dependency_variants``,
#22/#27)
------------------------------------------------------------------------------

``lvs.dependencies`` (above) rewrites each dependency subckt **once**, with
one shared ``lvs.params`` dict -- exactly right when the top subckt
instantiates each dependency a single time (``ro_ring5`` calling
``ro_nand2``/``ro_stage`` once each). It cannot express ``ro_array_core``:
the design netlist defines a **single** ``.subckt ro_ring5 ... wstv=0.42
lstv=2 cld=0.5f`` and calls it four times (``xr1``-``xr4``) with four
different ``wstv=`` overrides, and ``layout/`` holds four physically
distinct ring cells for those four sizings -- one shared ``params`` dict
cannot produce four distinct comparison subckts from one definition.

``lvs.dependency_variants`` is a list of::

    {
      "subckt": "ro_ring5",
      "nested": ["ro_nand2", "ro_stage"],
      "drop_prefixes": ["Cld"],
      "drop_kwargs": ["cld"],
      "instances": [
        {"rename": "_r1", "top_instance_pattern": "^xr1\\b",
         "params": {"wstv": 0.42, "lstv": 2}},
        {"rename": "_r2", "top_instance_pattern": "^xr2\\b",
         "params": {"wstv": 0.44, "lstv": 2}},
        ...
      ]
    }

For each ``instances[]`` entry, ``build_variant_reference`` rewrites
``subckt`` **and every name in ``nested``** (a dependency's own dependencies,
since ``ro_ring5``'s body itself calls ``ro_nand2``/``ro_stage`` -- both need
the *same* per-ring rename so the renamed copies keep calling each other,
not the shared unrenamed originals) using that instance's own ``params``/
``drop_prefixes``/``drop_kwargs`` (falling back to the variant's own, then to
``lvs.drop_prefixes``/``lvs.drop_kwargs``), then suffixes every whole-word
occurrence of ``subckt`` or a ``nested`` name in the rewritten lines with
that instance's own ``rename`` -- so the four sizings coexist as four
distinct subckt definitions in one reference file (``ro_ring5_r1``,
``ro_nand2_r1``, ``ro_stage_r1``, ``ro_ring5_r2``, ...). The rename is
**only** a reference-file bookkeeping device (``lvs.flatten_reference: true``
needs four distinct definitions to inline) -- nothing in ``design/`` or the
composed layout is renamed.

``repoint_variant_instances`` then rewrites the **top** subckt's own
instance-call lines: for each ``dependency_variants[]`` entry's each
``instances[]`` entry, any line matching that instance's own
``top_instance_pattern`` regex has its bare ``subckt`` name suffixed with
``rename`` and every one of that instance's ``params`` keys stripped as a
``key=<value>`` keyword argument (whatever the value -- the top subckt's own
instance-call lines pass **literal** overrides, e.g. ``xr1 ... ro_ring5
wstv=0.42 lstv=2 cld=0.5f``, not the ``name=name`` pass-through form
``build_reference``'s ``drop_kwargs`` handles, so this is a distinct
transformation from that one) since the renamed callee's own header no
longer declares any of those parameters (transformation 1 already
substituted them into literals).
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
from _klt_common import BuildError, run_klt, write_json  # noqa: E402

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
    params: dict[str, float] | None,
    drop_prefixes: tuple[str, ...],
    drop_kwargs: tuple[str, ...] = (),
) -> list[str]:
    """Rewrite an xschem-exported subckt into a klt-lvs-ready reference.

    Four transformations, each deliberately minimal and each visible in the
    written-out result:

    1. ``params`` values are substituted for the subckt's own parameter names
       wherever they appear as an ``=<name>`` value token (this design's
       starve devices are sized ``L=lstv W=wstv``, so this covers ``L=``/
       ``W=`` in particular, but is not limited to them), and the parameter
       defaults are dropped from the ``.subckt`` line. A bare occurrence of
       the parameter name *inside* a quoted expression (e.g. the ``wstv`` in
       ``ad='int((1 + 1)/2) * wstv / 1 * 0.29'``, not immediately preceded by
       ``=``) is deliberately left unevaluated, unchanged from this script's
       original single-subckt behaviour -- see "The LVS match is
       width-sensitive" in ``layout/README.md`` for why that is fine (``klt
       lvs`` does not compare ``ad``/``as``/``pd``/``ps`` for these devices).
    2. A pass-through keyword argument on an instance-call line (``name=name``
       -- e.g. ``xg ro en n1 vddr vss ro_nand2 wstv=wstv lstv=lstv cld=cld``,
       ``ro_ring5``'s own forwarding of its parameters to each sub-gate
       instance) is dropped entirely rather than substituted, once a
       multi-subckt reference (``lvs.dependencies``, below) needs to
       instantiate one already-parameterized subckt from another: the callee
       subckt's own header no longer declares that parameter (transformation
       1 already stripped it, replacing every internal use with a literal),
       so passing it by keyword would name an undeclared parameter.
       ``drop_kwargs`` extends this to a pass-through parameter that is *not*
       in ``params`` because nothing surviving the rewrite reads it -- e.g.
       ``cld``, whose only use is the ``Cld`` load capacitor transformation 3
       removes. Left in place, ``klt lvs``'s SPICE reader warns
       ``Not a known parameter for circuit 'RO_STAGE': 'CLD'`` once per
       instance line and silently ignores it, so dropping it is cosmetic
       for the verdict but keeps the generated reference free of warnings a
       reviewer would otherwise have to triage.
    3. Element cards whose name starts with one of ``drop_prefixes`` are
       removed -- for this design that is ``ro_stage``/``ro_nand2``'s ``Cld``
       lumped load capacitor, a *simulation* load model with no physical
       counterpart in the layout, not a device the layout omits.
    4. Unitless ``L=``/``W=`` values gain an explicit ``u`` suffix -- see this
       module's docstring for why (klayout-tools#1492).
    """
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.lower().startswith(".subckt"):
            # Drop `name=value` parameter defaults from the port list.
            head = [tok for tok in stripped.split() if "=" not in tok]
            out.append(" ".join(head))
            continue
        if drop_prefixes and stripped.upper().startswith(
            tuple(p.upper() for p in drop_prefixes)
        ):
            continue
        for name in drop_kwargs:
            line = re.sub(rf"\s+{re.escape(name)}={re.escape(name)}\b", "", line)
        if params:
            for name, value in params.items():
                line = re.sub(
                    rf"\s+{re.escape(name)}={re.escape(str(name))}\b", "", line
                )
                line = re.sub(rf"=({re.escape(name)})\b", f"={value}", line)
        out.append(_GEOMETRY_RE.sub(r"\1=\2u", line))
    return out


def build_variant_reference(
    netlist: Path,
    variant: dict,
    instance: dict,
    *,
    default_drop_prefixes: tuple[str, ...],
    default_drop_kwargs: tuple[str, ...],
) -> list[str]:
    """One renamed, parametrized copy of a same-subckt LVS dependency.

    ``variant`` is one ``lvs.dependency_variants[]`` entry (``subckt`` plus
    that subckt's own ``nested`` dependencies, e.g. ``ro_ring5`` naming
    ``["ro_nand2", "ro_stage"]``); ``instance`` is one of its ``instances[]``
    entries (``rename``, ``params``, and the ``drop_prefixes``/``drop_kwargs``
    this instance's own rewrite uses, each falling back to the variant's own,
    then to the caller's default). See this module's docstring,
    "A same-subckt, differently-parametrized reference", for why a shared
    ``lvs.dependencies`` entry cannot express this.

    Every whole-word occurrence of ``subckt`` or a ``nested`` name in the
    rewritten output is suffixed with ``instance["rename"]`` -- including
    inside ``nested``'s own instance-call lines, so a renamed dependency
    keeps calling its own renamed siblings rather than the shared unrenamed
    originals.
    """
    # Nested (innermost) dependencies first, the variant's own subckt last --
    # mirrors the dependency order a hand-written reference would use, and
    # matches this design's own ring hierarchy (ro_nand2/ro_stage inside
    # ro_ring5).
    names = [*variant.get("nested", ()), variant["subckt"]]
    rename = instance["rename"]
    params = instance.get("params", variant.get("params"))
    drop_prefixes = tuple(
        instance.get(
            "drop_prefixes", variant.get("drop_prefixes", default_drop_prefixes)
        )
    )
    drop_kwargs = tuple(
        instance.get("drop_kwargs", variant.get("drop_kwargs", default_drop_kwargs))
    )
    out: list[str] = []
    for name in names:
        rewritten = build_reference(
            extract_subckt(netlist, name),
            params=params,
            drop_prefixes=drop_prefixes,
            drop_kwargs=drop_kwargs,
        )
        for line in rewritten:
            for sibling in names:
                line = re.sub(rf"\b{re.escape(sibling)}\b", sibling + rename, line)
            out.append(line)
        out.append("")
    return out


def repoint_variant_instances(
    lines: list[str], dependency_variants: list[dict]
) -> list[str]:
    """Repoint the *top* subckt's own instance-call lines at renamed variants.

    Unlike ``build_reference``'s ``drop_kwargs`` (which strips only the
    ``name=name`` pass-through form), a top subckt's own instance-call lines
    pass **literal** overrides (``xr1 ... ro_ring5 wstv=0.42 lstv=2
    cld=0.5f``), so this strips ``key=<any value>`` for each of the matched
    instance's own ``params`` keys **plus** the variant/instance's own
    ``drop_kwargs`` (e.g. ``cld``, which is never in ``params`` -- nothing
    surviving the rewrite reads it -- but is still a literal override on the
    top subckt's own instance-call line).
    """
    out: list[str] = []
    for line in lines:
        for variant in dependency_variants:
            subckt = variant["subckt"]
            for instance in variant.get("instances", ()):
                if not re.search(instance["top_instance_pattern"], line):
                    continue
                if not re.search(rf"\b{re.escape(subckt)}\b", line):
                    continue
                line = re.sub(
                    rf"\b{re.escape(subckt)}\b", subckt + instance["rename"], line
                )
                drop_names = set(instance.get("params", {})) | set(
                    instance.get("drop_kwargs", variant.get("drop_kwargs", ()))
                )
                for name in drop_names:
                    line = re.sub(rf"\s+{re.escape(name)}=\S+", "", line)
        out.append(line)
    return out


def build_lvs_reference(
    reference_source: Path, lvs_spec: dict
) -> tuple[list[str], list[str]]:
    """Assemble a cell's whole LVS reference netlist from its ``lvs`` block.

    Returns ``(lines, variant_names)`` -- the reference body (dependencies,
    then renamed dependency variants, then the top subckt) and the renamed
    variant subckt names, for the generated file's own provenance header.

    **Every** emitted subckt body is put through
    :func:`repoint_variant_instances`, not just the top one. A plain
    ``lvs.dependencies`` entry can itself instantiate a variant subckt --
    ``ro_array_core``'s own ``xr1``..``xr4`` call ``ro_ring5`` at four
    different ``wstv`` widths, and only the renamed ``ro_ring5_r1``..``_r4``
    copies are ever emitted -- so skipping it there leaves the generated
    reference calling a bare, undefined name.

    That failure is silent, which is why it is called out here: ``klt lvs``
    does **not** error on an unresolvable instance call, it drops the
    instance and compares what is left. Before this, ``layout/sampler_core``'s
    own generated reference was short by exactly its four dropped
    ``ro_ring5`` instances -- 176 devices where the schematic has 264 -- and
    nothing in the run said so. The only visible symptom was a reference
    device count a reader had to already know was wrong.
    """
    params = lvs_spec.get("params")
    drop_prefixes = tuple(lvs_spec.get("drop_prefixes", ()))
    drop_kwargs = tuple(lvs_spec.get("drop_kwargs", ()))
    dependency_subckts = lvs_spec.get("dependencies", ())
    dependency_variants = lvs_spec.get("dependency_variants", ())

    def rewritten(subckt: str) -> list[str]:
        lines = build_reference(
            extract_subckt(reference_source, subckt),
            params=params,
            drop_prefixes=drop_prefixes,
            drop_kwargs=drop_kwargs,
        )
        if dependency_variants:
            lines = repoint_variant_instances(lines, dependency_variants)
        return lines

    out: list[str] = []
    for dependency in dependency_subckts:
        out.extend(rewritten(dependency))
        out.append("")
    variant_names: list[str] = []
    for variant in dependency_variants:
        for instance in variant.get("instances", ()):
            out.extend(
                build_variant_reference(
                    reference_source,
                    variant,
                    instance,
                    default_drop_prefixes=drop_prefixes,
                    default_drop_kwargs=drop_kwargs,
                )
            )
            variant_names.append(variant["subckt"] + instance["rename"])
    out.extend(rewritten(lvs_spec["subckt"]))
    return out, variant_names


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
        only an existing stream to place. See
        ``layout/ro_ring5-connectivity-poc/README.md`` for why this needs
        hand-declared ``ports[]`` (a pre-existing cell never reported a
        ``ports[]`` list to any ``klt gen`` response the way a fresh
        primitive does). Its ``gds_path`` is written relative to the
        **cell.json** (e.g. ``"../ro_nand2/ro_nand2.gds"``), which keeps the
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
    ``generator``/``params``/``cell_name`` shape ``compose_cell`` always
    supported) or a reference to an *earlier* stage's own composed output
    (``block["from_stage"]``, naming that earlier stage's ``name``) -- which
    ``klt gen-compose`` accepts unmodified as a further ``generator_report``,
    since its own response already carries ``generator: "gen-compose"`` plus
    a ``ports[]`` promoted from that stage's own ``pins[]`` (see this
    module's docstring and ``layout/README.md``'s "Two-pass composition"
    section for why a cell ever needs more than one stage: routing two nets
    that would otherwise cross on the same metal layer, resolved by moving
    one of them to a second routing-metal level in a second pass over the
    first pass's own composed output).

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
            ref_name = block["from_stage"]
            blocks_request.append(
                {
                    "id": block["id"],
                    "generator_report": stage_responses[ref_name],
                    **(
                        {"orientation": block["orientation"]}
                        if block.get("orientation", "none") != "none"
                        else {}
                    ),
                }
            )
            continue
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
    extract = run_klt(["extract", f"{cell}.gds", "--deck", deck], env=env, cwd=out_dir)
    write_json(out_dir / "extract.json", extract)

    # 5. LVS against the design's own schematic-exported subckt.
    lvs_spec = spec["lvs"]
    reference_source = REPO_ROOT / lvs_spec["reference"]
    dependency_subckts = lvs_spec.get("dependencies", ())
    reference_lines, variant_names = build_lvs_reference(reference_source, lvs_spec)
    reference_path = out_dir / f"{cell}.ref.spice"
    dependency_note = (
        f" plus dependency subckt(s) {', '.join(dependency_subckts)}"
        if dependency_subckts
        else ""
    )
    if variant_names:
        dependency_note += f" plus dependency variant(s) {', '.join(variant_names)}"
    reference_path.write_text(
        "\n".join(
            [
                f"* Reference netlist for {cell} LVS -- GENERATED by "
                "layout/bin/compose-cell.py",
                f"* Source: {lvs_spec['reference']} .subckt "
                f"{lvs_spec['subckt']}{dependency_note}",
                "* Only unit spellings (and any substituted subckt parameter)",
                "* differ from the source -- see compose-cell.py's docstring.",
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
    lvs_request = {
        "layout": {"netlist": str(Path(extract["netlist_path"]).name)},
        "reference": {
            "netlist": reference_path.name,
            "form": "subckt-call",
            "deck": deck,
            # A multi-subckt reference (lvs.dependencies) leaves klt lvs more
            # than one candidate top circuit -- for ro_ring5, RO_NAND2 and
            # RO_STAGE are top circuits of the *file* even though the design
            # instantiates them from RO_RING5, because the reader sees three
            # definitions and no single root. `reference.top` names the one
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
