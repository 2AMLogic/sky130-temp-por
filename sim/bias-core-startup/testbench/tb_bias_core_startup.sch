v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por bias_core startup testbench (issue #19).
*
* Same DUT and same open-circuit loading as
* sim/bias-core-smoke/testbench/tb_bias_core_smoke.sch -- the ONLY difference
* is how the supply is applied. The smoke testbench holds VDD at a fixed
* value and asks ngspice to find a DC operating point cold (`.op`); this one
* ramps VDD from 0 V and integrates the circuit forward in time (`tran ...
* uic`), which is what a real power-up does.
*
* Why this testbench exists (issue #19): bias_core is an always-on
* self-biased core whose network equations admit a degenerate zero-current
* solution alongside the intended one, so a cold `.op` has to be steered onto
* a branch by ngspice's own convergence-aid continuation (gmin stepping),
* not by circuit physics. Measured across a 10 mV supply sweep at tt/27 degC,
* that continuation lands on a NON-PHYSICAL point (internal node NB at
* -7e8 V, and the supply *sourcing* milliamps into its own only energy
* source) at a few percent of supply points, scattered, with the failing set
* changing completely when only the linear solver is swapped -- see
* sim/bias-core-op-branch/ for that evidence. A ramp-from-0 V transient has
* no such freedom: it starts from the physical all-zero state and follows the
* circuit's own trajectory, so the branch it reaches is a property of the
* circuit rather than of the solver's initial guess.
*
* Load: none. IBIAS/VREF/BIAS_OK are read open-circuit, exactly as in the
* smoke testbench, so the settled values are directly comparable to
* sim/bias-core-smoke/'s own record.
*
* Supply: V1 is a PWL ramp 0 V -> 'vsup' over 'tramp', then held flat to
* 'tstop'. All three are .params the corner runner (vsup) or the manifest
* deck.params block (tramp, tstop) sets, so one schematic serves the whole
* PVT matrix.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include, .temp
*   - the numeric supply value: 'vsup' is a .param the runner sets
*   - the .control analysis/measurement block (`tran ... uic`)
}
G {}
K {}
V {}
S {}
E {}
T {bias_core startup testbench -- transient from a 0 V cold start
DUT is design/bias_core.sym, identical instantiation and open-circuit
loading to sim/bias-core-smoke/testbench/tb_bias_core_smoke.sch.
Connectivity is by net label (lab_pin on every pin), no wires.
V1 ramps 0 -> 'vsup' over 'tramp' and holds to 'tstop'; corner (.lib),
.temp and the tran analysis are injected by sim/bin/corner-run.py.} 100 -450 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value="PWL(0 0 'tramp' 'vsup' 'tstop' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bias_core.sym} 600 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 500 -220 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 500 -180 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 700 -220 0 0 {name=dutibias lab=IBIAS}
C {devices/lab_pin.sym} 700 -200 0 0 {name=dutvref lab=VREF}
C {devices/lab_pin.sym} 700 -180 0 0 {name=dutbiasok lab=BIAS_OK}
