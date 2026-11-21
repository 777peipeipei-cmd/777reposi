"""穴の要素: B級の展示タイム順位・モーターの直近10走の調子・今節の前走までの調子を作る（全24場の公式データ）。
usage: python3 -I venues/hole_features.py  (入力 /tmp/mbrace/out_all, 出力 /tmp/mbrace/ana.pkl)
"""
import pandas as pd, numpy as np
b=pd.read_csv('/tmp/mbrace/out_all/boats.csv'); r=pd.read_csv('/tmp/mbrace/out_all/races.csv')
b=b[b.finish.between(1,6)&b.entry.between(1,6)].copy(); b['entry']=b.entry.astype(int)
b['top3']=(b.finish<=3).astype(float); b['win']=(b.finish==1).astype(float)
base=b.groupby(['entry','cls'])[['top3','win']].transform('mean'); b['r3']=b.top3-base.top3; b['rw']=b.win-base.win
# payouts
r['tan_pay']=pd.to_numeric(r.tan_pay,errors='coerce')
def fuku(row):
    d={}
    try:
        for c,p in zip(str(row.fuku_combo).split('|'),str(row.fuku_pay).split('|')): d[int(c)]=float(p)
    except: pass
    return d
r['fk']=r.apply(fuku,axis=1)
b=b.merge(r[['date','jcd','race','tan_pay','fk']],on=['date','jcd','race'],how='left')
b['tan_ret']=np.where(b.win==1,b.tan_pay,0)/100
b['fuku_ret']=[ (fk.get(int(w),0)/100 if isinstance(fk,dict) else 0) for fk,w in zip(b.fk,b.waku)]
# 展示順位
b['ex_rank']=b.groupby(['date','jcd','race']).ex_time.rank(method='min')
b['ex_gap']=b.ex_time-b.groupby(['date','jcd','race']).ex_time.transform(lambda s: s.nsmallest(2).iloc[-1])
# モーター直近: 同じ場・同じモーター番号の直前10走の r3 平均（当日より前）
b=b.sort_values(['jcd','motor_no','date','race'])
b['m_recent']=b.groupby(['jcd','motor_no']).r3.transform(lambda s: s.shift(1).rolling(10,min_periods=6).mean())
# 選手の今節: 同じ場・同じタイトルでの前走までの r3 平均
b=b.sort_values(['jcd','racer','date','race'])
b['s_recent']=b.groupby(['jcd','racer','title']).r3.transform(lambda s: s.shift(1).expanding(min_periods=3).mean())
b.to_pickle('/tmp/mbrace/ana.pkl')
