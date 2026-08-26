v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por temp_core startup testbench, EN released after supply is
* up (issue #22, scenario B; scenario A is sim/temp-core-startup/).
*
* Same DUT wiring and same physical `tran ... uic` supply-ramp-from-0V
* method as sim/temp-core-startup/ (see that schematic's own header for the
* issue #19 rationale) -- the ONLY difference is EN's own waveform: instead
* of being tied to VDD (asserted through the whole ramp), EN is held LOW
* until well after VDD has completed its ramp and settled, then released.
* That is the DR-002 startup ordering temp_core will actually see once
* temp_por_top exists (issue #10): EN is intended to be driven from RESETn,
* which only deasserts once POR has already released -- i.e. supply already
* up. This schematic substantiates that temp_core's own startup kick still
* clears the degenerate zero-current branch when EN arrives LATE, not just
* when it was asserted for the whole ramp (sim/temp-core-startup/'s own
* claim).
*
* V2 is a PWL held at 0 V until 'ten_start' (> 'tramp', i.e. after V1's own
* ramp has completed and the supply has been flat for a while), then ramps
* to 'vsup' by 'ten_end' and holds to 'tstop'.
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
T {temp_core startup testbench -- transient from a 0 V cold start, EN held
LOW until after the supply has ramped and settled, then released
(scenario B of issue #22; scenario A is sim/temp-core-startup/, EN tied
high through the whole ramp). DUT is design/temp_core.sym alongside
design/bias_core.sym (temp_core's IBIAS pin needs bias_core's active
drive). Connectivity is by net label (lab_pin on every pin), no wires.
V1 ramps VDD 0 -> 'vsup' over 'tramp'; V2 ramps EN 0 -> 'vsup' from
'ten_start' to 'ten_end' ('ten_start' > 'tramp'). corner (.lib), .temp and
the tran analysis are injected by sim/bin/corner-run.py.} 100 -600 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -200 0 0 {name=V1 value="PWL(0 0 'tramp' 'vsup' 'tstop' 'vsup')" savecurrent=true}
C {devices/lab_pin.sym} 200 -230 0 0 {name=v1p lab=VDD}
C {devices/lab_pin.sym} 200 -170 0 0 {name=v1m lab=0}
C {devices/vsource.sym} 200 100 0 0 {name=V2 value="PWL(0 0 'ten_start' 0 'ten_end' 'vsup' 'tstop' 'vsup')"}
C {devices/lab_pin.sym} 200 70 0 0 {name=v2p lab=EN}
C {devices/lab_pin.sym} 200 130 0 0 {name=v2m lab=0}
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
C {devices/lab_pin.sym} 900 -170 0 0 {name=duten lab=EN}
C {devices/lab_pin.sym} 1100 -220 0 0 {name=dutptat lab=PTAT}
C {devices/lab_pin.sym} 1100 -180 0 0 {name=dutctat lab=CTAT}
