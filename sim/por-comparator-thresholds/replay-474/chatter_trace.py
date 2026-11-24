import sys, json
from pathlib import Path
R=str(Path(__file__).resolve().parents[1])
sys.path.insert(0,R); sys.path.insert(0,R+'/../bin')
import sim_common, threshold_extractor as tx
from pathlib import Path
d=sys.argv[1]
w=sim_common.load_wave(Path(d+'/waveform.raw.json'))
r=tx.analyze(w,'rise','fall')
print(r['verdict'], r['up']['result'], [ (round(e['vdd_v'],4),e['direction']) for e in r['up']['edges']], r['down']['result'], [(round(e['vdd_v'],4),e['direction']) for e in r['down']['edges']])
t=w['time']; vdd=w['v(vdd)']
ks=[k for k in w if k in('v(xbias.noko)','v(xbias.nokx)','v(bias_ok)','v(por_raw)','v(xbias.nokl)','v(xbias.na)','v(xbias.pb)')]
print(ks)
# print trace through up segment every ~0.1V and around edges
import bisect
for tgt in [0.8,1.0,1.2,1.4,1.6,1.8,2.0,2.2,2.4,2.6,2.8,3.0,3.3,3.6]:
    i=min(range(len(t)//2),key=lambda j:abs(vdd[j]-tgt))
    print('%.2f'%vdd[i], ' '.join('%s=%.3f'%(k[2:],w[k][i]) for k in ks))
# max NOKO during the up ramp and where BIAS_OK first flips
n=len(t); pk=max(range(n),key=lambda j:vdd[j])
noko=w['v(xbias.noko)']; bo=w['v(bias_ok)']
print('peak noko up-seg', max(noko[:pk]), 'at vdd', vdd[max(range(pk),key=lambda j:noko[j])])
flips=[(round(vdd[i],3),round(t[i]*1e3,3),'up' if i<pk else 'dn', round(bo[i],2)) for i in range(1,n) if (bo[i]>0.5*vdd[i])!=(bo[i-1]>0.5*vdd[i-1])]
print('bias_ok flips (vdd,t_ms,seg,val):',flips)
