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
    q = 1 / np.where(np.isnan(O), 1e6, O)
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


def main(bpath, rpath, kbdir, out):
    d, keyl, O = build(bpath, rpath, kbdir)
    Q = market_probs(O)
    n = len(keyl)
    dates = np.array([k[0] for k in keyl])
    ud = np.unique(dates)
    fold = {dt: i % 5 for i, dt in enumerate(ud)}          # 日付ごとに5分割（同じ日は同じ組）
    fo = np.array([fold[x] for x in dates])
    res = dict(races=int(n), venues={VENUE[j]: int(sum(1 for k in keyl if k[1] == j)) for j in VENUE})
    # 市場だけの対数尤度（3連単の当たり目）
    idx = {p: k for k, p in enumerate(PERMS)}
    win = d.tri1.values[::6]
    ll_mkt = np.array([np.log(Q[i, idx[win[i]]]) for i in range(n)])
    S = stage_data(d, keyl, Q, FEATS)
    ll_mod = np.zeros(n)
    W = []
    P = np.zeros((n, 120))
    for f in range(5):
        tr, te = fo != f, fo == f
        ws = [fit(X[tr], Y[tr], M[tr]) for X, Y, M in S]
        W.append(ws)
        for st, (X, Y, M) in enumerate(S):
            ll_mod[te] += logp(X[te], Y[te], M[te], ws[st])[0]
        for i in np.where(te)[0]:
            P[i] = combo_probs(d, keyl, Q, FEATS, ws, i)
    diff = ll_mod - ll_mkt
    rng = np.random.default_rng(0)
    bs = [diff[rng.integers(0, n, n)].mean() for _ in range(1000)]
    res['loglik_per_race'] = dict(market=round(float(ll_mkt.mean()), 4), model=round(float(ll_mod.mean()), 4),
                                  diff=round(float(diff.mean()), 4), diff_90=[round(float(np.percentile(bs, 5)), 4), round(float(np.percentile(bs, 95)), 4)])
    res['weights_mean'] = {st: dict(zip(['log_market'] + FEATS, np.round(np.mean([w[k] for w in W], 0), 3).tolist()))
                           for k, st in enumerate(['1着', '2着', '3着'])}
    # 買う実験
    pay = d.tri_pay1.values[::6]
    res['betting'] = {}
    for th in [1.0, 1.1, 1.2, 1.3, 1.5]:
        for lo, hi in [(1, 1e9), (6, 1e9), (6, 50)]:
            inv = ret = hits = 0
            per = []
            for i in range(n):
                ev = P[i] * O[i]
                buy = (ev >= th) & (O[i] >= lo) & (O[i] < hi)
                k = int(buy.sum())
                if not k:
                    continue
                r_ = pay[i] if buy[idx[win[i]]] else 0
                inv += 100 * k; ret += r_; hits += r_ > 0
                per.append((100 * k, r_))
            if not per:
                continue
            per = np.array(per)
            bs = [per[ix, 1].sum() / per[ix, 0].sum() for ix in (rng.integers(0, len(per), len(per)) for _ in range(500))]
            res['betting'][f'EV>={th} odds{lo}-{hi if hi < 1e9 else "inf"}'] = dict(
                races=len(per), bets=int(inv / 100), roi=round(ret / inv * 100, 1), hits=int(hits),
                roi_90=[round(float(np.percentile(bs, 5)) * 100, 1), round(float(np.percentile(bs, 95)) * 100, 1)])
    # 市場の確率どおりに全部買った時（基準）と、5分前→確定の差
    res['baseline_all_combos_roi'] = round(float(sum(pay) / (100 * 120 * n)) * 100, 1)
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(*sys.argv[1:5])
