import json, math, datetime as dt, statistics as st
KIT='/root/work/makefun/gta6/gta6-twitch-ccu-forecast-01-kit'

def load(cid):
    return json.load(open(f'{KIT}/input/{cid}.in'))

def hourly_map(comp_or_case, key='hourly'):
    return comp_or_case

def series(c, start=None):
    """dict offset_hours -> viewers, offsets relative to c['day_start']."""
    s=dt.datetime.fromisoformat(c['day_start'].replace('Z','+00:00'))
    out={}
    for p in c['hourly']:
        t=dt.datetime.fromisoformat(p['from'].replace('Z','+00:00'))
        out[round((t-s).total_seconds()/3600)]=p['viewers']
    return out

def est_unlock(c):
    """Hour offset (relative to day_start) with the sharpest log jump in [-14, +16]."""
    h=series(c)
    best=None
    for k in range(-14,17):
        a,b=h.get(k-1),h.get(k)
        if a is None or b is None or a<=0 or b<=0: continue
        g=math.log(max(b,1))-math.log(max(a,1))
        # also look at next hour to prefer the start of the ramp
        if best is None or g>best[0]: best=(g,k)
    return None if best is None else best[1]

def traj(c):
    """log trajectory relative to hour 0 (the release day's first hour), offsets 0..23."""
    h=series(c)
    v0=h.get(0)
    if not v0 or v0<=0: return None
    out={}
    for k in range(0,24):
        v=h.get(k)
        if v is not None and v>0: out[k]=math.log(v)-math.log(v0)
    return out
