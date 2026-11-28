"""オッズ込みモデル（回収率狙い）。

流れ
 1. 艇ごとの1着確率モデル (勾配ブースティング)。特徴量は build_dataset.py のものに、
    締切5分前の3連単オッズから逆算した「市場の1着確率」とその順位を足したもの。
 2. Harville (Plackett-Luce) で 120 通りの3連単確率 p_model を作る。
 3. 締切5分前の3連単オッズから市場確率 p_mkt = (1/odds) を正規化したものを作る。
 4. Benter 型の合成: P(c) ∝ exp(a·log p_model + b·log p_mkt) を条件付きロジットで推定。
 5. 期待値 EV = P(c) × odds(5分前) が閾値を超える組み合わせを買う。
    閾値・オッズ上限・1レースの最大点数は学習期間 (8〜9月) の交差検証だけで決め、
    10月 (テスト) では一切調整しない。

払戻は実際の確定払戻 (結果の3連単配当)。判断に使うのは締切5分前オッズなので、
「最終オッズで判断した」より現実に近いが、それでも締切直前の変動は再現できない。

usage: python ev_model.py FEATURES_CSV ODDS_DIR TEST_START [OUT_JSON]
"""
import glob
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, os.path.dirname(__file__))
from train_eval import FEATURES  # noqa: E402

PERMS = list(itertools.permutations(range(1, 7), 3))   # 枠番の並び 120通り
KEYS = [f'{a}{b}{c}' for a, b, c in PERMS]
ODDS_MIN_BEFORE = '5'    # 判断に使うオッズ (締切何分前か)
MKT_FEATS = ['mkt_win', 'mkt_win_rk', 'mkt_win_logit']


# ---------- データ ----------
def load_odds(odds_dir):
    out = {}
    for f in glob.glob(os.path.join(odds_dir, '*.json')):
        j = json.load(open(f))
        ts = j.get('tri_by_min', {})
        src = ts.get(ODDS_MIN_BEFORE) or ts.get('10') or {}
        o = np.array([float(src.get(k, 0) or 0) for k in KEYS])
        if (o <= 0).sum() > 20:          # 5分前オッズが無い → 使わない
            continue
        o[o <= 0] = np.nan
        out[(int(j['date']), int(j['race']))] = o
    return out


def market_probs(o):
    q = np.where(np.isnan(o), 0, 1 / np.nan_to_num(o, nan=np.inf))
    return q / q.sum()


def add_market_feats(df, odds):
    rows = []
    for (d, r), g in df.groupby(['date', 'race']):
        o = odds.get((d, r))
        if o is None:
            continue
        q = market_probs(o)
        win = np.zeros(6)
        for (a, _, _), v in zip(PERMS, q):
            win[a - 1] += v
        for w in range(1, 7):
            rows.append((d, r, w, win[w - 1]))
    m = pd.DataFrame(rows, columns=['date', 'race', 'waku', 'mkt_win'])
    df = df.merge(m, on=['date', 'race', 'waku'], how='inner')
    df['mkt_win_rk'] = df.groupby(['date', 'race'])['mkt_win'].rank(ascending=False, method='min')
    df['mkt_win_logit'] = np.log(df['mkt_win'].clip(1e-4, 1 - 1e-4) / (1 - df['mkt_win'].clip(1e-4, 1 - 1e-4)))
    return df


# ---------- モデル ----------
def boat_model():
    return HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=250,
                                          l2_regularization=1.0, random_state=0)


def harville(p):
    p = np.clip(np.asarray(p, float), 1e-6, None)
    p = p / p.sum()
    return np.array([p[a - 1] * p[b - 1] / (1 - p[a - 1]) * p[c - 1] / (1 - p[a - 1] - p[b - 1])
                     for a, b, c in PERMS])


def race_table(df, pcol, odds):
    """レースごとに 120 通りの p_model, p_mkt, odds, 的中フラグ, 払戻 を並べる。"""
    races = []
    for (d, r), g in df.groupby(['date', 'race']):
        g = g.sort_values('waku')
        if len(g) != 6 or (d, r) not in odds or not isinstance(g['tri_combo'].iloc[0], str):
            continue
        o = odds[(d, r)]
        pm = harville(g[pcol].values)
        races.append(dict(date=d, race=r, pm=pm, pq=market_probs(o), odds=o,
                          win=KEYS.index(g['tri_combo'].iloc[0].replace('-', '')),
                          pay=float(g['tri_pay'].iloc[0]), cls1=int(g['cls'].iloc[0])))
    return races


def fit_benter(races):
    lm = np.array([np.log(np.clip(x['pm'], 1e-9, None)) for x in races])
    lq = np.array([np.log(np.clip(x['pq'], 1e-9, None)) for x in races])
    y = np.array([x['win'] for x in races])

    def nll(w):
        s = w[0] * lm + w[1] * lq
        s -= s.max(1, keepdims=True)
        ls = s - np.log(np.exp(s).sum(1, keepdims=True))
        return -ls[np.arange(len(y)), y].sum()
    return minimize(nll, x0=[0.5, 0.5], method='Nelder-Mead').x


def combine(race, w):
    s = w[0] * np.log(np.clip(race['pm'], 1e-9, None)) + w[1] * np.log(np.clip(race['pq'], 1e-9, None))
    s = np.exp(s - s.max())
    return s / s.sum()


# ---------- 買い方 ----------
def bets_for(race, p, rule):
    o = race['odds']
    kind = rule['kind']
    if kind == 'top1':
        return [int(np.argmax(p))]
    if kind == 'topN':
        return list(np.argsort(-p)[:rule['n']])
    if kind == 'favorite':
        return [int(np.nanargmin(o))]
    if kind == 'ev':
        ev = p * o
        ok = (~np.isnan(o)) & (ev >= rule['thr']) & (o <= rule['omax']) & (o >= rule.get('omin', 1))
        idx = np.where(ok)[0]
        return list(idx[np.argsort(-ev[idx])][:rule['maxn']])
    if kind == 'edge':
        # 市場確率に対してモデル確率が何倍か (p / p_mkt) が閾値以上のものを買う
        ed = p / np.clip(race['pq'], 1e-9, None)
        ok = (~np.isnan(o)) & (ed >= rule['thr']) & (o <= rule['omax'])
        idx = np.where(ok)[0]
        return list(idx[np.argsort(-ed[idx])][:rule['maxn']])
    raise ValueError(kind)


def simulate(races, probs, rule):
    per = []
    for race, p in zip(races, probs):
        b = bets_for(race, p, rule)
        ret = race['pay'] if race['win'] in b else 0.0
        per.append((len(b), ret, int(race['win'] in b)))
    per = np.array(per, float)
    return per


def summarize(per, label, boot=True):
    n_bets = per[:, 0].sum()
    stake = n_bets * 100
    ret = per[:, 1].sum()
    out = dict(rule=label, races_bet=int((per[:, 0] > 0).sum()), bets=int(n_bets), hits=int(per[:, 2].sum()),
               hit_rate=round(per[:, 2].sum() / max(n_bets, 1) * 100, 2),
               roi=round(ret / stake * 100, 1) if stake else None,
               profit=int(ret - stake))
    if boot and stake:
        rng = np.random.default_rng(0)
        bs = []
        for _ in range(3000):
            s = per[rng.integers(0, len(per), len(per))]
            st = s[:, 0].sum() * 100
            if st:
                bs.append(s[:, 1].sum() / st * 100)
        out['roi_ci90'] = [round(np.percentile(bs, 5), 1), round(np.percentile(bs, 95), 1)]
    return out


GRID = [dict(kind=k, thr=t, omax=om, maxn=mn)
        for k, ts in (('ev', (0.8, 0.9, 1.0, 1.1, 1.2, 1.5, 2.0)), ('edge', (1.2, 1.5, 2.0, 3.0)))
        for t in ts
        for om in (30, 60, 100, 200, 500)
        for mn in (1, 2, 3, 5)]


def oof_probs(tr, feats, k=5):
    """学習期間内で日付単位の k 分割 → 艇モデルの OOF 確率。"""
    days = np.array(sorted(tr['date'].unique()))
    fold = {d: i % k for i, d in enumerate(days)}
    f = tr['date'].map(fold)
    p = np.zeros(len(tr))
    for i in range(k):
        m = boat_model().fit(tr.loc[f != i, feats], tr.loc[f != i, 'y'])
        p[(f == i).values] = m.predict_proba(tr.loc[f == i, feats])[:, 1]
    tr = tr.copy()
    tr['p'] = p / tr.assign(p=p).groupby(['date', 'race'])['p'].transform('sum')
    return tr, f


def main(csv, odds_dir, test_start, out_json=None):
    df = pd.read_csv(csv)
    df = df[df['rank'].between(1, 6)]
    df = df[df.groupby(['date', 'race'])['waku'].transform('count') == 6].copy()
    df['y'] = (df['rank'] == 1).astype(int)
    odds = load_odds(odds_dir)
    df = add_market_feats(df, odds)
    tr = df[df['date'] < int(test_start)].copy()
    te = df[df['date'] >= int(test_start)].copy()

    results = {}
    for variant, feats in [('model', FEATURES), ('model+odds', FEATURES + MKT_FEATS)]:
        # --- 学習期間: OOF 確率 → Benter 合成も日付分割で交差推定 → 買い方を選ぶ
        tro, fold = oof_probs(tr, feats)
        r_tr = race_table(tro, 'p', odds)
        rfold = np.array([fold[tro.index[(tro.date == x['date']) & (tro.race == x['race'])][0]] for x in r_tr])
        comb_tr = [None] * len(r_tr)
        for i in range(5):
            w = fit_benter([x for x, f in zip(r_tr, rfold) if f != i])
            for j in np.where(rfold == i)[0]:
                comb_tr[j] = combine(r_tr[j], w)
        model_tr = [x['pm'] for x in r_tr]
        best = {}
        for name, probs in [('model_only', model_tr), ('benter', comb_tr)]:
            scored = []
            for rule in GRID:
                s = summarize(simulate(r_tr, probs, rule), rule, boot=False)
                if s['bets'] >= 150:            # 少なすぎる買い方は選ばない
                    scored.append((s['roi'], rule, s))
            scored.sort(key=lambda x: -x[0])
            best[name] = scored[0] if scored else (None, dict(kind='top1'), {'bets': 0})

        # --- テスト: 学習期間全体で再学習、合成の重みも学習期間全体で推定
        m = boat_model().fit(tr[feats], tr['y'])
        te2 = te.copy()
        p = m.predict_proba(te[feats])[:, 1]
        te2['p'] = p / te2.assign(p=p).groupby(['date', 'race'])['p'].transform('sum')
        r_te = race_table(te2, 'p', odds)
        w_all = fit_benter(r_tr)
        comb_te = [combine(x, w_all) for x in r_te]
        model_te = [x['pm'] for x in r_te]
        mkt_te = [x['pq'] for x in r_te]

        rows = [
            summarize(simulate(r_te, model_te, dict(kind='top1')), 'モデル 1点 (最有力)'),
            summarize(simulate(r_te, comb_te, dict(kind='top1')), '合成 1点 (最有力)'),
            summarize(simulate(r_te, comb_te, dict(kind='topN', n=3)), '合成 上位3点'),
            summarize(simulate(r_te, comb_te, dict(kind='topN', n=5)), '合成 上位5点'),
            summarize(simulate(r_te, mkt_te, dict(kind='favorite')), '1番人気だけ'),
            summarize(simulate(r_te, model_te, best['model_only'][1]),
                      f"EV モデルのみ {best['model_only'][1]}"),
            summarize(simulate(r_te, comb_te, best['benter'][1]),
                      f"EV 合成 {best['benter'][1]}"),
        ]
        results[variant] = dict(test_races=len(r_te), train_races=len(r_tr),
                                benter_weights=[round(float(x), 3) for x in w_all],
                                chosen_on_train={k: dict(rule=v[1], train=v[2]) for k, v in best.items()},
                                test=rows)
        print(f'== {variant}: train {len(r_tr)}R, test {len(r_te)}R, benter w={w_all.round(3)}')
        for k, v in best.items():
            print('  chosen on train', k, v[1], 'train ROI', v[0], 'bets', v[2].get('bets'))
        for r in rows:
            print('  ', r)
    if out_json:
        json.dump(results, open(out_json, 'w'), ensure_ascii=False, indent=1, default=str)
    return results


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
