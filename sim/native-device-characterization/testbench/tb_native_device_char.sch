v {xschem version=3.4.7 file_version=1.2
* sky130-temp-por native-device characterization testbench (issue #27).
*
* Characterizes sky130's two near-zero-Vt (native) NMOS flavors -- the
* device class MASSIST in design/por_output_chain.sch is drawn from, and
* the nfet_03v3_nvt-vs-nfet_05v0_nvt choice spec/porting-plan.md Sec2.6
* defers to a characterization issue.  No cell of this design is
* instantiated here: the DUTs are bare PDK devices, so what this testbench
* measures is the DEVICE, not the block.
*
* Both flavors are BINNED, fixed-(L,W) library cells (see
* design/por_output_chain.md) -- ngspice's bin lookup rejects any (L,W)
* outside each flavor's own menu -- so the three DUT geometries below are
* menu entries read out of the pinned PDK's own corner files, not free
* sizing choices.
*
* Three galvanically independent sub-networks share only ground, so one
* deck (and therefore one ngspice invocation per PVT point) serves all
* four measurement classes:
*
*   A. VDDA, a fixed 'vsup' rail.  Per DUT geometry, two copies:
*      ON  -- gate AND drain at 'vsup', source/bulk at 0: exactly MASSIST's
*             always-on operating point, so its drain current IS the static
*             current MASSIST costs in the released state.
*      OFF -- gate at 0, drain at 'vsup': off-state/subthreshold leakage
*             for reference.
*      Both are read through their own 0 V ammeter source, so each device's
*      current is separated from the rail total.
*
*   B. VSWN, swept 0 -> 3.63 V by the manifest's second `dc` analysis, with
*      each DUT's gate tied to the swept rail (the MASSIST connection).
*      The rail voltage at which the drain current first crosses a stated
*      assist current is the minimum VDD at which assist conduction begins
*      -- i.e. the measurement behind por_output_chain.md's "conducts from
*      the very first millivolt" claim.
*
*   C. VDCN, a fixed 100 mV drain bias, with the gate on VGN swept
*      -1.0 -> +2.0 V by the manifest's first `dc` analysis.  Linear-region
*      constant-current Vth extraction: Vth is the VGS at which the drain
*      current crosses 100 nA * (W/L), the usual constant-current criterion,
*      evaluated per geometry because the criterion scales with W/L.
*
* Network A carries no swept source, so its currents are constant through
* both sweeps; the manifest reads them at the first point of the second
* sweep and guards that constancy (`ia_flat_n05l25`), which is what would
* break if these sub-networks were ever accidentally coupled.
*
* Connectivity is by net label (lab_pin on every device and source pin),
* no wires -- same convention as sim/bias-core-startup/'s testbench.
*
* Deliberately NOT in this schematic (the corner runner injects them):
*   - the .lib model corner include and .temp
*   - the numeric supply value: 'vsup' is a .param the runner sets
*   - the .control block with the two `dc` analyses and the measurements
}
G {}
K {}
V {}
S {}
E {}
T {native-device characterization testbench -- sky130 nfet_05v0_nvt / nfet_03v3_nvt
Three independent sub-networks (fixed 'vsup' rail / swept rail / fixed 100 mV drain
with swept gate) x three PDK bin geometries.  Every DUT drain is read through its
own 0 V ammeter source.  Corner (.lib), .temp and both `dc` analyses are injected
by sim/bin/corner-run.py from sim/native-device-characterization/experiment.json.} 100 -1800 0 0 0.4 0.4 {}
C {devices/vsource.sym} 200 -1700 0 0 {name=VA value='vsup' savecurrent=true}
C {devices/lab_pin.sym} 200 -1730 0 0 {name=p_va lab=VDDA}
C {devices/lab_pin.sym} 200 -1670 0 0 {name=m_va lab=0}
C {devices/vsource.sym} 500 -1700 0 0 {name=VSW value=0 savecurrent=true}
C {devices/lab_pin.sym} 500 -1730 0 0 {name=p_vsw lab=VSWN}
C {devices/lab_pin.sym} 500 -1670 0 0 {name=m_vsw lab=0}
C {devices/vsource.sym} 800 -1700 0 0 {name=VDC value=0.1 savecurrent=true}
C {devices/lab_pin.sym} 800 -1730 0 0 {name=p_vdc lab=VDCN}
C {devices/lab_pin.sym} 800 -1670 0 0 {name=m_vdc lab=0}
C {devices/vsource.sym} 1100 -1700 0 0 {name=VG value=0 savecurrent=true}
C {devices/lab_pin.sym} 1100 -1730 0 0 {name=p_vg lab=VGN}
C {devices/lab_pin.sym} 1100 -1670 0 0 {name=m_vg lab=0}
T {nfet_05v0_nvt bin 003 (W=1, L=25) -- the bin MASSIST is drawn at} 80 -1470 0 0 0.25 0.25 {}
C {devices/vsource.sym} 320 -1420 0 0 {name=VON_N05L25 value=0 savecurrent=true}
C {devices/lab_pin.sym} 320 -1450 0 0 {name=p_von_n05l25 lab=VDDA}
C {devices/lab_pin.sym} 320 -1390 0 0 {name=m_von_n05l25 lab=DON_N05L25}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 300 -1300 0 0 {name=MON_N05L25
L=25
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 320 -1330 0 0 {name=d_von_n05l25 lab=DON_N05L25}
C {devices/lab_pin.sym} 280 -1300 0 0 {name=g_von_n05l25 lab=VDDA}
C {devices/lab_pin.sym} 320 -1270 0 0 {name=s_von_n05l25 lab=0}
C {devices/lab_pin.sym} 320 -1300 0 0 {name=b_von_n05l25 lab=0}
T {ON: MASSIST condition: VGS = VDS = 'vsup'} 240 -1230 0 0 0.2 0.2 {}
C {devices/vsource.sym} 720 -1420 0 0 {name=VOFF_N05L25 value=0 savecurrent=true}
C {devices/lab_pin.sym} 720 -1450 0 0 {name=p_voff_n05l25 lab=VDDA}
C {devices/lab_pin.sym} 720 -1390 0 0 {name=m_voff_n05l25 lab=DOFF_N05L25}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 700 -1300 0 0 {name=MOFF_N05L25
L=25
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 720 -1330 0 0 {name=d_voff_n05l25 lab=DOFF_N05L25}
C {devices/lab_pin.sym} 680 -1300 0 0 {name=g_voff_n05l25 lab=0}
C {devices/lab_pin.sym} 720 -1270 0 0 {name=s_voff_n05l25 lab=0}
C {devices/lab_pin.sym} 720 -1300 0 0 {name=b_voff_n05l25 lab=0}
T {OFF: off state: VGS = 0, VDS = 'vsup'} 640 -1230 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1120 -1420 0 0 {name=VSWD_N05L25 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1120 -1450 0 0 {name=p_vswd_n05l25 lab=VSWN}
C {devices/lab_pin.sym} 1120 -1390 0 0 {name=m_vswd_n05l25 lab=DSWD_N05L25}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 1100 -1300 0 0 {name=MSWD_N05L25
L=25
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1120 -1330 0 0 {name=d_vswd_n05l25 lab=DSWD_N05L25}
C {devices/lab_pin.sym} 1080 -1300 0 0 {name=g_vswd_n05l25 lab=VSWN}
C {devices/lab_pin.sym} 1120 -1270 0 0 {name=s_vswd_n05l25 lab=0}
C {devices/lab_pin.sym} 1120 -1300 0 0 {name=b_vswd_n05l25 lab=0}
T {SWD: assist-onset sweep: gate tied to the swept rail} 1040 -1230 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1520 -1420 0 0 {name=VVT_N05L25 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1520 -1450 0 0 {name=p_vvt_n05l25 lab=VDCN}
C {devices/lab_pin.sym} 1520 -1390 0 0 {name=m_vvt_n05l25 lab=DVT_N05L25}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 1500 -1300 0 0 {name=MVT_N05L25
L=25
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1520 -1330 0 0 {name=d_vvt_n05l25 lab=DVT_N05L25}
C {devices/lab_pin.sym} 1480 -1300 0 0 {name=g_vvt_n05l25 lab=VGN}
C {devices/lab_pin.sym} 1520 -1270 0 0 {name=s_vvt_n05l25 lab=0}
C {devices/lab_pin.sym} 1520 -1300 0 0 {name=b_vvt_n05l25 lab=0}
T {VT: Vth extraction: VDS = 100 mV, gate swept} 1440 -1230 0 0 0.2 0.2 {}
T {nfet_05v0_nvt bin 006 (W=1, L=8)  -- next-longest 05v0_nvt bin} 80 -1170 0 0 0.25 0.25 {}
C {devices/vsource.sym} 320 -1120 0 0 {name=VON_N05L8 value=0 savecurrent=true}
C {devices/lab_pin.sym} 320 -1150 0 0 {name=p_von_n05l8 lab=VDDA}
C {devices/lab_pin.sym} 320 -1090 0 0 {name=m_von_n05l8 lab=DON_N05L8}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 300 -1000 0 0 {name=MON_N05L8
L=8
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 320 -1030 0 0 {name=d_von_n05l8 lab=DON_N05L8}
C {devices/lab_pin.sym} 280 -1000 0 0 {name=g_von_n05l8 lab=VDDA}
C {devices/lab_pin.sym} 320 -970 0 0 {name=s_von_n05l8 lab=0}
C {devices/lab_pin.sym} 320 -1000 0 0 {name=b_von_n05l8 lab=0}
T {ON: MASSIST condition: VGS = VDS = 'vsup'} 240 -930 0 0 0.2 0.2 {}
C {devices/vsource.sym} 720 -1120 0 0 {name=VOFF_N05L8 value=0 savecurrent=true}
C {devices/lab_pin.sym} 720 -1150 0 0 {name=p_voff_n05l8 lab=VDDA}
C {devices/lab_pin.sym} 720 -1090 0 0 {name=m_voff_n05l8 lab=DOFF_N05L8}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 700 -1000 0 0 {name=MOFF_N05L8
L=8
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 720 -1030 0 0 {name=d_voff_n05l8 lab=DOFF_N05L8}
C {devices/lab_pin.sym} 680 -1000 0 0 {name=g_voff_n05l8 lab=0}
C {devices/lab_pin.sym} 720 -970 0 0 {name=s_voff_n05l8 lab=0}
C {devices/lab_pin.sym} 720 -1000 0 0 {name=b_voff_n05l8 lab=0}
T {OFF: off state: VGS = 0, VDS = 'vsup'} 640 -930 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1120 -1120 0 0 {name=VSWD_N05L8 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1120 -1150 0 0 {name=p_vswd_n05l8 lab=VSWN}
C {devices/lab_pin.sym} 1120 -1090 0 0 {name=m_vswd_n05l8 lab=DSWD_N05L8}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 1100 -1000 0 0 {name=MSWD_N05L8
L=8
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1120 -1030 0 0 {name=d_vswd_n05l8 lab=DSWD_N05L8}
C {devices/lab_pin.sym} 1080 -1000 0 0 {name=g_vswd_n05l8 lab=VSWN}
C {devices/lab_pin.sym} 1120 -970 0 0 {name=s_vswd_n05l8 lab=0}
C {devices/lab_pin.sym} 1120 -1000 0 0 {name=b_vswd_n05l8 lab=0}
T {SWD: assist-onset sweep: gate tied to the swept rail} 1040 -930 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1520 -1120 0 0 {name=VVT_N05L8 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1520 -1150 0 0 {name=p_vvt_n05l8 lab=VDCN}
C {devices/lab_pin.sym} 1520 -1090 0 0 {name=m_vvt_n05l8 lab=DVT_N05L8}
C {sky130_fd_pr/nfet_05v0_nvt.sym} 1500 -1000 0 0 {name=MVT_N05L8
L=8
W=1
nf=1
mult=1
model=nfet_05v0_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1520 -1030 0 0 {name=d_vvt_n05l8 lab=DVT_N05L8}
C {devices/lab_pin.sym} 1480 -1000 0 0 {name=g_vvt_n05l8 lab=VGN}
C {devices/lab_pin.sym} 1520 -970 0 0 {name=s_vvt_n05l8 lab=0}
C {devices/lab_pin.sym} 1520 -1000 0 0 {name=b_vvt_n05l8 lab=0}
T {VT: Vth extraction: VDS = 100 mV, gate swept} 1440 -930 0 0 0.2 0.2 {}
T {nfet_03v3_nvt bin 006 (W=0.42, L=0.8) -- longest-channel bin that flavor offers} 80 -870 0 0 0.25 0.25 {}
C {devices/vsource.sym} 320 -820 0 0 {name=VON_N03L08 value=0 savecurrent=true}
C {devices/lab_pin.sym} 320 -850 0 0 {name=p_von_n03l08 lab=VDDA}
C {devices/lab_pin.sym} 320 -790 0 0 {name=m_von_n03l08 lab=DON_N03L08}
C {sky130_fd_pr/nfet_03v3_nvt.sym} 300 -700 0 0 {name=MON_N03L08
L=0.8
W=0.42
nf=1
mult=1
model=nfet_03v3_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 320 -730 0 0 {name=d_von_n03l08 lab=DON_N03L08}
C {devices/lab_pin.sym} 280 -700 0 0 {name=g_von_n03l08 lab=VDDA}
C {devices/lab_pin.sym} 320 -670 0 0 {name=s_von_n03l08 lab=0}
C {devices/lab_pin.sym} 320 -700 0 0 {name=b_von_n03l08 lab=0}
T {ON: MASSIST condition: VGS = VDS = 'vsup'} 240 -630 0 0 0.2 0.2 {}
C {devices/vsource.sym} 720 -820 0 0 {name=VOFF_N03L08 value=0 savecurrent=true}
C {devices/lab_pin.sym} 720 -850 0 0 {name=p_voff_n03l08 lab=VDDA}
C {devices/lab_pin.sym} 720 -790 0 0 {name=m_voff_n03l08 lab=DOFF_N03L08}
C {sky130_fd_pr/nfet_03v3_nvt.sym} 700 -700 0 0 {name=MOFF_N03L08
L=0.8
W=0.42
nf=1
mult=1
model=nfet_03v3_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 720 -730 0 0 {name=d_voff_n03l08 lab=DOFF_N03L08}
C {devices/lab_pin.sym} 680 -700 0 0 {name=g_voff_n03l08 lab=0}
C {devices/lab_pin.sym} 720 -670 0 0 {name=s_voff_n03l08 lab=0}
C {devices/lab_pin.sym} 720 -700 0 0 {name=b_voff_n03l08 lab=0}
T {OFF: off state: VGS = 0, VDS = 'vsup'} 640 -630 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1120 -820 0 0 {name=VSWD_N03L08 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1120 -850 0 0 {name=p_vswd_n03l08 lab=VSWN}
C {devices/lab_pin.sym} 1120 -790 0 0 {name=m_vswd_n03l08 lab=DSWD_N03L08}
C {sky130_fd_pr/nfet_03v3_nvt.sym} 1100 -700 0 0 {name=MSWD_N03L08
L=0.8
W=0.42
nf=1
mult=1
model=nfet_03v3_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1120 -730 0 0 {name=d_vswd_n03l08 lab=DSWD_N03L08}
C {devices/lab_pin.sym} 1080 -700 0 0 {name=g_vswd_n03l08 lab=VSWN}
C {devices/lab_pin.sym} 1120 -670 0 0 {name=s_vswd_n03l08 lab=0}
C {devices/lab_pin.sym} 1120 -700 0 0 {name=b_vswd_n03l08 lab=0}
T {SWD: assist-onset sweep: gate tied to the swept rail} 1040 -630 0 0 0.2 0.2 {}
C {devices/vsource.sym} 1520 -820 0 0 {name=VVT_N03L08 value=0 savecurrent=true}
C {devices/lab_pin.sym} 1520 -850 0 0 {name=p_vvt_n03l08 lab=VDCN}
C {devices/lab_pin.sym} 1520 -790 0 0 {name=m_vvt_n03l08 lab=DVT_N03L08}
C {sky130_fd_pr/nfet_03v3_nvt.sym} 1500 -700 0 0 {name=MVT_N03L08
L=0.8
W=0.42
nf=1
mult=1
model=nfet_03v3_nvt
spiceprefix=X}
C {devices/lab_pin.sym} 1520 -730 0 0 {name=d_vvt_n03l08 lab=DVT_N03L08}
C {devices/lab_pin.sym} 1480 -700 0 0 {name=g_vvt_n03l08 lab=VGN}
C {devices/lab_pin.sym} 1520 -670 0 0 {name=s_vvt_n03l08 lab=0}
C {devices/lab_pin.sym} 1520 -700 0 0 {name=b_vvt_n03l08 lab=0}
T {VT: Vth extraction: VDS = 100 mV, gate swept} 1440 -630 0 0 0.2 0.2 {}
