import sys, json
from pathlib import Path
R='/home/ubuntu/GitHub/sky130-temp-por/.loom/worktrees/issue-474/sim/por-comparator-thresholds'
sys.path.insert(0,R)
import run_thresholds_campaign as rc
man=rc.sim_common.load_manifest(rc.MANIFEST)
pdk=rc.cr.resolve_pdk(rc.cr.load_pin())
proc,temp,off,seed=sys.argv[1],float(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])
mc=dict(rc.mc_effective(man)); mc['seed']=seed-off
v=man['variants']['real-bias-core']
d=Path(sys.argv[5]); d.mkdir(parents=True,exist_ok=True)
head=rc.tb_netlist_head(v,d,pdk)
(d/'netlist.spice').write_text(rc.build_netlist(head,v,mc['rate_v_per_s']))
req=rc.build_mc_request(proc,temp,off,mc,man,'local')
(d/'request.json').write_text(json.dumps(req,indent=2))
print(req['monte_carlo'])
