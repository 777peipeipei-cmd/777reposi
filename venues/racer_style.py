"""選手ごとの「色」を全24場の公式データから作る。
- 前付け率・外に出る率・枠5,6での平均進入
- コース別の得意/苦手（同じ級別の平均との差、出走が少ない選手は平均に寄せる縮小推定、ポイント）:
  1コース1着・2コース1着・4コース1着・5コース3着内・6コース3着内
- スタート: 平均ST・STのばらつき（標準偏差）
検証（2025/11〜07で作り 2026/08〜10で確認）: イン逃げの得意/苦手の差は次の3か月も約10ポイント残る（苦手 −6.8、得意 +3.2）。
5コース3着内 6.6、6コース 5.1、2コース 4.0、カド 3.1、平均ST 4.6ポイントの差が残る。
出力: live/racer_style.csv
usage: python3 -I venues/racer_style.py /tmp/mbrace/out_all/boats.csv live/racer_style.csv
"""
import sys
import numpy as np
import pandas as pd

b = pd.read_csv(sys.argv[1], low_memory=False)
b = b[b.entry.between(1, 6) & b.waku.between(1, 6)].copy()
b['entry'] = b.entry.astype(int)
b['mae'] = b.entry < b.waku
b['ato'] = b.entry > b.waku
g = b.groupby(['racer', 'name']).agg(n=('entry', 'size'), mae=('mae', 'mean'), ato=('ato', 'mean'),
                                       win=('finish', lambda s: (s == 1).mean())).reset_index()
g = g.merge(b[b.waku >= 5].groupby('racer').entry.mean().rename('out_entry'), on='racer', how='left')
f = b[b.finish.between(1, 6)].copy()
f['win1'] = (f.finish == 1).astype(float); f['top3'] = (f.finish <= 3).astype(float)
base = f.groupby(['entry', 'cls'])[['win1', 'top3']].mean()
K = 20
for course, col, lab in [(1, 'win1', 'c1_1着'), (2, 'win1', 'c2_1着'), (4, 'win1', 'c4_1着'), (5, 'top3', 'c5_3着内'), (6, 'top3', 'c6_3着内')]:
    x = f[f.entry == course].copy()
    x['b'] = [base.loc[(course, c), col] if (course, c) in base.index else np.nan for c in x.cls]
    t = x.groupby('racer').agg(n=(col, 'size'), v=(col, 'mean'), b=('b', 'mean'))
    t[lab] = ((t.v * t.n + t.b * K) / (t.n + K) - t.b) * 100
    g = g.merge(t[[lab]], on='racer', how='left')
f['st'] = pd.to_numeric(f.st_raw, errors='coerce')
st = f.groupby('racer').st.agg(['mean', 'std'])
st.columns = ['平均ST', 'STばらつき']
g = g.merge(st, on='racer', how='left')
g = g[g.n >= 30]
g['mae'] = (g.mae * 100).round(1); g['ato'] = (g.ato * 100).round(1); g['win'] = (g.win * 100).round(1)
g = g.round(2)
g = g.rename(columns={'racer': '登番', 'name': '名前', 'n': '出走', 'mae': '前付け率', 'ato': '外に出る率', 'win': '1着率', 'out_entry': '枠5_6の平均進入'})
g.to_csv(sys.argv[2], index=False)
print(len(g), 'racers')
