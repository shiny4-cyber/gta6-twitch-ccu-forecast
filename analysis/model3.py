"""Surplus model, offset-clean: hour h (1..24) = offset o = h-1 from day_start."""
import json, math
from model2 import (KIT, LEVELS, series, unlock_hour, parse_platforms, tier_of,
                    diurnal, baseline_level, case_baseline, _ts)

def build(case, exclude=()):
    items=[]
    for c in case['comparables']:
        nm=c['name']
        if nm.startswith('Grand Theft Auto VI category'): continue
        if nm in exclude: continue
        h=series(c)
        if not all(k in h for k in range(24)): continue
        items.append({'name':nm,'h':h,'u':unlock_hour(c),'plat':parse_platforms(c['platforms']),
                      'tier':tier_of(c['unlock']),'weekday':_ts(c['day_start']).weekday(),'v1':h[0]})
    return items

def prep_pool(items,D):
    for c in items:
        c['a']=baseline_level(c,D)
        c['S']={o:(math.log(c['h'][o])-c['a']-D[o%24]) for o in range(24)}
        c['S1']=c['S'][0]
        c['L']={o:(c['S'][o]-c['S1']) for o in range(24)}
    return items

def wmean(xs,ws):
    s=sum(ws); return sum(x*w for x,w in zip(xs,ws))/s if s else 0.0

def wls(xs,ys,ws):
    mx=wmean(xs,ws); my=wmean(ys,ws)
    sxx=sum(w*(x-mx)**2 for x,w in zip(xs,ws))
    sxy=sum(w*(x-mx)*(y-my) for x,y,w in zip(xs,ys,ws))
    b=sxy/sxx if sxx>1e-12 else 0.0
    return my-b*mx,b,mx,sxx

def base_weights(case,items,P):
    plat=parse_platforms(case['plat']) if case.get('plat') else None
    wd=case.get('weekday'); p1=case['p1']
    ws=[]
    for c in items:
        w=c['tier']
        if plat is not None:
            pc1=c['plat']; same=plat['pc']==pc1['pc']
            ov=sum(1 for k in plat if plat[k] and pc1[k]); un=sum(1 for k in plat if plat[k] or pc1[k])
            w*=(1.0 if same else P.get('w_pc',0.6))*(0.6+0.4*(ov/un if un else 1.0))
        if wd is not None and c['weekday']!=wd: w*=P.get('w_wd',0.9)
        w*=math.exp(-0.5*((c['u']-P.get('u_case',4))/P.get('sig_u',6.0))**2)
        w*=math.exp(-0.5*((math.log(c['v1'])-math.log(p1))/P.get('sig_l',1.5))**2)
        ws.append(w)
    return ws

def wq(pairs,q):
    pairs=sorted(pairs); tot=sum(w for _,w in pairs)
    if tot<=0: return 0.0
    t=q*tot; cum=0.0
    for i,(v,w) in enumerate(pairs):
        prev=cum; cum+=w
        if cum>=t:
            if w<=0 or i+1>=len(pairs): return v
            f=(t-prev)/w
            return v+(pairs[i+1][0]-v)*(f-0.5)
    return pairs[-1][0]

def predict(case,P):
    excl=P.get('exclude',())
    items=prep_pool(build(case,excl),diurnal(build(case,excl)))
    p1=max(1.0,case['p1']); D=diurnal(build(case,excl))
    a_case=case.get('a_case') or case_baseline(case,D)
    if a_case is None: a_case=math.log(p1)-D[0]
    S1=math.log(p1)-a_case-D[0]
    ws=base_weights(case,items,P)
    xs=[c['S1'] for c in items]
    A={};B={};MX={};SXX={}
    for o in range(1,24):
        A[o],B[o],MX[o],SXX[o]=wls(xs,[c['L'][o] for c in items],ws)
    k=P.get('bsmooth',1); Bs={}
    for o in range(1,24):
        num=den=0.0
        for g in range(o-k,o+k+1):
            if 1<=g<=23: num+=B[g]; den+=1
        Bs[o]=num/den
    cap=P.get('bcap',1.0)
    Bs={o:max(-cap,min(cap,v)) for o,v in Bs.items()}
    md={o:A[o]+Bs[o]*(S1-MX[o]) for o in range(1,24)}
    ess=(sum(ws)**2)/sum(w*w for w in ws)
    lam=min(1.0,ess/(ess+P.get('ess_k',8.0)))
    infl=P.get('infl',0.35)
    rows={}
    for o in range(1,24):
        res=[(c['L'][o]-(A[o]+Bs[o]*(c['S1']-MX[o])),w) for c,w in zip(items,ws)]
        sd=math.sqrt(max(1e-9,wmean([r*r for r,_ in res],ws)))
        se=sd*math.sqrt(1.0/ess+(S1-MX[o])**2/max(1e-9,SXX[o]))
        f=math.sqrt(1.0+(infl*se/max(sd,1e-9))**2)
        qs=[]
        for tau in LEVELS:
            e=wq(res,tau)
            par=(-1.6449 if tau==0.05 else -0.6745 if tau==0.25 else 0.0 if tau==0.5 else 0.6449 if False else 0.6745 if tau==0.75 else 1.6449)*sd*f
            e=lam*e+(1-lam)*par
            qs.append(math.exp(math.log(p1)+(D[o%24]-D[0])+md[o]+e))
        rows[o+1]=[min(1e9,max(1e-6,x)) for x in qs]
    return rows,{'ess':ess,'S1':S1,'a_case':a_case,'B':Bs}
