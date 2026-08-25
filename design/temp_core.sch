v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {temp_core -- PTAT/CTAT temperature-sensing core (issue #7, sky130 port of gf180-temp-por)} -900 -1500 0 0 0.6 0.6 {}
T {Topology ported from gf180-temp-por's design/temp_core.sch (DR-005:\nDVBE/VBE bandgap-style core, deliberately left uncompensated -- the PTAT\nterm is published raw), per spec/porting-plan.md Sec1.1 and this repo's own\nDR-002 (architecture carryover). 8:1 emitter-area PNP pair (XQ1 :\nXQ8A..XQ8H) sets DVBE = (kT/q)*ln(8); the error amplifier forces V(NA) =\nV(NB) so the branch current is I = DVBE/R1 (PTAT), and the matched mirror\nleg XMP3/XMPC3 drops that same current through R2 (fixed leg) + R2TRIM\n(trim leg -- see the PTAT GAIN RESISTOR + TRIM NODE band below) into VSS,\ngiving V(PTAT) = ((R2+R2TRIM)/R1)*(kT/q)*ln(8) -- PTAT by construction and\nfree of R's absolute value and tempco, which cancel in the same-flavour\nres_xhigh_po ratio (matching bias_core's own R1/R2/RT choice, issue #6).\n\nDevice mapping onto sky130 per porting-plan.md Sec2.2 (issue #7):\n  nfet_03v3/pfet_03v3      -> sky130_fd_pr__nfet_g5v0d10v5/pfet_g5v0d10v5\n  pnp_10p00x10p00          -> sky130_fd_pr__pnp_05v5_W3p40L3p40 (eight\n                              separate X-instances, not one m=8 instance --\n                              same sky130 PNP-model quirk bias_core's own\n                              header documents: mult scales only the\n                              mismatch terms, not Is)\n  ppolyf_u                 -> sky130_fd_pr__res_xhigh_po\n  cap_mim_2f0_m3m4_noshield -> sky130_fd_pr__cap_mim_m3_1\n\nSizing is a MECHANICAL, FIRST-ORDER PORT, same convention as bias_core\n(issue #6): every W/L carries over unchanged from gf180-temp-por's ratified\ntemp_core (same drawn geometry, bare micron numbers per this repo's own\nsky130 unit convention -- see design/README.md), so ratio-derived\nquantities (R2/R1, the 8:1 PNP emitter-area ratio, the mirror ratios) are\nexactly preserved, but the resulting PTAT slope, CTAT intercept and startup\nmargins have NOT been simulated or characterized against sky130 models --\nno sky130 PNP/resistor/amplifier-offset characterization exists yet in this\nrepo (spec/porting-plan.md Sec2.5/Sec4 item 2). Do not treat any voltage,\nslope or current implied by this schematic as verified; re-sizing once\ncharacterization lands is expected follow-on work, not a defect in this\nport. Per spec/porting-plan.md Sec1.3: this exact topology, on gf180mcu\nitself, measured OUTSIDE its own accuracy targets under 3-sigma mismatch\n(DR-011-temp-accuracy-mismatch-not-met) -- carrying the topology here is\nnot a presumption it clears sky130's (not-yet-derived) accuracy target.\n\nInterface contract (unchanged in shape from gf180's temp_core, ported by\nissue #7):\n  VDD/VSS  3.3 V nominal supply pair on sky130 5V I/O-class devices\n           (g5v0d10v5), 2.97-3.63 V (DR-001), matching bias_core.\n  IBIAS    shared bias-mirror node from bias_core (issue #6). Convention\n           carried from gf180/bias_core: bias_core SOURCES current INTO\n           this pin; XMBD is the local mirror diode. Nothing here depends\n           on its absolute accuracy -- it sets only amplifier tail/cascode\n           bias, never the PTAT current, which is DVBE/R1. Per DR-010\n           (carried from gf180): this pin is HIGH-Z when the cell is\n           disabled and NEVER clamped -- the net is shared with\n           por_comparator and por_output_chain (issues #8/#9), which need\n           it in exactly the state EN is low.\n  EN       enable, active high. Intended to be driven from RESETn at the\n           top level once temp_por_top (issue #10) exists, so the sensor\n           is enabled only after POR releases (DR-002 startup ordering) --\n           wired here per issue #7's own guidance even though the driving\n           RESETn signal is not yet a committed cell (por_output_chain,\n           issue #9). EN low: mirror gate PG pulled to VDD, local bias\n           node NBG pulled to VSS, PTAT and CTAT pulled to VSS, and the\n           IBIAS pin left high-Z (DR-010).\n  PTAT     analog PTAT output (DR-002). This cell has NO output buffer\n           (gf180's DR-005 puts that in a separate temp_buffer cell, not\n           yet ported here) -- a consuming testbench must specify a\n           high-impedance load.\n  CTAT     analog CTAT output (DR-002) = VEB of XQ1, the same single\n           diode-connected vertical PNP that forms the 1x leg of the\n           ratio pair, tapped through XRISO so pad capacitance never\n           sees the loop node.} -900 -1440 0 0 0.3 0.3 {}
N -1100 -1000 -1040 -1000 {}
C {devices/iopin.sym} -1100 -1000 0 0 {name=p_vdd lab=VDD}
N -1100 -940 -1040 -940 {}
C {devices/iopin.sym} -1100 -940 0 0 {name=p_vss lab=VSS}
N -1100 -880 -1040 -880 {}
C {devices/ipin.sym} -1100 -880 0 0 {name=p_ibias lab=IBIAS}
N -1100 -820 -1040 -820 {}
C {devices/ipin.sym} -1100 -820 0 0 {name=p_en lab=EN}
N -1100 -760 -1040 -760 {}
C {devices/opin.sym} -1100 -760 0 0 {name=p_ptat lab=PTAT}
N -1100 -700 -1040 -700 {}
C {devices/opin.sym} -1100 -700 0 0 {name=p_ctat lab=CTAT}
T {BIAS + ENABLE  --  local mirror off IBIAS; every branch dies with EN low (mechanical port of gf180's temp_core, issue #7).} -1100 -120 0 0 0.4 0.4 {}
N -980 -30 -980 -70 {}
C {devices/lab_pin.sym} -980 -70 0 0 {name=l1 lab=IBIAS}
N -1020 0 -1080 0 {}
C {devices/lab_pin.sym} -1080 0 0 0 {name=l2 lab=NBG}
N -980 30 -980 70 {}
C {devices/lab_pin.sym} -980 70 0 0 {name=l3 lab=VSS}
N -980 0 -930 0 {}
C {devices/lab_pin.sym} -930 0 0 0 {name=l4 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -1000 0 0 0 {name=MBD
L=2
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -740 -30 -740 -70 {}
C {devices/lab_pin.sym} -740 -70 0 0 {name=l5 lab=IBIAS}
N -780 0 -840 0 {}
C {devices/lab_pin.sym} -840 0 0 0 {name=l6 lab=EN}
N -740 30 -740 70 {}
C {devices/lab_pin.sym} -740 70 0 0 {name=l7 lab=NBG}
N -740 0 -690 0 {}
C {devices/lab_pin.sym} -690 0 0 0 {name=l8 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 0 0 0 {name=MPASS
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -500 -30 -500 -70 {}
C {devices/lab_pin.sym} -500 -70 0 0 {name=l9 lab=NBG}
N -540 0 -600 0 {}
C {devices/lab_pin.sym} -600 0 0 0 {name=l10 lab=ENB}
N -500 30 -500 70 {}
C {devices/lab_pin.sym} -500 70 0 0 {name=l11 lab=VSS}
N -500 0 -450 0 {}
C {devices/lab_pin.sym} -450 0 0 0 {name=l12 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -520 0 0 0 {name=MDNB
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {NO disabled-state clamp on the IBIAS pin -- DR-010, carried from gf180's\nown temp_core (mechanical port, issue #7). IBIAS is a SHARED net\n(bias_core sources it; temp_core, por_comparator and por_output_chain all\nconsume it) and EN is intended to be RESETn once temp_por_top exists\n(issue #10) -- a clamp here would short the shared node to VSS for the\nentire pre-POR window, the exact bias-vs-POR lockup gf180's own DR-010\nmeasured and rejected. MPASS (off) and MDNB (NBG -> VSS) already turn the\nlocal mirror off, so the pin is high-Z with EN low and nothing else is\nneeded. A single-cell testbench that forces an ideal current into this\npin must terminate it itself. Not yet re-verified on sky130 models (issue\n#7) -- gf180's own measurement (sim/bias-core-ibias-sharing/) does not\ncarry numerically, only the DR-010 requirement it establishes does.} 1060 -180 0 0 0.4 0.4 {}
N -260 -30 -260 -70 {}
C {devices/lab_pin.sym} -260 -70 0 0 {name=l17 lab=PB}
N -300 0 -360 0 {}
C {devices/lab_pin.sym} -360 0 0 0 {name=l18 lab=NBG}
N -260 30 -260 70 {}
C {devices/lab_pin.sym} -260 70 0 0 {name=l19 lab=VSS}
N -260 0 -210 0 {}
C {devices/lab_pin.sym} -210 0 0 0 {name=l20 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -280 0 0 0 {name=MBN1
L=2
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -20 30 -20 70 {}
C {devices/lab_pin.sym} -20 70 0 0 {name=l21 lab=PB}
N -60 0 -120 0 {}
C {devices/lab_pin.sym} -120 0 0 0 {name=l22 lab=PB}
N -20 -30 -20 -70 {}
C {devices/lab_pin.sym} -20 -70 0 0 {name=l23 lab=VDD}
N -20 0 30 0 {}
C {devices/lab_pin.sym} 30 0 0 0 {name=l24 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -40 0 0 0 {name=MBP
L=4
W=10
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 220 -30 220 -70 {}
C {devices/lab_pin.sym} 220 -70 0 0 {name=l25 lab=PCAS}
N 180 0 120 0 {}
C {devices/lab_pin.sym} 120 0 0 0 {name=l26 lab=NBG}
N 220 30 220 70 {}
C {devices/lab_pin.sym} 220 70 0 0 {name=l27 lab=VSS}
N 220 0 270 0 {}
C {devices/lab_pin.sym} 270 0 0 0 {name=l28 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 0 0 0 {name=MBN2
L=2
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 460 30 460 70 {}
C {devices/lab_pin.sym} 460 70 0 0 {name=l29 lab=PCAS}
N 420 0 360 0 {}
C {devices/lab_pin.sym} 360 0 0 0 {name=l30 lab=PCAS}
N 460 -30 460 -70 {}
C {devices/lab_pin.sym} 460 -70 0 0 {name=l31 lab=VDD}
N 460 0 510 0 {}
C {devices/lab_pin.sym} 510 0 0 0 {name=l32 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 440 0 0 0 {name=MCB
L=8
W=1
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 700 30 700 70 {}
C {devices/lab_pin.sym} 700 70 0 0 {name=l33 lab=ENB}
N 660 0 600 0 {}
C {devices/lab_pin.sym} 600 0 0 0 {name=l34 lab=EN}
N 700 -30 700 -70 {}
C {devices/lab_pin.sym} 700 -70 0 0 {name=l35 lab=VDD}
N 700 0 750 0 {}
C {devices/lab_pin.sym} 750 0 0 0 {name=l36 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 680 0 0 0 {name=MINVP
L=0.5
W=2
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 940 -30 940 -70 {}
C {devices/lab_pin.sym} 940 -70 0 0 {name=l37 lab=ENB}
N 900 0 840 0 {}
C {devices/lab_pin.sym} 840 0 0 0 {name=l38 lab=EN}
N 940 30 940 70 {}
C {devices/lab_pin.sym} 940 70 0 0 {name=l39 lab=VSS}
N 940 0 990 0 {}
C {devices/lab_pin.sym} 990 0 0 0 {name=l40 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 920 0 0 0 {name=MINVN
L=0.5
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {ERROR AMPLIFIER  --  PMOS pair + NMOS mirror load, NMOS common-source 2nd\nstage, mechanically ported from gf180's temp_core (issue #7). XMS2N is a\ncurrent-density copy of XML1, so the systematic input offset is\nstructurally near zero rather than a residual -- the same amplifier\nstructure bias_core (issue #6) reuses. gf180's own measured offset\n(<10 uV) does not carry to sky130 numerically; not yet simulated here.} -1100 120 0 0 0.4 0.4 {}
N -980 290 -980 330 {}
C {devices/lab_pin.sym} -980 330 0 0 {name=l41 lab=NT}
N -1020 260 -1080 260 {}
C {devices/lab_pin.sym} -1080 260 0 0 {name=l42 lab=PB}
N -980 230 -980 190 {}
C {devices/lab_pin.sym} -980 190 0 0 {name=l43 lab=VDD}
N -980 260 -930 260 {}
C {devices/lab_pin.sym} -930 260 0 0 {name=l44 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 260 0 0 {name=MT
L=4
W=20
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 290 -740 330 {}
C {devices/lab_pin.sym} -740 330 0 0 {name=l45 lab=N1}
N -780 260 -840 260 {}
C {devices/lab_pin.sym} -840 260 0 0 {name=l46 lab=NA}
N -740 230 -740 190 {}
C {devices/lab_pin.sym} -740 190 0 0 {name=l47 lab=NT}
N -740 260 -690 260 {}
C {devices/lab_pin.sym} -690 260 0 0 {name=l48 lab=NT}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -760 260 0 0 {name=MI1
L=4
W=32
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -500 290 -500 330 {}
C {devices/lab_pin.sym} -500 330 0 0 {name=l49 lab=N2}
N -540 260 -600 260 {}
C {devices/lab_pin.sym} -600 260 0 0 {name=l50 lab=NB}
N -500 230 -500 190 {}
C {devices/lab_pin.sym} -500 190 0 0 {name=l51 lab=NT}
N -500 260 -450 260 {}
C {devices/lab_pin.sym} -450 260 0 0 {name=l52 lab=NT}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -520 260 0 0 {name=MI2
L=4
W=32
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -260 230 -260 190 {}
C {devices/lab_pin.sym} -260 190 0 0 {name=l53 lab=N1}
N -300 260 -360 260 {}
C {devices/lab_pin.sym} -360 260 0 0 {name=l54 lab=N1}
N -260 290 -260 330 {}
C {devices/lab_pin.sym} -260 330 0 0 {name=l55 lab=VSS}
N -260 260 -210 260 {}
C {devices/lab_pin.sym} -210 260 0 0 {name=l56 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -280 260 0 0 {name=ML1
L=8
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -20 230 -20 190 {}
C {devices/lab_pin.sym} -20 190 0 0 {name=l57 lab=N2}
N -60 260 -120 260 {}
C {devices/lab_pin.sym} -120 260 0 0 {name=l58 lab=N1}
N -20 290 -20 330 {}
C {devices/lab_pin.sym} -20 330 0 0 {name=l59 lab=VSS}
N -20 260 30 260 {}
C {devices/lab_pin.sym} 30 260 0 0 {name=l60 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -40 260 0 0 {name=ML2
L=8
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 220 230 220 190 {}
C {devices/lab_pin.sym} 220 190 0 0 {name=l61 lab=PG}
N 180 260 120 260 {}
C {devices/lab_pin.sym} 120 260 0 0 {name=l62 lab=N2}
N 220 290 220 330 {}
C {devices/lab_pin.sym} 220 330 0 0 {name=l63 lab=VSS}
N 220 260 270 260 {}
C {devices/lab_pin.sym} 270 260 0 0 {name=l64 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 260 0 0 {name=MS2N
L=8
W=8
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 460 290 460 330 {}
C {devices/lab_pin.sym} 460 330 0 0 {name=l65 lab=PG}
N 420 260 360 260 {}
C {devices/lab_pin.sym} 360 260 0 0 {name=l66 lab=PB}
N 460 230 460 190 {}
C {devices/lab_pin.sym} 460 190 0 0 {name=l67 lab=VDD}
N 460 260 510 260 {}
C {devices/lab_pin.sym} 510 260 0 0 {name=l68 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 440 260 0 0 {name=MS2P
L=4
W=10
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 680 230 680 190 {}
C {devices/lab_pin.sym} 680 190 0 0 {name=l69 lab=PG}
N 680 290 680 330 {}
C {devices/lab_pin.sym} 680 330 0 0 {name=l70 lab=NZ}
C {sky130_fd_pr/cap_mim_m3_1.sym} 680 260 0 0 {name=CC
W=12
L=12
model=cap_mim_m3_1
spiceprefix=X
MF=1}
N 920 290 920 330 {}
C {devices/lab_pin.sym} 920 330 0 0 {name=l71 lab=NZ}
N 920 230 920 190 {}
C {devices/lab_pin.sym} 920 190 0 0 {name=l72 lab=N2}
N 900 260 840 260 {}
C {devices/lab_pin.sym} 840 260 0 0 {name=l73 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} 920 260 0 0 {name=RZ
W=2
L=1000
model=res_xhigh_po
spiceprefix=X
mult=1}
T {CASCODED PMOS MIRROR  --  three matched legs, mechanically ported from\ngf180's temp_core (issue #7). XMP1/XMP2 see identical VGS *and* identical\nVDS (the loop forces V(NA) = V(NB)), so the 1:1 ratio that sets DVBE is\nexact by construction; the cascode keeps leg 3 on ratio despite its higher\ndrain swing. gf180's own measured leg current (~2.5 uA) does not carry to\nsky130 numerically; not yet simulated here.} -1100 380 0 0 0.4 0.4 {}
N -980 550 -980 590 {}
C {devices/lab_pin.sym} -980 590 0 0 {name=l74 lab=M1D}
N -1020 520 -1080 520 {}
C {devices/lab_pin.sym} -1080 520 0 0 {name=l75 lab=PG}
N -980 490 -980 450 {}
C {devices/lab_pin.sym} -980 450 0 0 {name=l76 lab=VDD}
N -980 520 -930 520 {}
C {devices/lab_pin.sym} -930 520 0 0 {name=l77 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 520 0 0 {name=MP1
L=4
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 550 -740 590 {}
C {devices/lab_pin.sym} -740 590 0 0 {name=l78 lab=NA}
N -780 520 -840 520 {}
C {devices/lab_pin.sym} -840 520 0 0 {name=l79 lab=PCAS}
N -740 490 -740 450 {}
C {devices/lab_pin.sym} -740 450 0 0 {name=l80 lab=M1D}
N -740 520 -690 520 {}
C {devices/lab_pin.sym} -690 520 0 0 {name=l81 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -760 520 0 0 {name=MPC1
L=1
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -500 550 -500 590 {}
C {devices/lab_pin.sym} -500 590 0 0 {name=l82 lab=M2D}
N -540 520 -600 520 {}
C {devices/lab_pin.sym} -600 520 0 0 {name=l83 lab=PG}
N -500 490 -500 450 {}
C {devices/lab_pin.sym} -500 450 0 0 {name=l84 lab=VDD}
N -500 520 -450 520 {}
C {devices/lab_pin.sym} -450 520 0 0 {name=l85 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -520 520 0 0 {name=MP2
L=4
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -260 550 -260 590 {}
C {devices/lab_pin.sym} -260 590 0 0 {name=l86 lab=NB}
N -300 520 -360 520 {}
C {devices/lab_pin.sym} -360 520 0 0 {name=l87 lab=PCAS}
N -260 490 -260 450 {}
C {devices/lab_pin.sym} -260 450 0 0 {name=l88 lab=M2D}
N -260 520 -210 520 {}
C {devices/lab_pin.sym} -210 520 0 0 {name=l89 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -280 520 0 0 {name=MPC2
L=1
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -20 550 -20 590 {}
C {devices/lab_pin.sym} -20 590 0 0 {name=l90 lab=M3D}
N -60 520 -120 520 {}
C {devices/lab_pin.sym} -120 520 0 0 {name=l91 lab=PG}
N -20 490 -20 450 {}
C {devices/lab_pin.sym} -20 450 0 0 {name=l92 lab=VDD}
N -20 520 30 520 {}
C {devices/lab_pin.sym} 30 520 0 0 {name=l93 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -40 520 0 0 {name=MP3
L=4
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 220 550 220 590 {}
C {devices/lab_pin.sym} 220 590 0 0 {name=l94 lab=PTAT}
N 180 520 120 520 {}
C {devices/lab_pin.sym} 120 520 0 0 {name=l95 lab=PCAS}
N 220 490 220 450 {}
C {devices/lab_pin.sym} 220 450 0 0 {name=l96 lab=M3D}
N 220 520 270 520 {}
C {devices/lab_pin.sym} 270 520 0 0 {name=l97 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 200 520 0 0 {name=MPC3
L=1
W=8
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
T {STARTUP KICK + ENABLE GATING  --  CURRENT-referenced dead-loop detector,\nnot a level detector, mechanically ported from gf180's temp_core (issue\n#7). XMSU4 is a 1:8 replica of the mirror leg (same gate PG); XMSU5 turns\nthat into a gate voltage NR and XMSU2 mirrors it against XMSU1's\nIBIAS-referenced pull-up on ND. Alive: XMSU2 wins, ND ~ 0, kick idle.\nDead: XMSU4 delivers nothing, ND rises to VDD, XMSU3 pulls PG down and the\nloop restarts. The comparison is loop current vs. IBIAS current -- both\nscale together over PVT -- which is why this survives corners where an\nabsolute-level detector cannot (gf180's own finding: a dead core's VBE at\n-40 C can be HIGHER than a live core's VBE at 125 C, so no fixed voltage\nthreshold on NA separates the two states across the rated range -- a\ndevice-physics argument, not a gf180mcu-specific number, so it carries).\ngf180's own specific currents/voltages do not carry; not yet simulated on\nsky130 models. See design/temp_core.md.} -1100 620 0 0 0.4 0.4 {}
N -980 810 -980 850 {}
C {devices/lab_pin.sym} -980 850 0 0 {name=l98 lab=ND}
N -1020 780 -1080 780 {}
C {devices/lab_pin.sym} -1080 780 0 0 {name=l99 lab=PB}
N -980 750 -980 710 {}
C {devices/lab_pin.sym} -980 710 0 0 {name=l100 lab=VDD}
N -980 780 -930 780 {}
C {devices/lab_pin.sym} -930 780 0 0 {name=l101 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -1000 780 0 0 {name=MSU1
L=8
W=1
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N -740 750 -740 710 {}
C {devices/lab_pin.sym} -740 710 0 0 {name=l102 lab=ND}
N -780 780 -840 780 {}
C {devices/lab_pin.sym} -840 780 0 0 {name=l103 lab=NR}
N -740 810 -740 850 {}
C {devices/lab_pin.sym} -740 850 0 0 {name=l104 lab=VSS}
N -740 780 -690 780 {}
C {devices/lab_pin.sym} -690 780 0 0 {name=l105 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -760 780 0 0 {name=MSU2
L=2
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -500 750 -500 710 {}
C {devices/lab_pin.sym} -500 710 0 0 {name=l106 lab=PG}
N -540 780 -600 780 {}
C {devices/lab_pin.sym} -600 780 0 0 {name=l107 lab=ND}
N -500 810 -500 850 {}
C {devices/lab_pin.sym} -500 850 0 0 {name=l108 lab=VSS}
N -500 780 -450 780 {}
C {devices/lab_pin.sym} -450 780 0 0 {name=l109 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -520 780 0 0 {name=MSU3
L=1
W=4
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -260 750 -260 710 {}
C {devices/lab_pin.sym} -260 710 0 0 {name=l110 lab=ND}
N -300 780 -360 780 {}
C {devices/lab_pin.sym} -360 780 0 0 {name=l111 lab=ENB}
N -260 810 -260 850 {}
C {devices/lab_pin.sym} -260 850 0 0 {name=l112 lab=VSS}
N -260 780 -210 780 {}
C {devices/lab_pin.sym} -210 780 0 0 {name=l113 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} -280 780 0 0 {name=MDND
L=0.5
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N -20 810 -20 850 {}
C {devices/lab_pin.sym} -20 850 0 0 {name=l114 lab=PG}
N -60 780 -120 780 {}
C {devices/lab_pin.sym} -120 780 0 0 {name=l115 lab=EN}
N -20 750 -20 710 {}
C {devices/lab_pin.sym} -20 710 0 0 {name=l116 lab=VDD}
N -20 780 30 780 {}
C {devices/lab_pin.sym} 30 780 0 0 {name=l117 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} -40 780 0 0 {name=MENPG
L=0.5
W=4
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 220 750 220 710 {}
C {devices/lab_pin.sym} 220 710 0 0 {name=l118 lab=PTAT}
N 180 780 120 780 {}
C {devices/lab_pin.sym} 120 780 0 0 {name=l119 lab=ENB}
N 220 810 220 850 {}
C {devices/lab_pin.sym} 220 850 0 0 {name=l120 lab=VSS}
N 220 780 270 780 {}
C {devices/lab_pin.sym} 270 780 0 0 {name=l121 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 200 780 0 0 {name=MENPT
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 460 750 460 710 {}
C {devices/lab_pin.sym} 460 710 0 0 {name=l122 lab=CTAT}
N 420 780 360 780 {}
C {devices/lab_pin.sym} 360 780 0 0 {name=l123 lab=ENB}
N 460 810 460 850 {}
C {devices/lab_pin.sym} 460 850 0 0 {name=l124 lab=VSS}
N 460 780 510 780 {}
C {devices/lab_pin.sym} 510 780 0 0 {name=l125 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 440 780 0 0 {name=MENCT
L=1
W=1
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 700 810 700 850 {}
C {devices/lab_pin.sym} 700 850 0 0 {name=l204 lab=NR}
N 660 780 600 780 {}
C {devices/lab_pin.sym} 600 780 0 0 {name=l205 lab=PG}
N 700 750 700 710 {}
C {devices/lab_pin.sym} 700 710 0 0 {name=l206 lab=VDD}
N 700 780 750 780 {}
C {devices/lab_pin.sym} 750 780 0 0 {name=l207 lab=VDD}
C {sky130_fd_pr/pfet_g5v0d10v5.sym} 680 780 0 0 {name=MSU4
L=4
W=1
nf=1
mult=1
model=pfet_g5v0d10v5
spiceprefix=X}
N 940 750 940 710 {}
C {devices/lab_pin.sym} 940 710 0 0 {name=l208 lab=NR}
N 900 780 840 780 {}
C {devices/lab_pin.sym} 840 780 0 0 {name=l209 lab=NR}
N 940 810 940 850 {}
C {devices/lab_pin.sym} 940 850 0 0 {name=l210 lab=VSS}
N 940 780 990 780 {}
C {devices/lab_pin.sym} 990 780 0 0 {name=l211 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 920 780 0 0 {name=MSU5
L=2
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 1180 750 1180 710 {}
C {devices/lab_pin.sym} 1180 710 0 0 {name=l212 lab=N2}
N 1140 780 1080 780 {}
C {devices/lab_pin.sym} 1080 780 0 0 {name=l213 lab=ENB}
N 1180 810 1180 850 {}
C {devices/lab_pin.sym} 1180 850 0 0 {name=l214 lab=VSS}
N 1180 780 1230 780 {}
C {devices/lab_pin.sym} 1230 780 0 0 {name=l215 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 1160 780 0 0 {name=MDN2
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
N 1420 750 1420 710 {}
C {devices/lab_pin.sym} 1420 710 0 0 {name=l216 lab=NT}
N 1380 780 1320 780 {}
C {devices/lab_pin.sym} 1320 780 0 0 {name=l217 lab=ENB}
N 1420 810 1420 850 {}
C {devices/lab_pin.sym} 1420 850 0 0 {name=l218 lab=VSS}
N 1420 780 1470 780 {}
C {devices/lab_pin.sym} 1470 780 0 0 {name=l219 lab=VSS}
C {sky130_fd_pr/nfet_g5v0d10v5.sym} 1400 780 0 0 {name=MDNT
L=1
W=2
nf=1
mult=1
model=nfet_g5v0d10v5
spiceprefix=X}
T {XMSU4 : 1/8 replica of the mirror leg        XMSU5 : replica-current diode (NR)\nXMDN2 / XMDNT : disable clamps, mechanically ported from gf180's temp_core\n(issue #7). With the tail off, NT and the stage-1 output N2 would\notherwise float high-impedance and risk opening an unwanted leakage path\nwhile the cell is supposed to be OFF -- gf180's own measured leakage path\n(sim/temp-core-startup/) does not carry to sky130 numerically, only the\ndisable-clamp requirement it motivates does.} 600 890 0 0 0.3 0.3 {}
T {SENSING CORE  --  8:1 vertical-PNP emitter-area ratio (pnp_05v5_W3p40L3p40\nunit cell, matching bias_core's own choice, issue #6). Eight unit cells in\nparallel, NOT one instance with mult=8: sky130's vertical-PNP model scales\nmult only into the mismatch terms, not Is -- the same quirk bias_core's\nown header documents (mechanical port of gf180's temp_core, issue #7). R1\nturns DVBE into the PTAT branch current; XQ1's VEB is also the CTAT\noutput.} -1100 880 0 0 0.4 0.4 {}
N -980 1070 -980 1110 {}
C {devices/lab_pin.sym} -980 1110 0 0 {name=l126 lab=VSS}
N -1020 1040 -1080 1040 {}
C {devices/lab_pin.sym} -1080 1040 0 0 {name=l127 lab=VSS}
N -980 1010 -980 970 {}
C {devices/lab_pin.sym} -980 970 0 0 {name=l128 lab=NA}
C {sky130_fd_pr/pnp_05v5.sym} -1000 1040 0 0 {name=Q1
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N -740 1070 -740 1110 {}
C {devices/lab_pin.sym} -740 1110 0 0 {name=l129 lab=VSS}
N -780 1040 -840 1040 {}
C {devices/lab_pin.sym} -840 1040 0 0 {name=l130 lab=VSS}
N -740 1010 -740 970 {}
C {devices/lab_pin.sym} -740 970 0 0 {name=l131 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} -760 1040 0 0 {name=Q8A
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N -500 1070 -500 1110 {}
C {devices/lab_pin.sym} -500 1110 0 0 {name=l132 lab=VSS}
N -540 1040 -600 1040 {}
C {devices/lab_pin.sym} -600 1040 0 0 {name=l133 lab=VSS}
N -500 1010 -500 970 {}
C {devices/lab_pin.sym} -500 970 0 0 {name=l134 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} -520 1040 0 0 {name=Q8B
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N -260 1070 -260 1110 {}
C {devices/lab_pin.sym} -260 1110 0 0 {name=l135 lab=VSS}
N -300 1040 -360 1040 {}
C {devices/lab_pin.sym} -360 1040 0 0 {name=l136 lab=VSS}
N -260 1010 -260 970 {}
C {devices/lab_pin.sym} -260 970 0 0 {name=l137 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} -280 1040 0 0 {name=Q8C
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N -20 1070 -20 1110 {}
C {devices/lab_pin.sym} -20 1110 0 0 {name=l138 lab=VSS}
N -60 1040 -120 1040 {}
C {devices/lab_pin.sym} -120 1040 0 0 {name=l139 lab=VSS}
N -20 1010 -20 970 {}
C {devices/lab_pin.sym} -20 970 0 0 {name=l140 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} -40 1040 0 0 {name=Q8D
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N 220 1070 220 1110 {}
C {devices/lab_pin.sym} 220 1110 0 0 {name=l141 lab=VSS}
N 180 1040 120 1040 {}
C {devices/lab_pin.sym} 120 1040 0 0 {name=l142 lab=VSS}
N 220 1010 220 970 {}
C {devices/lab_pin.sym} 220 970 0 0 {name=l143 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} 200 1040 0 0 {name=Q8E
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N 460 1070 460 1110 {}
C {devices/lab_pin.sym} 460 1110 0 0 {name=l144 lab=VSS}
N 420 1040 360 1040 {}
C {devices/lab_pin.sym} 360 1040 0 0 {name=l145 lab=VSS}
N 460 1010 460 970 {}
C {devices/lab_pin.sym} 460 970 0 0 {name=l146 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} 440 1040 0 0 {name=Q8F
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N 700 1070 700 1110 {}
C {devices/lab_pin.sym} 700 1110 0 0 {name=l147 lab=VSS}
N 660 1040 600 1040 {}
C {devices/lab_pin.sym} 600 1040 0 0 {name=l148 lab=VSS}
N 700 1010 700 970 {}
C {devices/lab_pin.sym} 700 970 0 0 {name=l149 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} 680 1040 0 0 {name=Q8G
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N 940 1070 940 1110 {}
C {devices/lab_pin.sym} 940 1110 0 0 {name=l150 lab=VSS}
N 900 1040 840 1040 {}
C {devices/lab_pin.sym} 840 1040 0 0 {name=l151 lab=VSS}
N 940 1010 940 970 {}
C {devices/lab_pin.sym} 940 970 0 0 {name=l152 lab=NC}
C {sky130_fd_pr/pnp_05v5.sym} 920 1040 0 0 {name=Q8H
model=pnp_05v5_W3p40L3p40
spiceprefix=X
m=1}
N 1160 1070 1160 1110 {}
C {devices/lab_pin.sym} 1160 1110 0 0 {name=l153 lab=NB}
N 1160 1010 1160 970 {}
C {devices/lab_pin.sym} 1160 970 0 0 {name=l154 lab=NC}
N 1140 1040 1080 1040 {}
C {devices/lab_pin.sym} 1080 1040 0 0 {name=l155 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} 1160 1040 0 0 {name=R1
W=2
L=119.47
model=res_xhigh_po
spiceprefix=X
mult=1}
T {PTAT GAIN RESISTOR + TRIM NODE -- gf180's temp_core carried a 6-bit\nbinary-weighted ladder (R2T5..R2T0) shorted segment-by-segment by\nmetal-strapped nfet switches (a metal-1 mask option, fuse/OTP-ready\nhook-up point for later -- see spec/porting-plan.md Sec1.1, \"trim\nmechanism ... a layout/process-portable mechanism, not a device\nthreshold\"). Per issue #7's own scope, this port represents only the ONE\nnet a layout-time metal strap would land on: R2 (fixed) + R2TRIM\n(shortable), PTAT-to-VSS, with node PTAT_TRIM exposed between them as the\nwave-1 single-point 25 C gain-trim tap. Shorting PTAT_TRIM to VSS in\nlayout removes R2TRIM from the path (raises the gain); leaving it open\n(as drawn here) keeps the untrimmed value. This gives the SAME total trim\nRANGE gf180's six segments summed to, as ONE segment instead of six --\nsizing the physical strap-ladder itself (bit count, granularity, the\nactual trim code) is layout scope, deferred to a future issue; no switch\ntransistors are instantiated here.\n\nR2 carries gf180's R2F value; R2TRIM carries the sum of gf180's six\nsegments (R2T5+R2T4+R2T3+R2T2+R2T1+R2T0 = 450.88), both mechanically\nported same-flavour (res_xhigh_po, matching R1) at the same drawn\ngeometry -- same first-order, not-yet-characterized caveat as R1 and\nevery other device in this cell. See design/temp_core.md.} -1100 1100 0 0 0.4 0.4 {}
N -1000 1330 -1000 1370 {}
C {devices/lab_pin.sym} -1000 1370 0 0 {name=l156 lab=PTAT}
N -1000 1270 -1000 1230 {}
C {devices/lab_pin.sym} -1000 1230 0 0 {name=l157 lab=PTAT_TRIM}
N -1020 1300 -1080 1300 {}
C {devices/lab_pin.sym} -1080 1300 0 0 {name=l158 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} -1000 1300 0 0 {name=R2
W=2
L=2652.6
model=res_xhigh_po
spiceprefix=X
mult=1}
N -760 1330 -760 1370 {}
C {devices/lab_pin.sym} -760 1370 0 0 {name=l159 lab=PTAT_TRIM}
N -760 1270 -760 1230 {}
C {devices/lab_pin.sym} -760 1230 0 0 {name=l160 lab=VSS}
N -780 1300 -840 1300 {}
C {devices/lab_pin.sym} -840 1300 0 0 {name=l161 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} -760 1300 0 0 {name=R2TRIM
W=2
L=450.88
model=res_xhigh_po
spiceprefix=X
mult=1}
N 920 1330 920 1370 {}
C {devices/lab_pin.sym} 920 1370 0 0 {name=l177 lab=NA}
N 920 1270 920 1230 {}
C {devices/lab_pin.sym} 920 1230 0 0 {name=l178 lab=CTAT}
N 900 1300 840 1300 {}
C {devices/lab_pin.sym} 840 1300 0 0 {name=l179 lab=VSS}
C {sky130_fd_pr/res_xhigh_po.sym} 920 1300 0 0 {name=RISO
W=2
L=111.05
model=res_xhigh_po
spiceprefix=X
mult=1}
T {XRISO: CTAT pad isolation} 840 1420 0 0 0.3 0.3 {}
