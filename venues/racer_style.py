"""選手ごとの「色」（前付け・アウトに出る・コース別の成績）を全24場の公式データから作る。
出力: live/racer_style.csv（登番・名前・出走数・前付け率・外に出る率・1着率・枠5,6での平均進入）
usage: python3 -I venues/racer_style.py /tmp/mbrace/out_all/boats.csv live/racer_style.csv
"""
import sys
import pandas as pd

b = pd.read_csv(sys.argv[1], low_memory=False)
b = b[b.entry.between(1, 6) & b.waku.between(1, 6)]
b['mae'] = b.entry < b.waku
b['ato'] = b.entry > b.waku
g = b.groupby(['racer', 'name']).agg(n=('entry', 'size'), mae=('mae', 'mean'), ato=('ato', 'mean'),
                                       win=('finish', lambda s: (s == 1).mean()))
out56 = b[b.waku >= 5].groupby('racer').entry.mean().rename('out_entry')
g = g.reset_index().merge(out56, on='racer', how='left')
g = g[g.n >= 30]
g['mae'] = (g.mae * 100).round(1); g['ato'] = (g.ato * 100).round(1); g['win'] = (g.win * 100).round(1)
g['out_entry'] = g.out_entry.round(2)
g.columns = ['登番', '名前', '出走', '前付け率', '外に出る率', '1着率', '枠5_6の平均進入']
g.to_csv(sys.argv[2], index=False)
print(len(g), 'racers')
