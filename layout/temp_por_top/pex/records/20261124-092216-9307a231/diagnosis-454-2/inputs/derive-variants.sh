#!/bin/sh
# Derives the three diagnostic netlist variants in this directory from the
# pinned grid inputs. Run `sh derive-variants.sh <variant> [out]` from this
# directory. The default output is <variant>.spice.
#
# Variants (issue #454, increment of 2026-11-26; one netlist change each):
#   nocc    remove the 131 net-to-net coupling capacitors (Ccc_* cards) -- the
#           extraction model's vertical-overlap + critical-net lateral coupling
#   nor     replace every lumped series (star) resistor value with 1e-06 ohm
#           (569 cards, pattern `R..._tN <terminal-node> <hub>`) -- an effective
#           short of the parasitic series R, keeping connectivity
#   01v8swap the flat schematic DUT with the extractor's model substitution
#           applied by hand: nfet/pfet_g5v0d10v5 -> nfet/pfet_01v8 (114 cards)
#
# The committed copies (temp_por_top.pex.nocc.spice, temp_por_top.pex.nor.spice,
# schematic-dut.flat.01v8swap.spice) were produced by exactly these pipelines.
set -e
GRID=../../grid
V=${1:?variant: nocc|nor|01v8swap}
OUT=${2:-$V.spice}
case "$V" in
  nocc)
    grep -vE '^Ccc_' < "$GRID/temp_por_top.pex.spice" > "$OUT" ;;
  nor)
    sed -E 's/^(R[A-Za-z0-9_$.|]*_t[0-9]+ [^ ]+ [^ ]+) [0-9.e+-]+$/\1 1e-06/' \
      < "$GRID/temp_por_top.pex.spice" > "$OUT" ;;
  01v8swap)
    sed -e 's/sky130_fd_pr__nfet_g5v0d10v5/sky130_fd_pr__nfet_01v8/g' \
        -e 's/sky130_fd_pr__pfet_g5v0d10v5/sky130_fd_pr__pfet_01v8/g' \
      < "$GRID/artifacts/schematic-dut.flat.spice" > "$OUT" ;;
  *) echo "unknown variant: $V" >&2; exit 2 ;;
esac
echo "wrote $OUT" >&2
