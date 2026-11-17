"""Increment-path model: pool hourly log increments by phase (o - unlock), build the path, correct
with two covariates, and read quantiles from the pooled empirical shape of standardised residuals."""
import json, math
from model2 import KIT, LEVELS, series, unlock_hour, parse_platforms, tier_of, diurnal, case_baseline, _ts
from model4 import robust_baseline, wmean, wq

KG=(-16,44,1)
KB=list(range(KG[0],KG[1]))

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
        if a is None:
            c['S']=c['S1']=c['L']=c['I']=None
        else:
            c['S']={o:math.log(c['h'][o])-a-D[o%24] for o in range(24)}
            c['S1']=c['S'][0]
            c['L']={o:c['S'][o]-c['S1'] for o in range(24)}
            c['I']={o:(c['L'][o]-c['L'][o-1]) for o in range(1,24)}
        c['x1']=math.log(c['v1']); c['x2']=c['S1'] if c['S1'] is not None else None
    return items,D

def phase_path(I_by_bin, K):
    """cumulative path for a case whose hour 1 sits at phase K (k at o=0): path[o]."""
    path={0:0.0}
    for o in range(1,24):
        acc=0.0
        for j in range(1,o+1):
            k=j-K
            acc+=I_by_bin.get(max(KB[0],min(KB[-1],k)),0.0)
        path[o]=acc
    return path

def weighted_ols3(x1,x2,y,w):
    sw=sum(w)
    if sw<=0 or len(y)<4: return 0.0,0.0,0.0,0.0,0.0
    m1=sum(a*b for a,b in zip(x1,w))/sw; m2=sum(a*b for a,b in zip(x2,w))/sw; my=sum(a*b for a,b in zip(y,w))/sw
    s11=sum(wi*(a-m1)**2 for a,wi in zip(x1,w)); s22=sum(wi*(a-m2)**2 for a,wi in zip(x2,w))
    s12=sum(wi*(a-m1)*(b-m2) for a,b,wi in zip(x1,x2,w))
    s1y=sum(wi*(a-m1)*(c-my) for a,c,wi in zip(x1,y,w)); s2y=sum(wi*(a-m2)*(c-my) for a,c,wi in zip(x2,y,w))
    det=s11*s22-s12*s12
    if abs(det)<1e-9: return my,0.0,0.0,m1,m2
    b1=(s1y*s22-s2y*s12)/det; b2=(s2y*s11-s1y*s12)/det
    return my-b1*m1-b2*m2,b1,b2,m1,m2

def predict(case,P):
    items,D=prep(case,P.get('exclude',()))
    p1=max(1.0,case['p1'])
    a_case=case.get('a_case') or case_baseline(case,D)
    S1=None if a_case is None else math.log(p1)-a_case-D[0]
    cp=parse_platforms(case.get('plat','')) if case.get('plat') else None
    wd=case.get('weekday'); ws=[]
    for c in items:
        w=c['tier']
        if c['I'] is None: w*=0.2
        if cp is not None:
            same=cp['pc']==c['plat']['pc']
            ov=sum(1 for k in cp if cp[k] and c['plat'][k]); un=sum(1 for k in cp if cp[k] or c['plat'][k])
            w*=(1.0 if same else P.get('w_pc',0.6))*(0.6+0.4*(ov/un if un else 1.0))
        if wd is not None and c['weekday']!=wd: w*=P.get('w_wd',0.9)
        w*=math.exp(-0.5*((c['x1']-math.log(p1))/P.get('sig_l',1.5))**2)
        w*=math.exp(-0.5*((c['u']-P.get('u_case',4))/P.get('sig_u',8.0))**2)
        ws.append(w)
    ok=[(c,w) for c,w in zip(items,ws) if c['I'] is not None]
    if not ok: raise SystemExit('no pool')
    m1=wmean([c['x1'] for c,_ in ok],[w for _,w in ok]); m2=wmean([c['x2'] for c,_ in ok],[w for _,w in ok])
    # pooled increments by phase bin
    acc={k:0.0 for k in KB}; wsum={k:0.0 for k in KB}
    for c,w in ok:
        for o in range(1,24):
            k=o-c['u']
            if KG[0]<=k<KG[1]:
                acc[k]+=w*c['I'][o]; wsum[k]+=w
    Ib={k:(acc[k]/wsum[k] if wsum[k]>0 else None) for k in KB}
    known=[k for k in KB if Ib[k] is not None]
    for k in KB:
        if Ib[k] is None and known:
            below=[x for x in known if x<k]; above=[x for x in known if x>k]
            if below and above:
                k0,k1=below[-1],above[0]; Ib[k]=Ib[k0]+(Ib[k1]-Ib[k0])*(k-k0)/(k1-k0)
            elif below: Ib[k]=Ib[below[-1]]
            else: Ib[k]=Ib[above[0]]
    # smooth increments lightly
    Ib2={k:0.25*Ib[KB[max(0,i-1)]]+0.5*Ib[k]+0.25*Ib[KB[min(len(KB)-1,i+1)]] for i,k in enumerate(KB)}
    u_case=P.get('u_case',4)
    path_case=phase_path(Ib2,u_case)
    paths={c['name']:phase_path(Ib2,c['u']) for c,_ in ok}
    # covariate correction of the path residual
    A={};B1={};B2={}
    for o in range(1,24):
        ys=[c['L'][o]-paths[c['name']][o] for c,_ in ok]; ww=[w for _,w in ok]
        a,b1,b2,_,_=weighted_ols3([c['x1'] for c,_ in ok],[c['x2'] for c,_ in ok],ys,ww)
        A[o]=a;B1[o]=b1;B2[o]=b2
    cap=P.get('bcap',1.5)
    def smooth(dd):
        out={}
        for o in range(1,24):
            acc2=[dd[g] for g in range(o-1,o+2) if 1<=g<=23]
            out[o]=max(-cap,min(cap,sum(acc2)/len(acc2)))
        return out
    B1s,B2s,B1x,B2x=smooth(B1),smooth(B2),smooth(A),None
    x1c=math.log(p1); x2c=S1 if S1 is not None else m2
    lo1=min(c['x1'] for c,_ in ok); hi1=max(c['x1'] for c,_ in ok)
    lo2=min(c['x2'] for c,_ in ok); hi2=max(c['x2'] for c,_ in ok)
    x1c=max(lo1,min(hi1,x1c)); x2c=max(lo2,min(hi2,x2c))
    md={}
    for o in range(1,24):
        md[o]=path_case[o]+B1x[o]+B1s[o]*(x1c-m1)+B2s[o]*(x2c-m2)
    ess=(sum(ws)**2)/sum(w*w for w in ws)
    lam=min(1.0,ess/(ess+P.get('ess_k',8.0)))
    infl=P.get('infl',0.3); mult=P.get('mult',0.85)
    sxx=max(1e-9,sum(w*(c['x2']-m2)**2 for c,w in ok))
    rows={}
    scales={}; std=[]
    for o in range(1,24):
        res=[(c['L'][o]-(paths[c['name']][o]+B1x[o]+B1s[o]*(c['x1']-m1)+B2s[o]*(c['x2']-m2)),w) for c,w in ok]
        sd=math.sqrt(max(1e-9,wmean([r*r for r,_ in res],[w for _,w in res])))
        scales[o]=sd
        for r,w in res: std.append((r/sd,w))
    shape=[wq(std,t) for t in LEVELS]
    for o in range(1,24):
        sd=scales[o]
        se=sd*math.sqrt(1.0/ess+((x2c-m2)**2)/sxx)
        f=math.sqrt(1.0+(infl*se/max(sd,1e-9))**2)
        qs=[]
        for i,tau in enumerate(LEVELS):
            emp=shape[i]*sd*f*mult
            z=(-1.6449 if tau==0.05 else -0.6745 if tau==0.25 else 0.0 if tau==0.5 else 0.6745 if tau==0.75 else 1.6449)
            e=lam*emp+(1-lam)*z*0.15*math.sqrt(o)
            qs.append(math.exp(math.log(p1)+(D[o%24]-D[0])+md[o]+e))
        rows[o+1]=[min(1e9,max(1e-6,x)) for x in qs]
    return rows,{'ess':ess,'S1':S1,'shape':shape,'md':md}
