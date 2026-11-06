"""期末の級別境界・事故率の検証用データ（venues/shobu_features.py の出力を使う）。
usage: python3 -I venues/kimatsu_features.py  (出力 /tmp/mbrace/kimatsu.pkl)
"""
import pandas as pd, numpy as np
b=pd.read_pickle('/tmp/mbrace/shobu.pkl')
b['dt']=pd.to_datetime(b.date.astype(str))
b['per']=np.where(b.dt.dt.month.isin([11,12,1,2,3,4]),'P1','P2')  # P1: 2025/11-2026/04, P2: 2026/05-10
b['pend']=np.where(b.per=='P1',pd.Timestamp('2026-04-30'),pd.Timestamp('2026-10-31'))
b['days_left']=(b.pend-b.dt).dt.days
PT={1:10,2:8,3:6,4:4,5:2,6:1}
b['pt']=b.finish.map(PT).fillna(0)
fr=b.finish_raw.astype(str)
b['acc']=np.select([fr.isin(['F','L0','L1']),fr.str.startswith('S')],[20,10],0)
b['started']=fr.str.match(r'^(0[1-6]|F|L|S)')
b=b.sort_values(['racer','date','race'])
g=b.groupby(['racer','per'])
b['cum_pt']=g.pt.transform(lambda s:s.shift(1).fillna(0).cumsum())
b['cum_n']=g.started.transform(lambda s:s.shift(1).fillna(0).cumsum())
b['cum_acc']=g.acc.transform(lambda s:s.shift(1).fillna(0).cumsum())
b['rate']=b.cum_pt/b.cum_n.replace(0,np.nan); b['accr']=b.cum_acc/b.cum_n.replace(0,np.nan)
# 期末の順位境界: 期末時点の勝率の分位（A1上位20%、A2次の20%）
fin=b.groupby(['racer','per']).agg(pt=('pt','sum'),n=('started','sum')); fin=fin[fin.n>=60]; fin['r']=fin.pt/fin.n
th={p:(fin.loc[(slice(None),p),'r'].quantile(0.8),fin.loc[(slice(None),p),'r'].quantile(0.6)) for p in ['P1','P2']}
print('境界(A1,A2)',{k:(round(v[0],2),round(v[1],2)) for k,v in th.items()})
b['tA1']=b.per.map({k:v[0] for k,v in th.items()}); b['tA2']=b.per.map({k:v[1] for k,v in th.items()})
d=np.minimum(abs(b.rate-b.tA1),abs(b.rate-b.tA2))
nearest=np.where(abs(b.rate-b.tA1)<abs(b.rate-b.tA2),b.rate-b.tA1,b.rate-b.tA2)
b['bd']=pd.cut(pd.Series(nearest,index=b.index),[-9,-0.3,-0.1,0,0.1,0.3,9],labels=['境界より0.3以上下','0.1〜0.3下','0〜0.1下(あと少し)','0〜0.1上(ぎりぎり)','0.1〜0.3上','0.3以上上'])
b['late']=pd.cut(b.days_left,[-1,30,75,999],labels=['期末30日以内','期末31〜75日','それ以前'])
b.to_pickle('/tmp/mbrace/kimatsu.pkl')
