"""1号艇のイン苦手・イン得意と万舟率（公式1年分、5場）。usage: python3 -I venues/inweak_manshu_check.py"""
import pandas as pd
S = pd.read_pickle('/tmp/mbrace/manshu.pkl')
B = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False, usecols=['date','jcd','race','waku','racer'])
st = pd.read_csv('live/racer_style.csv')
print(st.columns.tolist()[:20])
b1 = B[B.waku == 1].merge(st[['登番', 'c1_1着']], left_on='racer', right_on='登番', how='left')
S = S.merge(b1[['date', 'jcd', 'race', 'c1_1着']], on=['date', 'jcd', 'race'], how='left')
S['inweak'] = S['c1_1着'] <= -5
S['instrong'] = S['c1_1着'] >= 5
base = S.man.mean() * 100
def show(n, m):
    d = S[m]; print(f'{n:38s} R={len(d):5d} 万舟 {d.man.mean()*100:5.1f}%  1号艇1着 {(d.win.str[0]=="1").mean()*100:5.1f}%')
show('全体', S.man.notna())
show('1号艇 イン苦手(-5以下)', S.inweak)
show('1号艇 イン得意(+5以上)', S.instrong)
show('イン苦手 & A1が0人', S.inweak & (S.nA1 == 0))
show('イン苦手 & 枠なりでない', S.inweak & ~S.wakunari.fillna(True).astype(bool))
show('イン苦手 & 1号艇A1', S.inweak & (S.b1cls == 'A1'))
show('イン苦手 & 1号艇B級', S.inweak & S.b1cls.str.startswith('B'))
for j, v in {1:'桐生',4:'平和島',12:'住之江',15:'丸亀',24:'大村'}.items():
    show(f'  {v} イン苦手', S.inweak & (S.jcd == j))
