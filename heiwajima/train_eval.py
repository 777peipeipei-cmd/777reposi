"""時系列分割で (a) ルール予想 と (b) 機械学習モデル を比較する。

各艇の1着確率をモデルで出し、Plackett-Luce で120通りの3連単確率を計算して
一番確率の高い1点を買う想定で評価する (100円/レース)。

usage: python train_eval.py FEATURES_CSV TEST_START(YYYYMMDD) [OUT_JSON]
"""
import itertools
import json
import sys

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

FEATURES = [
    'entry', 'waku', 'cls', 'age', 'weight', 'grade',
    'nat_win', 'nat_2', 'nat_3', 'loc_win', 'loc_2', 'loc_3',
    'motor_2', 'motor_3', 'boat_2', 'boat_3', 'avg_st', 'recent_win',
    'c_win', 'c_2', 'c_3', 'c_st', 'zenken',
    'ex_time', 'ex_st', 'lap', 'turn', 'straight', 'tilt', 'wind', 'wave',
    'ex_time_rk', 'lap_rk', 'turn_rk', 'straight_rk', 'nat_win_rk', 'motor_2_rk', 'loc_win_rk',
    'ex_time_dev', 'lap_dev', 'turn_dev', 'straight_dev', 'nat_win_dev', 'motor_2_dev', 'loc_win_dev',
    'race',
]
# コース別成績 (c_*) はサイトが「現在の値」を返している可能性があるので外した版も作る
NO_COURSE_STATS = [f for f in FEATURES if not f.startswith('c_')]

ENTRY_W = {1: 3.0, 2: 1.2, 3: 1.0, 4: 0.7, 5: 0.3, 6: 0.0}


def rule_score(df):
    """10/31 の手作業予想と同じルール。"""
    s = df['entry'].map(ENTRY_W).fillna(0)
    s += 0.6 * df['nat_win'].fillna(4.5) + 0.15 * df['loc_win'].where(df['loc_win'] > 0, df['nat_win']).fillna(4.5)
    s += 0.02 * df['motor_2'].fillna(35) + 0.01 * df['boat_2'].fillna(35)
    s += 0.12 * (3.5 - df['ex_time_rk'].fillna(3.5))
    s += -0.9 * (df['avg_st'].fillna(0.16) - 0.15) * 10
    return s


def pl_best(p):
    """6艇の1着確率 → Plackett-Luce で最も確率の高い3連単 (枠番の並び)."""
    p = np.clip(np.asarray(p, float), 1e-6, None)
    p = p / p.sum()
    best, bp = None, -1
    for i, j, k in itertools.permutations(range(6), 3):
        v = p[i] * p[j] / (1 - p[i]) * p[k] / (1 - p[i] - p[j])
        if v > bp:
            best, bp = (i, j, k), v
    return best, bp


def evaluate(test, score_col, label):
    res = []
    for (d, r), g in test.groupby(['date', 'race']):
        g = g.sort_values('waku')
        if g['rank'].isna().any() or not isinstance(g['tri_combo'].iloc[0], str):
            continue
        s = g[score_col].values
        if score_col.startswith('p_'):
            (i, j, k), _ = pl_best(s)
        else:
            i, j, k = np.argsort(-s)[:3]
        w = g['waku'].values
        pick = f'{w[i]}-{w[j]}-{w[k]}'
        actual = g['tri_combo'].iloc[0]
        a = [int(x) for x in actual.split('-')]
        res.append(dict(date=d, race=r, pick=pick, actual=actual,
                        win_hit=int(w[i]) == a[0],
                        tri_hit=pick == actual,
                        trio_hit=set(map(int, pick.split('-'))) == set(a),
                        pay=g['tri_pay'].iloc[0] if pick == actual else 0))
    r = pd.DataFrame(res)
    n = len(r)
    return dict(model=label, races=n,
                win_hit=round(r.win_hit.mean() * 100, 1),
                trifecta_hit=round(r.tri_hit.mean() * 100, 1),
                trio_hit=round(r.trio_hit.mean() * 100, 1),
                roi=round(r.pay.sum() / (100 * n) * 100, 1)), r


def main(csv, test_start, out_json=None):
    df = pd.read_csv(csv)
    df = df[df['rank'].between(1, 6)]           # 欠場・失格などを除く
    full = df.groupby(['date', 'race'])['waku'].transform('count') == 6
    df = df[full].copy()
    df['y'] = (df['rank'] == 1).astype(int)
    tr = df[df['date'] < int(test_start)].copy()
    te = df[df['date'] >= int(test_start)].copy()
    print(f'train {tr.groupby(["date","race"]).ngroups} races ({tr.date.min()}-{tr.date.max()}), '
          f'test {te.groupby(["date","race"]).ngroups} races ({te.date.min()}-{te.date.max()})')

    te['rule'] = rule_score(te)
    te['entry1'] = -te['entry']   # 「1-2-3 固定」ベースライン

    def norm(p, frame):
        return p / frame.assign(p=p).groupby(['date', 'race'])['p'].transform('sum')

    models = {
        'p_logit': (make_pipeline(SimpleImputer(), StandardScaler(), LogisticRegression(C=0.3, max_iter=2000)), FEATURES),
        'p_gbm': (HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300,
                                                 l2_regularization=1.0, random_state=0), FEATURES),
        'p_gbm_nocourse': (HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=300,
                                                          l2_regularization=1.0, random_state=0), NO_COURSE_STATS),
    }
    for name, (m, feats) in models.items():
        m.fit(tr[feats], tr['y'])
        te[name] = norm(m.predict_proba(te[feats])[:, 1], te)

    summary, details = [], {}
    for col, label in [('entry1', '1-2-3固定'), ('rule', 'ルール(10/31版)'),
                       ('p_logit', 'ロジスティック回帰'), ('p_gbm', '勾配ブースティング'),
                       ('p_gbm_nocourse', '勾配ブースティング(コース別成績なし)')]:
        s, r = evaluate(te, col, label)
        summary.append(s)
        details[label] = r
        print(s)

    # 特徴量の効き具合 (permutation importance は重いので GBM の単純な代替: ロジスティック係数)
    lr = models['p_logit'][0]
    coef = sorted(zip(FEATURES, lr[-1].coef_[0]), key=lambda x: -abs(x[1]))[:12]
    print('logit top coefs:', [(f, round(c, 2)) for f, c in coef])

    if out_json:
        json.dump(dict(summary=summary, logit_top=[(f, round(float(c), 3)) for f, c in coef]),
                  open(out_json, 'w'), ensure_ascii=False, indent=1)
    return te, details


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
