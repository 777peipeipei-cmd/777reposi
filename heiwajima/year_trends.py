"""平和島 1年分の結果データ (results_year.py の出力) から傾向を集計する。

結果だけのデータなので選手の勝率などは無い。進入コース・レース番号・月・
グレード別の1着率、2着/3着のコース分布、3連単配当の分布を出す。

usage: python year_trends.py RESULTS_DIR [OUT_JSON]
"""
import glob
import json
import os
import sys

import pandas as pd


def load(src):
    rows = []
    for f in sorted(glob.glob(os.path.join(src, '*.json'))):
        d = json.load(open(f))
        tri = (d.get('trifecta') or [{}])[0] or {}
        for b in d['boats']:
            rows.append(dict(date=d['date'], race=d['race'], waku=b['course'], entry=b.get('shinnyuu'),
                             rank=b.get('rank'), race_rank=b.get('race_rank'), grade=b.get('grade'),
                             kimete=b.get('kimete'), pay=tri.get('kingaku'), pop=tri.get('ninki')))
    df = pd.DataFrame(rows)
    df['month'] = df['date'].astype(str).str[:6]
    return df


def pct(s):
    return (s * 100).round(1)


def main(src, out_json=None):
    df = load(src)
    races = df.drop_duplicates(['date', 'race'])
    n = len(races)
    out = {'races': n, 'days': int(df['date'].nunique()),
           'from': str(df['date'].min()), 'to': str(df['date'].max())}

    win = df[df['rank'] == 1]
    out['win_by_entry'] = pct(win['entry'].value_counts(normalize=True).sort_index()).to_dict()
    out['second_by_entry'] = pct(df[df['rank'] == 2]['entry'].value_counts(normalize=True).sort_index()).to_dict()
    out['third_by_entry'] = pct(df[df['rank'] == 3]['entry'].value_counts(normalize=True).sort_index()).to_dict()

    # 1コース (進入) が勝った割合をレース番号・月・レース種別ごとに
    w1 = win.assign(in_win=win['entry'] == 1)
    out['in_win_by_race'] = pct(w1.groupby('race')['in_win'].mean()).to_dict()
    out['in_win_by_month'] = pct(w1.groupby('month')['in_win'].mean()).to_dict()
    rr = w1.groupby('race_rank')['in_win'].agg(['mean', 'count'])
    out['in_win_by_race_rank'] = {k: [round(v['mean'] * 100, 1), int(v['count'])] for k, v in rr.iterrows() if v['count'] >= 20}

    # 1コースが逃げた時の2着コース
    nige = win[win['entry'] == 1][['date', 'race']]
    sec = df[df['rank'] == 2].merge(nige, on=['date', 'race'])
    out['second_when_in_wins'] = pct(sec['entry'].value_counts(normalize=True).sort_index()).to_dict()

    out['kimete'] = pct(win['kimete'].value_counts(normalize=True)).to_dict()

    pay = races['pay'].dropna()
    out['trifecta_pay'] = {'median': int(pay.median()), 'mean': int(pay.mean()),
                           'manshu_rate': round((pay >= 10000).mean() * 100, 1)}
    # 3連単の出目 上位
    combo = df[df['rank'] <= 3].sort_values('rank').groupby(['date', 'race'])['waku'] \
        .apply(lambda s: '-'.join(map(str, s.tolist())) if len(s) == 3 else None).dropna()
    out['top_combos'] = pct(combo.value_counts(normalize=True).head(10)).to_dict()

    print(json.dumps(out, ensure_ascii=False, indent=1))
    if out_json:
        json.dump(out, open(out_json, 'w'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
