"""節の日（初日・2日目・中日・準優日・最終日）ごとの傾向。公式データ1年分（5場、2025/11〜2026/10）。
usage: python3 -I venues/setsu_day_check.py  （/tmp/mbrace/out_all を読み、/tmp/mbrace/setsu.pkl を書く）
"""
import pandas as pd, numpy as np
R = pd.read_csv('/tmp/mbrace/out_all/races.csv', low_memory=False)
B = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False, usecols=['date','jcd','race','title','waku','cls','finish','entry'])
R['pay'] = pd.to_numeric(R.tri_pay.astype(str).str.split('|').str[0], errors='coerce')
R['win'] = R.tri_combo.astype(str).str.split('|').str[0]
t = B[B.waku == 1][['date','jcd','race','title','cls','entry']]
R = R.merge(t, on=['date','jcd','race'], how='left')
R = R[R.jcd.isin([1,4,12,15,24])].dropna(subset=['pay'])
R['d'] = pd.to_datetime(R.date.astype(str))
# 節: 同じ場・同じタイトルで連続した日
days = R.groupby(['jcd','title','d']).size().reset_index()[['jcd','title','d']].sort_values(['jcd','d'])
days['new'] = (days.groupby('jcd').d.diff() != pd.Timedelta(days=1)) | (days.title != days.groupby('jcd').title.shift())
days['meet'] = days.new.cumsum()
days['day'] = days.groupby('meet').cumcount() + 1
days['n'] = days.groupby('meet').day.transform('max')
R = R.merge(days[['jcd','title','d','meet','day','n']], on=['jcd','title','d'])
R = R[R.n >= 4]
def lab(r):
    if r.day == 1: return '1初日'
    if r.day == r.n: return '5最終日'
    if r.day == r.n - 1: return '4準優日(最終日前日)'
    if r.day == 2: return '2二日目'
    return '3中日'
R['phase'] = R.apply(lab, axis=1)
R['in1'] = R.win.str[0] == '1'
R['man'] = R.pay >= 10000
R['naka'] = (R.pay >= 3000) & (R.pay < 10000)
R['A1in'] = R.cls == 'A1'
VEN = {1:'桐生',4:'平和島',12:'住之江',15:'丸亀',24:'大村'}
def summ(g):
    return pd.Series({'R': len(g), 'イン1着%': g.in1.mean()*100, '万舟%': g.man.mean()*100, '中穴(30-100倍)%': g.naka.mean()*100,
                      '平均配当': g.pay.mean(), '中央配当': g.pay.median(), '1号艇A1%': g.A1in.mean()*100,
                      'A1のイン1着%': g[g.A1in].in1.mean()*100, 'B級のイン1着%': g[g.cls.astype(str).str.startswith('B')].in1.mean()*100})
print('節の数', R.meet.nunique(), '期間', R.d.min().date(), R.d.max().date())
print(R.groupby('phase').apply(summ).round(1).to_string())
for j in VEN:
    print('\n==', VEN[j], '節', R[R.jcd==j].meet.nunique())
    print(R[R.jcd==j].groupby('phase').apply(summ).round(1)[['R','イン1着%','万舟%','中穴(30-100倍)%','中央配当','1号艇A1%','A1のイン1着%','B級のイン1着%']].to_string())
# 前半(1-6R)/後半(7-12R) x phase
R['half'] = np.where(R.race <= 6, '前半1-6R', '後半7-12R')
print('\n== 全5場 前半/後半')
print(R.groupby(['phase','half']).apply(summ).round(1)[['R','イン1着%','万舟%','中央配当']].to_string())
# 2着コース(逃げ時)
esc = R[R.in1]
esc['sec'] = esc.win.str[2]; esc['thd'] = esc.win.str[4]
print('\n== 逃げた時の2着・3着の艇番（%）')
print((pd.crosstab(esc.phase, esc.sec, normalize='index')*100).round(1).to_string())
print((pd.crosstab(esc.phase, esc.thd, normalize='index')*100).round(1).to_string())
print('\n== 1着の艇番（%）')
print((pd.crosstab(R.phase, R.win.str[0], normalize='index')*100).round(1).to_string())
R.to_pickle('/tmp/mbrace/setsu.pkl')
