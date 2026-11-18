import glob, json, pandas as pd, numpy as np
S = pd.read_pickle('/tmp/mbrace/manshu.pkl')
sc = {(int(j), int(d), int(r)): (s, w.replace('-', ''), p) for j, d, r, s, w, p in zip(S.jcd, S.date, S.race, S.score, S.win, S.pay)}
rows = []
for jcd in (1, 4, 24):
    for f in glob.glob(f'/tmp/mbrace/kb_odds_{jcd:02d}/*.json'):
        j = json.load(open(f)); k = (jcd, int(j['date']), int(j['race']))
        od = (j.get('tri_by_min') or {}).get('5') or {}
        if k not in sc or len(od) < 100: continue
        o = {}
        for c, v in od.items():
            try: x = float(v)
            except ValueError: continue
            if x > 0: o[c.replace('-', '')] = x
        s, win, pay = sc[k]; srt = sorted(o.items(), key=lambda t: t[1])
        for name, lo, hi in [('100倍以上の安い順6点', 100, 1e9), ('50〜150倍の安い順6点', 50, 150), ('30倍以上の安い順6点', 30, 1e9)]:
            sel = [c for c, x in srt if lo <= x < hi][:6]
            rows.append((s, name, 100*len(sel), pay if win in sel else 0, pay >= 10000))
d = pd.DataFrame(rows, columns=['score', 'kind', 'inv', 'ret', 'man'])
d['grp'] = np.where(d.score >= 4, '荒れ要素4つ以上', np.where(d.score >= 2, '2〜3', '0〜1'))
print(d.groupby(['kind', 'grp']).apply(lambda g: pd.Series({'R': len(g), '万舟%': g.man.mean()*100, '回収率': g.ret.sum()/g.inv.sum()*100, '的中率': (g.ret>0).mean()*100})).round(1).to_string())
