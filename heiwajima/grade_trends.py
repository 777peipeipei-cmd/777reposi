"""1年分の結果データで、グレード別 (G1 / G3 / 一般) の傾向を比べる。

kyoteibiyori の grade コード: 1=G1 (周年記念), 2=G2, 3=G3, 0/その他=SG?, 99=一般。
平和島の 2025/12〜2026/10 には SG と G2 は無かった。

usage: python grade_trends.py RESULTS_DIR [OUT_JSON]
"""
import json
import sys

import pandas as pd

from year_trends import load

GRADE_NAME = {1: 'G1', 2: 'G2', 3: 'G3', 99: '一般'}


def grade_label(g):
    try:
        g = int(g)
    except (TypeError, ValueError):
        return '不明'
    return GRADE_NAME.get(g, f'SG?({g})')


def main(src, out_json=None):
    df = load(src)
    df['grade_name'] = df['grade'].map(grade_label)
    out = {}
    for gname, g in df.groupby('grade_name'):
        races = g.drop_duplicates(['date', 'race'])
        win = g[g['rank'] == 1]
        nige = win[win['entry'] == 1][['date', 'race']]
        sec = g[g['rank'] == 2].merge(nige, on=['date', 'race'])
        pay = races['pay'].dropna()
        out[gname] = dict(
            races=len(races),
            series=sorted(g['date'].astype(str).str[:6].unique().tolist()),
            in_win=round((win['entry'] == 1).mean() * 100, 1),
            win_by_entry=(win['entry'].value_counts(normalize=True).sort_index() * 100).round(1).to_dict(),
            manshu_rate=round((pay >= 10000).mean() * 100, 1),
            pay_median=int(pay.median()), pay_mean=int(pay.mean()),
            kimete=(win['kimete'].value_counts(normalize=True) * 100).round(1).to_dict(),
            second_when_in_wins=(sec['entry'].value_counts(normalize=True).sort_index() * 100).round(1).to_dict(),
        )
        # グレード戦の中でもレース種別 (予選 / 準優 / 優勝戦 など)
        rr = win.assign(in_win=win['entry'] == 1).groupby('race_rank')['in_win'].agg(['mean', 'count'])
        out[gname]['in_win_by_race_rank'] = {k: [round(v['mean'] * 100, 1), int(v['count'])] for k, v in rr.iterrows()}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if out_json:
        json.dump(out, open(out_json, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
