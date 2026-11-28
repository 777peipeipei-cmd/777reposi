"""kyoteibiyori の詳細データ (2026/08〜) で、展示の各タイムと SG/G1 成績が結果にどう効くかを見る (場ごと)。

- 展示タイム・周回・周り足・直線・展示ST のレース内順位ごとの 1着率 / 3着内率
- 1号艇がその順位のとき (1位 / 5〜6位) の1着率
- グレード常連 (SG/G1 出走30回以上 または 優出1回以上) とそれ以外の1着率 (1コース / 外枠)

usage: python detail_check.py OUT_JSON 名前=DETAIL_DIR [名前=DETAIL_DIR ...]
"""
import glob
import json
import os
import re
import sys

import numpy as np
import pandas as pd


def num(x):
    m = re.search(r'-?\d+\.?\d*', str(x or ''))
    return float(m.group()) if m else np.nan


def ex_st(s):
    s = str(s or '')
    v = num(s.replace('F', ''))
    return -v if s.startswith('F') else v


def load(d):
    rows = []
    for f in glob.glob(os.path.join(d, '*.json')):
        j = json.load(open(f))
        ch = {c['course']: c for c in (j.get('chokuzen') or []) if isinstance(c, dict)}
        if len(j.get('boats', [])) != 6:
            continue
        for b in j['boats']:
            c = ch.get(b['course'], {})
            has = b.get('shoritsu_sg') is not None
            rows.append(dict(date=int(j['date']), race=int(j['race']), waku=b['course'],
                             entry=c.get('shinnyuu') or b['course'], rank=b.get('rank'), cls=b.get('kyubetsu'),
                             ex_time=num(c.get('display')), ex_st=ex_st(c.get('start')),
                             lap=num(c.get('shukai')) or np.nan, turn=num(c.get('mawariashi')) or np.nan,
                             straight=num(c.get('chokusen')) or np.nan,
                             has_sg=int(has), sg_starts=num(b.get('shinnyu_sg')) if has else 0,
                             sg_yushutsu=num(b.get('yushutsu_count_sg')) if has else 0))
    df = pd.DataFrame(rows)
    df = df[pd.to_numeric(df['rank'], errors='coerce').between(1, 6)]
    df['rank'] = df['rank'].astype(int)
    df = df[df.groupby(['date', 'race'])['waku'].transform('count') == 6]
    for c in ('lap', 'turn', 'straight'):
        df.loc[df[c] <= 0, c] = np.nan
    g = df.groupby(['date', 'race'])
    for c in ('ex_time', 'lap', 'turn', 'straight'):
        df[f'{c}_rk'] = g[c].rank(method='min')
    df['ex_st_abs'] = df['ex_st'].abs()
    df['ex_st_rk'] = g['ex_st_abs'].rank(method='min')
    df['regular'] = ((df['sg_starts'] >= 30) | (df['sg_yushutsu'] >= 1)).astype(int)
    return df


def pct(x):
    return round(float(x) * 100, 1)


def analyze(df):
    out = dict(races=int(df.groupby(['date', 'race']).ngroups))
    for c, label in [('ex_time_rk', '展示タイム'), ('lap_rk', '周回'), ('turn_rk', '周り足'),
                     ('straight_rk', '直線'), ('ex_st_rk', '展示ST')]:
        t = df.dropna(subset=[c]).groupby(c)
        out[label] = {int(k): [pct((x['rank'] == 1).mean()), pct((x['rank'] <= 3).mean()), len(x)] for k, x in t if k <= 6}
        w1 = df[(df['entry'] == 1)].dropna(subset=[c])
        out[label + '_1コース'] = {'1位': [pct((w1[w1[c] == 1]['rank'] == 1).mean()), int((w1[c] == 1).sum())],
                                    '5〜6位': [pct((w1[w1[c] >= 5]['rank'] == 1).mean()), int((w1[c] >= 5).sum())]}
    who = np.where(df['regular'] == 1, 'グレード常連', np.where(df['has_sg'] == 1, 'SG/G1経験少', '経験なし'))
    d = df.assign(who=who)
    out['常連_1コース'] = {k: [pct((x['rank'] == 1).mean()), len(x)] for k, x in d[d.entry == 1].groupby('who')}
    out['常連_外枠4-6'] = {k: [pct((x['rank'] == 1).mean()), len(x)] for k, x in d[d.entry >= 4].groupby('who')}
    return out


def main(out_json, pairs):
    res = {}
    for name, d in pairs:
        if os.path.isdir(d) and glob.glob(os.path.join(d, '*.json')):
            res[name] = analyze(load(d))
            print(name, json.dumps(res[name], ensure_ascii=False))
    json.dump(res, open(out_json, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], [tuple(a.split('=', 1)) for a in sys.argv[2:]])
