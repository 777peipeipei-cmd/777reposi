import pandas as pd, numpy as np
S = pd.read_pickle('/tmp/mbrace/setsu.pkl')
B = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False, usecols=['date','jcd','race','waku','cls','motor_2','ex_time','age','entry'])
B['exr'] = B.groupby(['date','jcd','race']).ex_time.rank(method='min')
g = B.groupby(['date','jcd','race'])
f = pd.DataFrame({
 'b1cls': g.apply(lambda x: str(x[x.waku==1].cls.iloc[0]) if (x.waku==1).any() else '?'),
 'b1mot': g.apply(lambda x: x[x.waku==1].motor_2.iloc[0] if (x.waku==1).any() else np.nan),
 'b1exr': g.apply(lambda x: x[x.waku==1].exr.iloc[0] if (x.waku==1).any() else np.nan),
 'bex1': g.apply(lambda x: ((x.waku!=1)&(x.cls.astype(str).str.startswith('B'))&(x.exr==1)).any()),
 'nA1': g.apply(lambda x: (x.cls=='A1').sum()),
 'wakunari': g.apply(lambda x: (x.entry==x.waku).all()),
}).reset_index()
S = S.merge(f, on=['date','jcd','race'], how='left')
S['man'] = S.pay >= 10000
base = S.man.mean()*100
print(f'全体の万舟率 {base:.1f}%  ({len(S)}R)')
def show(name, mask):
    m = S[mask]; print(f'{name:40s} R={len(m):5d} 万舟 {m.man.mean()*100:5.1f}%')
show('1号艇A1', S.b1cls=='A1'); show('1号艇A2', S.b1cls=='A2'); show('1号艇B1', S.b1cls=='B1'); show('1号艇B2', S.b1cls=='B2')
show('1号艇モーター30%未満', S.b1mot<30); show('1号艇の展示 5〜6位', S.b1exr>=5)
show('風7m以上', S.wind>=7); show('風5m以上', S.wind>=5)
show('B級の展示1位(2〜6号艇)あり', S.bex1)
show('A1が0人', S.nA1==0); show('A1が3人以上', S.nA1>=3)
show('枠なりでない(前付け等)', ~S.wakunari.fillna(True))
show('初日', S.phase=='1初日'); show('最終日', S.phase=='5最終日')
show('前半1-6R', S.race<=6); show('後半7-12R', S.race>6)
show('1号艇B級 & 展示5〜6位', S.b1cls.str.startswith('B') & (S.b1exr>=5))
show('1号艇B級 & 前半', S.b1cls.str.startswith('B') & (S.race<=6))
show('1号艇B級 & 初日', S.b1cls.str.startswith('B') & (S.phase=='1初日'))
show('1号艇B級 & 風5m以上', S.b1cls.str.startswith('B') & (S.wind>=5))
show('1号艇B級 & モーター30%未満', S.b1cls.str.startswith('B') & (S.b1mot<30))
show('1号艇A1 & 展示1〜2位 & 風5m未満', (S.b1cls=='A1') & (S.b1exr<=2) & (S.wind<5))
# score: count of factors
S['score'] = (S.b1cls.str.startswith('B')).astype(int) + (S.b1exr>=5).astype(int) + (S.wind>=5).astype(int) + (S.b1mot<30).astype(int) + (S.phase=='1初日').astype(int) + S.bex1.astype(int) + (~S.wakunari.fillna(True)).astype(int)
print(S.groupby('score').man.agg(['size','mean']).assign(mean=lambda d: (d['mean']*100).round(1)).to_string())
VEN={1:'桐生',4:'平和島',12:'住之江',15:'丸亀',24:'大村'}
for j in VEN:
    t = S[S.jcd==j].groupby('race').man.mean().mul(100).round(0).astype(int)
    print(VEN[j], '万舟%(R別):', ' '.join(f'{r}R{v}' for r, v in t.items()))
S.to_pickle('/tmp/mbrace/manshu.pkl')
