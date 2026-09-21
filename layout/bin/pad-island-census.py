#!/usr/bin/env python3
"""Pad-point electrical-island census for a composed full cell.

Issue #69: a composed cell's `connectivity[].pins[]` claim a set of
sub-block pads as members of one cross-block net each, but nothing in the
`klt gen` -> `klt gen-compose` -> `klt drc` -> `klt extract` chain proves
the *pad itself* is electrically the same island as the rest of the net --
`gen-compose`'s `routed: true` verifies landings against the caller-declared
port coordinates only, with no connectivity check that a leg's landing pin
ever touches the placed block's internal net (the upstream coordinate-trust
gap, 2AMLogic/klayout-tools#2210). #69's own investigation used exactly this
census to find the failure mode: every supply rail resolved to one
continuous island *in isolation* while every block's real pad sat in a
separate block-local island, because the assembly's hand-declared
`ports[]` had been pre-translated into the assembly frame and
`placement.origins_um` translated them a second time.

This script is that census, formalized as re-runnable evidence: it builds
the **same `klayout.db.LayoutToNetlist` connectivity graph `klt erc` builds**
over the ERC supply spec's declared stackup (conductors, label texts as net
names, vias -- the recipe mirrored from klayout-tools' own
`erc.py::_extract_connectivity`), then probes a small window centered on
**every pad the cell.json declares as a pin of a connectivity net**
(`connectivity[].pins[]` plus the top-level `pins[]`). Each probe's
position is anchored the way #69's own investigation anchored it — the
**sibling block's `compose.response.json` port coordinates** (the placed
geometry's authoritative report) translated by
`placement.origins_um[block]` exactly once — NOT the assembly's own
hand-declared `ports[]` entry, because a descriptor whose entries had
been pre-translated (exactly the #69 bug) is *self-consistent with its
own distortion*: probing `declared + origin` would land on wherever the
router stamped its landing pads and re-report the rails as one island
even while every real pad sat disconnected. For blocks with no sibling
response to consult (the declare-only `promo_stub` external-pin stubs),
the assembly's own declaration is the only source and is used directly,
recorded as such. As a second, independent regression guard the census
also **frame-checks the assembly's own declared port** against the
sibling source of truth -- a mismatch is the #69 bug arriving again and
fails the census even if the islands happen to still connect.

For every net it then asserts the invariant #69's fix restored:

    every probed pad of net N resolves to the SAME extracted-net cluster

i.e. the rail, every block's real supply pad, and the external stub pin
are one electrical island, not N+1 separate ones. When a net's pads land
in different clusters the census reports each pad's island (cluster id +
label-set name) and exits non-zero.

Provenance: the report is written next to the cell.json as
`<cell>/pad-island-census.json` and pins the exact GDS it verified with a
`sha256:` content hash, so it can be cited like any other committed
envelope. Because the probe needs `klayout.db` directly (no `klt` verb
exposes island membership — the gap filed generically as
2AMLogic/klayout-tools#2218), this script always runs on the same
interpreter `klt` itself runs on, so the census sees the klayout build
`klt erc` sees: the `klt` entrypoint's own shebang names that
interpreter, so the script re-executes itself under it (no ambient
`klayout.db` of a possibly different build is trusted).

Usage
-----

    python3 layout/bin/pad-island-census.py layout/bias_core/cell.json
    python3 layout/bin/pad-island-census.py layout/bias_core/cell.json \
        --window-um 0.3

Exits 0 when every declared net's probed pads share one island (and every
probe hit exactly one net); exits 1 otherwise or on any usage/read error,
after writing the evidence file either way.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

#: Probe window side, um. Small on purpose: sub-block pad columns sit on a
#: ~1um pitch (e.g. bias_core_settle_flag's `nkg` at y=107.085 vs `nokx`
#: at 108.085), so #69's original 2um window would straddle two pads'
#: margin rings there and name two nets per probe. A 0.3um window stays
#: strictly inside the drawn landing pad (0.42um square at the smallest)
#: and at least one full pad-pitch away from any foreign pad's geometry.
DEFAULT_WINDOW_UM = 0.3

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _hop_to_klt_interpreter() -> None:
    """Re-exec under the interpreter `klt` runs on.

    The census must run on the *same* klayout build `klt` (and therefore
    `klt erc`) vendor-pins -- an ambient `klayout.db` of a different build
    can differ in behavior (observed live: klayout 0.30.12 rejects an
    overload a different build accepted), so the hop is unconditional even
    when some klayout imports fine here. `klt` is a console-script whose
    shebang names the python that has klayout_tools (and its vendored
    klayout) importable, so reading that shebang finds the interpreter
    without guessing install strategies (uv tool, venv, ...). Idempotent:
    an env var set before re-exec prevents any loop.
    """
    import os
    import shutil

    if os.environ.get("_LOOM_PAD_CENSUS_HOPPED"):
        return
    klt = shutil.which("klt")
    if not klt:
        _fail("no `klt` on PATH to name the klayout-pinned interpreter")
        raise SystemExit(1)
    try:
        first = Path(klt).read_text().splitlines()[0]
    except OSError as exc:
        _fail(f"could not read `klt` entrypoint {klt}: {exc}")
        raise SystemExit(1)
    if not first.startswith("#!"):
        _fail(f"`klt` entrypoint {klt} has no shebang to name its interpreter")
        raise SystemExit(1)
    interpreter = first[2:].strip()
    env = {**os.environ, "_LOOM_PAD_CENSUS_HOPPED": "1"}
    os.execve(interpreter, [interpreter, str(Path(__file__).absolute()), *sys.argv[1:]], env)


def _ensure_klayout():
    _hop_to_klt_interpreter()
    # execve replaces the process; reaching here means the hop did not run.
    import klayout.db as kdb

    return kdb


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _spec_layer(value) -> tuple[int, int] | None:
    """`"67/20"` -> (67, 20); None stays None (validate like erc's parser)."""
    if value is None:
        return None
    try:
        ld, dt = (int(part) for part in str(value).split("/", 1))
        return (ld, dt)
    except (TypeError, ValueError):
        _fail(f"spec layer {value!r} is not `<layer>/<datatype>`")
        raise SystemExit(1)


def _region(kdb, layout, cell, layer):
    """Flattened Region idiom shared with klayout-tools' `_layout.region`."""
    index = layout.find_layer(*layer) if layer else None
    if index is None:
        return kdb.Region()
    return kdb.Region(cell.begin_shapes_rec(index))


def _texts(kdb, layout, cell, layer):
    index = layout.find_layer(*layer) if layer else None
    if index is None:
        return kdb.Texts()
    return kdb.Texts(cell.begin_shapes_rec(index))


def _probe_points(spec: dict, spec_dir: Path) -> list[dict]:
    """Every (net, block, port) pin a connectivity net declares, resolved
    to its in-assembly probe position.

    The authoritative anchor for a device block's pad is **that block's own
    `compose.response.json`** — the report of the geometry actually placed —
    translated by `placement.origins_um[block]` exactly once (the #69
    method). The assembly's own hand-declared `ports[]` entry is NOT used
    as the probe position (a pre-translated descriptor is self-consistent
    with its own distortion), but it IS frame-checked against the sibling
    source: `declared_matches_source` false is the #69 bug returning and
    fails the census however the islands connect. Blocks with no sibling
    response (the declare-only promo-stub external pins) fall back to the
    assembly's own declaration and are recorded as such.
    """
    origins = spec.get("placement", {}).get("origins_um", {})
    blocks = {block["id"]: block for block in spec.get("blocks", [])}

    def sibling_response_ports(block_id):
        cache = getattr(sibling_response_ports, "_cache", {})
        if block_id in cache:
            return cache[block_id]
        cell = blocks[block_id].get("cell", {}) if block_id in blocks else {}
        gds_path = cell.get("gds_path")
        result = None
        if gds_path:
            block_dir = (spec_dir / gds_path).resolve().parent
            # Only a stream from a DIFFERENT directory is a sibling cell with
            # its own response; a same-directory stream (the declare-only
            # promo-stub blocks) has no sibling and would otherwise find the
            # assembly's own final response, whose ports[] are the promoted
            # top-level pins -- not this block's ports.
            if block_dir != spec_dir.resolve():
                response = block_dir / "compose.response.json"
                if response.exists():
                    try:
                        result = json.loads(response.read_text())["ports"]
                    except (ValueError, KeyError):
                        _fail(f"unparseable sibling response: {response}")
                        raise SystemExit(1)
        getattr(sibling_response_ports, "_cache", {})[block_id] = result
        return result

    seen: set[tuple[str, str, str]] = set()
    probes: list[dict] = []
    candidates = []
    for conn in spec.get("connectivity", []):
        for pin in conn.get("pins", []):
            candidates.append((conn["net"], pin["block"], pin["port"]))
    for pin in spec.get("pins", []):
        candidates.append((pin["net"], pin["block"], pin["port"]))
    for net, block_id, port_name in candidates:
        if (net, block_id, port_name) in seen:
            continue
        seen.add((net, block_id, port_name))
        if block_id not in blocks:
            _fail(f"pin names unknown block {block_id!r}")
            raise SystemExit(1)
        declared = None
        for port in blocks[block_id].get("cell", {}).get("ports", []):
            if port["name"] == port_name:
                declared = port
                break
        sibling_ports = sibling_response_ports(block_id)
        source = None
        if sibling_ports:
            for port in sibling_ports:
                if port["name"] == port_name:
                    source = port
                    break
            if source is None:
                _fail(
                    f"block {block_id!r}'s sibling compose.response.json "
                    f"reports no port {port_name!r} the assembly pins"
                )
                raise SystemExit(1)
        if source is None and declared is None:
            _fail(f"block {block_id!r} declares no port {port_name!r}")
            raise SystemExit(1)
        anchor = source or declared
        probe_from_declaration = source is None
        declared_matches_source = None
        if source is not None and declared is not None:
            declared_matches_source = (
                abs(anchor["x_um"] - declared["x_um"]) < 1e-9
                and abs(anchor["y_um"] - declared["y_um"]) < 1e-9
            )
        origin = origins.get(block_id, {})
        px = anchor["x_um"] + origin.get("x", 0.0)
        py = anchor["y_um"] + origin.get("y", 0.0)
        probes.append(
            {
                "net": net,
                "block": block_id,
                "port": port_name,
                "x_um": px,
                "y_um": py,
                "port_layer": (
                    f"{anchor.get('layer').get('layer')}/{anchor.get('layer').get('datatype')}"
                    if isinstance(anchor.get("layer"), dict)
                    else str(anchor.get("layer"))
                ),
                "probe_source": (
                    "assembly_declaration"
                    if probe_from_declaration
                    else "sibling_compose_response"
                ),
                "declared_matches_source": declared_matches_source,
            }
        )
    return probes


def run_census(
    kdb,
    *,
    cell_dir: Path,
    cell_name: str,
    gds_path: Path,
    spec_path: Path,
    erc_spec_path: Path,
    erc_spec: dict,
    window_um: float,
) -> tuple[dict, bool]:
    layout = kdb.Layout()
    layout.read(str(gds_path))
    top_cell = layout.cell(cell_name)
    if top_cell is None:
        _fail(f"{gds_path} has no cell named {cell_name!r}")
        raise SystemExit(1)
    if len(layout.top_cells()) != 1:
        _fail(f"{gds_path} has {len(layout.top_cells())} top cells; need exactly 1")
        raise SystemExit(1)

    l2n = kdb.LayoutToNetlist(top_cell.name, layout.dbu)
    conductor_layers: list[tuple[str, int]] = []
    regions_by_name: dict[str, object] = {}
    register_index_by_layer: dict[tuple[int, int], int] = {}
    for entry in erc_spec.get("stackup", []):
        layer = _spec_layer(entry.get("layer"))
        reg = _region(kdb, layout, top_cell, layer)
        register_index = l2n.register(reg, entry["name"])
        l2n.connect(reg)
        label_layer = _spec_layer(entry.get("label_layer"))
        if label_layer is not None:
            texts = _texts(kdb, layout, top_cell, label_layer)
            l2n.register(texts, f"{entry['name']}_label")
            l2n.connect(reg, texts)
        conductor_layers.append((entry["name"], register_index))
        regions_by_name[entry["name"]] = reg
        if layer is not None:
            register_index_by_layer[layer] = register_index
    for via in erc_spec.get("vias", []):
        via_region = _region(kdb, layout, top_cell, _spec_layer(via.get("layer")))
        l2n.register(via_region, via["name"])
        l2n.connect(via_region)
        role_a, role_b = via["between"]
        l2n.connect(regions_by_name[role_a], via_region)
        l2n.connect(via_region, regions_by_name[role_b])

    try:
        l2n.extract_netlist()
    except Exception as exc:  # klayout raises bare RuntimeError on failure
        _fail(f"connectivity extraction failed: {exc}")
        raise SystemExit(1)

    circuit = l2n.netlist().circuit_by_name(top_cell.name)
    if circuit is None:
        _fail(f"no circuit named {top_cell.name!r} in the extracted graph")
        raise SystemExit(1)

    nets = [net for net in circuit.each_net() if net.cluster_id != 0]

    # Per net AND per conductor layer: that net's polygons on that layer,
    # so a probe can be scoped to its own port's layer (a pad's island
    # membership is a property of the net at the pad's own layer -- an
    # unrelated net merely *passing overhead on a higher plane* inside the
    # probe window is not part of the pad's island, and DRC-clean plane
    # crossings right above a pad are common on a densely-routed row).
    net_regions: dict[tuple[object, int], object] = {}
    for net in nets:
        for _, register_index in conductor_layers:
            net_regions[(net, register_index)] = l2n.polygons_of_net(net, register_index)

    probes = _probe_points(json.loads(spec_path.read_text()), spec_path.parent)
    probe_reports: list[dict] = []
    half_dbu = window_um / 2.0
    for probe in probes:
        port_layer = tuple(_spec_layer(probe["port_layer"]))
        box = kdb.Region(
            kdb.Box(
                int(round((probe["x_um"] - half_dbu) / layout.dbu)),
                int(round((probe["y_um"] - half_dbu) / layout.dbu)),
                int(round((probe["x_um"] + half_dbu) / layout.dbu)),
                int(round((probe["y_um"] + half_dbu) / layout.dbu)),
            )
        )
        # All conductor layers when the pad's own layer is not one the ERC
        # spec registers; otherwise exactly the pad's own layer.
        probe_layers = (
            [register_index_by_layer[port_layer]]
            if port_layer in register_index_by_layer
            else [register_index for _, register_index in conductor_layers]
        )
        hit_ids = []
        hit_names = []
        for net in nets:
            matched_layer = any(
                not net_regions[(net, register_index)].interacting(box).is_empty()
                for register_index in probe_layers
            )
            if matched_layer:
                hit_ids.append(int(net.cluster_id))
                hit_names.append(str(net.expanded_name()))
        probe_reports.append(
            {
                **probe,
                "island_cluster_id": hit_ids[0] if len(hit_ids) == 1 else None,
                "island_name": hit_names[0] if len(hit_names) == 1 else None,
                "all_matched_cluster_ids": sorted(set(hit_ids)),
                "all_matched_names": hit_names or [],
            }
        )

    groups: list[dict] = []
    for net in sorted({probe["net"] for probe in probes}):
        members = [p for p in probe_reports if p["net"] == net]
        cluster_ids = sorted({p["island_cluster_id"] for p in members if p["island_cluster_id"] is not None})
        names = sorted({p["island_name"] for p in members if p["island_name"] is not None})
        frame_ok = all(p.get("declared_matches_source") is not False for p in members)
        one_island = (
            len(members) > 0
            and all(p["island_cluster_id"] is not None for p in members)
            and len(cluster_ids) == 1
        )
        groups.append(
            {
                "net": net,
                "probe_count": len(members),
                "island_cluster_ids": cluster_ids,
                "island_names": names,
                "declared_frame_matches_source": frame_ok,
                "same_island": one_island and frame_ok,
            }
        )

    klayout_version = getattr(kdb, "__version__", None)
    report = {
        "schema_version": 1,
        "cell": cell_name,
        "method": (
            "LayoutToNetlist pad-point island census mirroring klt erc's own "
            "connectivity extraction (klayout_tools erc.py::_extract_connectivity)"
        ),
        "file": str(gds_path.relative_to(REPO_ROOT)),
        "provenance": {
            "input": {"content_hash": _sha256(gds_path), "role": "layout"},
            "spec": {"content_hash": _sha256(spec_path), "role": "cell-descriptor"},
            "erc_spec": {"content_hash": _sha256(erc_spec_path), "role": "stackup"},
            "klayout_version": klayout_version,
        },
        "probe_window_um": window_um,
        "probes": probe_reports,
        "groups": groups,
        "summary": {
            "probe_count": len(probe_reports),
            "net_count": len(groups),
            "nets_one_island": sum(1 for g in groups if g["same_island"]),
            "status": "ok" if all(g["same_island"] for g in groups) else "split_islands",
        },
    }
    return report, all(g["same_island"] for g in groups)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("spec", type=Path, help="path to a layout/<cell>/cell.json")
    parser.add_argument(
        "--spec-sidecar",
        type=Path,
        default=None,
        help=(
            "the klt erc supply spec to borrow the stackup/vias graph from "
            "(default: the sibling erc-supply-spec.json)"
        ),
    )
    parser.add_argument(
        "--window-um",
        type=float,
        default=DEFAULT_WINDOW_UM,
        help="probe window side in um (default 0.3, smaller than the pad pitch)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="evidence output path (default <cell_dir>/pad-island-census.json)",
    )
    args = parser.parse_args(argv)

    spec_path = args.spec.resolve()
    if not spec_path.exists():
        _fail(f"cell.json not found: {spec_path}")
        return 1
    spec = json.loads(spec_path.read_text())
    cell_dir = spec_path.parent
    cell_name = spec["cell"]
    gds_path = cell_dir / f"{cell_name}.gds"
    if not gds_path.exists():
        _fail(f"composed GDS not found: {gds_path}")
        return 1
    erc_spec_path = args.spec_sidecar or (cell_dir / "erc-supply-spec.json")
    if not erc_spec_path.exists():
        _fail(f"ERC supply spec not found: {erc_spec_path}")
        return 1
    out_path = args.out or (cell_dir / "pad-island-census.json")

    kdb = _ensure_klayout()
    report, ok = run_census(
        kdb,
        cell_dir=cell_dir,
        cell_name=cell_name,
        gds_path=gds_path,
        spec_path=spec_path,
        erc_spec_path=Path(erc_spec_path).resolve(),
        erc_spec=json.loads(Path(erc_spec_path).resolve().read_text()),
        window_um=args.window_um,
    )
    out_path.write_text(json.dumps(report, indent=2) + "\n")

    for group in report["groups"]:
        state = "OK  " if group["same_island"] else "FAIL"
        ids = group["island_cluster_ids"] or []
        names = group["island_names"] or []
        print(f"{state} {group['net']}: {group['probe_count']} pads -> islands {ids} {names}")
    print(f"census evidence written to {out_path}")
    if not ok:
        print("status: split_islands (see report)", file=sys.stderr)
        return 1
    print("status: ok (every probed net is one electrical island)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
