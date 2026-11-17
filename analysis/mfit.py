"""Parameterised model: alignment(clock|phase) x covariates(elev|scale|both)."""
import json, math
from model2 import KIT, LEVELS, series, unlock_hour, parse_platforms, tier_of, diurnal, case_baseline, _ts
from model4 import robust_baseline, pool_ramp, Rget, wmean, wq

def build(case,exclude=()):
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

def prep(case,exclude=()):
    items=build(case,exclude); D=diurnal(items)
    for c in items:
        a,n=robust_baseline(c,D)
        c['a']=a
        if a is None:
            c['S']=c['S1']=c['L']=None; c['xv']=(math.log(c['v1'])-11.0, 0.0)
        else:
            c['S']={o:(math.log(c['h'][o])-a-D[o%24]) for o in range(24)}
            c['S1']=c['S'][0]
            c['L']={o:(c['S'][o]-c['S1']) for o in range(24)}
            c['xv']=(math.log(c['v1']), c['S1'])
    return items,D

def solve3(x1,x2,y,w):
    """weighted OLS y = a + b1 x1 + b2 x2."""
    n=len(y); sw=sum(w)
    m1=sum(a*b for a,b in zip(x1,w))/sw; m2=sum(a*b for a,b in zip(x2,w))/sw; my=sum(a*b for a,b in zip(y,w))/sw
    s11=sum(wi*(a-m1)**2 for a,wi in zip(x1,w))
    s22=sum(wi*(a-m2)**2 for a,wi in zip(x2,w))
    s12=sum(wi*(a-m1)*(b-m2) for a,b,wi in zip(x1,x2,w))
    s1y=sum(wi*(a-m1)*(c-my) for a,c,wi in zip(x1,y,w))
    s2y=sum(wi*(a-m2)*(c-my) for a,c,wi in zip(x2,y,w))
    det=s11*s22-s12*s12
    if abs(det)<1e-9: return my,0.0,0.0,m1,m2
    b1=(s1y*s22-s2y*s12)/det; b2=(s2y*s11-s1y*s12)/det
    a=my-b1*m1-b2*m2
    return a,b1,b2,m1,m2

def predict(case,P):
    excl=P.get('exclude',())
    items,D=prep(case,excl)
    p1=max(1.0,case['p1'])
    a_case=case.get('a_case')
    if a_case is None: a_case=case_baseline(case,D)
    S1=None
    if a_case is not None: S1=math.log(p1)-a_case-D[0]
    plat=parse_platforms(case['plat']) if case.get('plat') else None
    wd=case.get('weekday')
    ws=[]
    for c in items:
        w=c['tier']
        if c['S'] is None: w*=0.2
        if plat is not None:
            pc1=c['plat']; same=plat['pc']==pc1['pc']
            ov=sum(1 for kk in plat if plat[kk] and pc1[kk]); un=sum(1 for kk in plat if plat[kk] or pc1[kk])
            w*=(1.0 if same else P.get('w_pc',0.6))*(0.6+0.4*(ov/un if un else 1.0))
        if wd is not None and c['weekday']!=wd: w*=P.get('w_wd',0.9)
        w*=math.exp(-0.5*((math.log(c['v1'])-math.log(p1))/P.get('sig_l',1.5))**2)
        w*=math.exp(-0.5*((c['u']-P.get('u_case',4))/P.get('sig_u',8.0))**2)
        ws.append(w)
    ok=[(c,w) for c,w in zip(items,ws) if c['S'] is not None]
    m1=wmean([c['xv'][0] for c,_ in ok],[w for _,w in ok])
    m2=wmean([c['xv'][1] for c,_ in ok],[w for _,w in ok])
    # clip case covariates into observed range
    x1c=math.log(p1); x2c=S1 if S1 is not None else m2
    lo1=min(c['xv'][0] for c,_ in ok); hi1=max(c['xv'][0] for c,_ in ok)
    lo2=min(c['xv'][1] for c,_ in ok); hi2=max(c['xv'][1] for c,_ in ok)
    x1c=max(lo1,min(hi1,x1c)); x2c=max(lo2,min(hi2,x2c)) if P.get('clip',True) else x2c
    cov=P.get('cov','both')
    A={};B1={};B2={}
    for o in range(1,24):
        ys=[c['L'][o] for c,_ in ok]; ww=[w for _,w in ok]
        a,b1,b2,mm1,mm2=solve3([c['xv'][0] for c,_ in ok],[c['xv'][1] for c,_ in ok],ys,ww)
        if cov=='elev': b1=0.0
        if cov=='scale': b2=0.0
        A[o]=a;B1[o]=b1;B2[o]=b2
    cap=P.get('bcap',1.5)
    def smooth(dd):
        out={}
        for o in range(1,24):
            acc=[dd[g] for g in range(o-1,o+2) if 1<=g<=23]
            out[o]=max(-cap,min(cap,sum(acc)/len(acc)))
        return out
    B1s=smooth(B1); B2s=smooth(B2)
    # adjust pool S for the covariate effects, then pool ramp by alignment
    Badj={o:(B1s[o],B2s[o]) for o in range(1,24)}
    for c,_ in ok:
        c['Sadj']={o:(c['S'][o]-(B1s[o]*(c['xv'][0]-m1) if o>=1 else 0.0)-(B2s[o]*(c['xv'][1]-m2) if o>=1 else 0.0)) for o in range(24)}
    align=P.get('align','clock')
    u_case=P.get('u_case',4)
    R=pool_ramp([dict(c, S=c['Sadj']) for c,_ in ok],[w for _,w in ok],{},m2)
    md={}
    for o in range(1,24):
        cov_term=B1s[o]*(x1c-m1)+B2s[o]*(x2c-m2)
        if align=='phase':
            ramp=(Rget(R,o-u_case)-Rget(R,-u_case))
        else:
            ramp=Rget(R,o)-Rget(R,0)
        md[o]=ramp+cov_term
    ess=(sum(ws)**2)/sum(w*w for w in ws)
    lam=min(1.0,ess/(ess+P.get('ess_k',8.0)))
    infl=P.get('infl',0.3)
    sxx2=max(1e-9,sum(w*(c['xv'][1]-m2)**2 for c,w in ok))
    rows={}
    for o in range(1,24):
        res=[]
        for c,w in zip(items,ws):
            if c['S'] is None: continue
            cov_c=B1s[o]*(c['xv'][0]-m1)+B2s[o]*(c['xv'][1]-m2)
            ramp_c=(Rget(R,o-c['u'])-Rget(R,-c['u'])) if align=='phase' else (Rget(R,o)-Rget(R,0))
            res.append((c['L'][o]-ramp_c-cov_c,w))
        sd=math.sqrt(max(1e-9,wmean([r*r for r,_ in res],[w for _,w in res])))
        se=sd*math.sqrt(1.0/ess+((x2c-m2)**2)/sxx2)
        f=math.sqrt(1.0+(infl*se/max(sd,1e-9))**2)
        qs=[]
        for tau in LEVELS:
            e=wq(res,tau)
            z=(-1.6449 if tau==0.05 else -0.6745 if tau==0.25 else 0.0 if tau==0.5 else 0.6745 if tau==0.75 else 1.6449)
            e=lam*e+(1-lam)*z*sd*f
            qs.append(math.exp(math.log(p1)+(D[o%24]-D[0])+md[o]+e))
        rows[o+1]=[min(1e9,max(1e-6,x)) for x in qs]
    return rows,{'ess':ess,'S1':S1,'m1':m1,'m2':m2,'B1':B1s,'B2':B2s,'lam':lam}
