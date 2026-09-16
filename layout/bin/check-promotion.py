#!/usr/bin/env python3
"""Verify a sub-block's newly-promoted pins compose cleanly from outside it.

Issue #56: a `layout/bias_core_*/cell.json`'s own `pins[]` promotes a net to
a top-level, externally-reachable pad -- but promoting a pin is not enough
on its own, because `klt gen-compose`'s same-block self-collision check
(issue #1527) can still reject a route that approaches a promoted pad from
outside if the pad's own surrounding geometry is not genuinely clear. The
issue's own Ask #2 requires each newly-promoted pin be "confirmed by
successfully composing a downstream cell.json against it (a minimal repro
block declaring just that pin and routing to a dummy destination is
enough)" -- this script is that minimal repro, run for real (not eyeballed)
and its result committed as evidence, same "verification is the product"
discipline `compose-cell.py` itself follows.

For a target cell's own already-composed GDS (`<cell>.gds`, referenced via
`blocks[].cell` -- klayout-tools' own "existing cell in a stream" mechanism,
`docs/cli/gen-compose.md`), this script:

  1. Hand-declares every port `compose.response.json` reports (so the
     downstream request sees the target exactly as any real downstream
     composition would -- not a trimmed subset).
  2. Places one small dummy pad (`promo_stub.gds`, drawn fresh next to this
     script -- a bare declare-only 2-port stub, no PDK awareness needed
     since it never leaves this throwaway verification) some distance away
     from the target cell's own bbox, in the direction the pin under test
     already faces (`direction_deg` -- 0/180 gets a pad further east/west,
     90/270 further north/south).
  3. Routes a 2-pin net from the pin under test to that dummy pad, one net
     per pin (by default every pin whose own `block` starts with `stub_` --
     this cell.json's own convention for a #56 promotion stub, see
     `layout/README.md`; `--net` overrides the selection).
  4. Runs `klt gen-compose` for real and writes the request/response next to
     this script's target `--out-prefix`, so the check is re-runnable
     evidence, not a one-off log dump.

Usage
-----

    python3 layout/bin/check-promotion.py layout/bias_core_mirror_amp/cell.json

Exits non-zero (after writing the evidence either way) if any tested net
comes back in the response's own `unrouted_nets[]`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _klt_common import BuildError, run_klt, write_json  # noqa: E402

#: How far (um) to place the dummy target from the promoted pin, along the
#: direction the pin's own port already faces. Generous on purpose: this
#: throwaway harness places one dummy per tested pin independently, with no
#: awareness of where any *other* pin's own dummy landed, so a short reach
#: risks two unrelated dummies (or a dummy and another pin's own route)
#: colliding with each other -- a harness artifact, not a signal about the
#: cell under test. A reach comfortably larger than this repo's largest
#: sub-block bounding box (bias_core_passives is ~5533um wide, see its own
#: README) would be needed to rule that out in general; in practice the
#: sub-blocks checked so far are within a couple hundred um, so this value
#: is picked empirically per this script's own observed collisions, not
#: derived from a hard bound -- widen it further if a future cell's own
#: check reports an unrouted net whose only listed reason names another
#: `dummy_*` block.
_REACH_UM = 40.0


def _dummy_offset(direction_deg: float) -> tuple[float, float]:
    if direction_deg == 0:
        return (_REACH_UM, 0.0)
    if direction_deg == 180:
        return (-_REACH_UM, 0.0)
    if direction_deg == 90:
        return (0.0, _REACH_UM)
    if direction_deg == 270:
        return (0.0, -_REACH_UM)
    raise BuildError(f"non-orthogonal direction_deg {direction_deg!r}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "cell_json", type=Path, help="path to the sub-block's cell.json"
    )
    parser.add_argument(
        "--net",
        action="append",
        dest="nets",
        default=None,
        help="net name to test (repeatable); default: every pins[] entry "
        "whose block starts with 'stub_'",
    )
    parser.add_argument(
        "--out-prefix",
        default="downstream-check",
        help="basename (in the cell's own directory) for the written "
        "<prefix>.request.json / <prefix>.response.json",
    )
    args = parser.parse_args(argv)

    cell_dir = args.cell_json.resolve().parent
    spec = json.loads(args.cell_json.read_text())
    cell_name = spec["cell"]
    response = json.loads((cell_dir / "compose.response.json").read_text())

    promo_ports = [
        p
        for p in response["ports"]
        if args.nets is not None
        and p["name"] in args.nets
        or args.nets is None
        and p.get("block", "").startswith("stub_")
    ]
    if not promo_ports:
        raise BuildError(
            f"{args.cell_json}: no promoted pins matched (nets={args.nets})"
        )

    stub_gds = cell_dir / "promo_stub.gds"
    if not stub_gds.exists():
        raise BuildError(f"{stub_gds} does not exist -- draw it first (see README)")

    sub_ports = [
        {
            "name": p["name"],
            "x_um": p["x_um"],
            "y_um": p["y_um"],
            "layer": {"layer": p["layer"]["layer"], "datatype": p["layer"]["datatype"]},
            "width_um": p["width_um"],
            "direction_deg": p["direction_deg"],
        }
        for p in response["ports"]
    ]

    blocks = [
        {
            "id": "sub",
            "cell": {
                "gds_path": f"{cell_name}.gds",
                "cell_name": cell_name,
                "ports": sub_ports,
                "bbox_um": response["bbox_um"],
            },
        }
    ]
    order = ["sub"]
    origins = {"sub": {"x": 0.0, "y": 0.0}}
    connectivity = []
    for p in promo_ports:
        net = p["name"]
        dummy_id = f"dummy_{net}"
        dx, dy = _dummy_offset(p["direction_deg"])
        origin_x = p["x_um"] + dx
        origin_y = p["y_um"] + dy - 0.085
        blocks.append(
            {
                "id": dummy_id,
                "cell": {
                    "gds_path": "promo_stub.gds",
                    "cell_name": "promo_stub",
                    "ports": [
                        {
                            "name": "PAD",
                            "x_um": 0.0,
                            "y_um": 0.085,
                            "layer": {"layer": 67, "datatype": 20},
                            "width_um": 0.17,
                            "direction_deg": (p["direction_deg"] + 180) % 360,
                        }
                    ],
                },
            }
        )
        order.append(dummy_id)
        origins[dummy_id] = {"x": origin_x, "y": origin_y}
        connectivity.append(
            {
                "net": net,
                "pins": [
                    {"block": "sub", "port": net},
                    {"block": dummy_id, "port": "PAD"},
                ],
            }
        )

    request = {
        "pdk": {"variant": "sky130A"},
        "blocks": blocks,
        "placement": {"strategy": "explicit", "order": order, "origins_um": origins},
        "connectivity": connectivity,
        "routing": {
            "layer_role": "metal",
            "width_um": 0.17,
            "cross_block_layer_role": "metal2",
        },
        "options": {
            "cell_name": f"{cell_name}_downstream_check",
            "output": f"{args.out_prefix}.gds",
        },
    }
    write_json(cell_dir / f"{args.out_prefix}.request.json", request)
    env = dict(os.environ)
    result = run_klt(
        ["gen-compose", f"{args.out_prefix}.request.json"], env=env, cwd=cell_dir
    )
    write_json(cell_dir / f"{args.out_prefix}.response.json", result)

    unrouted = result.get("unrouted_nets", [])
    tested = sorted(p["name"] for p in promo_ports)
    print(f"{cell_name}: tested {tested}")
    if unrouted:
        print(f"{cell_name}: UNROUTED (self-block collision or similar): {unrouted}")
        return 1

    # Belt-and-braces: DRC the downstream-composed stream too, not just the
    # routability verdict above -- a route gen-compose accepts is only its
    # own "no problem found" heuristic, never a DRC-clean guarantee
    # (docs/cli/gen-compose.md's own "Geometry is advisory" note).
    drc = run_klt(
        ["drc", f"{args.out_prefix}.gds", "--deck", "sky130"], env=env, cwd=cell_dir
    )
    write_json(cell_dir / f"{args.out_prefix}.drc.json", drc)
    if drc.get("status") != "clean":
        print(
            f"{cell_name}: downstream-check DRC not clean: {drc.get('violation_count')} violation(s)"
        )
        return 1

    print(
        f"{cell_name}: all {len(tested)} promoted pins compose cleanly against a "
        f"downstream target, downstream DRC clean"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
