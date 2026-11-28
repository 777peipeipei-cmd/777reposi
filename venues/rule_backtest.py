"""live/README.md の買い方（固い／荒れそう／中間、6点800円、低オッズ除外、高オッズ2点に200円）を
機械的なルールにして、公式データ1年分で回収率を出す。

公式データには各組み合わせのオッズが無いので、次の近似を使う（結果の読み方に注意）:
- 艇の強さを条件付きロジット（1着になる確率）で学習し、2・3着は Harville 式で3連単の確率を出す。
- 推定オッズ = 0.75 / 推定確率（控除25%）。低オッズ除外と「高い2点に200円」はこの推定オッズで決める。
- 当たった目だけは実際の払戻（公式の確定配当）で精算する。当たり目の実配当が除外ラインより低ければ「買っていない」扱い。
- 周回タイムは公式に無いので、展示タイムで代用。枠なりは本番の進入で判定（レース前には完全には分からない）。

usage: python3 -I venues/rule_backtest.py BOATS_CSV RACES_CSV OUT_JSON
"""
import itertools
import json
import sys

import numpy as np
import pandas as pd

VENUE = {1: '桐生', 4: '平和島', 12: '住之江', 15: '丸亀', 24: '大村'}
TEST_FROM = 20260801
ROUGH_R = {4: {1, 2, 3, 4, 7, 8}, 1: {1, 2, 3, 4, 5, 8}, 12: {2, 3, 4, 6, 7, 8}, 15: {2, 3, 4, 5, 6, 7}, 24: set()}


# ---------------- データ ----------------
def load(bpath, rpath):
    b = pd.read_csv(bpath, low_memory=False)
    r = pd.read_csv(rpath, low_memory=False)
    r['tri_pay1'] = pd.to_numeric(r.tri_pay.astype(str).str.split('|').str[0], errors='coerce')
    r['tri_combo1'] = r.tri_combo.astype(str).str.split('|').str[0]
    r = r.dropna(subset=['tri_pay1'])
    r = r[r.tri_combo1.str.match(r'^[1-6]-[1-6]-[1-6]$')]
    b = b[b.jcd.isin(VENUE)]
    cnt = b.groupby(['date', 'jcd', 'race']).waku.transform('size')
    b = b[(cnt == 6)].copy()
    b['ex_rank'] = b.groupby(['date', 'jcd', 'race']).ex_time.rank(method='min')
    b['ex_gap'] = b.groupby(['date', 'jcd', 'race']).ex_time.transform(lambda s: s.nsmallest(2).diff().iloc[-1] if s.notna().sum() >= 2 else np.nan)
    keys = ['date', 'jcd', 'race']
    b = b.merge(r[keys + ['wind', 'race_type_k', 'tri_combo1', 'tri_pay1']], on=keys, how='inner')
    return b.sort_values(keys + ['waku'])


def features(b):
    X = []
    for w in range(1, 7):
        for j in VENUE:
            X.append(((b.waku == w) & (b.jcd == j)).astype(float).rename(f'w{w}_{j}'))
    for c in ['A1', 'A2', 'B1']:
        X.append((b.cls == c).astype(float).rename(c))
    X.append(b.nat_win.rename('nat_win'))
    X.append(b.loc_win.clip(0, 9).rename('loc_win'))
    X.append((b.motor_2 / 10).rename('motor'))
    exr = b.ex_rank.fillna(3.5)
    X.append(exr.rename('ex_rank'))
    X.append((exr == 1).astype(float).rename('ex1'))
    X.append(((b.age >= 50) & (b.waku == 1)).astype(float).rename('old_in'))
    X.append(((b.wind >= 6) & (b.waku == 1)).astype(float).rename('wind_in'))
    return pd.concat(X, axis=1).fillna(0).values


def fit_clogit(X, y, n, iters=400, lr=0.5, l2=1e-3):
    """条件付きロジット（レースごとに6艇でsoftmax、1着を当てる）。X: (n*6, k)"""
    Xr = X.reshape(n, 6, -1)
    mu, sd = Xr.reshape(-1, Xr.shape[2]).mean(0), Xr.reshape(-1, Xr.shape[2]).std(0) + 1e-9
    Z = (Xr - mu) / sd
    Y = y.reshape(n, 6)
    w = np.zeros(Z.shape[2])
    for _ in range(iters):
        s = Z @ w
        s -= s.max(1, keepdims=True)
        p = np.exp(s); p /= p.sum(1, keepdims=True)
        g = np.einsum('nk,nkd->d', p - Y, Z) / n + l2 * w
        w -= lr * g
    return lambda Xn: _pred(Xn, w, mu, sd)


def _pred(X, w, mu, sd):
    Z = (X.reshape(-1, 6, X.shape[1]) - mu) / sd
    s = Z @ w
    s -= s.max(1, keepdims=True)
    p = np.exp(s)
    return p / p.sum(1, keepdims=True)


def harville(p):
    out = {}
    for a, b_, c in itertools.permutations(range(6), 3):
        out[f'{a+1}-{b_+1}-{c+1}'] = p[a] * p[b_] / (1 - p[a]) * p[c] / (1 - p[a] - p[b_])
    return out


# ---------------- 分類と買い目 ----------------
def classify(x, jcd, race):
    b1 = x.iloc[0]
    if (jcd not in (4,) and not (jcd == 1 and race <= 5)
            and b1.ex_rank == 1 and b1.ex_gap >= 0.05 and b1.wind < 5 and b1.cls == 'A1'
            and b1.age < 50 and (x.entry.values == x.waku.values).all()):
        return '固い'
    n = 0
    n += b1.cls in ('B1', 'B2')
    n += b1.motor_2 < 30
    n += b1.wind >= 7
    n += race in ROUGH_R[jcd]
    n += bool(((x.cls.isin(['B1', 'B2'])) & (x.ex_rank == 1) & (x.waku != 1)).any())
    return '荒れそう' if n >= 2 else '中間'


def candidates(cls, x, p, prob, mode):
    """分類ごとの候補の目（優先順）。mode で変形版を切り替える。"""
    order = list(np.argsort(-p) + 1)                         # モデルの強さ順
    exo = list(x.sort_values('ex_time').waku.astype(int))    # 展示順
    if cls == '固い':
        s = [2, 3, 4]
        c = [f'1-{a}-{b}' for a in s for b in s if a != b]
        return sorted(c, key=lambda k: -prob[k]), 4
    if cls == '荒れそう':
        hole = [w for w in exo if w != 1 and x.set_index('waku').loc[w, 'cls'] in ('B1', 'B2')][:1]
        A = hole[0] if hole else [w for w in exo if w != 1][0]
        B = [w for w in order if w != A][0]
        rest = [w for w in order if w not in (A, B)]
        c = [f'{A}-{B}-{r}' for r in rest] + [f'{B}-{A}-{r}' for r in rest]
        return sorted(c, key=lambda k: -prob[k]), 6
    # 中間
    b1 = x.iloc[0]
    if b1.cls in ('A1', 'A2') or order[0] == 1:
        if mode == 'second3':
            s2 = [2, 3, 4]
        else:
            s2 = [2, 3] + [w for w in exo if w in (4, 5, 6)][:1]
        s3 = sorted(set(s2) | set([w for w in exo if w in (5, 6)][:1]) | {2, 3, 4})
        c = [f'1-{a}-{b}' for a in s2 for b in s3 if a != b]
        return sorted(c, key=lambda k: -prob[k]), 6
    B = [w for w in order if w != 1][0]
    rest = [w for w in order if w not in (1, B)]
    c = [f'1-{B}-{r}' for r in rest] + [f'{B}-1-{r}' for r in rest]
    return sorted(c, key=lambda k: -prob[k]), 6


def run(b, p_all, mode='base', floor=8.0, heavy=True, cls_only=None):
    rows = []
    for i, ((date, jcd, race), x) in enumerate(b.groupby(['date', 'jcd', 'race'], sort=False)):
        p = p_all[i]
        prob = harville(p)
        cls = classify(x, jcd, race) if cls_only is None else cls_only
        if mode == 'fav6':
            cand, k = sorted(prob, key=lambda c: -prob[c]), 6
        else:
            cand, k = candidates(cls, x, p, prob, mode)
        est = {c: 0.75 / prob[c] for c in cand}
        win, pay = x.tri_combo1.iloc[0], x.tri_pay1.iloc[0]
        if win in est:
            est[win] = pay / 100            # 当たり目は実配当を使う
        picks = [c for c in cand if est[c] >= floor][:k]
        if not picks:
            rows.append(dict(date=date, jcd=jcd, race=race, cls=cls, inv=0, ret=0))
            continue
        top2 = set(sorted(picks, key=lambda c: -est[c])[:2]) if heavy and len(picks) > 2 else set()
        amt = {c: (200 if c in top2 else 100) for c in picks}
        ret = pay / 100 * amt[win] if win in amt else 0
        rows.append(dict(date=date, jcd=jcd, race=race, cls=cls, inv=sum(amt.values()), ret=ret, hit=win in amt))
    return pd.DataFrame(rows)


def summ(d):
    d = d[d.inv > 0]
    if len(d) == 0:
        return dict(n=0)
    roi = d.ret.sum() / d.inv.sum()
    # レース単位のブートストラップで回収率の90%区間
    rng = np.random.default_rng(0)
    inv, ret = d.inv.values, d.ret.values
    bs = [ret[ix].sum() / inv[ix].sum() for ix in (rng.integers(0, len(d), len(d)) for _ in range(500))]
    return dict(n=int(len(d)), hit=round(float(d.hit.mean()) * 100, 1), roi=round(roi * 100, 1),
                lo=round(float(np.percentile(bs, 5)) * 100, 1), hi=round(float(np.percentile(bs, 95)) * 100, 1),
                avg_hit_pay=int(d[d.ret > 0].ret.mean()) if (d.ret > 0).any() else 0, profit=int(d.ret.sum() - d.inv.sum()))


def main(bpath, rpath, out):
    b = load(bpath, rpath)
    n = len(b) // 6
    X = features(b)
    y = (b.finish == 1).astype(float).values
    keys = b[['date', 'jcd', 'race']].iloc[::6]
    tr = (keys.date < TEST_FROM).values
    trmask = np.repeat(tr, 6)
    model = fit_clogit(X[trmask], y[trmask], int(tr.sum()))
    P = model(X)
    # 推定オッズの当てはまり（当たり目の推定 vs 実配当）
    chk = []
    for i, (_, x) in enumerate(b.groupby(['date', 'jcd', 'race'], sort=False)):
        if not tr[i]:
            pr = harville(P[i])
            chk.append((np.log(0.75 / pr[x.tri_combo1.iloc[0]]), np.log(x.tri_pay1.iloc[0] / 100)))
    chk = np.array(chk)
    res = dict(races=int(n), train=int(tr.sum()), test=int((~tr).sum()),
               odds_corr=round(float(np.corrcoef(chk[:, 0], chk[:, 1])[0, 1]), 3),
               fav1_win_test=round(float((P[~tr].argmax(1) == b.finish.values.reshape(n, 6)[~tr].argmin(1)).mean()) * 100, 1))
    variants = {
        '今のルール（8倍未満除外・高い2点200円）': dict(),
        '同じ・除外ライン6倍': dict(floor=6.0),
        '同じ・除外ライン15倍': dict(floor=15.0),
        '同じ・均等買い(100円×6)': dict(heavy=False),
        '中間の2着候補を2・3・4に固定': dict(mode='second3'),
        '比較: モデル上位6点・除外なし': dict(mode='fav6', floor=0.0, heavy=False),
    }
    res['variants'] = {}
    for name, kw in variants.items():
        d = run(b, P, **kw)
        d['test'] = d.date >= TEST_FROM
        ent = dict(all=summ(d), test=summ(d[d.test]))
        ent['by_cls'] = {c: summ(d[d.cls == c]) for c in ['固い', '荒れそう', '中間']}
        ent['by_venue'] = {VENUE[j]: summ(d[d.jcd == j]) for j in VENUE}
        res['variants'][name] = ent
        print(name, ent['all'], ent['test'], flush=True)
    json.dump(res, open(out, 'w'), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != 'variants'}, ensure_ascii=False))


if __name__ == '__main__':
    main(*sys.argv[1:4])
