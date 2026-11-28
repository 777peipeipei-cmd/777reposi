"""グレードレース・グレード選手の特徴量を足したモデルと、今のモデルを比べる。

追加する特徴量 (レース前の出走表の値だけ):
  レース側: is_grade (G1/G3), is_g1, is_g3
  選手側 : SG/G1 の勝率・2連対率・3連対率・出走数・1着数・優出数・優勝数・準優出数
           has_sg  … SG/G1 の成績がある (= グレード戦に出たことがある)。
                     成績が無い選手は率を NaN のままにして、has_sg=0 で区別する (0% と混ぜない)。
           grade_regular … SG/G1 出走 30回以上 または 優出 1回以上
  組み合わせ: grade_regular × 1コース / 4〜6コース、レース内のグレード常連の人数、
              一般戦でグレード常連が自分だけか、レース内の SG/G1 勝率の順位

評価は ev_model.py と同じ: 8〜9月で学習 (日付単位の交差検証で期待値ルールを選ぶ) → 10月で評価。

usage: python grade_model.py FEATURES_CSV RACES_SG_DIR ODDS_DIR TEST_START [OUT_JSON]
"""
import glob
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import ev_model as E  # noqa: E402
from train_eval import FEATURES  # noqa: E402

GRADE_FEATS = ['is_grade', 'is_g1', 'is_g3',
               'has_sg', 'grade_regular', 'sg_win', 'sg_2', 'sg_3', 'sg_starts', 'sg_rank1',
               'sg_yushutsu', 'sg_yusho', 'sg_junyu',
               'gr_in', 'gr_outer', 'n_regular', 'only_regular_in_general', 'sg_win_rk']


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return np.nan


def load_sg(src):
    rows = []
    for f in glob.glob(os.path.join(src, '*.json')):
        d = json.load(open(f))
        for b in d['boats']:
            has = b.get('shoritsu_sg') is not None
            rows.append(dict(
                date=int(d['date']), race=int(d['race']), waku=b['course'],
                has_sg=int(has),
                sg_win=num(b.get('shoritsu_sg')),
                sg_2=num(b.get('fukusho_sg')) * 100 if has else np.nan,
                sg_3=num(b.get('sanren_sg')) * 100 if has else np.nan,
                sg_starts=num(b.get('shinnyu_sg')) if has else 0.0,
                sg_rank1=num(b.get('rank1_count_sg')) if has else 0.0,
                sg_yushutsu=num(b.get('yushutsu_count_sg')) if has else 0.0,
                sg_yusho=num(b.get('yusho_count_sg')) if has else 0.0,
                sg_junyu=num(b.get('junyu_count_sg')) if has else 0.0,
            ))
    return pd.DataFrame(rows)


def add_grade_feats(df, sg):
    df = df.merge(sg, on=['date', 'race', 'waku'], how='left')
    df['has_sg'] = df['has_sg'].fillna(0)
    for c in ('sg_starts', 'sg_rank1', 'sg_yushutsu', 'sg_yusho', 'sg_junyu'):
        df[c] = df[c].fillna(0)
    g = pd.to_numeric(df['grade'], errors='coerce')
    df['is_g1'] = (g == 1).astype(int)
    df['is_g3'] = (g == 3).astype(int)
    df['is_grade'] = (g.isin([0, 1, 2, 3])).astype(int)
    df['grade_regular'] = ((df['sg_starts'] >= 30) | (df['sg_yushutsu'] >= 1)).astype(int)
    df['gr_in'] = df['grade_regular'] * (df['entry'] == 1)
    df['gr_outer'] = df['grade_regular'] * (df['entry'] >= 4)
    grp = df.groupby(['date', 'race'])
    df['n_regular'] = grp['grade_regular'].transform('sum')
    df['only_regular_in_general'] = ((df['is_grade'] == 0) & (df['grade_regular'] == 1) & (df['n_regular'] == 1)).astype(int)
    df['sg_win_rk'] = grp['sg_win'].rank(ascending=False, method='min')   # 成績なしは NaN
    return df


def describe(df):
    """グレード常連とそれ以外の成績 (詳細データ 8〜10月 全体)。"""
    out = {}
    d = df.copy()
    d['win'] = (d['rank'] == 1).astype(int)
    d['who'] = np.where(d['grade_regular'] == 1, 'グレード常連', np.where(d['has_sg'] == 1, 'SG/G1経験少', 'SG/G1経験なし'))
    d['race_type'] = np.where(d['is_g1'] == 1, 'G1', np.where(d['is_g3'] == 1, 'G3', '一般'))
    out['counts'] = d.groupby(['race_type', 'who']).size().unstack(fill_value=0).to_dict()
    t = d.groupby(['who', 'entry'])['win'].agg(['mean', 'count'])
    out['win_by_entry'] = {f'{w}|{c}': [round(r['mean'] * 100, 1), int(r['count'])] for (w, c), r in t.iterrows()}
    t = d[d['entry'] == 1].groupby(['race_type', 'who'])['win'].agg(['mean', 'count'])
    out['in_win'] = {f'{a}|{b}': [round(r['mean'] * 100, 1), int(r['count'])] for (a, b), r in t.iterrows()}
    t = d[d['entry'] >= 4].groupby(['race_type', 'who'])['win'].agg(['mean', 'count'])
    out['outer_win'] = {f'{a}|{b}': [round(r['mean'] * 100, 1), int(r['count'])] for (a, b), r in t.iterrows()}
    # 同じ級別 (A1) の中でもグレード常連は強いか
    a1 = d[d['cls'] == 4]
    t = a1.groupby(['who', a1['entry'] == 1])['win'].agg(['mean', 'count'])
    out['A1_only'] = {f'{w}|1コース={c}': [round(r['mean'] * 100, 1), int(r['count'])] for (w, c), r in t.iterrows()}
    return out


def evaluate_subsets(r_te, probs, rule, grade_of):
    rows = {}
    for name, keep in [('全体', lambda g: True), ('G1', lambda g: g == 1), ('G3', lambda g: g == 3), ('一般', lambda g: g == 99)]:
        idx = [i for i, x in enumerate(r_te) if keep(grade_of[(x['date'], x['race'])])]
        if not idx:
            continue
        sub = [r_te[i] for i in idx]
        p = [probs[i] for i in idx]
        s = E.summarize(E.simulate(sub, p, rule), name)
        wins = sum(int(np.argmax(pp) // 20) + 1 == int(E.KEYS[x['win']][0]) for x, pp in zip(sub, p))
        s['win_hit'] = round(wins / len(sub) * 100, 1)    # 1着的中 (最有力の目の1着艇)
        s['races'] = len(sub)
        rows[name] = s
    return rows


def main(csv, sg_dir, odds_dir, test_start, out_json=None):
    df = pd.read_csv(csv)
    df = df[df['rank'].between(1, 6)]
    df = df[df.groupby(['date', 'race'])['waku'].transform('count') == 6].copy()
    df['y'] = (df['rank'] == 1).astype(int)
    odds = E.load_odds(odds_dir)
    df = E.add_market_feats(df, odds)
    df = add_grade_feats(df, load_sg(sg_dir))
    grade_of = {(d, r): int(g) for (d, r), g in df.groupby(['date', 'race'])['grade'].first().items()}
    tr = df[df['date'] < int(test_start)]
    te = df[df['date'] >= int(test_start)]

    res = dict(describe=describe(df),
               race_counts={k: {str(g): int(n) for g, n in v.drop_duplicates(['date', 'race'])['grade'].value_counts().items()}
                            for k, v in (('train', tr), ('test', te))})
    print('race counts by grade', res['race_counts'])

    for variant, feats in [('現行モデル', FEATURES), ('グレード特徴量あり', FEATURES + GRADE_FEATS)]:
        tro, fold = E.oof_probs(tr, feats)
        r_tr = E.race_table(tro, 'p', odds)
        scored = []
        for rule in E.GRID:
            s = E.summarize(E.simulate(r_tr, [x['pm'] for x in r_tr], rule), rule, boot=False)
            if s['bets'] >= 150:
                scored.append((s['roi'], rule, s))
        scored.sort(key=lambda x: -x[0])
        ev_rule = scored[0][1]

        m = E.boat_model().fit(tr[feats], tr['y'])
        te2 = te.copy()
        p = m.predict_proba(te[feats])[:, 1]
        te2['p'] = p / te2.assign(p=p).groupby(['date', 'race'])['p'].transform('sum')
        r_te = E.race_table(te2, 'p', odds)
        probs = [x['pm'] for x in r_te]
        res[variant] = dict(ev_rule_chosen_on_train=ev_rule, train_roi_of_rule=scored[0][0],
                            top1=evaluate_subsets(r_te, probs, dict(kind='top1'), grade_of),
                            ev=evaluate_subsets(r_te, probs, ev_rule, grade_of))
        print('==', variant, 'EV rule (train)', ev_rule, scored[0][0])
        for k in ('top1', 'ev'):
            for sub, s in res[variant][k].items():
                print('  ', k, sub, {x: s[x] for x in ('races', 'bets', 'hits', 'win_hit', 'hit_rate', 'roi', 'roi_ci90')})
    print(json.dumps(res['describe'], ensure_ascii=False, indent=1))
    if out_json:
        json.dump(res, open(out_json, 'w'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main(*sys.argv[1:5], sys.argv[5] if len(sys.argv) > 5 else None)
