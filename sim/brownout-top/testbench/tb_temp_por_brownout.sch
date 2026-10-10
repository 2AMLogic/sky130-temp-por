v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por assembled temp_por_top BROWN-OUT testbench (issue #116).
*
* DUT is the unchanged assembled design/temp_por_top.sym (bias_core +
* temp_core + por_comparator + por_output_chain); nothing is replaced by an
* ideal bias or an ideal sensor load.  PTAT and CTAT are left OPEN (no output
* buffer exists in the design; their loading is therefore "none", stated, not
* assumed).
*
* Supply: behavioural source BVDD.  Power-up is a constant-rate ramp
* min(v(VSETN), rup*time) from a physical 0 V start (as sim/supply-ramp-top),
* then ONE dip with four independent stimulus axes, all .params written per
* request by sim/brownout-top/run_brownout_campaign.py:
*   vlow  absolute dip floor (V)           -> excursion  ex = v(VSETN) - vlow
*   sf    falling slew (V/s)               -> fall time  ex/sf   (derived)
*   th    hold at the floor (s)            -> independent of both slews
*   sr    recovery slew (V/s)              -> recovery   ex/sr   (derived)
*   t0    dip start (s)                    -> baseline settling window
* Edge durations are DERIVED from excursion/slew, never a fixed duration, so
* the supply axis (v(VSETN), swept by klt corners.supply_v) does not couple
* into any slew.  vlow >= v(VSETN) (the runner uses 99) is the no-dip control.
* max(ex, 1m) only guards the division when ex = 0.
*
* Deliberately NOT here (klt sim injects them): the .lib corner include,
* .temp, the numeric final supply, the .control analysis block, measurements.
}
G {}
K {}
V {}
S {}
E {}
T {temp_por_top brown-out testbench -- transient from a physical 0 V start.
BVDD: power-up ramp, then one dip (vlow, falling slew sf, hold th, recovery
slew sr) starting at t0.  PTAT/CTAT open.  Connectivity is by net label.} 100 -700 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -300 0 0 {name=VSET value=3.3 savecurrent=false}
C {devices/lab_pin.sym} 200 -330 0 0 {name=vsetp lab=VSETN}
C {devices/lab_pin.sym} 200 -270 0 0 {name=vsetm lab=0}
C {devices/bsource.sym} 200 0 0 0 {name=BVDD VAR=V FUNC="min(v(VSETN), \{rup\}*time) - max(v(VSETN)-\{vlow\},0)*( min(max((time-\{t0\})*\{sf\}/max(v(VSETN)-\{vlow\},1m),0),1) - min(max((time-\{t0\}-max(v(VSETN)-\{vlow\},1m)/\{sf\}-\{th\})*\{sr\}/max(v(VSETN)-\{vlow\},1m),0),1) )"}
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
* delivered bias branch: drain current of the bias_core device that drives the IBIAS node (XMPIB, PMOS)
* and the consumer-side diode/mirror devices; BSIM4 [id] is positive for normal conduction (KCL-checked in the probe)
.save @m.xdut.xbias.xmpib.msky130_fd_pr__pfet_g5v0d10v5[id]
.save @m.xdut.xcmp.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id]
.save @m.xdut.xpor.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id]
.save @m.xdut.xtemp.xmbd.msky130_fd_pr__nfet_g5v0d10v5[id]
.options method=gear trtol=50
"}
