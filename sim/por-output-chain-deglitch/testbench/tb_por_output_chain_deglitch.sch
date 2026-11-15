v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por por_output_chain cell-level deglitch testbench (issue #349).
*
* DUT is the unchanged design/por_output_chain.sym -- no design edit (the issue's
* out-of-scope list forbids one). The cell is driven from IDEAL comparator and
* bias inputs per the issue's own acceptance criteria:
*
*   - I1 injects a constant 1 uA into IBIAS (the shared bias-mirror node;
*     bias_core delivers ~0.78-1.2 uA there per sim/bias-core-startup and the
*     glitch-top delivered-bias measurement, and sim/iq-top's ideal-bias variant
*     uses exactly 1 uA). The value is the deck param 'ibias'.
*
*   - V2 drives POR_RAW with ONE PWL: a sub-deglitch pulse first (tg0..tg1),
*     a settle gap, then the real trip at ttrip that stays high through tstop.
*     The ordering is deliberate: POR_RAW's real trip is the LAST edge, so
*     RESETn has exactly one rising VDD/2-class crossing in the whole window --
*     the rejected glitch contributes none by construction -- and a single
*     integ()-based threshold-crossing extraction resolves both the release
*     time and the short-pulse rejection (see experiment.json).
*
* Times come from deck params (tg0/tg1/tpre/ttrip/tstop) that the corner runner
* emits as .param lines into every generated deck; the measurement expressions
* use matching numeric literals (a .param is not readable as a vector in the
* .control section) and state the stimulus times in their notes.
*
* Deliberately NOT in this schematic (the corner runner injects them, so one
* schematic serves the whole PVT matrix):
*   - the .lib model corner include, .temp
*   - the numeric supply value: V1 is 'vsup', a .param the runner sets (and the
*     source name klt's supply_v corner axis alters on the batch backend)
*   - the .control analysis/measurement block
}
G {}
K {}
V {}
S {}
E {}
T {por_output_chain deglitch testbench -- cell level, ideal bias + POR_RAW PWL
(sub-deglitch pulse at tg0..tg1, settle, real trip at ttrip).
Connectivity is by net label; PTAT/CTAT-style outputs do not exist here.
Not a spec claim: no deglitch/pulse-width target exists (design/por_output_chain.md).} 100 -480 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {devices/vsource.sym} 200 0 0 0 {name=V2 value="PWL(0 0 'tg0' 'vsup' 'tg1' 0 'tpre' 0 'ttrip' 'vsup')" savecurrent=false}
C {devices/lab_pin.sym} 200 -30 0 0 {name=v2p lab=POR_RAW}
C {devices/lab_pin.sym} 200 30 0 0 {name=v2m lab=0}
C {devices/isource.sym} 400 -200 0 0 {name=I1 value='ibias'}
C {devices/lab_pin.sym} 400 -230 0 0 {name=i1p lab=VDD}
C {devices/lab_pin.sym} 400 -170 0 0 {name=i1m lab=IBIAS}
C {design/por_output_chain.sym} 700 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 600 -230 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 600 -210 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 600 -190 0 0 {name=dutibias lab=IBIAS}
C {devices/lab_pin.sym} 600 -170 0 0 {name=dutporraw lab=POR_RAW}
C {devices/lab_pin.sym} 800 -200 0 0 {name=dutresetn lab=RESETn}
