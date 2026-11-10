"""「固い／荒れそう」の判定基準を過去データに当てて、外れる要因を調べる。
データ: kyoteibiyori 直前情報（2026/08〜10、桐生・平和島・大村・丸亀・住之江）＋公式データ。
固い = 1号艇が周回1位で2位との差が0.8%以上（1周計測で約0.3秒、桐生は約0.15秒）かつ風5m未満。
usage: python3 -I venues/class_check.py
"""
import glob, json, re
import numpy as np
import pandas as pd

b = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False)
r = pd.read_csv('/tmp/mbrace/out_all/races.csv', low_memory=False)
r['tri_pay'] = pd.to_numeric(r.tri_pay, errors='coerce'); r['tri_pop'] = pd.to_numeric(r.tri_pop, errors='coerce')
st = pd.read_csv('/home/user/777reposi/live/racer_style.csv').set_index('登番')
rows = []
for jd in ['01', '04', '24', '15', '12']:
    for f in glob.glob(f'/tmp/mbrace/kb_detail_{jd}/*.json'):
        d = json.load(open(f)); ch = d.get('chokuzen') or []
        if len(ch) != 6: continue
        try:
            sh = {int(c['course']): int(c['shukai']) for c in ch}
            tj = {int(c['course']): int(c['tenji']) for c in ch}
        except Exception: continue
        if min(sh.values()) <= 0: continue
        s = sorted(sh.values()); rk = pd.Series(sh).rank(method='min'); trk = pd.Series(tj).rank(method='min')
        def stv(x):
            m = re.search(r'(\d*\.\d+)', str(x)); v = float(m.group(1)) if m else np.nan
            return -v if 'F' in str(x) else v
        ex_st = {int(c['course']): stv(c.get('start')) for c in ch}
        w = re.search(r'\d+', str(ch[0].get('wind_speed') or '')); wind = int(w.group()) if w else np.nan
        ent = {int(c['course']): int(c['shinnyuu']) for c in ch if c.get('shinnyuu')}
        rows.append(dict(jcd=int(jd), date=int(d['date']), race=int(d['race']), r1=rk[1], gap1=(s[1] - sh[1]) / sh[1] * 100 if rk[1] == 1 else -(sh[1] - s[0]) / s[0] * 100,
                         rk2=rk[2], rk3=rk[3], rk4=rk[4], rk=dict(rk), trk1=trk[1], st1=ex_st[1], st_best_other=np.nanmin([abs(ex_st[k]) for k in (2, 3, 4)]),
                         wind=wind, nari=(len(ent) == 6 and all(k == v for k, v in ent.items()))))
x = pd.DataFrame(rows)
k = ['date', 'jcd', 'race']
one = b[b.waku == 1][k + ['racer', 'cls', 'age', 'motor_2']].rename(columns={'cls': 'cls1', 'age': 'age1', 'motor_2': 'motor1', 'racer': 'racer1'})
fin = b[b.finish.between(1, 3)].pivot_table(index=k, columns='finish', values='waku', aggfunc='first').rename(columns={1.0: 'w1', 2.0: 'w2', 3.0: 'w3'}).reset_index()
oth = b[b.waku.between(2, 6)].groupby(k).apply(lambda g: pd.Series({'nA1_oth': (g.cls == 'A1').sum(), 'A1_34': ((g.cls == 'A1') & g.waku.isin([3, 4])).sum()})).reset_index()
x = x.merge(one, on=k).merge(fin, on=k).merge(oth, on=k).merge(r[k + ['tri_pay', 'tri_pop', 'kimete', 'race_type_k']], on=k)
x['c1'] = x.racer1.map(st['c1_1着'])
x['win1'] = x.w1 == 1; x['man'] = x.tri_pay >= 10000
x['kata'] = (x.r1 == 1) & (x.gap1 >= 0.8) & (x.wind < 5)
x['are'] = (x.cls1.isin(['B1', 'B2']) & (x.r1 >= 4)) | (x.wind >= 7)
x['grp'] = np.where(x.kata, '固い', np.where(x.are, '荒れそう', '中間'))
x.to_pickle('/tmp/mbrace/class_check.pkl')
def agg(g):
    return pd.Series({'R': len(g), '1号艇1着%': round(g.win1.mean() * 100, 1), '1号艇3着内%': round(((g.w1 == 1) | (g.w2 == 1) | (g.w3 == 1)).mean() * 100, 1),
                      '万舟%': round(g.man.mean() * 100, 1), '配当中央値': g.tri_pay.median(), '6番人気以内%': round((g.tri_pop <= 6).mean() * 100, 1)})
print('== 分類ごとの結果'); print(x.groupby('grp').apply(agg).to_string())
kt = x[x.kata].copy()
print('\n== 固い判定のレース: 要因ごとの1号艇1着率')
kt['級別'] = kt.cls1; kt['年齢'] = np.where(kt.age1 >= 50, '50歳〜', '〜49歳')
kt['イン'] = pd.cut(kt.c1, [-99, -5, 5, 99], labels=['イン苦手', '普通', 'イン得意'])
kt['展示ST'] = pd.cut(kt.st1, [-9, -0.001, 0.10, 0.17, 9], labels=['F', '〜.10', '.11〜.17', '.18〜（遅い）'])
kt['差'] = pd.cut(kt.gap1, [0, 1.2, 1.8, 99], labels=['0.3〜0.45秒', '0.45〜0.65秒', '0.65秒〜'])
kt['展示タイム順位'] = np.where(kt.trk1 <= 2, '2位以内', '3位以下')
kt['外にA1'] = np.where(kt.A1_34 > 0, '3・4号艇にA1あり', 'なし')
kt['2・3号艇の周回'] = np.where((kt.rk2 <= 3) | (kt.rk3 <= 3), '2か3号艇が周回3位以内', 'どちらも4位以下')
kt['進入'] = np.where(kt.nari, '枠なり', '前付けあり')
kt['モーター'] = pd.cut(kt.motor1, [-1, 0.01, 30, 40, 101], labels=['0', '〜30', '30-40', '40〜'])
kt['場'] = kt.jcd.map({1: '桐生', 4: '平和島', 24: '大村', 15: '丸亀', 12: '住之江'})
kt['R帯'] = pd.cut(kt.race, [0, 4, 8, 12], labels=['1-4R', '5-8R', '9-12R'])
for c in ['場', 'R帯', '級別', '年齢', 'イン', '展示ST', '差', '展示タイム順位', '外にA1', '2・3号艇の周回', '進入', 'モーター']:
    t = kt.groupby(c, observed=True).apply(lambda g: pd.Series({'R': len(g), '1着%': round(g.win1.mean() * 100, 1), '万舟%': round(g.man.mean() * 100, 1)}))
    print('-', c); print(t.to_string())
w = kt[kt.win1]
print('\n== 固い判定で1号艇が逃げた時（', len(w), 'R）')
print('2着の枠:', (w.w2.value_counts(normalize=True) * 100).round(1).sort_index().to_dict())
print('3着の枠:', (w.w3.value_counts(normalize=True) * 100).round(1).sort_index().to_dict())
w2rk = [row.rk[int(row.w2)] for row in w.itertuples()]; w3rk = [row.rk[int(row.w3)] for row in w.itertuples()]
print('2着艇の周回順位:', (pd.Series(w2rk).value_counts(normalize=True) * 100).round(1).sort_index().to_dict())
print('3着艇の周回順位:', (pd.Series(w3rk).value_counts(normalize=True) * 100).round(1).sort_index().to_dict())
print('配当: 中央値', w.tri_pay.median(), ' 6番人気以内', round((w.tri_pop <= 6).mean() * 100, 1), '%  10番人気以内', round((w.tri_pop <= 10).mean() * 100, 1), '%  万舟', round(w.man.mean() * 100, 1), '%')
l = kt[~kt.win1]
print('\n== 固い判定で1号艇が負けた時（', len(l), 'R）: 決まり手', (l.kimete.value_counts(normalize=True) * 100).round(1).to_dict(), ' 1着の枠', (l.w1.value_counts(normalize=True) * 100).round(1).sort_index().to_dict())
