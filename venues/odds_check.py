"""kyoteibiyori のオッズ (2026/08 以降) で「勝負レース」を検証し直す。

使うオッズ
- 3連単: 締切5分前のオッズ (時系列データ) … レース前に見られる値
- 単勝・2連単・2連複・拡連複・3連複: **最終オッズしか無い**。締切直前の買い方の再現としては少し有利な前提になる
  (最終オッズはレース後に確定する値)。表には必ずどちらのオッズかを書く。
払戻と的中は公式データ (races.csv) で判定する。

1. 券種ごとに「オッズ帯別の的中率・平均払戻・回収率」(1番人気〜人気薄まで、全組み合わせ)
2. 1号艇絡みの固定買い目を、オッズが 2.3〜3.5倍 / 2.3倍以上 の時だけ買った場合
3. 公式データの段階で残った候補条件に、オッズ条件を足した場合

usage: python odds_check.py OFFICIAL_OUT_DIR OUT_JSON JCD=ODDS_DIR [JCD=ODDS_DIR ...] [--grade-override CSV]
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import analyze as A  # noqa: E402

KIND = {'t': '単勝', '2t': '2連単', '2f': '2連複', 'k': '拡連複', '3f': '3連複', '3t': '3連単(5分前)'}
OFF = {'t': 'tan', '2t': 'exa', '2f': 'qui', 'k': 'wide', '3f': 'trio', '3t': 'tri'}
BANDS = [1.0, 1.5, 2.0, 2.3, 2.6, 3.0, 3.5, 5.0, 10.0, 30.0, 1e9]


def odds_value(s):
    """'1.8-2.2' (拡連複・複勝) は下限を使う。"""
    try:
        return float(str(s).split('-')[0])
    except ValueError:
        return np.nan


def canon(kind, combo):
    c = str(combo)
    if kind in ('2f', 'k', '3f'):
        return '-'.join(sorted(c))
    return '-'.join(c)


def load_odds(d):
    out = {}
    for f in glob.glob(os.path.join(d, '*.json')):
        j = json.load(open(f))
        o = {k: {canon(k, c): odds_value(v) for c, v in j['final'].get(k, {}).items()} for k in ('t', '2t', '2f', 'k', '3f')}
        o['3t'] = {canon('3t', c): odds_value(v) for c, v in (j.get('tri_by_min', {}).get('5') or {}).items()}
        out[(int(j['date']), int(j['race']))] = o
    return out


def winners(r):
    """公式データ → 券種ごとの {組番: 払戻}。"""
    out = {}
    for _, x in r.iterrows():
        w = {}
        for k, col in OFF.items():
            combos = str(x.get(f'{col}_combo') or '').split('|')
            pays = str(x.get(f'{col}_pay') or '').split('|')
            w[k] = {c: int(p) for c, p in zip(combos, pays) if c and c != 'nan' and p.isdigit()}
        out[(int(x['date']), int(x['race']))] = w
    return out


def band_table(odds, win):
    rows = []
    for key, o in odds.items():
        if key not in win:
            continue
        for k in KIND:
            for c, v in o.get(k, {}).items():
                if not v or np.isnan(v) or v <= 0:
                    continue
                pay = win[key][k].get(c, 0)
                rows.append((k, v, pay))
    df = pd.DataFrame(rows, columns=['kind', 'odds', 'pay'])
    df['band'] = pd.cut(df['odds'], BANDS, right=False)
    out = {}
    for k, g in df.groupby('kind'):
        t = g.groupby('band', observed=True).agg(n=('pay', 'size'), hits=('pay', lambda s: (s > 0).sum()), ret=('pay', 'sum'))
        out[KIND[k]] = {str(b): dict(n=int(x.n), hit=round(x.hits / x.n * 100, 1), roi=round(x.ret / (100 * x.n) * 100, 1))
                        for b, x in t.iterrows() if x.n >= 20}
    return out


def fav_table(odds, win):
    """各券種の1番人気だけを買い続けた場合。"""
    out = {}
    for k in KIND:
        pays = []
        for key, o in odds.items():
            if key not in win or not o.get(k):
                continue
            c = min(o[k], key=lambda x: o[k][x] if o[k][x] and not np.isnan(o[k][x]) else 1e9)
            pays.append(win[key][k].get(c, 0))
        s = A.stats(pays)
        s['roi_ci90'] = A.boot_ci(pays)
        out[KIND[k]] = s
    return out


def fixed_bets(df, odds, win, cond_masks):
    """1号艇絡みの固定買い目 × 条件 × オッズ帯。"""
    res = []
    bets = [('t', lambda x: '1', '単勝 1号艇'),
            ('2f', lambda x: canon('2f', f"1{x['best2']}"), '2連複 1-相手1位'),
            ('k', lambda x: canon('k', f"1{x['best2']}"), '拡連複 1-相手1位'),
            ('2t', lambda x: canon('2t', f"1{x['best2']}"), '2連単 1-相手1位'),
            ('3f', lambda x: canon('3f', f"1{x['best2']}{x['best3']}"), '3連複 1-相手1位-相手2位')]
    for cname, mask in cond_masks.items():
        sub = df[mask]
        for k, mk, bname in bets:
            for lo, hi, oname in [(0, 1e9, '全部'), (2.3, 3.5, '2.3〜3.5倍'), (2.3, 1e9, '2.3倍以上')]:
                pays = []
                for _, x in sub.iterrows():
                    key = (int(x['date']), int(x['race']))
                    if key not in odds or key not in win:
                        continue
                    c = mk(x)
                    v = odds[key][k].get(c)
                    if v is None or np.isnan(v) or not (lo <= v < hi):
                        continue
                    pays.append(win[key][k].get(c, 0))
                if len(pays) < 10:
                    continue
                s = A.stats(pays)
                s['roi_ci90'] = A.boot_ci(pays)
                res.append(dict(condition=cname, bet=bname, odds_filter=oname, **s))
    return res


def main(off_dir, out_json, pairs, grade_override=None):
    b, r = A.load(off_dir, grade_override)
    res = {}
    for jcd, d in pairs:
        name = A.VENUE[jcd]
        odds = load_odds(d)
        if not odds:
            continue
        rr = r[r.jcd == jcd]
        win = winners(rr)
        df = A.race_frame(b[b.jcd == jcd], rr)
        df = df[df.date >= min(k[0] for k in odds)]
        c = A.conditions(df)
        masks = {
            '全レース': pd.Series(True, index=df.index),
            '1号艇A1': c['1号艇A1'],
            '1号艇A1 & 他艇にA級なし': c['1号艇A1'] & c['他艇にA級なし'],
            '1号艇A級 & 勝率で1点以上上': c['1号艇A級'] & c['1号艇が勝率で他艇より1点以上上'],
            '1号艇A1 & 展示1位': c['1号艇A1'] & c['1号艇の展示1位(直前情報)'],
            '1号艇A1 & モーター35%以上 & 他艇のA級1人以下': c['1号艇A1'] & c['1号艇モーター35%以上'] & c['他艇のA級1人以下'],
            '他艇にA級なし & 一般戦': c['他艇にA級なし'] & c['一般戦'],
        }
        res[name] = dict(races_with_odds=len(odds), bands=band_table(odds, win), favorites=fav_table(odds, win),
                         fixed=fixed_bets(df, odds, win, masks))
        print('==', name, 'races with odds', len(odds))
        for kind, t in res[name]['bands'].items():
            print(' ', kind, {k: (v['n'], v['hit'], v['roi']) for k, v in t.items()})
        for kind, s in res[name]['favorites'].items():
            print('  1番人気', kind, s)
        for x in res[name]['fixed']:
            if x['odds_filter'] != '全部' and x['hit'] >= 40:
                print('  ', x)
    json.dump(res, open(out_json, 'w'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    args = sys.argv[3:]
    go = None
    if '--grade-override' in args:
        i = args.index('--grade-override')
        go = args[i + 1]
        args = args[:i] + args[i + 2:]
    main(sys.argv[1], sys.argv[2], [(int(a.split('=')[0]), a.split('=')[1]) for a in args], go)
