"""大村・桐生など場ごとの傾向と「勝負レース」候補の検証。

入力: parse.py が作る boats.csv / races.csv
- 払戻は「当たった組み合わせの配当」しか無い (全オッズは無い)。
  そのため「レース前に決められる固定の買い目」(例: 単勝1号艇、2連複1-2) なら、
  当たったか・いくら戻ったかが正確に分かり、回収率も正確に計算できる。
- 条件はレース前に分かる情報だけ (番組表: 級別・勝率・モーター・レース番号・グレード、
  直前情報: 展示タイム順位)。学習期間 (前半約9か月) で条件を選び、テスト期間 (後半約3か月) で評価する。

usage: python analyze.py OUT_DIR(boats.csv, races.csv) SPLIT_DATE(YYYYMMDD) OUT_JSON [GRADE_OVERRIDE_CSV]
"""
import itertools
import json
import re
import sys

import numpy as np
import pandas as pd

VENUE = {24: "大村", 1: "桐生", 4: "平和島", 15: "丸亀"}
SG_WORDS = ['クラシック', 'オールスター', 'グランドチャンピオン', 'オーシャンカップ', 'メモリアル', 'ダービー',
            'チャレンジカップ', 'グランプリ']
G1_WORDS = ['ダイヤモンドカップ', 'レディースチャンピオン', 'ヤングダービー', 'マスターズチャンピオン',
            'ＢＢＣトーナメント', 'クイーンズクライマックス', 'ＧⅠ', 'Ｇ１', '地区選手権', 'チャンピオンカップ']
G2_WORDS = ['ＧⅡ', 'Ｇ２', 'モーターボート大賞', 'レディースオールスター', '秩父宮妃記念杯', 'ＭＢ大賞']
G3_WORDS = ['ＧⅢ', 'Ｇ３', 'オールレディース', 'マスターズリーグ', 'イースタンヤング', 'ウエスタンヤング',
            '企業杯', 'キリンカップ', 'サントリーカップ', 'アサヒビールカップ', 'ＪＲ九州', '日本財団会長杯']


def anniversary_g1(t):
    """競走場そのものの「開設◯周年記念」だけを G1 とする。
    ＢＴＳ・ＭＢＰ・Ｄ・Ｓ など場外発売場の周年記念は一般戦 (周年の数字が小さい)。"""
    m = re.search(r'開設([０-９0-9]+)周年記念', t)
    if not m:
        return False
    n = int(m.group(1).translate(str.maketrans('０１２３４５６７８９', '0123456789')))
    return n >= 50


def grade_of(title):
    t = str(title)
    if anniversary_g1(t):
        return 'G1'
    if 'ボートレース' in t and any(w in t for w in SG_WORDS) or t.startswith('ＳＧ'):
        return 'SG'
    if any(w in t for w in G1_WORDS):
        return 'G1'
    if any(w in t for w in G2_WORDS):
        return 'G2'
    if any(w in t for w in G3_WORDS):
        return 'G3'
    return '一般'


def pct(x):
    return round(float(x) * 100, 1)


def load(d, grade_override=None):
    """grade_override: date,jcd,grade の CSV があれば、大会名からの判定より優先する (正式なグレードが分かる場合)。"""
    b = pd.read_csv(f'{d}/boats.csv')
    r = pd.read_csv(f'{d}/races.csv', dtype=str)
    for c in ('date', 'jcd', 'race', 'wind', 'wave'):
        r[c] = pd.to_numeric(r[c], errors='coerce')
    r['grade'] = r.merge(b.drop_duplicates(['date', 'jcd', 'race'])[['date', 'jcd', 'race', 'title']],
                         on=['date', 'jcd', 'race'], how='left')['title'].map(grade_of).values
    b['grade'] = b['title'].map(grade_of)
    if grade_override:
        g = pd.read_csv(grade_override)
        m = dict(zip(zip(g['date'], g['jcd']), g['grade']))
        b['grade'] = [m.get((dd, jj), gg) for dd, jj, gg in zip(b['date'], b['jcd'], b['grade'])]
        r['grade'] = [m.get((dd, jj), gg) for dd, jj, gg in zip(r['date'], r['jcd'], r['grade'])]
    b['ex_rk'] = b.groupby(['date', 'jcd', 'race'])['ex_time'].rank(method='min')
    return b, r


def first(r, kind):
    """券種の1つ目の組番と払戻 (同着で複数ある時は先頭)。"""
    c = r[f'{kind}_combo'].fillna('').str.split('|')
    p = r[f'{kind}_pay'].fillna('').str.split('|')
    return c, p


# ---------------- 1. 傾向 ----------------
def trends(b, r):
    out = {}
    fin = b[b['finish'].between(1, 6)]
    full = fin.groupby(['date', 'jcd', 'race'])['waku'].transform('count') == 6
    fin = fin[full]
    win = fin[fin['finish'] == 1]
    out['races'] = int(r.shape[0])
    out['days'] = int(r['date'].nunique())
    out['in_win'] = pct((win['entry'] == 1).mean())
    out['win_by_entry'] = {int(k): pct(v) for k, v in win['entry'].value_counts(normalize=True).sort_index().items()}
    out['in_win_by_race'] = {int(k): pct(v) for k, v in win.groupby('race')['entry'].apply(lambda s: (s == 1).mean()).items()}
    w1 = fin[fin['waku'] == 1]
    out['waku1_win_by_class'] = {k: [pct((g['finish'] == 1).mean()), len(g)] for k, g in w1.groupby('cls')}
    out['in_win_by_grade'] = {k: [pct((g['entry'] == 1).mean()), len(g)] for k, g in win.groupby('grade')}
    nige = win[win['entry'] == 1][['date', 'jcd', 'race']]
    sec = fin[fin['finish'] == 2].merge(nige)
    out['second_when_in_wins'] = {int(k): pct(v) for k, v in sec['entry'].value_counts(normalize=True).sort_index().items()}
    out['kimete'] = {k: pct(v) for k, v in r['kimete'].value_counts(normalize=True).items() if v > 0.003}
    tri = pd.to_numeric(first(r, 'tri')[1].str[0], errors='coerce')
    out['manshu_rate'] = pct((tri >= 10000).mean())
    meds = {}
    for k in ('tan', 'exa', 'qui', 'wide', 'tri', 'trio'):
        p = pd.to_numeric(first(r, k)[1].str[0], errors='coerce')
        meds[k] = int(p.median())
    out['pay_median_first'] = meds
    exr = fin.dropna(subset=['ex_rk'])
    out['win_by_ex_rank'] = {int(k): [pct((g['finish'] == 1).mean()), pct((g['finish'] <= 3).mean())] for k, g in exr.groupby('ex_rk') if k <= 6}
    rw = r.merge(win[['date', 'jcd', 'race', 'entry']], on=['date', 'jcd', 'race'])
    rw['wind_bin'] = pd.cut(rw['wind'], [-1, 1, 3, 5, 99], labels=['0-1m', '2-3m', '4-5m', '6m+'])
    rw['wave_bin'] = pd.cut(rw['wave'], [-1, 2, 5, 9, 99], labels=['0-2cm', '3-5cm', '6-9cm', '10cm+'])
    out['in_win_by_wind'] = {str(k): [pct((g['entry'] == 1).mean()), len(g)] for k, g in rw.groupby('wind_bin', observed=True)}
    out['in_win_by_wave'] = {str(k): [pct((g['entry'] == 1).mean()), len(g)] for k, g in rw.groupby('wave_bin', observed=True)}
    out['in_win_by_wind_dir'] = {k: [pct((g['entry'] == 1).mean()), len(g)] for k, g in rw.groupby('wind_dir') if len(g) >= 30}
    return out


# ---------------- 2. 勝負レース ----------------
def race_frame(b, r):
    """1レース1行: 条件に使う列 + 各買い目の払戻 (外れ=0)。"""
    rows = []
    rr = r.set_index(['date', 'jcd', 'race'])
    for key, g in b.groupby(['date', 'jcd', 'race']):
        if len(g) != 6 or key not in rr.index:
            continue
        g = g.sort_values('waku')
        x = rr.loc[key]
        if isinstance(x, pd.DataFrame):
            x = x.iloc[0]
        w = g.set_index('waku')
        others = w.drop(1)
        best2 = int(others['nat_win'].idxmax())               # 2〜6号艇で全国勝率が一番の艇
        best3 = int(others.drop(best2)['nat_win'].idxmax())
        top = int(w['nat_win'].idxmax())
        row = dict(date=key[0], jcd=key[1], race=key[2], grade=g['grade'].iloc[0],
                   c1=w.loc[1, 'cls'], n1=w.loc[1, 'nat_win'], l1=w.loc[1, 'loc_win'], m1=w.loc[1, 'motor_2'],
                   gap1=w.loc[1, 'nat_win'] - others['nat_win'].max(),
                   nA_others=int(others['cls'].str.startswith('A').sum()),
                   ex1=w.loc[1, 'ex_rk'], best2=best2, best3=best3, top=top)
        res = {}
        for kind in ('tan', 'fuku', 'exa', 'qui', 'wide', 'trio'):
            combos = str(x.get(f'{kind}_combo') or '').split('|')
            pays = str(x.get(f'{kind}_pay') or '').split('|')
            res[kind] = {c: int(p) for c, p in zip(combos, pays) if c and p.isdigit()}

        def pay(kind, combo):
            return res[kind].get(combo, 0)

        def unordered(a, bb):
            return '-'.join(map(str, sorted([a, bb])))
        row.update({
            '単勝 1号艇': pay('tan', '1'),
            '単勝 全国勝率1位': pay('tan', str(top)),
            '2連単 1-2': pay('exa', '1-2'),
            '2連単 1-3': pay('exa', '1-3'),
            '2連単 1-相手1位': pay('exa', f'1-{best2}'),
            '2連複 1-2': pay('qui', '1-2'),
            '2連複 1-3': pay('qui', '1-3'),
            '2連複 1-相手1位': pay('qui', unordered(1, best2)),
            '拡連複 1-2': pay('wide', '1-2'),
            '拡連複 1-3': pay('wide', '1-3'),
            '拡連複 1-相手1位': pay('wide', unordered(1, best2)),
            '3連複 1-相手1位-相手2位': pay('trio', '-'.join(map(str, sorted([1, best2, best3])))),
            '3連複 1-2-3': pay('trio', '1-2-3'),
        })
        rows.append(row)
    return pd.DataFrame(rows)


BETS = ['単勝 1号艇', '単勝 全国勝率1位', '2連単 1-2', '2連単 1-3', '2連単 1-相手1位', '2連複 1-2', '2連複 1-3',
        '2連複 1-相手1位', '拡連複 1-2', '拡連複 1-3', '拡連複 1-相手1位', '3連複 1-相手1位-相手2位', '3連複 1-2-3']


def conditions(df):
    """レース前に分かる条件の候補 (名前 → bool Series)。"""
    c = {
        '1号艇A1': df.c1 == 'A1', '1号艇A級': df.c1.str.startswith('A'), '1号艇B級': df.c1.str.startswith('B'),
        '1号艇全国勝率7以上': df.n1 >= 7, '1号艇全国勝率6以上': df.n1 >= 6,
        '1号艇当地勝率7以上': df.l1 >= 7, '1号艇当地勝率6以上': df.l1 >= 6,
        '1号艇モーター40%以上': df.m1 >= 40, '1号艇モーター35%以上': df.m1 >= 35,
        '1号艇が勝率で他艇より1点以上上': df.gap1 >= 1.0, '1号艇が勝率で他艇より0.5点以上上': df.gap1 >= 0.5,
        '他艇にA級なし': df.nA_others == 0, '他艇のA級1人以下': df.nA_others <= 1,
        '1〜4R': df.race <= 4, '5〜8R': df.race.between(5, 8), '9〜12R': df.race >= 9,
        '一般戦': df.grade == '一般', 'グレード戦': df.grade != '一般',
        '1号艇の展示1位(直前情報)': df.ex1 == 1, '1号艇の展示2位以内(直前情報)': df.ex1 <= 2,
    }
    return c


def stats(pays):
    pays = np.asarray(pays, float)
    n = len(pays)
    hits = (pays > 0).sum()
    return dict(n=int(n), hits=int(hits), hit=pct(hits / n) if n else None,
                avg_pay=round(pays[pays > 0].mean() / 100, 2) if hits else None,
                roi=pct(pays.sum() / (100 * n)) if n else None)


def boot_ci(pays, k=3000):
    pays = np.asarray(pays, float)
    if len(pays) == 0:
        return None
    rng = np.random.default_rng(0)
    s = [pays[rng.integers(0, len(pays), len(pays))].sum() / (100 * len(pays)) * 100 for _ in range(k)]
    return [round(np.percentile(s, 5), 1), round(np.percentile(s, 95), 1)]


def search(df, split, min_n=60):
    tr, te = df[df.date < split], df[df.date >= split]
    ctr, cte = conditions(tr), conditions(te)
    names = list(ctr)
    found = []
    for k in (1, 2, 3):
        for combo in itertools.combinations(names, k):
            mtr = np.logical_and.reduce([ctr[c].values for c in combo])
            if mtr.sum() < min_n:
                continue
            for bet in BETS:
                s = stats(tr.loc[mtr, bet])
                if s['hit'] >= 45 and (s['avg_pay'] or 0) >= 2.3 and s['roi'] > 100:
                    found.append((combo, bet, s))
    # 学習期間の回収率の下限 (90%区間の下側) で並べて上位だけテストする
    scored = []
    for combo, bet, s in found:
        mtr = np.logical_and.reduce([ctr[c].values for c in combo])
        lo = boot_ci(tr.loc[mtr, bet].values, 1000)[0]
        scored.append((lo, combo, bet, s))
    scored.sort(key=lambda x: -x[0])
    out = []
    seen = set()
    for lo, combo, bet, s in scored:
        if (bet, combo[:1]) in seen and len(out) >= 5:
            continue
        seen.add((bet, combo[:1]))
        mte = np.logical_and.reduce([cte[c].values for c in combo])
        p = te.loc[mte, bet].values
        out.append(dict(condition=' & '.join(combo), bet=bet, train=s, train_roi_ci90_low=lo,
                        test=stats(p), test_roi_ci90=boot_ci(p)))
        if len(out) >= 10:
            break
    return dict(n_candidates_passing_train=len(found), top=out)


def baseline_table(df, split):
    te = df[df.date >= split]
    tr = df[df.date < split]
    return {bet: dict(train=stats(tr[bet]), test=stats(te[bet])) for bet in BETS}


def main(d, split, out_json, grade_override=None):
    b, r = load(d, grade_override)
    res = {}
    split = int(split)
    for jcd, name in VENUE.items():
        bb, rr = b[b.jcd == jcd], r[r.jcd == jcd]
        if rr.empty:
            continue
        df = race_frame(bb, rr)
        res[name] = dict(
            titles={g: sorted(bb[bb.grade == g]['title'].unique().tolist()) for g in bb['grade'].unique() if g != '一般'},
            trends=trends(bb, rr),
            bets_all_races=baseline_table(df, split),
            search=search(df, split),
            n_train=int((df.date < split).sum()), n_test=int((df.date >= split).sum()),
        )
        print(name, json.dumps(res[name]['trends'], ensure_ascii=False)[:600])
    json.dump(res, open(out_json, 'w'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main(*sys.argv[1:5])
