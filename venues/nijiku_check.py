"""2軸（2艇を軸にした買い方）の固定ルールの検証（全24場 公式データ、venues/hole_features.py の出力を使う）。
3連単6点 = A-B-3艇 + B-A-3艇（3着は展示タイム上位）、3連複4点 = A-B-残り全部。
usage: python3 -I venues/nijiku_check.py
"""
import pandas as pd, numpy as np
b=pd.read_pickle('/tmp/mbrace/ana.pkl')
r=pd.read_csv('/tmp/mbrace/out_all/races.csv',low_memory=False)
r['tri_pay']=pd.to_numeric(r.tri_pay,errors='coerce'); r['trio_pay']=pd.to_numeric(r.trio_pay,errors='coerce')
r=r.dropna(subset=['tri_pay'])
b['hole']=b.cls.isin(['B1','B2'])&(b.ex_rank==1)&(b.s_recent>0.05)
keys=['date','jcd','race']
g=b.groupby(keys)
rows=[]
for k,x in g:
    if len(x)!=6 or x.ex_time.isna().any(): continue
    x=x.sort_values('ex_time'); order=list(x.waku.astype(int))
    w1=1
    ex1=[w for w in order if w!=1][0]
    hole=list(x[x.hole].waku.astype(int))
    rows.append(dict(zip(keys,k),order=order,ex1=ex1,hole=hole[0] if hole else None))
d=pd.DataFrame(rows).merge(r[keys+['tri_combo','tri_pay','trio_combo','trio_pay']],on=keys)
def evalrule(name,f):
    res=[]
    for _,x in d.iterrows():
        ab=f(x)
        if not ab: continue
        a,bb=ab
        rest=[w for w in x.order if w not in (a,bb)]
        third=rest[:3]
        tri=[f'{a}-{bb}-{c}' for c in third]+[f'{bb}-{a}-{c}' for c in third]
        trio=['-'.join(map(str,sorted([a,bb,c]))) for c in rest]
        t=x.tri_combo; q=x.trio_combo
        ret6=x.tri_pay if t in tri else 0
        ret4=x.trio_pay if q in trio else 0
        res.append(dict(test=x.date>=20260801,ret6=ret6,ret4=ret4,man=(x.tri_pay>=10000),hit6=ret6>0,hit4=ret4>0,hitman=(ret6>0)&(x.tri_pay>=10000)))
    z=pd.DataFrame(res)
    out=z.groupby('test').agg(n=('ret6','size'),三連単6点_的中=('hit6','mean'),三連単6点_回収=('ret6','mean'),万舟的中=('hitman','sum'),三連複4点_的中=('hit4','mean'),三連複4点_回収=('ret4','mean'))
    out['三連単6点_回収']=(out['三連単6点_回収']/600*100).round(0); out['三連複4点_回収']=(out['三連複4点_回収']/400*100).round(0)
    out['三連単6点_的中']=(out['三連単6点_的中']*100).round(1); out['三連複4点_的中']=(out['三連複4点_的中']*100).round(1)
    print('==',name); print(out.to_string())
d['hole']=d.hole.apply(lambda v:int(v) if pd.notna(v) else 0)
evalrule('穴艇＋1号艇',lambda x:(x.hole,1) if x.hole and x.hole!=1 else None)
evalrule('穴艇＋展示1位以外の展示上位',lambda x:(x.hole,[w for w in x.order if w!=x.hole][0]) if x.hole else None)

evalrule('穴艇＋2〜4コースの穴艇のみ＋1号艇',lambda x:(x.hole,1) if x.hole in (2,3,4) else None)
evalrule('穴艇(1号艇)＋展示上位',lambda x:(1,[w for w in x.order if w!=1][0]) if x.hole==1 else None)
