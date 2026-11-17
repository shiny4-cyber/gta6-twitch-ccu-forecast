import json,sys,math,statistics as st,datetime as dt
sys.path.insert(0,'.')
import mfit, grade

def _iso(k):
    return (dt.datetime(2000,1,1,tzinfo=dt.timezone.utc)+dt.timedelta(hours=k)).strftime('%Y-%m-%dT%H:%M:%SZ')

def pseudo_case(case, target):
    items=mfit.build(case)
    comps=[]
    for x in items:
        if x['name']==target['name']: continue
        tier='Tier: comparable' if x['tier']==1.0 else ('Tier: early-access-contaminated' if x['tier']==0.25 else 'Tier: weak')
        unlock='%s; unlock %02d:00Z' % (tier, x['u'])
        comps.append({'name':x['name'],'day_start':'2000-01-01T00:00:00Z','unlock':unlock,
                      'platforms':x.get('plat_txt') or '',
                      'hourly':[{'from':_iso(k),'viewers':v} for k,v in sorted(x['h'].items())]})
    return {'comparables':comps,'known':[{'hour':1,'viewers':target['h'][0]}],
            'p1':target['h'][0],'plat':target.get('plat_txt',''),
            'weekday':target['weekday'],'day_start':'2000-01-01T00:00:00Z'}

def targets(case,minv1=15000,mintier=0.8):
    out=[]
    for x in mfit.build(case):
        if x['v1']>=minv1 and x['tier']>=mintier: out.append(x)
    return out

def run(case,P,verbose=False,minv1=15000,mintier=0.8):
    res=[]
    for t in targets(case,minv1,mintier):
        pc=pseudo_case(case,t)
        pc['plat']=t['plat_txt']
        rows,info=mfit.predict(pc,dict(P,exclude=()))
        ans={h:t['h'][h-1] for h in range(2,25)}
        r=grade.score_case(rows,ans)
        b=grade.score_case({h:grade.baseline_rows(t['h'][0])[h] for h in range(2,25)},ans)
        res.append({'name':t['name'],'loss':r['loss'],'base':b['loss'],'cov':r['coverage90'],'miss':r['typical_miss_pct']})
    L=[x['loss'] for x in res]
    return {'mean':st.mean(L) if L else float('nan'),'median':st.median(L) if L else float('nan'),
            'base':st.mean([x['base'] for x in res]) if res else float('nan'),
            'cov':st.mean([x['cov'] for x in res]) if res else float('nan'),
            'miss':st.mean([x['miss'] for x in res]) if res else float('nan'),'res':res}
