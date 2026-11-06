"""勝負駆け・F持ちの検証用データを作る（全24場の公式データ）。節(sid)・準優の日・予選最終日・2回乗りの何走目(k)・準優に乗ったか(qual)。
usage: python3 -I venues/shobu_features.py  (入力 /tmp/mbrace/out_all, 出力 /tmp/mbrace/shobu.pkl)
"""
import pandas as pd, numpy as np
b=pd.read_csv('/tmp/mbrace/out_all/boats.csv',low_memory=False)
b['st']=pd.to_numeric(b.st_raw,errors='coerce')
b['F']=b.finish_raw.astype(str).eq('F')
ok=b.finish.between(1,6)&b.entry.between(1,6)
b['top3']=np.where(ok,(b.finish<=3).astype(float),np.nan); b['win']=np.where(ok,(b.finish==1).astype(float),np.nan)
g=b[ok].groupby(['entry','cls'])[['top3','win']].mean().rename(columns={'top3':'e3','win':'ew'})
b=b.merge(g,left_on=['entry','cls'],right_index=True,how='left')
b['r3']=b.top3-b.e3; b['rw']=b.win-b.ew
stb=b[b.st.notna()].groupby(['entry','cls']).st.mean().rename('est'); b=b.merge(stb,left_on=['entry','cls'],right_index=True,how='left'); b['rst']=b.st-b.est
# series id: same jcd & title, dates within 1 day chain
b=b.sort_values(['jcd','title','date','race'])
d=b[['jcd','title','date']].drop_duplicates().sort_values(['jcd','title','date'])
d['gap']=d.groupby(['jcd','title']).date.diff().fillna(99)
d['dt']=pd.to_datetime(d.date.astype(str)); d['gapd']=d.groupby(['jcd','title']).dt.diff().dt.days.fillna(99)
d['sid']=(d.gapd>1).cumsum(); b=b.merge(d[['jcd','title','date','sid']],on=['jcd','title','date'])
# day index within series and 準優 day
semi=b[b.race_type=='準優勝戦'].groupby('sid').date.min().rename('semi_date')
b=b.merge(semi,left_on='sid',right_index=True,how='left')
days=b[['sid','date']].drop_duplicates().sort_values(['sid','date']); days['di']=days.groupby('sid').cumcount()
b=b.merge(days,on=['sid','date'])
prev=days.merge(semi,left_on='sid',right_index=True); prev=prev[prev.date<prev.semi_date].groupby('sid').date.max().rename('last_yosen')
b=b.merge(prev,left_on='sid',right_index=True,how='left')
qual=b[b.race_type=='準優勝戦'][['sid','racer']].drop_duplicates(); qual['qual']=True
b=b.merge(qual,on=['sid','racer'],how='left'); b['qual']=b.qual.fillna(False)
# nth race of the day per racer
b=b.sort_values(['sid','racer','date','race']); b['nday']=b.groupby(['sid','racer','date']).race.transform('size'); b['k']=b.groupby(['sid','racer','date']).cumcount()+1
b.to_pickle('/tmp/mbrace/shobu.pkl')
