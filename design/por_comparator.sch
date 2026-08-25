v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {por_comparator -- POR threshold comparator with hysteresis (issue #8, sky130 port of gf180-temp-por)} -300 -330 0 0 0.5 0.5 {}
T {Topology ported from gf180-temp-por's design/por_comparator.sch, per
spec/porting-plan.md Sec2.2 and this repo's own DR-002 (architecture
carryover): a bandgap-referenced comparator (VREF sourced by bias_core)
against a resistor-divided VDD tap, with hysteresis from resistor-network
positive feedback -- a static, non-time-domain mechanism. Deglitch (rejecting
a fast transient dip a hysteretic comparator would still trip on) is a
separate, additional mechanism owned by por_output_chain (issue #9); this
cell does not attempt to satisfy it here (DR-002's explicit hysteresis-vs-
deglitch ownership split, spec/porting-plan.md Sec1.1).

Device mapping onto sky130 per porting-plan.md Sec2.2 (issue #8):
  pfet_03v3/nfet_03v3      -> sky130_fd_pr__pfet_g5v0d10v5/nfet_g5v0d10v5
  ppolyf_u_3k (RTOP/RBOT/RHYS divider) -> sky130_fd_pr__res_xhigh_po (same
                              flavour bias_core's own R1/R2/RT ratio-tracking
                              legs use, so the ratio-cancellation argument
                              below is the same one design/bias_core.md
                              already makes for that flavour on sky130)

A three-segment res_xhigh_po string RTOP/RBOT/RHYS divides VDD; the SNS tap
(between RTOP and RBOT) is compared against VREF by an NMOS-input 5T OTA.
POR_RAW feeds back into the DIVIDER RATIO: MHSW shorts RHYS out while
POR_RAW is low, so

  VPOR-rise = VREF * (RTOP+RBOT)/RBOT            (reset asserted, RHYS shorted)
  VPOR-fall = VREF * (RTOP+RBOT+RHYS)/(RBOT+RHYS) (released, RHYS in circuit)
  V_hys     = VREF * RTOP*RHYS / (RBOT*(RBOT+RHYS))

Every one of those is VREF times a ratio of same-flavour, same-width
resistors, so sheet-rho corner spread and TC cancel in BOTH edges and in
their difference, on sky130 exactly as it did on gf180mcu's ppolyf_u_3k --
a device-physics argument, not a gf180mcu-specific number.

Sizing is a MECHANICAL, FIRST-ORDER PORT: every W/L (and every RTOP/RBOT/
RHYS drawn length) carries over unchanged from gf180-temp-por's ratified
por_comparator -- same drawn geometry, sky130's bare-micron-number
convention substituted for gf180's u-suffixed one (design/README.md's unit
convention note) -- so the RTOP/RBOT/RHYS ratios (and therefore the
VPOR-rise/VPOR-fall/V_hys ratios above) are exactly preserved, but the
resulting absolute VPOR-rise, VPOR-fall and V_hys values in volts have NOT
been simulated or characterized against sky130 models, nor against
bias_core's own (also not-yet-characterized) VREF -- no sky130 device
characterization exists yet in this repo (spec/porting-plan.md Sec4 item 2).
Per CLAUDE.md ("thresholds do not port"): no numeric VPOR/hysteresis figure
from gf180's own design/por_comparator.md is a sky130 target here or
anywhere else in this repo; re-deriving these against sky130 models and
bias_core's real VREF is expected follow-on work (spec/porting-plan.md
Sec2.3), not a defect in this port.

Interface contract (per design/README.md's internal-net table, issue #6):
  VDD/VSS  3.3 V nominal supply pair on sky130 5V I/O-class devices
           (g5v0d10v5), 2.97-3.63 V (DR-001)
  IBIAS    shared bias-mirror node from bias_core (issue #6). Convention
           carried from gf180: bias_core SOURCES current INTO this pin;
           this cell's own MDIB clamps the pin to VSS whenever disabled
           (BIAS_OK low), so it never presents a floating sink to the
           shared bus -- gf180's own DR-010 disabled-consumer-contract
           finding, carried here in shape.
  VREF     absolute reference from bias_core, compared against the divided
           VDD tap (SNS) -- this is what makes the threshold decision an
           absolute voltage rather than a rail fraction. Value is TBD
           pending sky130 characterization (bias_core's own VREF is itself
           still a first-order placeholder, issue #6).
  BIAS_OK  shared-core-valid flag from bias_core. Gates NBG (kills the tail
           + hysteresis-switch bias) and clamps CMPO to VSS when low, so
           POR_RAW reads a safe "not released" before the shared core is
           valid -- this cell's own authoritative-decision gate. The full
           startup-ordering AND with a pulse timer is por_output_chain's
           job (issue #9).
  POR_RAW  raw threshold decision, active HIGH: 1 means the divided VDD tap
           (SNS) is at or above VREF, i.e. VDD is above the (hysteretic)
           release threshold. Not the reset pin -- hysteresis lives here,
           deglitch + pulse + output drive live in por_output_chain (issue
           #9), per this repo's own DR-002 ownership split (design/
           README.md's internal-net table).

Below the comparator's own operating floor POR_RAW is undefined by
construction, same as gf180's own finding for this topology. Holding
RESETn low from 0 V in that regime is por_output_chain's below-floor
pull-down job (DR-002), not this cell's.} -300 -300 0 0 0.3 0.3 {}
N -300 -200 -240 -200 {lab=VDD}
N -300 -140 -240 -140 {lab=VSS}
N -300 -80 -240 -80 {lab=IBIAS}
N -300 -20 -240 -20 {lab=VREF}
N -300 40 -240 40 {lab=BIAS_OK}
N 240 -200 300 -200 {lab=POR_RAW}
C {devices/iopin.sym} -300 -200 0 1 {name=p_vdd lab=VDD}
C {devices/iopin.sym} -300 -140 0 1 {name=p_vss lab=VSS}
C {devices/ipin.sym} -300 -80 0 0 {name=p_ibias lab=IBIAS}
C {devices/ipin.sym} -300 -20 0 0 {name=p_vref lab=VREF}
C {devices/ipin.sym} -300 40 0 0 {name=p_bias_ok lab=BIAS_OK}
C {devices/opin.sym} 300 -200 0 0 {name=p_por_raw lab=POR_RAW}
T {ENABLE + NBG BIAS GENERATION -- BIAS_OK/BIAS_OKB local inverter, and the
same MPASS/MBD/MDNB pattern bias_core's own legs use, deriving a local NMOS
bias-mirror gate (NBG) off IBIAS, clamped to VSS whenever BIAS_OK is low.
MDIB additionally clamps the IBIAS PIN itself to VSS when disabled --
carried from gf180's own design/por_comparator.md finding (a disabled
consumer with no live sink otherwise left tens of uA flowing at ff/125 C on
gf180mcu). That specific measurement is gf180mcu evidence, not a sky130
one; the structural safeguard is carried per DR-010's shared-IBIAS
disabled-consumer contract (design/README.md) pending its own sky130
re-measurement.} -1100 -120 0 0 0.4 0.4 {}
N -980 -30 -980 -70 {}
C {devices/lab_pin.sym} -980 -70 0 0 {name=l1 lab=VDD}
N -1020 0 -1080 0 {}
C {devices/lab_pin.sym} -1080 0 0 0 {name=l2 lab=BIAS_OK}
N -980 30 -980 70 {}
C {devices/lab_pin.sym} -980 70 0 0 {name=l3 lab=BIAS_OKB}
N -980 0 -930 0 {}
C {devices/lab_pin.sym} -930 0 0 0 {name=l4 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 0 0 0 {name=MENP
L=0.5
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 -30 -740 -70 {}
C {devices/lab_pin.sym} -740 -70 0 0 {name=l5 lab=BIAS_OKB}
N -780 0 -840 0 {}
C {devices/lab_pin.sym} -840 0 0 0 {name=l6 lab=BIAS_OK}
N -740 30 -740 70 {}
C {devices/lab_pin.sym} -740 70 0 0 {name=l7 lab=VSS}
N -740 0 -690 0 {}
C {devices/lab_pin.sym} -690 0 0 0 {name=l8 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 0 0 0 {name=MENN
L=0.5
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -500 -30 -500 -70 {}
C {devices/lab_pin.sym} -500 -70 0 0 {name=l9 lab=IBIAS}
N -540 0 -600 0 {}
C {devices/lab_pin.sym} -600 0 0 0 {name=l10 lab=NBG}
N -500 30 -500 70 {}
C {devices/lab_pin.sym} -500 70 0 0 {name=l11 lab=VSS}
N -500 0 -450 0 {}
C {devices/lab_pin.sym} -450 0 0 0 {name=l12 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -520 0 0 0 {name=MBD
L=2
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -260 -30 -260 -70 {}
C {devices/lab_pin.sym} -260 -70 0 0 {name=l13 lab=IBIAS}
N -300 0 -360 0 {}
C {devices/lab_pin.sym} -360 0 0 0 {name=l14 lab=BIAS_OK}
N -260 30 -260 70 {}
C {devices/lab_pin.sym} -260 70 0 0 {name=l15 lab=NBG}
N -260 0 -210 0 {}
C {devices/lab_pin.sym} -210 0 0 0 {name=l16 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -280 0 0 0 {name=MPASS
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -20 -30 -20 -70 {}
C {devices/lab_pin.sym} -20 -70 0 0 {name=l17 lab=NBG}
N -60 0 -120 0 {}
C {devices/lab_pin.sym} -120 0 0 0 {name=l18 lab=BIAS_OKB}
N -20 30 -20 70 {}
C {devices/lab_pin.sym} -20 70 0 0 {name=l19 lab=VSS}
N -20 0 30 0 {}
C {devices/lab_pin.sym} 30 0 0 0 {name=l20 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -40 0 0 0 {name=MDNB
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 220 -30 220 -70 {}
C {devices/lab_pin.sym} 220 -70 0 0 {name=l83 lab=IBIAS}
N 180 0 120 0 {}
C {devices/lab_pin.sym} 120 0 0 0 {name=l84 lab=BIAS_OKB}
N 220 30 220 70 {}
C {devices/lab_pin.sym} 220 70 0 0 {name=l85 lab=VSS}
N 220 0 270 0 {}
C {devices/lab_pin.sym} 270 0 0 0 {name=l86 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 0 0 0 {name=MDIB
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {SENSE DIVIDER + HYSTERESIS -- a three-segment sky130_fd_pr__res_xhigh_po
string off VDD (RTOP/RBOT/RHYS, all one flavour and one drawn width, so
sheet-rho corner spread and TC cancel in every ratio -- design/bias_core.md's
own R1/R2/RT legs already make the identical cancellation argument for this
device flavour on sky130). MHSW shorts RHYS out whenever POR_RAW is LOW (its
gate is N1 = POR_RAW-bar), which is the whole hysteresis mechanism:

  reset asserted (POR_RAW low, MHSW on):   SNS = VDD * RBOT/(RTOP+RBOT)
     -> VPOR-rise = VREF * (RTOP+RBOT)/RBOT
  released      (POR_RAW high, MHSW off):  SNS = VDD * (RBOT+RHYS)/(RTOP+RBOT+RHYS)
     -> VPOR-fall = VREF * (RTOP+RBOT+RHYS)/(RBOT+RHYS)

  V_hys = VREF * RTOP * RHYS / (RBOT * (RBOT+RHYS))

Feeding POR_RAW back into the DIVIDER RATIO (rather than injecting a
bias-referenced current into the sense node) is DR-002's "resistor-network
positive feedback" mechanism taken literally: V_hys above has no I*R term,
so it inherits none of a current mirror's own corner spread. This is the
same structural argument gf180's own design history made for this topology
(spec/porting-plan.md Sec1.1); no gf180mcu number is carried by adopting it.

MHSW sits at the VSS end of the string on purpose: when it is on, its source
is at VSS and its gate is at VDD, so it has full overdrive and no body
effect, and its Ron appears in series with RBOT as a small fractional term.
A switch placed higher in the string would be gated at only Vgs =
VDD - V(tap) and would go soft exactly at the low-rail/cold corner the
release threshold binds at -- a device-physics argument, carried unchanged
from gf180's own topology.} -1100 140 0 0 0.4 0.4 {}
N -1000 290 -1000 330 {}
C {devices/lab_pin.sym} -1000 330 0 0 {name=l21 lab=SNS}
N -1000 230 -1000 190 {}
C {devices/lab_pin.sym} -1000 190 0 0 {name=l22 lab=VDD}
N -1020 260 -1080 260 {}
C {devices/lab_pin.sym} -1080 260 0 0 {name=l23 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} -1000 260 0 0 {name=RTOP
W=2
L=7897.44
model=res_xhigh_po
spiceprefix=X
mult=1}
N -760 290 -760 330 {}
C {devices/lab_pin.sym} -760 330 0 0 {name=l24 lab=SNSB}
N -760 230 -760 190 {}
C {devices/lab_pin.sym} -760 190 0 0 {name=l25 lab=SNS}
N -780 260 -840 260 {}
C {devices/lab_pin.sym} -840 260 0 0 {name=l26 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} -760 260 0 0 {name=RBOT
W=2
L=6769.23
model=res_xhigh_po
spiceprefix=X
mult=1}
N -520 290 -520 330 {}
C {devices/lab_pin.sym} -520 330 0 0 {name=l91 lab=VSS}
N -520 230 -520 190 {}
C {devices/lab_pin.sym} -520 190 0 0 {name=l92 lab=SNSB}
N -540 260 -600 260 {}
C {devices/lab_pin.sym} -600 260 0 0 {name=l93 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} -520 260 0 0 {name=RHYS
W=2
L=775.0
model=res_xhigh_po
spiceprefix=X
mult=1}
N -260 230 -260 190 {}
C {devices/lab_pin.sym} -260 190 0 0 {name=l94 lab=SNSB}
N -300 260 -360 260 {}
C {devices/lab_pin.sym} -360 260 0 0 {name=l95 lab=N1}
N -260 290 -260 330 {}
C {devices/lab_pin.sym} -260 330 0 0 {name=l96 lab=VSS}
N -260 260 -210 260 {}
C {devices/lab_pin.sym} -210 260 0 0 {name=l97 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -280 260 0 0 {name=MHSW
L=0.5
W=10
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {COMPARATOR CORE -- NMOS diff pair (SNS, VREF), PMOS mirror load diode-
referenced on the SNS branch (NA) so CMPO tracks SNS positively. MTAIL
mirrors NBG into the differential pair's tail (device sizing carried
mechanically from gf180 -- see the cell-level note above for the
not-yet-characterized caveat on the resulting absolute tail current).
MENSRC gates the mirror's OWN VDD connection (VDDA) with BIAS_OKB --
cutting the tail (MTAIL) alone is not enough to silence this block when
disabled: with CMPO clamped low by MDCMPO and VREF still a live,
always-present input, MINB's effective source becomes whichever of
{TN, CMPO} is lower -- CMPO, once clamped -- so its Vgs is measured against
that clamp, not against TN, and it conducts hard regardless of the
(correctly off) tail. This failure mode and its MENSRC fix are carried from
gf180's own design/por_comparator.md finding; not yet independently
re-measured on sky130.} -1100 400 0 0 0.4 0.4 {}
N -980 490 -980 450 {}
C {devices/lab_pin.sym} -980 450 0 0 {name=l27 lab=TN}
N -1020 520 -1080 520 {}
C {devices/lab_pin.sym} -1080 520 0 0 {name=l28 lab=NBG}
N -980 550 -980 590 {}
C {devices/lab_pin.sym} -980 590 0 0 {name=l29 lab=VSS}
N -980 520 -930 520 {}
C {devices/lab_pin.sym} -930 520 0 0 {name=l30 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -1000 520 0 0 {name=MTAIL
L=10
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -740 490 -740 450 {}
C {devices/lab_pin.sym} -740 450 0 0 {name=l31 lab=NA}
N -780 520 -840 520 {}
C {devices/lab_pin.sym} -840 520 0 0 {name=l32 lab=SNS}
N -740 550 -740 590 {}
C {devices/lab_pin.sym} -740 590 0 0 {name=l33 lab=TN}
N -740 520 -690 520 {}
C {devices/lab_pin.sym} -690 520 0 0 {name=l34 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 520 0 0 {name=MINA
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -500 490 -500 450 {}
C {devices/lab_pin.sym} -500 450 0 0 {name=l35 lab=CMPO}
N -540 520 -600 520 {}
C {devices/lab_pin.sym} -600 520 0 0 {name=l36 lab=VREF}
N -500 550 -500 590 {}
C {devices/lab_pin.sym} -500 590 0 0 {name=l37 lab=TN}
N -500 520 -450 520 {}
C {devices/lab_pin.sym} -450 520 0 0 {name=l38 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -520 520 0 0 {name=MINB
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -260 490 -260 450 {}
C {devices/lab_pin.sym} -260 450 0 0 {name=l39 lab=VDDA}
N -300 520 -360 520 {}
C {devices/lab_pin.sym} -360 520 0 0 {name=l40 lab=NA}
N -260 550 -260 590 {}
C {devices/lab_pin.sym} -260 590 0 0 {name=l41 lab=NA}
N -260 520 -210 520 {}
C {devices/lab_pin.sym} -210 520 0 0 {name=l42 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -280 520 0 0 {name=MLA
L=1
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -20 490 -20 450 {}
C {devices/lab_pin.sym} -20 450 0 0 {name=l43 lab=VDDA}
N -60 520 -120 520 {}
C {devices/lab_pin.sym} -120 520 0 0 {name=l44 lab=NA}
N -20 550 -20 590 {}
C {devices/lab_pin.sym} -20 590 0 0 {name=l45 lab=CMPO}
N -20 520 30 520 {}
C {devices/lab_pin.sym} 30 520 0 0 {name=l46 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -40 520 0 0 {name=MLB
L=1
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 220 490 220 450 {}
C {devices/lab_pin.sym} 220 450 0 0 {name=l87 lab=VDD}
N 180 520 120 520 {}
C {devices/lab_pin.sym} 120 520 0 0 {name=l88 lab=BIAS_OKB}
N 220 550 220 590 {}
C {devices/lab_pin.sym} 220 590 0 0 {name=l89 lab=VDDA}
N 220 520 270 520 {}
C {devices/lab_pin.sym} 270 520 0 0 {name=l90 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 200 520 0 0 {name=MENSRC
L=0.5
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
T {OUTPUT BUFFER + DISABLE CLAMP -- two inverting stages square CMPO up to a
rail-to-rail POR_RAW (even inversion count preserves polarity: CMPO high ==
POR_RAW high == release condition true). MDCMPO holds CMPO at VSS whenever
BIAS_OK is low, so POR_RAW reads a safe "not released" with no floating
node while the shared core is not yet valid.} -1100 660 0 0 0.4 0.4 {}
N -980 750 -980 710 {}
C {devices/lab_pin.sym} -980 710 0 0 {name=l47 lab=CMPO}
N -1020 780 -1080 780 {}
C {devices/lab_pin.sym} -1080 780 0 0 {name=l48 lab=BIAS_OKB}
N -980 810 -980 850 {}
C {devices/lab_pin.sym} -980 850 0 0 {name=l49 lab=VSS}
N -980 780 -930 780 {}
C {devices/lab_pin.sym} -930 780 0 0 {name=l50 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -1000 780 0 0 {name=MDCMPO
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -740 750 -740 710 {}
C {devices/lab_pin.sym} -740 710 0 0 {name=l51 lab=VDD}
N -780 780 -840 780 {}
C {devices/lab_pin.sym} -840 780 0 0 {name=l52 lab=CMPO}
N -740 810 -740 850 {}
C {devices/lab_pin.sym} -740 850 0 0 {name=l53 lab=N1}
N -740 780 -690 780 {}
C {devices/lab_pin.sym} -690 780 0 0 {name=l54 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -760 780 0 0 {name=MI1P
L=0.5
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -500 750 -500 710 {}
C {devices/lab_pin.sym} -500 710 0 0 {name=l55 lab=N1}
N -540 780 -600 780 {}
C {devices/lab_pin.sym} -600 780 0 0 {name=l56 lab=CMPO}
N -500 810 -500 850 {}
C {devices/lab_pin.sym} -500 850 0 0 {name=l57 lab=VSS}
N -500 780 -450 780 {}
C {devices/lab_pin.sym} -450 780 0 0 {name=l58 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -520 780 0 0 {name=MI1N
L=0.5
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -260 750 -260 710 {}
C {devices/lab_pin.sym} -260 710 0 0 {name=l59 lab=VDD}
N -300 780 -360 780 {}
C {devices/lab_pin.sym} -360 780 0 0 {name=l60 lab=N1}
N -260 810 -260 850 {}
C {devices/lab_pin.sym} -260 850 0 0 {name=l61 lab=POR_RAW}
N -260 780 -210 780 {}
C {devices/lab_pin.sym} -210 780 0 0 {name=l62 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -280 780 0 0 {name=MI2P
L=0.5
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -20 750 -20 710 {}
C {devices/lab_pin.sym} -20 710 0 0 {name=l63 lab=POR_RAW}
N -60 780 -120 780 {}
C {devices/lab_pin.sym} -120 780 0 0 {name=l64 lab=N1}
N -20 810 -20 850 {}
C {devices/lab_pin.sym} -20 850 0 0 {name=l65 lab=VSS}
N -20 780 30 780 {}
C {devices/lab_pin.sym} 30 780 0 0 {name=l66 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -40 780 0 0 {name=MI2N
L=0.5
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {No separate hysteresis-generation band: hysteresis is the RHYS/MHSW leg of
the sense divider above. That is DR-002's "resistor-network positive
feedback" taken literally -- POR_RAW feeds back into the divider ratio, not
into a summing node -- and it is why V_hys has no I*R term to drag it
across the resistor corners.} -1100 920 0 0 0.4 0.4 {}
