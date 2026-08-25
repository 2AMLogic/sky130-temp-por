v {xschem version=3.4.7 file_version=1.2}
G {}
K {}
V {}
S {}
E {}
T {temp_por_top -- temperature sensor + power-on-reset block, top level
(issue #10, sky130 port of gf180-temp-por)} -700 -840 0 0 0.6 0.6 {}
T {Assembly ported from gf180-temp-por's design/temp_por_top.sch and its
design/README.md hierarchy/net table, per spec/porting-plan.md Sec2.2 and
this repo's own DR-002 (architecture carryover) / DR-001 (device flavor).
Per CLAUDE.md the PDK is the variable, not the design: the instance list
and every internal net below carry over unchanged in shape from gf180's
own ratified top level.

Ratified pad interface (spec/porting-plan.md Sec2.8 reconciliation and this
repo's decision records; design/netlist.py --check asserts this exact port
list, in this exact order, against design/temp_por_top.sym):
  VDD, VSS  supply pair, 3.3 V nominal +/-10% (2.97-3.63 V steady state),
            sky130 5V I/O-class devices (g5v0d10v5)         -- DR-001
  PTAT      analog PTAT output                              -- DR-002
  CTAT      analog CTAT output                              -- DR-002
  RESETn    reset output, active low, push-pull             -- DR-002

No trim, config or programming pins and no digital temperature interface in
wave 1: the reset pulse is fixed (no oscillator/counter) and the sensor
interface is analog-only (spec/porting-plan.md Sec1.1, DR-002).

Hierarchy -- one cell per sibling sub-issue of #5, all four already ported:
  xbias  bias_core         shared bias / reference core      -- issue #6
  xtemp  temp_core         PTAT/CTAT sensing core            -- issue #7
  xcmp   por_comparator    threshold comparator + hysteresis -- issue #8
  xpor   por_output_chain  deglitch, one-shot, RESETn drive,
                           + POR startup-assist pull-down    -- issue #9

Internal nets (driver -> consumers), carried from gf180's own DR-005/DR-010
net contract via this repo's design/README.md:

  IBIAS    xbias -> xtemp, xcmp, xpor. ONE shared bias core, amortizing Iq
           and area (DR-005/DR-002). LIVENESS CONTRACT (gf180's DR-010,
           found the hard way there): a disabled consumer must present HIGH
           IMPEDANCE to this node and never clamp it, or the shared core is
           starved for the whole pre-POR window and the block locks up
           before POR can ever release. Preserved STRUCTURALLY here: the
           only consumer that has an enable at all is xtemp, and temp_core
           leaves IBIAS high-Z with EN low by construction (temp_core.md,
           EN row -- EN low parks PG at VDD and NBG at VSS locally, and
           does not touch the shared node); xcmp and xpor are unconditional
           consumers with no enable input. This level of the hierarchy adds
           NO switch, clamp, series device or extra load to IBIAS -- it is
           a plain shared net between one driver and three consumers.

  VREF     xbias -> xcmp. Absolute reference: the POR threshold is a
           voltage, not a rail fraction.

  BIAS_OK  xbias -> xcmp. Gates the authoritative release decision
           (DR-002 startup ordering); the comparator's decision is only
           trusted once the shared core is up.

  POR_RAW  xcmp -> xpor. Ownership split: hysteresis is the comparator's
           job, deglitch/pulse/drive are the output chain's. Active high =
           "rail is above VPOR and the decision is authoritative"
           (por_output_chain.sch's own polarity note).

  RESETn   xpor -> the top-level RESETn pad AND xtemp.EN. The sensor is
           enabled only after POR releases, which keeps temp_core out of
           the startup chicken-and-egg problem entirely (DR-002 startup
           ordering). Polarity works out with no inverter: RESETn high =
           reset released = EN high (active high, temp_core.md) = sensing
           enabled; RESETn low = in reset = sensor disabled and, per the
           contract above, IBIAS left high-Z.

This cell is ASSEMBLY ONLY -- it instantiates the four leaf cells and names
the nets between them, and adds no devices of its own. Every W/L, trip
point and timing element lives in a leaf cell, and every absolute value
there remains a first-order placeholder pending sky130 device
characterization (CLAUDE.md: thresholds do not port).} -700 -790 0 0 0.4 0.4 {}
N -700 -300 -640 -300 {}
C {devices/iopin.sym} -700 -300 0 0 {name=p_vdd lab=VDD}
N -700 -240 -640 -240 {}
C {devices/iopin.sym} -700 -240 0 0 {name=p_vss lab=VSS}
N -700 -180 -640 -180 {}
C {devices/opin.sym} -700 -180 0 0 {name=p_ptat lab=PTAT}
N -700 -120 -640 -120 {}
C {devices/opin.sym} -700 -120 0 0 {name=p_ctat lab=CTAT}
N -700 -60 -640 -60 {}
C {devices/opin.sym} -700 -60 0 0 {name=p_resetn lab=RESETn}
T {BIAS -- shared bias / reference core (issue #6). Drives IBIAS to all
three consumers, plus VREF and BIAS_OK to the comparator.} -300 -110 0 0 0.3 0.3 {}
C {bias_core.sym} -200 0 0 0 {name=xbias}
C {devices/lab_pin.sym} -300 -20 0 0 {name=l_bias_vdd lab=VDD}
C {devices/lab_pin.sym} -300 20 0 0 {name=l_bias_vss lab=VSS}
C {devices/lab_pin.sym} -100 -20 0 1 {name=l_bias_ibias lab=IBIAS}
C {devices/lab_pin.sym} -100 0 0 1 {name=l_bias_vref lab=VREF}
C {devices/lab_pin.sym} -100 20 0 1 {name=l_bias_ok lab=BIAS_OK}
T {POR THRESHOLD -- comparator + hysteresis (issue #8). Compares its own
divided-VDD tap against VREF, gated by BIAS_OK, and hands the raw
hysteretic decision to the output chain as POR_RAW.} -100 -130 0 0 0.3 0.3 {}
C {por_comparator.sym} 200 0 0 0 {name=xcmp}
C {devices/lab_pin.sym} 100 -40 0 0 {name=l_cmp_vdd lab=VDD}
C {devices/lab_pin.sym} 100 -20 0 0 {name=l_cmp_vss lab=VSS}
C {devices/lab_pin.sym} 100 0 0 0 {name=l_cmp_ibias lab=IBIAS}
C {devices/lab_pin.sym} 100 20 0 0 {name=l_cmp_vref lab=VREF}
C {devices/lab_pin.sym} 100 40 0 0 {name=l_cmp_ok lab=BIAS_OK}
C {devices/lab_pin.sym} 300 0 0 1 {name=l_cmp_raw lab=POR_RAW}
T {POR OUTPUT -- deglitch, one-shot, push-pull RESETn drive, and the
below-floor startup-assist pull-down (issue #9). RESETn is held asserted
from the first millivolt of VDD, independent of POR_RAW.} 400 -120 0 0 0.3 0.3 {}
C {por_output_chain.sym} 600 0 0 0 {name=xpor}
C {devices/lab_pin.sym} 500 -30 0 0 {name=l_por_vdd lab=VDD}
C {devices/lab_pin.sym} 500 -10 0 0 {name=l_por_vss lab=VSS}
C {devices/lab_pin.sym} 500 10 0 0 {name=l_por_ibias lab=IBIAS}
C {devices/lab_pin.sym} 500 30 0 0 {name=l_por_raw lab=POR_RAW}
C {devices/lab_pin.sym} 700 0 0 1 {name=l_por_resetn lab=RESETn}
T {TEMP SENSE -- PTAT/CTAT sensing core (issue #7). EN is driven directly
from RESETn: the sensor comes up only after POR releases (DR-002 startup
ordering), and with EN low it leaves the shared IBIAS node high-Z.} -100 160 0 0 0.3 0.3 {}
C {temp_core.sym} 200 250 0 0 {name=xtemp}
C {devices/lab_pin.sym} 100 220 0 0 {name=l_temp_vdd lab=VDD}
C {devices/lab_pin.sym} 100 240 0 0 {name=l_temp_vss lab=VSS}
C {devices/lab_pin.sym} 100 260 0 0 {name=l_temp_ibias lab=IBIAS}
C {devices/lab_pin.sym} 100 280 0 0 {name=l_temp_en lab=RESETn}
C {devices/lab_pin.sym} 300 230 0 1 {name=l_temp_ptat lab=PTAT}
C {devices/lab_pin.sym} 300 270 0 1 {name=l_temp_ctat lab=CTAT}
