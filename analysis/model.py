import json, math, datetime as dt
KIT='/root/work/makefun/gta6/gta6-twitch-ccu-forecast-01-kit'
LEVELS=[0.05,0.25,0.5,0.75,0.95]
Z=[-1.645,-0.674,0.0,0.674,1.645]

def _ts(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00'))

def comp_series(c):
    s=_ts(c['day_start']); out={}
    for p in c['hourly']:
        t=_ts(p['from']); k=round((t-s).total_seconds()/3600)
        v=p['viewers']
        if v is not None and v>0: out[k]=v
    return out

def est_unlock(h):
    """Robust: hour k in [-8,20] maximising mean(log v[k..k+2]) - mean(log v[k-4..k-1])."""
    def ml(a,b):
        vals=[math.log(h[k]) for k in range(a,b+1) if k in h]
        return sum(vals)/len(vals) if len(vals)>=2 else None
    best=None
    for k in range(-8,20):
        post=ml(k,k+2); pre=ml(k-4,k-1)
        if post is None or pre is None: continue
        g=post-pre
        # prefer the earliest hour of the ramp: require next hour not much bigger
        g2=g-(ml(k+1,k+3) or g)
        score=g+0.5*g2
        pen=0.02*abs(k+1)
        sc=score-pen
        if best is None or sc>best[0]: best=(sc,k,g)
    return None if best is None else best[1]

BN=(-14,42,2)   # R bins: start, end(excl), step
def _bins():
    a,b,st=BN
    return list(range(a,b,st))
BINS=_bins()

def fit(comps, iters=60):
    """Additive fit: y = a_c + R(k) + d(utc_hour). Returns dict."""
    rows=[]  # (ci, t, y, k, u)
    for ci,c in enumerate(comps):
        h=c['h']; u=c['u']
        for t,v in h.items():
            if t< -72 or t>72: continue
            rows.append((ci,t,math.log(v),t-u,t%24))
    n=len(comps)
    a=[0.0]*n
    R={b:0.0 for b in BINS}
    d=[0.0]*24
    for it in range(iters):
        # a_c
        acc=[0.0]*n; cnt=[0]*n
        for (ci,t,y,k,u) in rows:
            acc[ci]+=y-Rget(R,k)-d[u]; cnt[ci]+=1
        a=[acc[i]/cnt[i] if cnt[i] else 0.0 for i in range(n)]
        # R
        s=[0.0]*len(BINS); w=[0]*len(BINS)
        bidx={b:i for i,b in enumerate(BINS)}
        for (ci,t,y,k,u) in rows:
            b=min(BINS[-1],max(BINS[0], int(BN[2]*math.floor(k/BN[2]))))
            i=bidx[b]; s[i]+=y-a[ci]-d[u]; w[i]+=1
        R2={}
        for i,b in enumerate(BINS):
            R2[b]=s[i]/w[i] if w[i] else None
        # fill gaps by interpolation then smooth
        vals=fill(R2)
        sm=[0.0]*len(BINS)
        for i in range(len(BINS)):
            lo=vals[max(0,i-1)]; mid=vals[i]; hi=vals[min(len(BINS)-1,i+1)]
            sm[i]=0.25*lo+0.5*mid+0.25*hi
        R={b:sm[i] for i,b in enumerate(BINS)}
        # d
        s=[0.0]*24; w=[0]*24
        for (ci,t,y,k,u) in rows:
            s[u]+=y-a[ci]-Rget(R,k); w[u]+=1
        d=[s[i]/w[i] if w[i] else 0.0 for i in range(24)]
        m=sum(d)/24
        d=[x-m for x in d]
    return {'a':a,'R':R,'d':d}

def fill(dd):
    ks=sorted(dd)
    known=[(k,dd[k]) for k in ks if dd[k] is not None]
    if not known: return [0.0]*len(ks)
    out=[]
    for k in ks:
        if dd[k] is not None: out.append(dd[k]); continue
        lo=[x for x in known if x[0]<k]; hi=[x for x in known if x[0]>k]
        if lo and hi:
            (k0,v0),(k1,v1)=lo[-1],hi[0]
            out.append(v0+(v1-v0)*(k-k0)/(k1-k0))
        elif lo: out.append(lo[-1][1])
        else: out.append(hi[0][1])
    return out

def Rget(R,k):
    a,b,st=BN
    if k<=BINS[0]: return R[BINS[0]]
    if k>=BINS[-1]: return R[BINS[-1]]
    i=int(st*math.floor(k/st))
    if i in R and (i+st) in R:
        f=(k-i)/st
        return R[i]*(1-f)+R[i+st]*f
    return R[min(BINS,key=lambda x:abs(x-k))]

def prep(case, exclude_names=()):
    comps=[]
    for c in case['comparables']:
        nm=c['name']
        if nm.startswith('Grand Theft Auto VI category'): continue
        if nm in exclude_names: continue
        h=comp_series(c)
        if not all(k in h for k in range(24)): continue
        u=est_unlock(h)
        if u is None: continue
        tier=1.0
        txt=c['unlock']
        if 'Tier: early-access-contaminated' in txt: tier=0.25
        elif 'Tier: weak' in txt: tier=0.5
        elif 'unverified' in txt: tier=0.8
        comps.append({'name':nm,'h':h,'u':u,'plat':c['platforms'],'tier':tier,
                      'v1':h[0],'weekday':_ts(c['day_start']).weekday()})
    return comps

def wquant(vals, ws, q):
    """Weighted quantile, linear interpolation of the weighted CDF (numpy 'linear'-ish)."""
    pairs=sorted(zip(vals,ws))
    tot=sum(w for _,w in pairs)
    if tot<=0: return 0.0
    target=q*tot
    cum=0.0
    for i,(v,w) in enumerate(pairs):
        prev=cum; cum+=w
        if cum>=target:
            if w<=0 or cum==prev: return v
            f=(target-prev)/w
            if i+1<len(pairs):
                nxt=pairs[i+1][0]
                return v+(nxt-v)*(f-0.5)/1.0   # midpoint-ish smoothing
            return v
    return pairs[-1][0]

def plat_class(s):
    t=s.lower()
    pc='pc' in t or 'steam' in t
    ps='ps' in t
    xb='xbox' in t
    sw='switch' in t
    return (pc,ps,xb,sw)

def weights(comps, p1, u_case, weekday=None, sig_u=2.5, sig_l=1.0, wd_other=0.8, name=None):
    ws=[]
    pc0=plat_class(name) if name else None
    for c in comps:
        w=c['tier']
        if pc0 is not None:
            pc1=plat_class(c['plat'])
            same_pc = pc0[0]==pc1[0]
            ov=sum(a and b for a,b in zip(pc0,pc1)); un=sum(a or b for a,b in zip(pc0,pc1))
            w*= (0.5 if not same_pc else 1.0) * (0.6+0.4*(ov/un if un else 1))
        w*=math.exp(-0.5*((c['u']-u_case)/sig_u)**2)
        w*=math.exp(-0.5*((math.log(c['v1'])-math.log(p1))/sig_l)**2)
        if weekday is not None and c['weekday']!=weekday: w*=wd_other
        ws.append(w)
    return ws

def predict(case, params=None, exclude=(), name=None, u_case=None, shrink=None):
    p=params or {}
    comps=prep(case, exclude_names=exclude)
    if name:  # the pseudo-case's own platforms
        pass
    p1=case['known'][0]['viewers'] if 'known' in case else case['v1']
    p1=max(1.0,p1)
    if u_case is None:
        u_case=0
    f=fit(comps)
    R,d=f['R'],f['d']
    ws=weights(comps,p1,u_case,case.get('weekday'),p.get('sig_u',2.5),p.get('sig_l',1.0),
               p.get('wd_other',0.8), name=name)
    # case model trajectory
    m={h: (Rget(R,h-u_case)-Rget(R,-u_case)) + (d[h%24]-d[0]) for h in range(2,25)}
    # residuals per comparable per hour
    E={h:[] for h in range(2,25)}
    for c in comps:
        y=c['h']; uc=c['u']
        l1=math.log(y[0])
        for h in range(2,25):
            pred=(Rget(R,h-uc)-Rget(R,-uc)) + (d[h%24]-d[0])
            E[h].append(math.log(y[h])-l1-pred)
    rows={}
    for h in range(2,25):
        qs=[wquant(E[h],ws,t) for t in LEVELS]
        rows[h]=[math.exp(math.log(p1)+m[h]+z) for z in qs]
    for h in rows:
        rows[h]=[min(1e9,max(1e-6,x)) for x in rows[h]]
    return rows, {'u_case':u_case,'weights':ws,'comps':comps,'m':m}
