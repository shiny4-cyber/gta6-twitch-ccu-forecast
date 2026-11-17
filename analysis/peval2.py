"""Leave-one-comparable-out evaluation of the shipped model (main.forecast_case)."""
import sys,json,math,statistics as st,datetime as dt
sys.path.insert(0,'/root/work/gta6-forecast')
import main as M, grade
KIT=M.Path('/root/work/makefun/gta6/gta6-twitch-ccu-forecast-01-kit')

def iso(t0,k):
    return dt.datetime.fromtimestamp(t0+k*3600,dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

def targets(case,minv1,mintier):
    out=[]
    for c in case['comparables']:
        if c['name'].startswith('Grand Theft Auto VI category'): continue
        ser=M.comparable_series(c)
        if not all(o in ser for o in range(24)): continue
        if ser[0]>=minv1 and M.tier_weight(c['unlock'])>=mintier: out.append((c,ser))
    return out

def run(case,minv1=15000,mintier=0.8,verbose=False):
    res=[]
    for target,ser in targets(case,minv1,mintier):
        t0=M.parse_ts(target['day_start'])
        comps=[c for c in case['comparables'] if c['name']!=target['name']]
        hist=[{'from':iso(t0,o),'viewers':v} for o,v in sorted(ser.items()) if o<=0]
        pseudo={'schema':case['schema'],'id':'x','game':case['game'],'day_start':target['day_start'],
                'checkpoint':case['checkpoint'],'levels':case['levels'],
                'known':[{'hour':1,'viewers':ser[0],'from':iso(t0,0),'until':iso(t0,1),'reads':1}],
                'forecast':case['forecast'],'history':[],'history_hourly':hist,
                'streams':None,'categories_hourly':None,'comparables':comps,
                'notes':target['unlock']}
        rows=M.forecast_case(pseudo)
        ans={h:ser[h-1] for h in range(2,25)}
        r=grade.score_case(rows,ans)
        b=grade.score_case(M.baseline_rows(ser[0]),ans)
        res.append({'name':target['name'],'loss':r['loss'],'base':b['loss'],'cov':r['coverage90'],
                    'miss':r['typical_miss_pct']})
    L=[x['loss'] for x in res]
    return {'mean':st.mean(L),'median':st.median(L),'base':st.mean([x['base'] for x in res]),
            'cov':st.mean([x['cov'] for x in res]),'res':res}
