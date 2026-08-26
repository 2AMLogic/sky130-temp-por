v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por temp_core startup testbench (issue #22, same class as #19).
*
* Same method sim/bias-core-startup/ established for bias_core (issue #19):
* a cold `.op` cannot make a branch-selection claim about a self-biased
* DeltaVBE cell -- ngspice's continuation lands on a NON-PHYSICAL point at
* isolated PVT points (supply sinking milliamps, DeltaVBE nodes at ~1e8 V
* outside the rails) and which points those are changes when only the
* linear solver changes (sim/bias-core-op-branch/). temp_core has its own
* DeltaVBE loop, its own startup kick and its own enable gating
* (design/temp_core.md), and design/temp_core.md's "verification done"
* section previously recorded only a cold-.op spot check -- exactly the
* method issue #19 retired. This testbench replaces that spot check with a
* physical `tran ... uic` supply ramp from 0 V.
*
* DUT wiring: temp_core needs an ACTIVE IBIAS drive to do anything -- IBIAS
* is a shared bias-mirror node bias_core sources current into (DR-010), not
* an independent bias this cell can generate alone. So this testbench
* instantiates bias_core alongside temp_core, sharing VDD/VSS/IBIAS exactly
* as design/temp_core.md's own DC smoke check did:
*   Xbias VDD VSS IBIAS VREF BIAS_OK bias_core
*   Xdut  VDD VSS IBIAS EN PTAT CTAT temp_core
* bias_core's own startup is already substantiated by
* sim/bias-core-startup/ across the full PVT matrix; instantiating it here
* is necessary DUT plumbing, not a re-claim about bias_core itself.
*
* EN axis, scenario A (THIS testbench): EN tied directly to VDD, i.e. the
* enable gate is asserted for the entire power-up ramp -- the same
* "always-was-enabled" condition sim/bias-core-startup/ exercises for
* bias_core (which has no EN pin at all). Scenario B -- EN released only
* AFTER the supply is up, the DR-002 startup ordering temp_core will
* actually see once temp_por_top drives EN from RESETn -- is
* sim/temp-core-startup-en-delayed/, a separate testbench/claim (same house
* convention as bias-core-startup/bias-core-op-branch being separate
* slugs for separate claims).
*
* Load: PTAT/CTAT read open-circuit (this cell has no output buffer,
* design/temp_core.md), matching the DC smoke check's own loading.
*
* Supply: V1 is a PWL ramp 0 V -> 'vsup' over 'tramp', then held flat to
* 'tstop', identical in form to sim/bias-core-startup/'s own V1.
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
T {temp_core startup testbench -- transient from a 0 V cold start, EN tied
high through the whole ramp (scenario A of issue #22; scenario B is
sim/temp-core-startup-en-delayed/). DUT is design/temp_core.sym alongside
design/bias_core.sym (temp_core's IBIAS pin needs bias_core's active
drive). Connectivity is by net label (lab_pin on every pin), no wires.
V1 ramps 0 -> 'vsup' over 'tramp' and holds to 'tstop'; corner (.lib),
.temp and the tran analysis are injected by sim/bin/corner-run.py.} 100 -600 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value="PWL(0 0 'tramp' 'vsup' 'tstop' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {design/bias_core.sym} 600 -200 0 0 {name=XBIAS}
C {devices/lab_pin.sym} 500 -220 0 0 {name=biasvdd lab=VDD}
C {devices/lab_pin.sym} 500 -180 0 0 {name=biasvss lab=0}
C {devices/lab_pin.sym} 700 -220 0 0 {name=biasibias lab=IBIAS}
C {devices/lab_pin.sym} 700 -200 0 0 {name=biasvref lab=VREF}
C {devices/lab_pin.sym} 700 -180 0 0 {name=biasbiasok lab=BIAS_OK}
C {design/temp_core.sym} 1000 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 900 -230 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 900 -210 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 900 -190 0 0 {name=dutibias lab=IBIAS}
C {devices/lab_pin.sym} 900 -170 0 0 {name=duten lab=VDD}
C {devices/lab_pin.sym} 1100 -220 0 0 {name=dutptat lab=PTAT}
C {devices/lab_pin.sym} 1100 -180 0 0 {name=dutctat lab=CTAT}
