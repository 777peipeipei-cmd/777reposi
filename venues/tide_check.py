"""潮の満ち引きとレース結果の関係（平和島・大村、kyoteibiyori 直前情報の満潮/干潮時刻を使用）
usage: python3 -I venues/tide_check.py DETAIL_DIR JCD BOATS_CSV RACES_CSV [RESULTS_DIR_WITH_SHIMEKIRI]
締切時刻: RESULTS_DIR（平和島の results/*.json の shimekiri）が無い場合は、その場の標準的な締切時刻で近似する。
"""
import json, os, sys, glob
import pandas as pd

APPROX = {  # 1R〜12Rの標準締切（分）
    '24': [15*60+28, 15*60+57, 16*60+24, 16*60+51, 17*60+17, 17*60+48, 18*60+17, 18*60+48, 19*60+16, 19*60+48, 20*60+17, 20*60+45],
    '04': [10*60+52, 11*60+20, 11*60+48, 12*60+16, 12*60+44, 13*60+12, 13*60+40, 14*60+9, 14*60+41, 15*60+15, 15*60+43, 16*60+14],
}
HALF = 6 * 60 + 12  # 満潮→干潮のおおよその間隔（分）

def mins(s):
    try:
        h, m = s.split(':'); return int(h) * 60 + int(m)
    except Exception:
        return None

def phase(t, ch):
    """t: 締切（分）。ch: chokuzen（満潮/干潮時刻）。戻り値: ('上げ潮'/'下げ潮', 満潮または干潮からの経過分)"""
    ev = []
    for k in ('mancho1_jikan', 'mancho2_jikan'):
        m = mins(ch.get(k, '')); ev += [(m, 'H')] if m is not None else []
    for k in ('kancho1_jikan', 'kancho2_jikan'):
        m = mins(ch.get(k, '')); ev += [(m, 'L')] if m is not None else []
    if not ev:
        return None, None
    # 足りない山・谷を前後に補う
    more = []
    for m, k in ev:
        other = 'L' if k == 'H' else 'H'
        more += [(m - HALF, other), (m + HALF, other), (m - 2 * HALF, k), (m + 2 * HALF, k)]
    ev = sorted(set(ev + more))
    prev = [e for e in ev if e[0] <= t]
    if not prev:
        return None, None
    m, k = prev[-1]
    return ('下げ潮' if k == 'H' else '上げ潮'), t - m

def main(ddir, jcd, boats_csv, races_csv, resdir=None):
    boats = pd.read_csv(boats_csv, dtype={'jcd': str}); races = pd.read_csv(races_csv, dtype={'jcd': str})
    boats = boats[boats.jcd.str.zfill(2) == jcd]; races = races[races.jcd.str.zfill(2) == jcd]
    rows = []
    for f in glob.glob(os.path.join(ddir, '*.json')):
        d = json.load(open(f)); date, r = int(d['date']), int(d['race'])
        b0 = (d.get('boats') or [{}])[0]
        ch = b0 if 'kancho1_jikan' in b0 else (d.get('chokuzen') or [{}])[0]
        if isinstance(ch, list): ch = ch[0] if ch else {}
        t = None
        if resdir:
            rf = os.path.join(resdir, f"{date}_{r}.json")
            if os.path.exists(rf):
                t = mins(json.load(open(rf))['boats'][0].get('shimekiri', ''))
        if t is None:
            t = APPROX[jcd][r - 1]
        ph, el = phase(t, ch)
        rows.append(dict(date=date, race=r, phase=ph, elapsed=el, shio=ch.get('shio')))
    tide = pd.DataFrame(rows).dropna(subset=['phase'])
    w = boats[boats.finish == 1][['date', 'race', 'entry']].rename(columns={'entry': 'win_entry'})
    df = tide.merge(w, on=['date', 'race']).merge(races[['date', 'race', 'tri_pay', 'kimete']], on=['date', 'race'])
    df['tri_pay'] = pd.to_numeric(df.tri_pay.astype(str).str.replace(',', ''), errors='coerce')
    df['win_entry'] = pd.to_numeric(df.win_entry, errors='coerce')
    df['in1'] = df.win_entry == 1; df['man'] = df.tri_pay >= 10000
    df['near'] = pd.cut(df.elapsed, [-1, 90, 270, 999], labels=['転換直後(〜1.5h)', '中間', '転換前(4.5h〜)'])
    out = {}
    for key in ['phase', 'shio', 'near']:
        g = df.groupby(key).agg(R=('in1', 'size'), 一コース1着率=('in1', 'mean'), 万舟率=('man', 'mean'), 三連単中央値=('tri_pay', 'median'))
        g['一コース1着率'] = (g['一コース1着率'] * 100).round(1); g['万舟率'] = (g['万舟率'] * 100).round(1)
        out[key] = g
        print(f'== {key}'); print(g.to_string())
    g = pd.crosstab(df.phase, df.win_entry, normalize='index').mul(100).round(1)
    print('== 潮の向き × 1着の進入コース(%)'); print(g.to_string())
    print('races', len(df))

if __name__ == '__main__':
    main(*sys.argv[1:])
