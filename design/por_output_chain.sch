v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {por_output_chain -- deglitch, reset-pulse one-shot, push-pull RESETn drive,
and the POR startup-assist pull-down (issue #9, sky130 port of
gf180-temp-por)} -1400 -1500 0 0 0.6 0.6 {}
T {Topology ported from gf180-temp-por's design/por_output_chain.sch
(commit visible on 2AMLogic/gf180-temp-por main, 2026-08-25) and its
design/por_output_chain.md, per spec/porting-plan.md Sec2.2 and this repo's
own DR-002 (architecture carryover). Per design/README.md's verified
finding (issue #6/#9): the POR startup-assist pull-down lives INSIDE this
cell, not as a separate DR-002 leaf cell -- gf180's own design/README.md
says so explicitly, and its actual por_output_chain.sch confirms it (the
assist is the release-NAND's own below-floor leakage-divider default, not a
free-standing sub-block).

POR_RAW (raw, hysteretic threshold decision from por_comparator, #8) ->
deglitch dwell -> current-starved one-shot -> release NAND (TRIP AND PGDG)
-> push-pull RESETn. POLARITY CONVENTION (matches por_comparator, #8):
POR_RAW is ACTIVE HIGH = "rail is above VPOR and the comparator decision is
authoritative". Low, or undriven-low below the comparator's own operating
floor, means "not good" -- the fail-safe sense, because RESETn must degrade
to ASSERTED near 0 V (DR-002/DR-004-equivalent below-floor requirement).

Device mapping onto sky130 per porting-plan.md Sec2.2 (issue #9):
  nfet_03v3/pfet_03v3      -> sky130_fd_pr__nfet_g5v0d10v5/pfet_g5v0d10v5
                              (every deglitch/one-shot/trip-detector/output
                              MOS below, mechanically substituted)
  cap_mim_2f0_m3m4_noshield -> sky130_fd_pr__cap_mim_m3_1 (CDG, CTIM; same
                              ~2 fF/um2 order bias_core.md already used for
                              this substitution)

Sizing is a MECHANICAL, FIRST-ORDER PORT, same convention as bias_core (#6)
and por_comparator (#8): every W/L below carries over unchanged from
gf180-temp-por's ratified por_output_chain -- same drawn geometry, sky130's
bare-micron-number convention substituted for gf180's u-suffixed one
(design/README.md's unit convention note) -- so every device RATIO (the
deglitch tail vs. reference-leg ratios, the one-shot's current-mirror
ratios, the release-NAND's parallel-PMOS-vs-series-NMOS pull ratio, the
20:1 XMON/XMOP output-stage ratio) is exactly preserved. The resulting
absolute reset-pulse WIDTH, deglitch DWELL, and valid-low FLOOR voltage
have NOT been simulated or characterized against sky130 models, nor against
a real (also not-yet-characterized) IBIAS/POR_RAW from bias_core/
por_comparator -- no sky130 device characterization exists yet in this repo
(spec/porting-plan.md Sec4 item 2). Per CLAUDE.md ("thresholds do not
port"): no numeric pulse-width, dwell, or floor-voltage figure from gf180's
own design/por_output_chain.md is a sky130 target here or anywhere else in
this repo -- the one-shot capacitor sizes (CDG, CTIM) below are carried as
a FIRST-ORDER PLACEHOLDER timing element (the topology that makes a
fixed-width pulse buildable in a sub-uA budget), not a committed duration.
Re-deriving the real pulse width, dwell, and floor against sky130 models
and a real IBIAS/POR_RAW is expected follow-on work (spec/porting-plan.md
Sec2.3/Sec2.4), not a defect in this port.

Interface contract (per design/README.md's internal-net table, issue #6):
  VDD/VSS  3.3 V nominal supply pair on sky130 5V I/O-class devices
           (g5v0d10v5), 2.97-3.63 V (DR-001)
  IBIAS    shared bias-mirror node from bias_core (issue #6). Convention
           carried from gf180 (same as temp_core/por_comparator): bias_core
           SOURCES current INTO this pin; this cell's own MBD is the local
           mirror diode, ungated and always on -- per DR-010's shared-IBIAS
           disabled-consumer contract, at least one always-on diode-
           connected leg must stay on the shared node, and this cell's own
           MBD is it (this cell has no enable pin to gate it with).
  POR_RAW  input, active high (see polarity convention above), from
           por_comparator (#8). Low -- including undriven-low below the
           comparator's own operating floor -- is the fail-safe sense.
  RESETn   output, active low, push-pull (DR-002). Held low from the first
           millivolt of VDD, through the shared core's operating floor
           (where POR_RAW is undefined by construction), by this cell's own
           below-floor default -- NOT gated by POR_RAW. Drives both the
           top-level pad and temp_core.EN (design/README.md) once
           temp_por_top (#10) assembles the hierarchy.} -1400 -1440 0 0 0.3 0.3 {}
N -1400 -1000 -1340 -1000 {}
C {devices/iopin.sym} -1400 -1000 0 0 {name=p_vdd lab=VDD}
N -1400 -940 -1340 -940 {}
C {devices/iopin.sym} -1400 -940 0 0 {name=p_vss lab=VSS}
N -1400 -880 -1340 -880 {}
C {devices/ipin.sym} -1400 -880 0 0 {name=p_ibias lab=IBIAS}
N -1400 -820 -1340 -820 {}
C {devices/ipin.sym} -1400 -820 0 0 {name=p_por_raw lab=POR_RAW}
N -1400 -760 -1340 -760 {}
C {devices/opin.sym} -1400 -760 0 0 {name=p_resetn lab=RESETn}
T {BIAS -- local mirror diode off IBIAS (MBD), then a cascaded 1:50 PMOS
reference leg (MN1/MPD) and a 1:1 copy into the NMOS reference rail
(MP2/MND). Two cascaded stages rather than one long-ratio mirror, so the nA
reference legs track over corners better than a single wide-ratio mirror
against the diode would -- carried unchanged in shape from gf180's own
por_output_chain.sch. Standing draw from VDD is only these two reference
legs; every other branch below is a switched tail that conducts only while
a node is slewing (gf180's own Iq-budget argument, not yet re-measured on
sky130).} -1400 -120 0 0 0.4 0.4 {}
N -980 -30 -980 -70 {}
C {devices/lab_pin.sym} -980 -70 0 0 {name=l1 lab=IBIAS}
N -1020 0 -1080 0 {}
C {devices/lab_pin.sym} -1080 0 0 0 {name=l2 lab=IBIAS}
N -980 30 -980 70 {}
C {devices/lab_pin.sym} -980 70 0 0 {name=l3 lab=VSS}
N -980 0 -930 0 {}
C {devices/lab_pin.sym} -930 0 0 0 {name=l4 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -1000 0 0 0 {name=MBD
L=4
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -740 -30 -740 -70 {}
C {devices/lab_pin.sym} -740 -70 0 0 {name=l5 lab=PDN}
N -780 0 -840 0 {}
C {devices/lab_pin.sym} -840 0 0 0 {name=l6 lab=IBIAS}
N -740 30 -740 70 {}
C {devices/lab_pin.sym} -740 70 0 0 {name=l7 lab=VSS}
N -740 0 -690 0 {}
C {devices/lab_pin.sym} -690 0 0 0 {name=l8 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 0 0 0 {name=MN1
L=25
W=0.5
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -500 -30 -500 -70 {}
C {devices/lab_pin.sym} -500 -70 0 0 {name=l9 lab=VDD}
N -540 0 -600 0 {}
C {devices/lab_pin.sym} -600 0 0 0 {name=l10 lab=PDN}
N -500 30 -500 70 {}
C {devices/lab_pin.sym} -500 70 0 0 {name=l11 lab=PDN}
N -500 0 -450 0 {}
C {devices/lab_pin.sym} -450 0 0 0 {name=l12 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -520 0 0 0 {name=MPD
L=10
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -260 -30 -260 -70 {}
C {devices/lab_pin.sym} -260 -70 0 0 {name=l13 lab=VDD}
N -300 0 -360 0 {}
C {devices/lab_pin.sym} -360 0 0 0 {name=l14 lab=PDN}
N -260 30 -260 70 {}
C {devices/lab_pin.sym} -260 70 0 0 {name=l15 lab=NDL}
N -260 0 -210 0 {}
C {devices/lab_pin.sym} -210 0 0 0 {name=l16 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -280 0 0 0 {name=MP2
L=10
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -20 -30 -20 -70 {}
C {devices/lab_pin.sym} -20 -70 0 0 {name=l17 lab=NDL}
N -60 0 -120 0 {}
C {devices/lab_pin.sym} -120 0 0 0 {name=l18 lab=NDL}
N -20 30 -20 70 {}
C {devices/lab_pin.sym} -20 70 0 0 {name=l19 lab=VSS}
N -20 0 30 0 {}
C {devices/lab_pin.sym} 30 0 0 0 {name=l20 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -40 0 0 0 {name=MND
L=10
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {DEGLITCH -- current-starved differential pair (MDGPI/MDGNI) into the
dwell capacitor CDG, then two ratio-skewed restoring inverters (MG1P/MG1N,
MG2P/MG2N). This is DR-002's time-domain glitch rejection, separate from
por_comparator's own static hysteresis (#8): NDG has to traverse CDG at I/C
before MG1P/MG1N flip, so a POR_RAW excursion shorter than the dwell never
reaches PGDG. CDG's drawn size (11 um x 11 um, carried unchanged from
gf180) is a first-order placeholder for the dwell time, not a sky130-
derived value -- see the cell-level note above.

MG1P/MG1N and MG2P/MG2N are deliberately ratio-skewed (weak PMOS + strong
NMOS, then the mirror image) -- carried from gf180's own finding that this
is what fixes each node's LEAKAGE default while the shared bias core is
dead, below its own operating floor: POR_RAW low -> NDG high -> PGDG low ->
PGDGB high, which grounds the one-shot timer node and leaves the release
NAND's PMOS pull-ups on (see the OUTPUT section below).} -1400 140 0 0 0.4 0.4 {}
N -980 230 -980 190 {}
C {devices/lab_pin.sym} -980 190 0 0 {name=l21 lab=VDD}
N -1020 260 -1080 260 {}
C {devices/lab_pin.sym} -1080 260 0 0 {name=l22 lab=PDN}
N -980 290 -980 330 {}
C {devices/lab_pin.sym} -980 330 0 0 {name=l23 lab=NDGP}
N -980 260 -930 260 {}
C {devices/lab_pin.sym} -930 260 0 0 {name=l24 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 260 0 0 {name=MDGPT
L=10
W=10
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -720 230 -720 190 {}
C {devices/lab_pin.sym} -720 190 0 0 {name=l25 lab=NDGP}
N -760 260 -820 260 {}
C {devices/lab_pin.sym} -820 260 0 0 {name=l26 lab=POR_RAW}
N -720 290 -720 330 {}
C {devices/lab_pin.sym} -720 330 0 0 {name=l27 lab=NDG}
N -720 260 -670 260 {}
C {devices/lab_pin.sym} -670 260 0 0 {name=l28 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -740 260 0 0 {name=MDGPI
L=0.5
W=1
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -480 230 -480 190 {}
C {devices/lab_pin.sym} -480 190 0 0 {name=l29 lab=NDG}
N -520 260 -580 260 {}
C {devices/lab_pin.sym} -580 260 0 0 {name=l30 lab=POR_RAW}
N -480 290 -480 330 {}
C {devices/lab_pin.sym} -480 330 0 0 {name=l31 lab=NDGN}
N -480 260 -430 260 {}
C {devices/lab_pin.sym} -430 260 0 0 {name=l32 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -500 260 0 0 {name=MDGNI
L=0.5
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -240 230 -240 190 {}
C {devices/lab_pin.sym} -240 190 0 0 {name=l33 lab=NDGN}
N -280 260 -340 260 {}
C {devices/lab_pin.sym} -340 260 0 0 {name=l34 lab=NDL}
N -240 290 -240 330 {}
C {devices/lab_pin.sym} -240 330 0 0 {name=l35 lab=VSS}
N -240 260 -190 260 {}
C {devices/lab_pin.sym} -190 260 0 0 {name=l36 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -260 260 0 0 {name=MDGNT
L=10
W=10
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -40 230 -40 190 {}
C {devices/lab_pin.sym} -40 190 0 0 {name=l37 lab=NDG}
N -40 290 -40 330 {}
C {devices/lab_pin.sym} -40 330 0 0 {name=l38 lab=VSS}
C {sky130_fd_pr/cap_mim_m3_1.sym} -40 260 0 0 {name=CDG
W=11
L=11
model=cap_mim_m3_1
spiceprefix=X
MF=1}
N 240 230 240 190 {}
C {devices/lab_pin.sym} 240 190 0 0 {name=l39 lab=VDD}
N 200 260 140 260 {}
C {devices/lab_pin.sym} 140 260 0 0 {name=l40 lab=NDG}
N 240 290 240 330 {}
C {devices/lab_pin.sym} 240 330 0 0 {name=l41 lab=PGDG}
N 240 260 290 260 {}
C {devices/lab_pin.sym} 290 260 0 0 {name=l42 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 220 260 0 0 {name=MG1P
L=2
W=0.5
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 480 230 480 190 {}
C {devices/lab_pin.sym} 480 190 0 0 {name=l43 lab=PGDG}
N 440 260 380 260 {}
C {devices/lab_pin.sym} 380 260 0 0 {name=l44 lab=NDG}
N 480 290 480 330 {}
C {devices/lab_pin.sym} 480 330 0 0 {name=l45 lab=VSS}
N 480 260 530 260 {}
C {devices/lab_pin.sym} 530 260 0 0 {name=l46 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 460 260 0 0 {name=MG1N
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 720 230 720 190 {}
C {devices/lab_pin.sym} 720 190 0 0 {name=l47 lab=VDD}
N 680 260 620 260 {}
C {devices/lab_pin.sym} 620 260 0 0 {name=l48 lab=PGDG}
N 720 290 720 330 {}
C {devices/lab_pin.sym} 720 330 0 0 {name=l49 lab=PGDGB}
N 720 260 770 260 {}
C {devices/lab_pin.sym} 770 260 0 0 {name=l50 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 700 260 0 0 {name=MG2P
L=0.5
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 960 230 960 190 {}
C {devices/lab_pin.sym} 960 190 0 0 {name=l51 lab=PGDGB}
N 920 260 860 260 {}
C {devices/lab_pin.sym} 860 260 0 0 {name=l52 lab=PGDG}
N 960 290 960 330 {}
C {devices/lab_pin.sym} 960 330 0 0 {name=l53 lab=VSS}
N 960 260 1010 260 {}
C {devices/lab_pin.sym} 1010 260 0 0 {name=l54 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 940 260 0 0 {name=MG2N
L=2
W=0.5
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {ONE-SHOT TIMER -- current-starved ramp gated by the deglitched power-good
(PGDG). MPT sources a starved reference current into TIM's node only while
MTSW is on (gated by PGDGB), and MDIS slams TIM back to VSS the instant
PGDG falls, which is what regenerates a full pulse after a brownout dip
(the same DR-002 requirement por_comparator's hysteresis does not by
itself satisfy). A fixed-width pulse inside a sub-uA Iq budget rules out an
RC network outright (an RC that reaches millisecond time constants at nA-
scale current needs a hundred-megohm-class resistor, unbuildable in this
area/Iq budget) -- carried unchanged in shape from gf180's own
design/por_output_chain.md rationale. CTIM's drawn size (4 x 28 um x 28 um,
carried unchanged from gf180) is a first-order placeholder for the pulse
width, not a sky130-derived duration.} -1400 400 0 0 0.4 0.4 {}
N -980 490 -980 450 {}
C {devices/lab_pin.sym} -980 450 0 0 {name=l55 lab=VDD}
N -1020 520 -1080 520 {}
C {devices/lab_pin.sym} -1080 520 0 0 {name=l56 lab=PDN}
N -980 550 -980 590 {}
C {devices/lab_pin.sym} -980 590 0 0 {name=l57 lab=NTS}
N -980 520 -930 520 {}
C {devices/lab_pin.sym} -930 520 0 0 {name=l58 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 520 0 0 {name=MPT
L=10
W=0.5
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 490 -740 450 {}
C {devices/lab_pin.sym} -740 450 0 0 {name=l59 lab=NTS}
N -780 520 -840 520 {}
C {devices/lab_pin.sym} -840 520 0 0 {name=l60 lab=PGDGB}
N -740 550 -740 590 {}
C {devices/lab_pin.sym} -740 590 0 0 {name=l61 lab=TIM}
N -740 520 -690 520 {}
C {devices/lab_pin.sym} -690 520 0 0 {name=l62 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -760 520 0 0 {name=MTSW
L=1
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -480 490 -480 450 {}
C {devices/lab_pin.sym} -480 450 0 0 {name=l63 lab=TIM}
N -520 520 -580 520 {}
C {devices/lab_pin.sym} -580 520 0 0 {name=l64 lab=PGDGB}
N -480 550 -480 590 {}
C {devices/lab_pin.sym} -480 590 0 0 {name=l65 lab=VSS}
N -480 520 -430 520 {}
C {devices/lab_pin.sym} -430 520 0 0 {name=l66 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -500 520 0 0 {name=MDIS
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -280 490 -280 450 {}
C {devices/lab_pin.sym} -280 450 0 0 {name=l67 lab=TIM}
N -280 550 -280 590 {}
C {devices/lab_pin.sym} -280 590 0 0 {name=l68 lab=VSS}
C {sky130_fd_pr/cap_mim_m3_1.sym} -280 520 0 0 {name=CTIM
W=28
L=28
model=cap_mim_m3_1
spiceprefix=X
MF=4}
T {TRIP DETECTOR -- two nA-limited current comparators (MDAPI/MDANT, then
MDBNI/MDBPT), not a starved CMOS inverter. Carried unchanged from gf180's
own finding that a starved-inverter trip point is two DIFFERENT threshold
mechanisms (pull-up loses at TIM ~ VDD-|Vtp|, pull-down wins at TIM ~ Vtn)
with opposite temperature coefficients, while a single current-comparator
trip (TIM = VDD - Vsg of a fixed nA source) is ONE mechanism with only a
Vsg(T) correction -- a device-physics argument about trip-point definition,
not a gf180mcu-specific number, so it carries.

MRLK (issue #56 on gf180, carried here as part of the same ratified
topology) is a RELEASE LATCH: once RESETn is high it holds ND1 at VSS
independently of the nA trip balance, so the release decision cannot be
walked back by a later shift in the shared IBIAS node (gf180's own finding:
enabling a downstream IBIAS consumer on RESETn's own release steps the
shared bias node and can otherwise re-trip the detector). It cannot latch
prematurely: RSTB = NAND(TRIP, PGDG), so PGDG low pins RSTB (and therefore
RESETn) low regardless of TRIP, and MRLK is gated by RESETn itself, so it
stays off throughout assertion.

Below-floor default (bias dead, no static current in the settled state):
MDAPI has Vsg = VDD against a sink gated at NDL ~ 0 V (off) and much
smaller in W/L, so ND1 pins HIGH; MDBNI then has Vgs = VDD against an off
PMOS source, so TRIP pins LOW. TRIP low is what holds the release NAND's
output at VDD -- see OUTPUT below.} -1400 660 0 0 0.4 0.4 {}
N -980 750 -980 710 {}
C {devices/lab_pin.sym} -980 710 0 0 {name=l69 lab=VDD}
N -1020 780 -1080 780 {}
C {devices/lab_pin.sym} -1080 780 0 0 {name=l70 lab=TIM}
N -980 810 -980 850 {}
C {devices/lab_pin.sym} -980 850 0 0 {name=l71 lab=ND1}
N -980 780 -930 780 {}
C {devices/lab_pin.sym} -930 780 0 0 {name=l72 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 780 0 0 {name=MDAPI
L=1
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 750 -740 710 {}
C {devices/lab_pin.sym} -740 710 0 0 {name=l73 lab=ND1}
N -780 780 -840 780 {}
C {devices/lab_pin.sym} -840 780 0 0 {name=l74 lab=NDL}
N -740 810 -740 850 {}
C {devices/lab_pin.sym} -740 850 0 0 {name=l75 lab=VSS}
N -740 780 -690 780 {}
C {devices/lab_pin.sym} -690 780 0 0 {name=l76 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 780 0 0 {name=MDANT
L=10
W=0.5
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -480 750 -480 710 {}
C {devices/lab_pin.sym} -480 710 0 0 {name=l77 lab=TRIP}
N -520 780 -580 780 {}
C {devices/lab_pin.sym} -580 780 0 0 {name=l78 lab=ND1}
N -480 810 -480 850 {}
C {devices/lab_pin.sym} -480 850 0 0 {name=l79 lab=VSS}
N -480 780 -430 780 {}
C {devices/lab_pin.sym} -430 780 0 0 {name=l80 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -500 780 0 0 {name=MDBNI
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -240 750 -240 710 {}
C {devices/lab_pin.sym} -240 710 0 0 {name=l81 lab=VDD}
N -280 780 -340 780 {}
C {devices/lab_pin.sym} -340 780 0 0 {name=l82 lab=PDN}
N -240 810 -240 850 {}
C {devices/lab_pin.sym} -240 850 0 0 {name=l83 lab=TRIP}
N -240 780 -190 780 {}
C {devices/lab_pin.sym} -190 780 0 0 {name=l84 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -260 780 0 0 {name=MDBPT
L=10
W=0.5
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -20 750 -20 710 {}
C {devices/lab_pin.sym} -20 710 0 0 {name=l85 lab=ND1}
N -60 780 -120 780 {}
C {devices/lab_pin.sym} -120 780 0 0 {name=l86 lab=RESETn}
N -20 810 -20 850 {}
C {devices/lab_pin.sym} -20 850 0 0 {name=l87 lab=VSS}
N -20 780 30 780 {}
C {devices/lab_pin.sym} 30 780 0 0 {name=l88 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -40 780 0 0 {name=MRLK
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {OUTPUT -- release NAND (MNAP1/MNAP2/MNAN1/MNAN2) + startup-assist keeper
(MAST) + push-pull driver (MOP/MON). RESETn releases only when the one-shot
has expired (TRIP) AND the deglitched rail is good (PGDG), so this cell --
not por_comparator -- owns the final release gate (DR-002).

A NAND, not a NOR, is what makes the below-floor startup assist work with
NO dedicated always-on device and NO static current: a NAND's pull-up is
two PARALLEL PMOS (MNAP1/MNAP2) against a SERIES NMOS stack (MNAN1/MNAN2),
so with both inputs at their dead-circuit default (low, per the TRIP
DETECTOR section above), RSTB is pulled to VDD by a leakage divider tens of
times in the PMOS pull-up's favour. RSTB = VDD turns MON fully on and holds
MOP fully off -- this IS the startup-assist pull-down this issue's own
title names, and it needs no separate always-on leg or current at all. A
NOR would land the other way and hand RESETn to leakage with the wrong
polarity. MAST closes the loop once RESETn is already low: it latches RSTB
high independently of TRIP/PGDG, so the assist survives even if
por_comparator drives POR_RAW high below its own operating floor. MOP/MON
are drawn at a 20:1 W/L ratio (carried unchanged from gf180) because the
valid-low floor as VDD -> 0 is a LEAKAGE-DIVIDER limit, not a drive-strength
one: a MOSFET's on/off ratio collapses toward 1 as VDD -> 0, so only
geometry -- not bias current -- can hold the floor down there.} -1400 950 0 0 0.3 0.3 {}
N -980 1010 -980 970 {}
C {devices/lab_pin.sym} -980 970 0 0 {name=l89 lab=VDD}
N -1020 1040 -1080 1040 {}
C {devices/lab_pin.sym} -1080 1040 0 0 {name=l90 lab=TRIP}
N -980 1070 -980 1110 {}
C {devices/lab_pin.sym} -980 1110 0 0 {name=l91 lab=RSTB}
N -980 1040 -930 1040 {}
C {devices/lab_pin.sym} -930 1040 0 0 {name=l92 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 1040 0 0 {name=MNAP1
L=0.5
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 1010 -740 970 {}
C {devices/lab_pin.sym} -740 970 0 0 {name=l93 lab=VDD}
N -780 1040 -840 1040 {}
C {devices/lab_pin.sym} -840 1040 0 0 {name=l94 lab=PGDG}
N -740 1070 -740 1110 {}
C {devices/lab_pin.sym} -740 1110 0 0 {name=l95 lab=RSTB}
N -740 1040 -690 1040 {}
C {devices/lab_pin.sym} -690 1040 0 0 {name=l96 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -760 1040 0 0 {name=MNAP2
L=0.5
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -480 1010 -480 970 {}
C {devices/lab_pin.sym} -480 970 0 0 {name=l97 lab=RSTB}
N -520 1040 -580 1040 {}
C {devices/lab_pin.sym} -580 1040 0 0 {name=l98 lab=TRIP}
N -480 1070 -480 1110 {}
C {devices/lab_pin.sym} -480 1110 0 0 {name=l99 lab=NNAND}
N -480 1040 -430 1040 {}
C {devices/lab_pin.sym} -430 1040 0 0 {name=l100 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -500 1040 0 0 {name=MNAN1
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -240 1010 -240 970 {}
C {devices/lab_pin.sym} -240 970 0 0 {name=l101 lab=NNAND}
N -280 1040 -340 1040 {}
C {devices/lab_pin.sym} -340 1040 0 0 {name=l102 lab=PGDG}
N -240 1070 -240 1110 {}
C {devices/lab_pin.sym} -240 1110 0 0 {name=l103 lab=VSS}
N -240 1040 -190 1040 {}
C {devices/lab_pin.sym} -190 1040 0 0 {name=l104 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -260 1040 0 0 {name=MNAN2
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -20 1010 -20 970 {}
C {devices/lab_pin.sym} -20 970 0 0 {name=l105 lab=VDD}
N -60 1040 -120 1040 {}
C {devices/lab_pin.sym} -120 1040 0 0 {name=l106 lab=RESETn}
N -20 1070 -20 1110 {}
C {devices/lab_pin.sym} -20 1110 0 0 {name=l107 lab=RSTB}
N -20 1040 30 1040 {}
C {devices/lab_pin.sym} 30 1040 0 0 {name=l108 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -40 1040 0 0 {name=MAST
L=10
W=0.5
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 240 1010 240 970 {}
C {devices/lab_pin.sym} 240 970 0 0 {name=l109 lab=VDD}
N 200 1040 140 1040 {}
C {devices/lab_pin.sym} 140 1040 0 0 {name=l110 lab=RSTB}
N 240 1070 240 1110 {}
C {devices/lab_pin.sym} 240 1110 0 0 {name=l111 lab=RESETn}
N 240 1040 290 1040 {}
C {devices/lab_pin.sym} 290 1040 0 0 {name=l112 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 220 1040 0 0 {name=MOP
L=1
W=1
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 480 1010 480 970 {}
C {devices/lab_pin.sym} 480 970 0 0 {name=l113 lab=RESETn}
N 440 1040 380 1040 {}
C {devices/lab_pin.sym} 380 1040 0 0 {name=l114 lab=RSTB}
N 480 1070 480 1110 {}
C {devices/lab_pin.sym} 480 1110 0 0 {name=l115 lab=VSS}
N 480 1040 530 1040 {}
C {devices/lab_pin.sym} 530 1040 0 0 {name=l116 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 460 1040 0 0 {name=MON
L=0.5
W=10
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {STARTUP-ASSIST NATIVE PULL-DOWN (MASSIST) -- an additional, independent
below-floor assist leg, gated directly from VDD/VSS with no dependency on
IBIAS, POR_RAW, or any node inside this cell's own bias/deglitch/trip
chain. porting-plan.md Sec1.2/Sec2.2/Sec2.6 (this repo's own porting plan,
issue #1) records that gf180's own DR-005 originally scoped the startup-
assist leg as "native/zero-Vt if available, else a minimally-biased
standard-Vt divider" -- gf180mcu's own native-device availability was
UNCONFIRMED at that authoring time, so gf180's own actual por_output_chain
ended up taking the "else" branch (the release-NAND leakage-divider
mechanism in the OUTPUT section above, entirely ordinary-Vt g5v0d10v5-
equivalent devices). sky130's near-zero-Vt devices are CONFIRMED available
(nfet_03v3_nvt, nfet_05v0_nvt) -- per porting-plan.md Sec1.2, "a strictly
better starting position, not a like-for-like swap" -- so this port adds
one, satisfying this issue's own device-mapping table.

DEVICE CHOICE (recorded inline per this issue -- porting-plan.md Sec2.6
defers the 03v3-vs-05v0 choice itself to a future characterization issue,
not resolved here): sky130_fd_pr__nfet_05v0_nvt, for two reasons found
while wiring this section, not just the 5V-class-match argument
porting-plan.md Sec2.6 already anticipated. First, it matches this
design's own 5V-class g5v0d10v5 device family (DR-001) rather than mixing
gate-oxide classes on the same 3.3 V-nominal rail. Second -- discovered
empirically against the installed PDK while sizing this device, not
assumed from naming convention -- sky130's native/near-zero-Vt devices are
FIXED-GEOMETRY library cells, not continuously-scalable primitives like the
g5v0d10v5 MOS or res_xhigh_po used everywhere else in this design: each
flavor ships only a small, discrete menu of pre-characterized (L, W)
combinations (ngspice's own automatic-binning model-card lookup rejects any
other pair with "could not find a valid modelname", confirmed empirically
against this repo's own installed sky130A PDK). `nfet_03v3_nvt`'s entire
menu is short-channel (L <= 0.8 um); `nfet_05v0_nvt`'s menu includes one
genuinely long-channel option (L = 25 um, W = 1 um) that `nfet_03v3_nvt`
has no equivalent of -- material to this leg's own weak-keeper intent (see
below), not just the gate-oxide-class argument alone.

MASSIST's gate is tied directly to VDD and its source to VSS, so it begins
conducting from the very first millivolt of VDD -- before IBIAS exists,
before MBD's mirror diode has any current to mirror, and independently of
whatever state the release-NAND leakage divider is in. It is drawn at the
longest-channel geometry sky130_fd_pr__nfet_05v0_nvt's own fixed-geometry
menu offers (L = 25 um, W = 1 um -- the device menu itself, not a free
choice, is what bounds how weak this leg can be drawn) so that once
RESETn is legitimately released, MOP's active drive overpowers it by a
wide margin -- the same weak-keeper-vs-strong-driver ratio argument MAST
already makes against the release NAND. Unlike MAST, MASSIST is NOT gated
off once released: it is a genuinely always-on leakage path by
construction (that is the point of a near-zero-Vt device -- it has no
meaningful off state to gate into), so it costs a small continuous static
current in the released state that this port has not yet characterized or
budgeted against a real por-iq figure. That trade-off -- and the
03v3-vs-05v0 choice itself -- is exactly the "genuinely new
characterization work" porting-plan.md Sec2.2/Sec2.6 already flags as
owned by a future issue, not resolved here; this port's own scope is the
mechanical topology
substitution CLAUDE.md calls for, not first characterization of a device
class gf180 never used.} -1400 1230 0 0 0.3 0.3 {}
N -980 1270 -980 1230 {}
C {devices/lab_pin.sym} -980 1230 0 0 {name=l117 lab=RESETn}
N -1020 1300 -1080 1300 {}
C {devices/lab_pin.sym} -1080 1300 0 0 {name=l118 lab=VDD}
N -980 1330 -980 1370 {}
C {devices/lab_pin.sym} -980 1370 0 0 {name=l119 lab=VSS}
N -980 1300 -930 1300 {}
C {devices/lab_pin.sym} -930 1300 0 0 {name=l120 lab=VSS}
C {sky130_fd_pr/nfet_05v0_nvt.sym} -1000 1300 0 0 {name=MASSIST
L=25
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
