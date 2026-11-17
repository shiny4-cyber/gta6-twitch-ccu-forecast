"""Phase-aligned surplus model: S(k) ramp + D(utc) diurnal + elevation slope B."""
import json, math
from model2 import (KIT, LEVELS, series, unlock_hour, parse_platforms, tier_of,
                    diurnal, case_baseline, _ts)

def robust_baseline(c,D,lo=-120,hi=-30,minpts=12):
    vals=[math.log(v)-D[t%24] for t,v in c['h'].items() if lo<=t<=hi and v>=2]
    if len(vals)<minpts:
        vals=[math.log(v)-D[t%24] for t,v in c['h'].items() if t<-6 and v>=2]
    if len(vals)<minpts: return None,len(vals)
    return sum(vals)/len(vals),len(vals)

def build(case,exclude=()):
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

def prep(case,exclude=()):
    items=build(case,exclude); D=diurnal(items)
    for c in items:
        a,n=robust_baseline(c,D)
        c['a']=a; c['nbase']=n
        if a is None:
            c['S']=None; c['S1']=None; c['L']=None
        else:
            c['S']={o:(math.log(c['h'][o])-a-D[o%24]) for o in range(24)}
            c['S1']=c['S'][0]
            c['L']={o:(c['S'][o]-c['S1']) for o in range(24)}
    return items,D

def wmean(xs,ws):
    s=sum(ws); return sum(x*w for x,w in zip(xs,ws))/s if s else 0.0

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

KG=(-14,42,2)
KB=list(range(KG[0],KG[1],KG[2]))

def pool_ramp(items,ws,B,mean_s1):
    """R over k: weighted mean of elevation-adjusted S."""
    s={k:0.0 for k in KB}; w={k:0.0 for k in KB}
    for c,wt in zip(items,ws):
        if c['S'] is None: continue
        for o in range(24):
            k=o-c['u']
            kk=max(KB[0],min(KB[-1]-1,int(KG[2]*math.floor(k/KG[2]))))
            adj=c['S'][o]-B.get(o,0.0)*(c['S1']-mean_s1)
            s[kk]+=wt*adj; w[kk]+=wt
    vals={}
    for k in KB:
        vals[k]=s[k]/w[k] if w[k]>0 else None
    ks=sorted(vals); known=[(k,vals[k]) for k in ks if vals[k] is not None]
    if not known: return {k:0.0 for k in KB}
    out={}
    for k in ks:
        if vals[k] is not None: out[k]=vals[k]; continue
        lo=[x for x in known if x[0]<k]; hi=[x for x in known if x[0]>k]
        if lo and hi:
            (k0,v0),(k1,v1)=lo[-1],hi[0]; out[k]=v0+(v1-v0)*(k-k0)/(k1-k0)
        elif lo: out[k]=lo[-1][1]
        else: out[k]=hi[0][1]
    sm={}
    for i,k in enumerate(KB):
        a=out[KB[max(0,i-1)]]; b=out[k]; c2=out[KB[min(len(KB)-1,i+1)]]
        sm[k]=0.25*a+0.5*b+0.25*c2
    return sm

def Rget(R,k):
    if k<=KB[0]: return R[KB[0]]
    if k>=KB[-1]: return R[KB[-1]]
    i=int(KG[2]*math.floor(k/KG[2]))
    f=(k-i)/KG[2]
    return R[i]*(1-f)+R[i+KG[2]]*f

def predict(case,P):
    excl=P.get('exclude',())
    items,D=prep(case,excl)
    p1=max(1.0,case['p1'])
    a_case=case.get('a_case')
    if a_case is None: a_case=case_baseline(case,D)
    info={'a_case':a_case}
    S1=None
    if a_case is not None: S1=math.log(p1)-a_case-D[0]
    plat=parse_platforms(case['plat']) if case.get('plat') else None
    wd=case.get('weekday')
    ws=[]
    for c in items:
        w=c['tier']
        if c['S'] is None: w*=0.15
        if plat is not None:
            pc1=c['plat']; same=plat['pc']==pc1['pc']
            ov=sum(1 for kk in plat if plat[kk] and pc1[kk]); un=sum(1 for kk in plat if plat[kk] or pc1[kk])
            w*=(1.0 if same else P.get('w_pc',0.6))*(0.6+0.4*(ov/un if un else 1.0))
        if wd is not None and c['weekday']!=wd: w*=P.get('w_wd',0.9)
        w*=math.exp(-0.5*((math.log(c['v1'])-math.log(p1))/P.get('sig_l',1.5))**2)
        w*=math.exp(-0.5*((c['u']-P.get('u_case',4))/P.get('sig_u',8.0))**2)
        ws.append(w)
    s1s=[c['S1'] for c in items if c['S1'] is not None]
    mean_s1=wmean([c['S1'] for c in items if c['S1'] is not None],[w for c,w in zip(items,ws) if c['S1'] is not None])
    # elevation slope per offset, from L(o) on S1
    B={}
    for o in range(24):
        xs=[c['S1'] for c in items if c['S'] is not None]
        ys=[c['L'][o] for c in items if c['S'] is not None]
        ww=[w for c,w in zip(items,ws) if c['S'] is not None]
        mx=wmean(xs,ww); my=wmean(ys,ww)
        sxx=sum(w*(x-mx)**2 for x,w in zip(xs,ww)); sxy=sum(w*(x-mx)*(y-my) for x,y,w in zip(xs,ys,ww))
        b=sxy/sxx if sxx>1e-9 else 0.0
        B[o]=max(-P.get('bcap',1.2),min(P.get('bcap',1.2),b))
    # smooth B across offsets
    Bs={}
    for o in range(24):
        acc=[B[g] for g in range(o-1,o+2) if 0<=g<24]
        Bs[o]=sum(acc)/len(acc)
    R=pool_ramp(items,ws,Bs,mean_s1)
    u_case=P.get('u_case',4)
    S1_use=S1 if S1 is not None else mean_s1
    md={}
    for o in range(1,24):
        md[o]=(Rget(R,o-u_case)-Rget(R,-u_case))+Bs[o]*(S1_use-mean_s1)
    ess=(sum(ws)**2)/sum(w*w for w in ws)
    lam=min(1.0,ess/(ess+P.get('ess_k',8.0)))
    infl=P.get('infl',0.3)
    rows={}
    for o in range(1,24):
        res=[]
        for c,w in zip(items,ws):
            if c['S'] is None: continue
            pred_c=(Rget(R,o-c['u'])-Rget(R,-c['u']))+Bs[o]*(c['S1']-mean_s1)
            res.append((c['L'][o]-pred_c,w))
        sd=math.sqrt(max(1e-9,wmean([r*r for r,_ in res],[w for _,w in res])))
        se=sd*math.sqrt(1.0/ess+((S1_use-mean_s1)**2)/max(1e-9,sum(w*(c['S1']-mean_s1)**2 for c,w in zip(items,ws) if c['S'] is not None)))
        f=math.sqrt(1.0+(infl*se/max(sd,1e-9))**2)
        qs=[]
        for tau in LEVELS:
            e=wq(res,tau)
            z=(-1.6449 if tau==0.05 else -0.6745 if tau==0.25 else 0.0 if tau==0.5 else 0.6745 if tau==0.75 else 1.6449)
            par=z*sd*f
            e=lam*e+(1-lam)*par
            qs.append(math.exp(math.log(p1)+(D[o%24]-D[0])+md[o]+e))
        rows[o+1]=[min(1e9,max(1e-6,x)) for x in qs]
    info.update({'ess':ess,'S1':S1,'mean_s1':mean_s1,'B':Bs})
    return rows,info
