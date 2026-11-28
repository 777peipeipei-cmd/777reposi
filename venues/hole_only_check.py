"""穴だけ買った時の回収率（締切5分前の3連単オッズで買い目を決め、公式の確定配当で精算）。
桐生・平和島・大村 2026/08〜11 の約1,790レース。データは /tmp/mbrace（コミットしない）。
usage: python3 -I venues/hole_only_check.py
"""
import glob, json, sys
import numpy as np, pandas as pd
R = pd.read_csv('/tmp/mbrace/out_all/races.csv', low_memory=False)
B = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False)
R['pay'] = pd.to_numeric(R.tri_pay.astype(str).str.split('|').str[0], errors='coerce')
R['win'] = R.tri_combo.astype(str).str.split('|').str[0].str.replace('-', '')
res = {(int(j), int(d), int(r)): (w, p) for j, d, r, w, p in zip(R.jcd, R.date, R.race, R.win, R.pay) if p == p}
B['exr'] = B.groupby(['date', 'jcd', 'race']).ex_time.rank(method='min')
bk = {}
for (d, j, r), g in B.groupby(['date', 'jcd', 'race']):
    bk[(int(j), int(d), int(r))] = g.set_index('waku')
races = []
for jcd in (1, 4, 24):
    for f in glob.glob(f'/tmp/mbrace/kb_odds_{jcd:02d}/*.json'):
        j = json.load(open(f)); k = (jcd, int(j['date']), int(j['race']))
        od = (j.get('tri_by_min') or {}).get('5') or {}
        if k not in res or len(od) < 100: continue
        o = {}
        for c, v in od.items():
            try: x = float(v)
            except ValueError: continue
            if x > 0: o[c.replace('-', '')] = x
        races.append((k, o))
print('races', len(races))
def run(name, pick):
    inv = ret = hit = n = 0; per = []
    for k, o in races:
        win, pay = res[k]
        sel = pick(k, o)
        if not sel: continue
        n += 1; i = 100 * len(sel); r = pay if win in sel else 0
        inv += i; ret += r; hit += r > 0; per.append(r - i)
        
    per = np.array(per); cum = per.cumsum(); dd = (np.maximum.accumulate(np.r_[0, cum])[1:] - cum).max()
    # longest losing streak
    s = m = 0
    for x in per:
        s = s + 1 if x < 0 else 0; m = max(m, s)
    # bootstrap 90% CI of ROI
    rng = np.random.default_rng(0); stakes = None
    print(f'{name}\tR={n}\t的中率={hit/n*100:.1f}%\t回収率={ret/inv*100:.0f}%\t収支={ret-inv:+,}\t最大連敗={m}\t最大ドローダウン={dd:,.0f}')
def cheapest_in(lo, hi, k=6):
    return lambda key, o: [c for c, x in sorted(o.items(), key=lambda t: t[1]) if lo <= x < hi][:k]
run('参考: 人気順上位6点（全部）', lambda key, o: [c for c, x in sorted(o.items(), key=lambda t: t[1])][:6])
run('参考: 今の方針(8倍以上で安い順6点)', cheapest_in(8, 1e9))
for lo, hi in [(20, 1e9), (30, 1e9), (50, 1e9), (100, 1e9), (30, 100)]:
    run(f'穴: {lo}倍以上{"" if hi>1e8 else f"{hi}倍未満"}の安い順6点', cheapest_in(lo, hi))
run('穴: 100倍以上を全部', lambda key, o: [c for c, x in o.items() if x >= 100])
def bten(key, o):
    g = bk.get(key)
    if g is None: return []
    cand = [w for w in g.index if w != 1 and str(g.loc[w, 'cls']).startswith('B') and g.loc[w, 'exr'] == 1]
    if not cand: return []
    h = str(int(cand[0]))
    return [c for c, x in sorted(o.items(), key=lambda t: t[1]) if c[0] == h and x >= 20][:6]
run('穴: B級の展示1位(2〜6号艇)を1着にした20倍以上の安い順6点', bten)
def bten2(key, o):
    g = bk.get(key)
    if g is None: return []
    cand = [w for w in g.index if w != 1 and str(g.loc[w, 'cls']).startswith('B') and g.loc[w, 'exr'] == 1]
    if not cand: return []
    h = str(int(cand[0]))
    return [c for c, x in sorted(o.items(), key=lambda t: t[1]) if h in c[:2] and x >= 20][:6]
run('穴: B級の展示1位を1・2着に入れた20倍以上の安い順6点', bten2)
def wk1weak(key, o):
    g = bk.get(key)
    if g is None or 1 not in g.index or not str(g.loc[1, 'cls']).startswith('B'): return []
    return [c for c, x in sorted(o.items(), key=lambda t: t[1]) if c[0] != '1' and x >= 20][:6]
run('穴: 1号艇B級のレースだけ、1号艇以外1着の20倍以上6点', wk1weak)
print('--- 30倍以上の安い順6点: 区間・場・月')
f = cheapest_in(30, 1e9)
rows = []
for k, o in races:
    win, pay = res[k]; sel = f(k, o)
    rows.append((k[0], k[1] // 100, 100 * len(sel), pay if win in sel else 0))
d = pd.DataFrame(rows, columns=['jcd', 'ym', 'inv', 'ret'])
rng = np.random.default_rng(0); bs = []
for _ in range(2000):
    s = d.sample(len(d), replace=True, random_state=rng.integers(1e9)); bs.append(s.ret.sum() / s.inv.sum() * 100)
print('90%区間', np.percentile(bs, [5, 95]).round(0))
print(d.groupby('jcd').apply(lambda g: round(g.ret.sum() / g.inv.sum() * 100)).to_string())
print(d.groupby('ym').apply(lambda g: round(g.ret.sum() / g.inv.sum() * 100)).to_string())
top = d[d.ret > 0].sort_values('ret', ascending=False).ret
print('当たり上位5本で払戻の', round(top.head(5).sum() / d.ret.sum() * 100), '%  総払戻', d.ret.sum())
