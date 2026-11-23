import sys
R='/home/ubuntu/GitHub/sky130-temp-por/.loom/worktrees/issue-474/sim/por-comparator-thresholds'
sys.path.insert(0,R)
import threshold_extractor as tx
def load(p):
    L=open(p).read().split('\n'); i=L.index('Variables:')+1; names=[]
    while not L[i].startswith('Values:'):
        names.append(L[i].split()[1].lower()); i+=1
    vals=[]; i+=1; n=len(names); cur=[]
    for ln in L[i:]:
        t=ln.split()
        if not t: continue
        if len(t)==2 and len(cur)==0: cur=[float(t[1])]
        else: cur.append(float(t[0]))
        if len(cur)==n: vals.append(cur); cur=[]
    return {nm:[r[k] for r in vals] for k,nm in enumerate(names)}
for n in sys.argv[1:]:
    w=load(f'/tmp/i474/rep/{n}.raw')
    r=tx.analyze(w,'rise','fall')
    print(n, len(w['time']), r['verdict'], 'up=%.5f'%(r['up'].get('vdd_v') or -1), 'dn=%.5f'%(r['down'].get('vdd_v') or -1), 'hys=%s'%r.get('hysteresis_v'))
