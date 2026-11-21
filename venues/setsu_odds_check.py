"""節の日ごと・前半後半ごとの買い方別回収率（締切5分前オッズ、桐生・平和島・大村 2026/08〜10）。
usage: python3 -I venues/setsu_odds_check.py  （先に setsu_day_check.py を実行）
"""
import glob, json, pandas as pd, numpy as np
S = pd.read_pickle('/tmp/mbrace/setsu.pkl')
ph = {(int(j), int(d), int(r)): (p, w.replace('-', ''), pay, r) for j, d, r, p, w, pay in zip(S.jcd, S.date, S.race, S.phase, S.win, S.pay)}
rows = []
for jcd in (1, 4, 24):
    for f in glob.glob(f'/tmp/mbrace/kb_odds_{jcd:02d}/*.json'):
        j = json.load(open(f)); k = (jcd, int(j['date']), int(j['race']))
        od = (j.get('tri_by_min') or {}).get('5') or {}
        if k not in ph or len(od) < 100: continue
        o = {}
        for c, v in od.items():
            try: x = float(v)
            except ValueError: continue
            if x > 0: o[c.replace('-', '')] = x
        p, win, pay, r = ph[k]
        srt = sorted(o.items(), key=lambda t: t[1])
        def ret(sel): return (100*len(sel), pay if win in sel else 0)
        rows.append((jcd, p, r, 'A 30倍以上の安い順6点', *ret([c for c, x in srt if x >= 30][:6])))
        rows.append((jcd, p, r, 'B 20〜50倍(中穴)の安い順6点', *ret([c for c, x in srt if 20 <= x < 50][:6])))
        rows.append((jcd, p, r, 'C 6〜8倍2点+30倍以上4点', *ret([c for c, x in srt if 6 <= x < 8][:2] + [c for c, x in srt if x >= 30][:4])))
        rows.append((jcd, p, r, 'D 8倍以上の安い順6点', *ret([c for c, x in srt if x >= 8][:6])))
        rows.append((jcd, p, r, 'E 6倍以上の安い順6点', *ret([c for c, x in srt if x >= 6][:6])))
d = pd.DataFrame(rows, columns=['jcd', 'phase', 'race', 'kind', 'inv', 'ret'])
f = lambda g: pd.Series({'R': len(g), '回収率': g.ret.sum() / g.inv.sum() * 100, '的中率': (g.ret > 0).mean() * 100})
print(d.groupby('kind').apply(f).round(1).to_string())
print(d.groupby(['kind', 'phase']).apply(f).round(0).unstack('phase')['回収率'].to_string())
d['half'] = np.where(d.race <= 6, '前半', '後半')
print(d.groupby(['kind', 'half']).apply(f).round(0).unstack('half')['回収率'].to_string())
