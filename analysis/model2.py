"""Surplus model: log viewers = baseline_c + diurnal(utc) + ramp_surplus(h - unlock_c)."""
import json, math, datetime as dt, re
KIT='/root/work/makefun/gta6/gta6-twitch-ccu-forecast-01-kit'
LEVELS=[0.05,0.25,0.5,0.75,0.95]

def _ts(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def _iso(k, base):
    return (base+dt.timedelta(hours=k)).strftime('%Y-%m-%dT%H:%M:%SZ')

def series(c):
    s=_ts(c['day_start']); out={}
    for p in c['hourly']:
        t=_ts(p['from']); k=round((t-s).total_seconds()/3600)
        if p['viewers'] and p['viewers']>0: out[k]=p['viewers']
    return out

UNLOCK_RE=re.compile(r'(?<![\d:])(\d{1,2}):00Z')

def unlock_hour(c):
    txt=c['unlock']
    cands=[]
    for m in UNLOCK_RE.finditer(txt):
        hh=int(m.group(1))
        # negative day: 2026-09-14T11:00Z style -> treat as before the day
        cands.append(hh)
    if 'Tier: early-access-contaminated' in txt and not cands: return 4
    if cands:
        # the wave that best represents the release day start: the smallest hour in [0,8] if any
        for hh in [0,1,2,3,4,5,6,7,8]:
            if hh in cands: return hh
        return min(cands)
    if 'midnight' in txt.lower(): return 4
    return 4

def parse_platforms(s):
    t=s.lower()
    return {'pc':('pc' in t or 'steam' in t), 'ps':('ps' in t), 'xb':('xbox' in t), 'sw':('switch' in t)}

def tier_of(txt):
    if 'early-access-contaminated' in txt: return 0.25
    if 'Tier: weak' in txt: return 0.5
    if 'unverified' in txt: return 0.8
    return 1.0

def build(case, exclude=()):
    items=[]
    for c in case['comparables']:
        nm=c['name']
        if nm.startswith('Grand Theft Auto VI category'): continue
        if nm in exclude: continue
        h=series(c)
        if not all(k in h for k in range(24)): continue
        items.append({'name':nm,'h':h,'u':unlock_hour(c),'plat':parse_platforms(c['platforms']),
                      'plat_txt':c['platforms'],'tier':tier_of(c['unlock']),
                      'weekday':_ts(c['day_start']).weekday(),'v1':h[0]})
    return items

def diurnal(items, lo=-400, hi=-14, lo2=40):
    """D[24] from clean non-release hours, day-centred."""
    S=[[] for _ in range(24)]
    for c in items:
        for t,v in c['h'].items():
            if t <= hi or t >= lo2:
                S[t%24].append(math.log(v))
    D=[]
    for u in range(24):
        xs=S[u]
        if xs: D.append(sum(xs)/len(xs))
        else: D.append(float('nan'))
    # fill nan and centre
    m=sum(x for x in D if x==x)/sum(1 for x in D if x==x)
    D=[(x if x==x else m)-m for x in D]
    return D

def baseline_level(c, D, lo=-120, hi=-30):
    vals=[math.log(v)-D[t%24] for t,v in c['h'].items() if lo<=t<=hi]
    if len(vals)<8:
        vals=[math.log(v)-D[t%24] for t,v in c['h'].items() if t<0]
    return sum(vals)/len(vals) if vals else math.log(c['v1'])-D[0]

def case_baseline(case, D):
    hh=case.get('history_hourly') or []
    if not hh: return None
    s=_ts(case['day_start']); vals=[]
    for p in hh:
        t=round((_ts(p['from'])-s).total_seconds()/3600)
        if -120<=t<=-30 and p['viewers'] and p['viewers']>0: vals.append(math.log(p['viewers'])-D[t%24])
    if len(vals)<8:
        vals=[]
        for p in hh:
            t=round((_ts(p['from'])-s).total_seconds()/3600)
            if t<0 and p['viewers'] and p['viewers']>0: vals.append(math.log(p['viewers'])-D[t%24])
    return sum(vals)/len(vals) if vals else None

def fit_pool(items, D):
    for c in items:
        c['a']=baseline_level(c,D)
        c['S']={t:(math.log(v)-c['a']-D[t%24]) for t,v in c['h'].items()}
        c['S1']=c['S'][0]
        c['L']={h:(c['S'][h]-c['S1']) for h in range(24) if h in c['S']}
    return items

def wq(pairs, q):
    pairs=sorted(pairs)
    tot=sum(w for v,w in pairs)
    if tot<=0: return 0.0
    t=q*tot; cum=0.0
    for i,(v,w) in enumerate(pairs):
        prev=cum; cum+=w
        if cum>=t:
            if w<=0: return v
            f=(t-prev)/w-0.5
            if 0<i+1<len(pairs):
                nxt=pairs[i+1][0]
                return v+(nxt-v)*max(0.0,min(1.0,f+0.5))
            return v
    return pairs[-1][0]

def predict(case, P):
    items=fit_pool(build(case, P.get('exclude',())), D_:=diurnal(build(case,P.get('exclude',()))))
    p1=max(1.0,case['known'][0]['viewers']) if 'known' in case else max(1.0,case['v1'])
    a_case=case.get('a_case')
    if a_case is None: a_case=case_baseline(case,D_)
    if a_case is None: a_case=math.log(p1)-D_[0]
    S1=math.log(p1)-a_case-D_[0]
    u_case=P.get('u_case',4)
    plat=parse_platforms(case.get('plat','')) if case.get('plat') else None
    ws=[]
    for c in items:
        w=c['tier']
        if plat is not None:
            pc1=c['plat']
            same=plat['pc']==pc1['pc']
            ov=sum(1 for k in plat if plat[k] and pc1[k]); un=sum(1 for k in plat if plat[k] or pc1[k])
            w*=(1.0 if same else P.get('w_pc',0.6))*(0.6+0.4*(ov/un if un else 1.0))
        w*=math.exp(-0.5*((c['u']-u_case)/P.get('sig_u',3.0))**2)
        w*=math.exp(-0.5*((c['S1']-S1)/P.get('sig_s',1.5))**2)
        w*=math.exp(-0.5*((math.log(c['v1'])-math.log(p1))/P.get('sig_l',1.2))**2)
        wd=case.get('weekday')
        if wd is not None and c['weekday']!=wd: w*=P.get('w_wd',0.85)
        ws.append(w)
    # model trajectory
    m={}
    for h in range(2,25):
        num=sum(w*c['L'].get(h,0.0) for w,c in zip(ws,items)); den=sum(ws)
        m[h]=num/den if den>0 else 0.0
    rows={}
    ess=(sum(ws)**2)/sum(w*w for w in ws) if ws else 0
    infl=P.get('infl',0.0)
    for h in range(2,25):
        res=[(c['L'].get(h,0.0)-m[h],w) for w,c in zip(ws,items)]
        sd=math.sqrt(max(1e-9,sum(w*r*r for r,w in res)/max(1e-9,sum(w for _,w in res))))
        # shrink toward parametric normal spread when evidence thin
        lam=min(1.0,max(0.0,ess/(ess+P.get('ess_k',6.0))))
        qs=[]
        for tau in LEVELS:
            e=wq(res,tau)
            par=(-1.6449 if tau==0.05 else -0.6745 if tau==0.25 else 0.0 if tau==0.5 else 0.6745 if tau==0.75 else 1.6449)*sd
            e=lam*e+(1-lam)*par
            e*= (1.0+infl/math.sqrt(max(1.0,ess)))
            qs.append(math.exp(math.log(p1)+ (D_[h%24]-D_[0]) + m[h] + e))
        rows[h]=[min(1e9,max(1e-6,x)) for x in qs]
    return rows,{'ess':ess,'S1':S1,'a_case':a_case,'ws':ws,'items':items,'m':m}
