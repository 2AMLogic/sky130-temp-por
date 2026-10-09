v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por por_comparator threshold testbench (issue #102).
*
* DUT: the unchanged design/por_comparator.sym (subckt por_comparator VDD VSS
* IBIAS VREF BIAS_OK POR_RAW); the netlist is spliced from the committed
* design/netlist/por_comparator.spice by the driver.
*
* Supply: behavioural source BVDD sweeps VDD UP from 0 V at a CONSTANT dVDD/dt
* ('rate', V/s) to the peak v(VSETN), then DOWN at the same |dVDD/dt| to 0 V:
*     V(VDD) = min( v(VSETN), rate*time, max(0, 2*v(VSETN) - rate*time) )
* The sweep time is derived from the rate (no fixed-duration confound, gf180
* DR-021). VSET is a scalar DC source so `klt sim` can sweep it with
* corners.supply_v; here it is only the sweep PEAK (single value), not a
* separate supply axis -- VDD itself is the swept variable.
* 'rate' is a .param supplied per request by the driver.
*
* IBIAS / VREF / BIAS_OK treatment: REAL design/bias_core.sym drives all three
* (variant "real-bias-core"): IBIAS, VREF and BIAS_OK come from bias_core on the
* same VDD, so the VREF/IBIAS dependence on process, temperature and supply
* moves the comparator edges. Reported separately from the ideal-bias variant.
* Deliberately NOT in this schematic (klt sim injects them): the .lib corner
* include, .temp, the numeric peak supply, the .control analysis block and the
* measurements.
}
G {}
K {}
V {}
S {}
E {}
T {por_comparator threshold testbench -- quasi-static VDD up/down sweep.
Connectivity is by net label (lab_pin on every pin), no wires.} 100 -700 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -300 0 0 {name=VSET value=3.63 savecurrent=false}
C {devices/lab_pin.sym} 200 -330 0 0 {name=vsetp lab=VSETN}
C {devices/lab_pin.sym} 200 -270 0 0 {name=vsetm lab=0}
C {devices/bsource.sym} 200 0 0 0 {name=BVDD VAR=V FUNC="min(v(VSETN), min(\{rate\}*time, max(0, 2*v(VSETN) - \{rate\}*time)))"}
C {devices/lab_pin.sym} 200 -30 0 0 {name=bvddp lab=VDD}
C {devices/lab_pin.sym} 200 30 0 0 {name=bvddm lab=0}
C {design/por_comparator.sym} 700 -200 0 0 {name=XDUT}
C {devices/lab_pin.sym} 600 -240 0 0 {name=dutvdd lab=VDD}
C {devices/lab_pin.sym} 600 -220 0 0 {name=dutvss lab=0}
C {devices/lab_pin.sym} 600 -200 0 0 {name=dutibias lab=IBIAS}
C {devices/lab_pin.sym} 600 -180 0 0 {name=dutvref lab=VREF}
C {devices/lab_pin.sym} 600 -160 0 0 {name=dutbok lab=BIAS_OK}
C {devices/lab_pin.sym} 800 -200 0 0 {name=dutporraw lab=POR_RAW}
C {design/bias_core.sym} 400 300 0 0 {name=XBIAS}
C {devices/lab_pin.sym} 300 280 0 0 {name=bcvdd lab=VDD}
C {devices/lab_pin.sym} 300 320 0 0 {name=bcvss lab=0}
C {devices/lab_pin.sym} 500 280 0 0 {name=bcibias lab=IBIAS}
C {devices/lab_pin.sym} 500 300 0 0 {name=bcvref lab=VREF}
C {devices/lab_pin.sym} 500 320 0 0 {name=bcbok lab=BIAS_OK}
C {devices/code_shown.sym} 1100 -300 0 0 {name=SAVES only_toplevel=false value="
.save v(vdd) v(por_raw) v(vref) v(ibias) v(bias_ok) i(bvdd)
.save v(xdut.sns) v(xdut.snsb) v(xdut.n1) v(xdut.cmpo)
.options method=gear trtol=50
"}
