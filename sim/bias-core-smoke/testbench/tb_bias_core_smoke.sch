v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por bias_core smoke testbench (issue #17).
*
* Instantiates design/bias_core.sch (the always-on shared bias/reference
* core) on a supply and reads its DC operating point across the sim/bin/
* corner-run.py PVT matrix. This is a *harness bring-up* check, not a spec
* claim: sim/ has never had a testbench before this issue, so this is the
* first proof the ported corner runner actually drives THIS repo's own
* design/ sources end to end (xschem -> ngspice -> parsed measurement ->
* committed record), not just sky130-bandgap's.
*
* Load: none. IBIAS/VREF/BIAS_OK are read open-circuit; bias_core has no
* enable pin and is always on (design/bias_core.md).
*
* Startup: unlike sky130-bandgap's bandgap_core (which needed an explicit
* .nodeset because its startup circuit is a separate not-yet-landed cell),
* bias_core owns its own on-die startup kick (design/bias_core.md) and
* solved cleanly via ngspice's automatic gmin-stepping fallback at every one
* of tt/ss/ff/sf/fs x -40/125 degC checked by hand before this testbench was
* written (no manual .nodeset seed used or needed) -- so none is added here.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {bias_core smoke testbench -- nominal operating point only
DUT is design/bias_core.sym. Connectivity is by net label (lab_pin on every
pin), no wires. Supply value comes from .param vsup; corner (.lib) and .temp
are injected by sim/bin/corner-run.py.} 100 -450 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bias_core.sym} 600 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 500 -220 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 500 -180 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 700 -220 0 0 {name=dutibias lab=IBIAS}
C {devices/lab_pin.sym} 700 -200 0 0 {name=dutvref lab=VREF}
C {devices/lab_pin.sym} 700 -180 0 0 {name=dutbiasok lab=BIAS_OK}
