"""3連単を締切5分前のオッズ帯ごとに全部買った時の的中率・回収率（払戻は公式の確定値）。
usage: python3 -I venues/odds_band_check.py JCD=ODDS_DIR=RACES_CSV [...]
例: python3 -I venues/odds_band_check.py 01=/tmp/mbrace/kb_odds_01=/tmp/mbrace/out/races.csv 24=/tmp/mbrace/kb_odds_24=/tmp/mbrace/out/races.csv 04=/tmp/mbrace/kb_odds_04=/tmp/mbrace/out_hw/races.csv
結果（2026/08〜10、約1,780レース）: 〜6倍 101% / 6-8 88% / 8-12 77% / 12-20 66% / 20-30 75% / 30-50 79% / 50-100 71% / 100〜 56%
"""
import glob, json, sys
import pandas as pd

rows = []
for arg in sys.argv[1:]:
    jd, odir, rc = arg.split('=')
    r = pd.read_csv(rc, low_memory=False); r = r[r.jcd == int(jd)]
    pay = pd.to_numeric(r.tri_pay, errors='coerce')
    res = {(int(a), int(b)): (str(c).replace('-', ''), float(p)) for a, b, c, p in zip(r.date, r.race, r.tri_combo, pay) if p == p}
    for f in glob.glob(f'{odir}/*.json'):
        j = json.load(open(f)); k = (int(j['date']), int(j['race']))
        od = (j.get('tri_by_min') or {}).get('5') or {}
        if k not in res or len(od) < 100:
            continue
        win, p = res[k]
        for c, v in od.items():
            try:
                o = float(v)
            except ValueError:
                continue
            if o > 0:
                rows.append((o, p / 100 if c == win else 0.0))
d = pd.DataFrame(rows, columns=['odds', 'ret'])
d['band'] = pd.cut(d.odds, [0, 6, 8, 12, 20, 30, 50, 100, 1e9], labels=['〜6', '6-8', '8-12', '12-20', '20-30', '30-50', '50-100', '100〜'])
t = d.groupby('band', observed=True).agg(n=('ret', 'size'), 的中率=('ret', lambda s: (s > 0).mean() * 100), 回収率=('ret', lambda s: s.mean() * 100)).round(1)
print(t.to_string())
