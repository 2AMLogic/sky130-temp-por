v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por assembled temp_por_top Iq testbench, iq-total state (issue #107).
*
* DUT is the unchanged assembled design/temp_por_top.sym, RESETn left to its
* own devices (natural released state, temp_core enabled by RESETn). VDD is
* brought from a physical 0 V start by BVDD (V(VDD) = min(v(VSETN),
* rate*time), a fast ramp, then held constant for the settling windows).
* Supply current is -i(BVDD), read from the saved waveform by the driver.
*
* Deliberately NOT in this schematic (klt sim injects them): the .lib corner
* include, .temp, the numeric final supply, the .control analysis block and
* the measurements.
}
G {}
K {}
V {}
S {}
E {}
T {temp_por_top Iq testbench (iq-total: natural released state). Transient from a physical 0 V start; fast constant-rate ramp to the swept supply on VSET, then a long hold; Iq is read from the settled trailing window. PTAT/CTAT left open. Connectivity is by net label.} 100 -700 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -300 0 0 {name=VSET value=3.3 savecurrent=false}
C {devices/lab_pin.sym} 200 -330 0 0 {name=vsetp lab=VSETN}
C {devices/lab_pin.sym} 200 -270 0 0 {name=vsetm lab=0}
C {devices/bsource.sym} 200 0 0 0 {name=BVDD VAR=V FUNC="min(v(VSETN), \{rate\}*time)"}
C {devices/lab_pin.sym} 200 -30 0 0 {name=bvddp lab=VDD}
C {devices/lab_pin.sym} 200 30 0 0 {name=bvddm lab=0}
C {design/temp_por_top.sym} 700 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 580 -220 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 580 -180 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 820 -240 0 0 {name=dutptat lab=PTAT}
C {devices/lab_pin.sym} 820 -200 0 0 {name=dutctat lab=CTAT}
C {devices/lab_pin.sym} 820 -160 0 0 {name=dutresetn lab=RESETn}
C {devices/code_shown.sym} 1100 -300 0 0 {name=SAVES only_toplevel=false value="
.save v(vdd) v(resetn) i(bvdd) v(ptat) v(ctat)
.save i(v.xdut.vsbias) i(v.xdut.vscmp) i(v.xdut.vspor) i(v.xdut.vstemp)
.save v(xdut.ibias) v(xdut.vref) v(xdut.bias_ok) v(xdut.por_raw)
.save v(xdut.xbias.na) v(xdut.xbias.nb) v(xdut.xbias.pg) v(xdut.xbias.pb) v(xdut.xbias.nbg)
.save v(xdut.xtemp.na) v(xdut.xtemp.nb)
.options method=gear trtol=50
"}
