import sys,json,itertools
sys.path.insert(0,'.')
import peval,mfit,grade
case=json.load(open(f'{mfit.KIT}/input/p00.in'))
ans=json.load(open('practice_answers.json'))
answers={c:{h+1:v for h,v in enumerate(d['hourly'])} for c,d in ans.items()}
plats={'p00':'PS5 only','p01':'PS4, Xbox One','p02':'PS5, PS4','p03':'PS5 only'}

def practice(P):
    out={}
    for cid in ['p00','p01','p02','p03']:
        c=json.load(open(f'{mfit.KIT}/input/{cid}.in'))
        c['p1']=c['known'][0]['viewers']; c['plat']=plats[cid]; c['weekday']=mfit._ts(c['day_start']).weekday()
        rows,info=mfit.predict(c,P)
        out[cid]=grade.score_case(rows,{h:v for h,v in answers[cid].items() if h>=2})
    return out

def obj(P,verbose=False):
    r=peval.run(case,P)
    pr=practice(P)
    if verbose:
        print('  pseudo %.3f (base %.3f) cov %.2f | practice'%(r['mean'],r['base'],r['cov']),
              ' '.join('%s %.3f'%(k,v['loss']) for k,v in pr.items()),'mean %.3f'%(sum(v['loss'] for v in pr.values())/4))
    return r['mean'],sum(v['loss'] for v in pr.values())/4
