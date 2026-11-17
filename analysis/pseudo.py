import json,sys,math,statistics as st
sys.path.insert(0,'.')
import model, grade

def pseudo_cases(case):
    comps=model.prep(case)
    out=[]
    for i,c in enumerate(comps):
        rest=[x for j,x in enumerate(comps) if j!=i]
        pseudo={'comparables':[],'known':[{'hour':1,'viewers':c['h'][0]}],'weekday':c['weekday']}
        for x in rest:
            pseudo['comparables'].append({'name':x['name'],'day_start':'2000-01-01T00:00:00Z','unlock':('Tier: comparable' if x['tier']==1 else ('Tier: early-access-contaminated' if x['tier']==0.25 else 'Tier: weak')),
                                          'platforms':x['plat'],'hourly':[{'from':_iso(k),'viewers':v} for k,v in sorted(x['h'].items())]})
        out.append((c,pseudo))
    return out

def _iso(k):
    import datetime as dt
    t=dt.datetime(2000,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(hours=k)
    return t.strftime('%Y-%m-%dT%H:%M:%SZ')

def run(case, params=None, verbose=False, exclude_self=True):
    res=[]
    for c,pseudo in pseudo_cases(case):
        rows,info=model.predict(pseudo,params,u_case=c['u'],name=c['plat'])
        ans={h:c['h'][h] for h in range(2,25)}
        r=grade.score_case(rows,ans)
        base=grade.baseline_rows(c['h'][0])
        rb=grade.score_case({h:base[h] for h in range(2,25)},ans)
        res.append({'name':c['name'],'loss':r['loss'],'cov':r['coverage90'],'base':rb['loss'],'miss':r['typical_miss_pct'],
                    'biased':{h:math.log(rows[h][2]/c['h'][h]) for h in range(2,25)}})
    L=[x['loss'] for x in res]; B=[x['base'] for x in res]
    return {'mean':st.mean(L),'median':st.median(L),'baseline':st.mean(B),'cov':st.mean([x['cov'] for x in res]),
            'res':res}
