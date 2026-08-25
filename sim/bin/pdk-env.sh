# Source me: exports the sky130 PDK environment this repo's harness expects.
#
#   source sim/bin/pdk-env.sh
#   xschem --rcfile "$XSCHEM_RCFILE" sim/bias-core-smoke/testbench/tb_bias_core_smoke.sch
#   ngspice ...            # remember to copy sim/spiceinit to ./.spiceinit
#
# Resolution order (single source of truth is sim/bin/corner-run.py --print-env):
#   PDK_ROOT env -> `volare path` -> default_pdk_root from sim/pdk.json
#   PDK env      -> variant from sim/pdk.json
#
# Not needed to run the corner runner itself: corner-run.py resolves the PDK on
# its own. This is for driving xschem/ngspice by hand.
#
# Ported from sky130-bandgap/sim/bin/pdk-env.sh (issue #17), unchanged.

_pdk_env_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-${(%):-%x}}")" && pwd)"
_pdk_env_out="$(python3 "${_pdk_env_dir}/corner-run.py" --print-env)" || {
  echo "pdk-env.sh: corner-run.py --print-env failed (is the pinned PDK installed?)" >&2
  unset _pdk_env_dir _pdk_env_out
  return 1 2>/dev/null || exit 1
}
eval "${_pdk_env_out}"
echo "PDK_ROOT=${PDK_ROOT}"
echo "PDK=${PDK}"
echo "SKY130_MODEL_LIB=${SKY130_MODEL_LIB}"
echo "XSCHEM_RCFILE=${XSCHEM_RCFILE}"
unset _pdk_env_dir _pdk_env_out
