v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por assembled temp_por_top Iq testbench, por-iq state (issue #107).
*
* DUT is the unchanged assembled design/temp_por_top.sym. VDD is brought from
* a physical 0 V start by BVDD (V(VDD) = min(v(VSETN), rate*time), a fast
* ramp, then held constant for the settling windows). Supply current is
* -i(BVDD); the driver reads it from the saved waveform and checks that it is
* settled, it is not a single OP number.
*
* por-iq = RESETn asserted (low). RESETn is a DUT OUTPUT that releases on its
* own once VDD is above VPOR-rise, so it is held low by a 0 V forcing source
* VRST (RESETn -> 0). The DUT netlist is not altered. VRST's own current is
* NOT part of the VDD measurement; the DUT's contention current (output
* stage pushing against the force) flows VDD -> MOP -> RESETn -> VRST, is
* INCLUDED in -i(BVDD), and is read separately as i(VRST).
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
T {temp_por_top Iq testbench (por-iq: RESETn forced low by VRST). Transient from a physical 0 V start; fast constant-rate ramp to the swept supply on VSET, then a long hold; Iq is read from the settled trailing window. PTAT/CTAT left open. Connectivity is by net label.} 100 -700 0 0 0.4 0.4 {}
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
C {devices/vsource.sym} 1000 -160 0 0 {name=VRST value=0 savecurrent=true}
C {devices/lab_pin.sym} 1000 -190 0 0 {name=vrstp lab=RESETn}
C {devices/lab_pin.sym} 1000 -130 0 0 {name=vrstm lab=0}
C {devices/code_shown.sym} 1100 -300 0 0 {name=SAVES only_toplevel=false value="
.save v(vdd) v(resetn) i(bvdd) v(ptat) v(ctat) i(vrst)
.save i(v.xdut.vsbias) i(v.xdut.vscmp) i(v.xdut.vspor) i(v.xdut.vstemp)
.save v(xdut.ibias) v(xdut.vref) v(xdut.bias_ok) v(xdut.por_raw)
.save v(xdut.xbias.na) v(xdut.xbias.nb) v(xdut.xbias.pg) v(xdut.xbias.pb) v(xdut.xbias.nbg)
.save v(xdut.xtemp.na) v(xdut.xtemp.nb)
.options method=gear trtol=50
"}
