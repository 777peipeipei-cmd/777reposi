"""展示の進入（前付け）とスロー/ダッシュの数がレース結果に与える影響。
usage: python3 -I venues/entry_check.py DETAIL_DIR JCD BOATS_CSV RACES_CSV
DETAIL_DIR: kyoteibiyori 直前情報キャッシュ（chokuzen に course=枠, shinnyuu=展示進入, slow_dash=1:スロー/2:ダッシュ）
"""
import json, os, sys, glob
import pandas as pd

def main(ddir, jcd, boats_csv, races_csv):
    boats = pd.read_csv(boats_csv, dtype={'jcd': str}); boats = boats[boats.jcd.str.zfill(2) == jcd]
    races = pd.read_csv(races_csv, dtype={'jcd': str}); races = races[races.jcd.str.zfill(2) == jcd]
    races['tri_pay'] = pd.to_numeric(races.tri_pay.astype(str).str.replace(',', ''), errors='coerce')
    rows = []
    for f in glob.glob(os.path.join(ddir, '*.json')):
        d = json.load(open(f)); ch = d.get('chokuzen') or []
        if len(ch) != 6: continue
        sd = [c.get('slow_dash') for c in ch]
        ent = {int(c['course']): int(c['shinnyuu']) for c in ch if c.get('shinnyuu')}
        if len(ent) != 6 or None in sd: continue
        n_dash = sum(1 for x in sd if int(x) == 2)
        waku_nari = all(k == v for k, v in ent.items())
        mae = [k for k, v in ent.items() if v < k]  # 内側のコースを取った艇（前付け）
        # ダッシュの先頭（カド）= ダッシュ艇のうち最も内側の展示進入
        dash_courses = sorted(int(c['shinnyuu']) for c in ch if int(c.get('slow_dash') or 0) == 2)
        kado = dash_courses[0] if dash_courses else None
        rows.append(dict(date=int(d['date']), race=int(d['race']), n_dash=n_dash, waku_nari=waku_nari,
                         maetsuke=len(mae) > 0, kado=kado))
    ex = pd.DataFrame(rows)
    fin = boats[boats.finish.between(1, 6)][['date', 'race', 'waku', 'entry', 'finish']]
    win = fin[fin.finish == 1][['date', 'race', 'entry']].rename(columns={'entry': 'win_entry'})
    df = ex.merge(win, on=['date', 'race']).merge(races[['date', 'race', 'tri_pay']], on=['date', 'race'])
    df['in1'] = df.win_entry == 1; df['man'] = df.tri_pay >= 10000
    df['kado_win'] = df.win_entry == df.kado
    def show(key):
        g = df.groupby(key).agg(R=('in1', 'size'), 一コース1着率=('in1', 'mean'), カド1着率=('kado_win', 'mean'), 万舟率=('man', 'mean'))
        for c in ['一コース1着率', 'カド1着率', '万舟率']: g[c] = (g[c] * 100).round(1)
        print(f'== {key}'); print(g.to_string())
    show('n_dash'); show('waku_nari'); show('kado')
    print('races', len(df))

if __name__ == '__main__':
    main(*sys.argv[1:])
