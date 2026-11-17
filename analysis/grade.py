"""Local re-implementation of the contest's score (RULES 'Scoring'), for practice cases."""
import json, math

LEVELS=[0.05,0.25,0.5,0.75,0.95]

def pinball_item(tau,y,q):
    d=math.log(max(y,1.0))-math.log(max(q,1e-9))
    return 2*max(tau*d,(tau-1)*d)

def score_case(rows, answers):
    """rows: {hour: [q05..q95]}, answers: {hour: viewers}"""
    tot=0.0; n=0; miss=[]; cov=0; hrs=0
    for h,ans in answers.items():
        q=rows[h]
        for tau,qq in zip(LEVELS,q):
            tot+=pinball_item(tau,ans,qq); n+=1
        miss.append(abs(math.log(max(ans,1))-math.log(q[2])))
        hrs+=1
        if q[0]<=ans<=q[4]: cov+=1
    return {'loss':tot/n,'typical_miss_pct':100*(math.exp(sum(miss)/len(miss))-1),'coverage90':cov/hrs,'hours':hrs}

def score_many(rows_by_case, answers_by_case):
    per={c:score_case(rows_by_case[c],answers_by_case[c]) for c in rows_by_case}
    items=sum(v['hours'] for v in per.values())
    total=sum(v['loss']*v['hours'] for v in per.values())/items
    cov=sum(v['coverage90']*v['hours'] for v in per.values())/items
    tm=sum(math.log(1+v['typical_miss_pct']/100)*v['hours'] for v in per.values())/items
    return {'loss':total,'coverage90':cov,'typical_miss_pct':100*(math.exp(tm)-1),'per_case':per}

def baseline_rows(p1):
    Z=[-1.645,-0.674,0,0.674,1.645]
    out={}
    for h in range(2,25):
        out[h]=[p1*math.exp(z*0.15*math.sqrt(h-1)) for z in Z]
    return out

if __name__=='__main__':
    ans=json.load(open('practice_answers.json'))
    answers={c:{h+1:v for h,v in enumerate(d['hourly'])} for c,d in ans.items()}
    # RULES worked example
    rows={2:[600000,800000,900000,1100000,1500000],3:[600000,800000,900000,1100000,1500000]}
    print('worked example:',score_case(rows,{2:1000000,3:700000}))
    rb={c:{h:v for h,v in baseline_rows(answers[c][1]).items()} for c in answers}
    r=score_many(rb,{c:{h:v for h,v in answers[c].items() if h>=2} for c in answers})
    print('baseline:',round(r['loss'],6),'cov',round(r['coverage90'],3),'miss%',round(r['typical_miss_pct'],1))
    for c,v in r['per_case'].items(): print(' ',c,round(v['loss'],6),round(v['coverage90'],3),round(v['typical_miss_pct'],1))
