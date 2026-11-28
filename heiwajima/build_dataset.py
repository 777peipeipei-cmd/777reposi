"""平和島の詳細データ (scrape.js の出力) を1艇1行の特徴量CSVにする。

使うのはレース前に分かる情報だけ:
  級別・全国/当地 勝率と2連率・モーター/ボート2連率・平均ST・コース別成績・
  展示タイム/展示ST/周回/周り足/直線・展示進入・風/波・レース番号/グレード。
使わない (リーク): 本番ST (detail.start)、本番進入 (detail.shinnyuu)、
  今節成績・得点率・レース後コメント・決まり手。

usage: python build_dataset.py RACES_DIR OUT_CSV
"""
import glob
import json
import os
import re
import sys

import pandas as pd

CLASS = {'A1': 4, 'A2': 3, 'B1': 2, 'B2': 1}


def num(x, default=None):
    if x is None:
        return default
    m = re.search(r'-?\d+\.?\d*', str(x))
    return float(m.group()) if m else default


def ex_st(s):
    """展示ST。'F.01' はフライング → 負の値で表す。"""
    s = str(s or '')
    v = num(s.replace('F', ''))
    if v is None:
        return None
    return -v if s.startswith('F') else v


def rows_for_race(d):
    ch = {c['course']: c for c in (d.get('chokuzen') or []) if isinstance(c, dict)}
    tri = (d.get('trifecta') or [{}])[0] or {}
    combo = None
    if tri.get('course1'):
        combo = f"{tri['course1']}-{tri['course2']}-{tri['course3']}"
    out = []
    for b in d['boats']:
        waku = b['course']           # 枠番
        c = ch.get(waku, {})
        entry = c.get('shinnyuu') or waku   # 展示進入 (本番進入は使わない)
        row = dict(
            date=d['date'], race=d['race'], waku=waku, entry=entry,
            race_rank=b.get('race_rank'), grade=b.get('grade'),
            rank=b.get('rank'),
            player_no=b.get('player_no'), name=b.get('player_name'),
            cls=CLASS.get(b.get('kyubetsu'), 2), age=b.get('age'),
            weight=num(b.get('taiju'), 0) / 10 if b.get('taiju') else None,
            nat_win=b.get('zenkoku_shoritsu'), nat_2=b.get('zenkoku_niren'), nat_3=b.get('zenkoku_sanren'),
            loc_win=b.get('touchi_shoritsu'), loc_2=b.get('touchi_niren'), loc_3=b.get('touchi_sanren'),
            motor_2=b.get('motor_niren'), motor_3=b.get('motor_sanren'),
            boat_2=b.get('boat_niren'), boat_3=b.get('boat_sanren'),
            avg_st=num(b.get('start_ave')),
            recent_win=num(b.get('saikin_shoritsu')),
            # 進入コース別の成績 (展示進入のコース)
            c_win=num(b.get(f'course{entry}_1_ave')),
            c_2=num(b.get(f'course{entry}_2_ave')),
            c_3=num(b.get(f'course{entry}_3_ave')),
            c_st=num(b.get(f'start{entry}_ave')),
            zenken=b.get('zenken_time'),
            ex_time=num(c.get('display')), ex_st=ex_st(c.get('start')),
            lap=num(c.get('shukai')), turn=num(c.get('mawariashi')), straight=num(c.get('chokusen')),
            tilt=num(c.get('chiruto')),
            wind=num(c.get('wind_speed')), wave=num(c.get('wave')),
            tri_combo=combo, tri_pay=tri.get('kingaku'), tri_pop=tri.get('ninki'),
        )
        for k in ('lap', 'turn', 'straight'):   # 0 = 計測なし
            if not row[k]:
                row[k] = None
        out.append(row)
    return out


def main(src, dst):
    rows = []
    for f in sorted(glob.glob(os.path.join(src, '*.json'))):
        d = json.load(open(f))
        if len(d.get('boats', [])) != 6:
            continue
        rows += rows_for_race(d)
    df = pd.DataFrame(rows)
    # レース内の順位・偏差
    g = df.groupby(['date', 'race'])
    for col, asc in [('ex_time', True), ('lap', True), ('turn', True), ('straight', True),
                     ('nat_win', False), ('motor_2', False), ('loc_win', False)]:
        df[f'{col}_rk'] = g[col].rank(ascending=asc, method='min')
        df[f'{col}_dev'] = df[col] - g[col].transform('mean')
    df.to_csv(dst, index=False)
    print(f'{df.groupby(["date","race"]).ngroups} races, {len(df)} rows -> {dst}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
