v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por assembled temp_por_top supply-ramp testbench (issue #98).
*
* DUT is the unchanged assembled design/temp_por_top.sym (bias_core +
* temp_core + por_comparator + por_output_chain); nothing is replaced by an
* ideal bias or an ideal sensor load, so the shared IBIAS node carries the real
* RESETn -> temp_core.EN interaction (spec/porting-plan.md Sec3.3).
*
* Supply: a behavioural source BVDD ramps VDD from 0 V at a CONSTANT dVDD/dt
* ('rate', V/s) and clips at the final supply v(VSETN):
*     V(VDD) = min( v(VSETN), rate * time )
* so ramp duration = supply / rate and the rate axis is independent of the
* supply axis (the fixed-duration confound of gf180 DR-021 is avoided by
* construction). VSET is an ordinary scalar DC source so `klt sim` can sweep
* it with corners.supply_v (an `alter` on a PULSE/PWL source is refused).
* 'rate' is a .param supplied per request by the driver (a local rate axis).
*
* Deliberately NOT in this schematic (klt sim injects them): the .lib corner
* include, .temp, the numeric final supply, the .control analysis block and
* the measurements. The transition checker runs on the saved waveforms
* (sim/supply-ramp-top/ramp_checker.py).
}
G {}
K {}
V {}
S {}
E {}
T {temp_por_top supply-ramp testbench -- transient from a physical 0 V
start. BVDD ramps VDD at constant 'rate' (V/s) up to the swept final
supply held on VSET. PTAT/CTAT are left open (no output buffer exists).
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -700 0 0 0.4 0.4 {}
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
.save v(xdut.ibias) v(xdut.vref) v(xdut.bias_ok) v(xdut.por_raw)
.save v(xdut.xbias.na) v(xdut.xbias.nb) v(xdut.xbias.pg) v(xdut.xbias.pb) v(xdut.xbias.nbg)
.save v(xdut.xtemp.na) v(xdut.xtemp.nb)
.options method=gear trtol=50
"}
