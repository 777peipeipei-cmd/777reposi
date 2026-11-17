"""周回などの直前情報に「オッズに織り込まれていない情報」があるかを調べる（2026/08〜、5場）。

考え方
- 市場の見立て: 締切5分前の3連単オッズから、各組み合わせの確率 q を出す（1/オッズ を合計1に正規化）。
- 3段階のモデル: 1着 → (1着が決まった時の) 2着 → 3着 を、それぞれ「市場の条件付き確率の対数」＋直前情報の特徴で
  条件付きロジットにする。市場の対数確率の係数が1・他が0なら市場そのもの。
- 直前情報を足して、日付でずらした検証（学習に使っていない日）で対数尤度が良くなるか → 良くなれば「織り込まれていない情報」がある。
- 買う実験: モデル確率 × 5分前オッズ（期待値）が閾値を超える目だけ100円ずつ買い、公式の確定配当で精算。

usage: python3 -I venues/lap_edge.py BOATS_CSV RACES_CSV KB_DIR OUT_JSON
"""
import glob
import itertools
import json
import os
import re
import sys

import numpy as np
import pandas as pd

VENUE = {1: '桐生', 4: '平和島', 12: '住之江', 15: '丸亀', 24: '大村'}
PERMS = [''.join(p) for p in itertools.permutations('123456', 3)]


def num(v):
    m = re.search(r'-?\d*\.?\d+', str(v or ''))
    return float(m.group()) if m else np.nan


def load_kb(kbdir):
    rows, odds = [], {}
    for j in VENUE:
        for f in glob.glob(os.path.join(kbdir, str(j), '*.json')):
            x = json.load(open(f))
            t5 = x['tri_by_min'].get('5') or {}
            if len(t5) < 100 or len(x['chokuzen']) != 6:
                continue
            o = np.array([num(t5.get(k)) for k in PERMS])
            o[~(o > 1.0)] = np.nan                      # 0・欠場などは売れていない扱い
            if np.isnan(o).sum() > 10:
                continue
            odds[(x['date'], j, x['race'])] = o
            for c in x['chokuzen']:
                rows.append(dict(date=x['date'], jcd=j, race=x['race'], waku=int(c['course']),
                                 lap=num(c['shukai']) / 100 if c['shukai'] else np.nan,
                                 turn=num(c['mawariashi']) / 100 if c['mawariashi'] else np.nan,
                                 straight=num(c['chokusen']) / 100 if c['chokusen'] else np.nan,
                                 tenji=num(c['tenji']) / 100 if c['tenji'] else np.nan,
                                 exst=num(c['start']), ex_course=c.get('shinnyuu'), tilt=num(c['chiruto'])))
    return pd.DataFrame(rows), odds


def build(bpath, rpath, kbdir):
    b = pd.read_csv(bpath, low_memory=False)
    r = pd.read_csv(rpath, low_memory=False)
    r['tri_pay1'] = pd.to_numeric(r.tri_pay.astype(str).str.split('|').str[0], errors='coerce')
    r['tri1'] = r.tri_combo.astype(str).str.split('|').str[0].str.replace('-', '')
    kb, odds = load_kb(kbdir)
    keys = ['date', 'jcd', 'race']
    d = b.merge(kb, on=keys + ['waku']).merge(r[keys + ['tri1', 'tri_pay1', 'wind']], on=keys)
    d = d[d.tri1.str.match(r'^[1-6]{3}$') & d.tri_pay1.notna()]
    n = d.groupby(keys).waku.transform('size')
    d = d[n == 6].sort_values(keys + ['waku'])
    g = d.groupby(keys)
    for c in ['lap', 'turn', 'straight', 'tenji']:
        d[c + '_rank'] = g[c].rank(method='min').fillna(3.5)
        d[c + '_z'] = ((d[c] - g[c].transform('mean')) / (g[c].transform('std') + 1e-6)).fillna(0).clip(-3, 3)
    d['lap_top_gap'] = g.lap.transform(lambda s: s.nsmallest(2).diff().iloc[-1] if s.notna().sum() >= 2 else 0).fillna(0)
    d['is_lap1'] = (d.lap_rank == 1).astype(float)
    d['lap1_gap'] = d.is_lap1 * d.lap_top_gap.clip(0, 1)
    d['exst_z'] = ((d.exst - g.exst.transform('mean')) / (g.exst.transform('std') + 1e-6)).fillna(0).clip(-3, 3)
    d['moved'] = (pd.to_numeric(d.ex_course, errors='coerce').fillna(d.waku) != d.waku).astype(float)
    keyl = list(d[keys].drop_duplicates().itertuples(index=False, name=None))
    O = np.array([odds[k] for k in keyl])
    return d, keyl, O


FEATS = ['lap_z', 'turn_z', 'straight_z', 'tenji_z', 'is_lap1', 'lap1_gap', 'exst_z', 'moved']


def market_probs(O):
    q = 1 / np.where(np.isnan(O) | (O <= 1.0), 1e6, O)
    return q / q.sum(1, keepdims=True)


def stage_data(d, keyl, Q, feats):
    """3段階それぞれの (選択肢の特徴, 正解) を作る。特徴の先頭は市場の条件付き確率の対数。"""
    F = d[feats].values.reshape(len(keyl), 6, len(feats)) if feats else np.zeros((len(keyl), 6, 0))
    win = d.tri1.values[::6]
    idx = {p: i for i, p in enumerate(PERMS)}
    S = []
    for st in range(3):
        Xs, ys, ms = [], [], []
        for i in range(len(keyl)):
            pre = win[i][:st]
            cands = [w for w in '123456' if w not in pre]
            mq = []
            for w in cands:
                mq.append(sum(Q[i, idx[p]] for p in PERMS if p[:st + 1] == pre + w))
            mq = np.array(mq) / sum(mq)
            X = np.concatenate([np.log(mq + 1e-9)[:, None], F[i, [int(w) - 1 for w in cands]]], 1)
            pad = 6 - len(cands)
            Xs.append(np.vstack([X, np.zeros((pad, X.shape[1]))]))
            ms.append(np.r_[np.ones(len(cands)), np.zeros(pad)])
            ys.append(np.r_[[1.0 if w == win[i][st] else 0.0 for w in cands], np.zeros(pad)])
        S.append((np.array(Xs), np.array(ys), np.array(ms)))
    return S


def fit(X, Y, M, iters=300, lr=0.3, l2=1e-2):
    w = np.zeros(X.shape[2]); w[0] = 1.0
    for _ in range(iters):
        s = X @ w + np.log(M + 1e-12)
        s -= s.max(1, keepdims=True)
        p = np.exp(s) * M; p /= p.sum(1, keepdims=True)
        g = np.einsum('nk,nkd->d', p - Y, X) / len(X) + l2 * (w - np.r_[1.0, np.zeros(len(w) - 1)])
        w -= lr * g
    return w


def logp(X, Y, M, w):
    s = X @ w + np.log(M + 1e-12)
    s -= s.max(1, keepdims=True)
    p = np.exp(s) * M; p /= p.sum(1, keepdims=True)
    return np.log((p * Y).sum(1) + 1e-12), p


def combo_probs(d, keyl, Q, feats, ws, i):
    """レース i の120通りのモデル確率（3段階の積）。"""
    F = d[feats].values.reshape(len(keyl), 6, len(feats))[i] if feats else np.zeros((6, 0))
    idx = {p: k for k, p in enumerate(PERMS)}
    out = np.zeros(120)

    def stage(pre, st):
        cands = [w for w in '123456' if w not in pre]
        mq = np.array([sum(Q[i, idx[p]] for p in PERMS if p[:st + 1] == pre + w) for w in cands])
        mq /= mq.sum()
        X = np.concatenate([np.log(mq + 1e-9)[:, None], F[[int(w) - 1 for w in cands]]], 1)
        s = X @ ws[st]; s -= s.max(); p = np.exp(s); p /= p.sum()
        return dict(zip(cands, p))
    p1 = stage('', 0)
    for a in p1:
        p2 = stage(a, 1)
        for b_ in p2:
            p3 = stage(a + b_, 2)
            for c in p3:
                out[idx[a + b_ + c]] = p1[a] * p2[b_] * p3[c]
    return out


def cv(d, keyl, Q, feats, fo):
    """日付5分割の検証。学習に使っていない日の対数尤度(レースごと)・120通りの確率・係数を返す。"""
    n = len(keyl)
    S = stage_data(d, keyl, Q, feats)
    ll = np.zeros(n)
    P = np.zeros((n, 120))
    W = []
    for f in range(5):
        tr, te = fo != f, fo == f
        ws = [fit(X[tr], Y[tr], M[tr]) for X, Y, M in S]
        W.append(ws)
        for st, (X, Y, M) in enumerate(S):
            ll[te] += logp(X[te], Y[te], M[te], ws[st])[0]
        for i in np.where(te)[0]:
            P[i] = combo_probs(d, keyl, Q, feats, ws, i)
    wm = {st: dict(zip(['log_market'] + feats, np.round(np.mean([w[k] for w in W], 0), 3).tolist()))
          for k, st in enumerate(['1着', '2着', '3着'])}
    return ll, P, wm


def ci(x, rng, k=1000):
    bs = [x[rng.integers(0, len(x), len(x))].mean() for _ in range(k)]
    return [round(float(np.percentile(bs, 5)), 4), round(float(np.percentile(bs, 95)), 4)]


def betting(P, O, pay, win_ix, rng, ths=(None, 1.0, 1.1, 1.2, 1.3), ranges=((1, 1e9), (6, 1e9), (6, 50))):
    """th=None は「その範囲の目を全部買う」基準。"""
    out = {}
    On = np.nan_to_num(O)
    for th in ths:
        for lo, hi in ranges:
            per = []
            for i in range(len(O)):
                buy = (On[i] >= lo) & (On[i] < hi)
                if th is not None:
                    buy &= np.nan_to_num(P[i] * O[i]) >= th
                k = int(buy.sum())
                if k:
                    per.append((100 * k, pay[i] if buy[win_ix[i]] else 0))
            if not per:
                continue
            per = np.array(per, float)
            bs = [per[ix, 1].sum() / per[ix, 0].sum() for ix in (rng.integers(0, len(per), len(per)) for _ in range(500))]
            name = ('全部買い' if th is None else f'EV>={th}') + f' odds{lo}-{hi if hi < 1e9 else "inf"}'
            out[name] = dict(races=len(per), bets=int(per[:, 0].sum() / 100), roi=round(per[:, 1].sum() / per[:, 0].sum() * 100, 1),
                             hits=int((per[:, 1] > 0).sum()),
                             roi_90=[round(float(np.percentile(bs, 5)) * 100, 1), round(float(np.percentile(bs, 95)) * 100, 1)])
    return out


def main(bpath, rpath, kbdir, out):
    d, keyl, O = build(bpath, rpath, kbdir)
    Q = market_probs(O)
    n = len(keyl)
    dates = np.array([k[0] for k in keyl])
    fold = {dt: i % 5 for i, dt in enumerate(np.unique(dates))}   # 日付ごとに5分割（同じ日は同じ組）
    fo = np.array([fold[x] for x in dates])
    rng = np.random.default_rng(0)
    res = dict(races=int(n), venues={VENUE[j]: int(sum(1 for k in keyl if k[1] == j)) for j in VENUE})
    idx = {p: k for k, p in enumerate(PERMS)}
    win = d.tri1.values[::6]
    win_ix = np.array([idx[w] for w in win])
    pay = d.tri_pay1.values[::6]
    ll_mkt = np.log(Q[np.arange(n), win_ix])
    ll_cal, P_cal, w_cal = cv(d, keyl, Q, [], fo)          # 市場オッズの補正だけ（人気・穴の偏り）
    ll_mod, P_mod, w_mod = cv(d, keyl, Q, FEATS, fo)       # 補正＋周回などの直前情報
    res['loglik_per_race'] = dict(
        market=round(float(ll_mkt.mean()), 4), calib=round(float(ll_cal.mean()), 4), model=round(float(ll_mod.mean()), 4),
        calib_minus_market=round(float((ll_cal - ll_mkt).mean()), 4), calib_minus_market_90=ci(ll_cal - ll_mkt, rng),
        model_minus_calib=round(float((ll_mod - ll_cal).mean()), 4), model_minus_calib_90=ci(ll_mod - ll_cal, rng))
    res['by_venue_model_minus_calib'] = {VENUE[j]: dict(n=int(m.sum()), diff=round(float((ll_mod - ll_cal)[m].mean()), 4), diff_90=ci((ll_mod - ll_cal)[m], rng))
                                         for j in VENUE for m in [np.array([k[1] == j for k in keyl])] if m.sum()}
    res['weights_calib'] = w_cal
    res['weights_model'] = w_mod
    res['betting_calib'] = betting(P_cal, O, pay, win_ix, rng)
    res['betting_model'] = betting(P_mod, O, pay, win_ix, rng, ths=(1.0, 1.1, 1.2, 1.3))
    # 5分前オッズと確定配当のずれ（当たり目）
    o5 = O[np.arange(n), win_ix]
    ok = ~np.isnan(o5)
    res['final_over_5min_median'] = round(float(np.median(pay[ok] / 100 / o5[ok])), 3)
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:5])
