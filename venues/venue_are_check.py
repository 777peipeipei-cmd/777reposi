import pandas as pd, numpy as np
S = pd.read_pickle('/tmp/mbrace/manshu.pkl')
S['wave'] = pd.to_numeric(S.wave, errors='coerce')
S['b1B'] = S.b1cls.str.startswith('B')
S['b1ex56'] = S.b1exr >= 5
S['wind5'] = S.wind >= 5
S['wind7'] = S.wind >= 7
S['wave5'] = S.wave >= 5
S['mot30'] = S.b1mot < 30
S['init'] = S.phase == '1初日'
S['last'] = S.phase == '5最終日'
S['nonwaku'] = ~S.wakunari.fillna(True).astype(bool)
S['front'] = S.race <= 5
S['A1zero'] = S.nA1 == 0
F = {'1号艇B級':'b1B','1号艇展示5-6位':'b1ex56','風5m+':'wind5','風7m+':'wind7','波5cm+':'wave5','1号艇モーター<30%':'mot30','初日':'init','最終日':'last','B級の展示1位あり':'bex1','枠なりでない':'nonwaku','1〜5R':'front','A1が0人':'A1zero'}
VEN={1:'桐生',4:'平和島',12:'住之江',15:'丸亀',24:'大村'}
rows=[]
for j,v in VEN.items():
    d=S[S.jcd==j]; base=d.man.mean()*100
    r={'場':v,'R':len(d),'万舟%':round(base,1)}
    for k,c in F.items():
        m=d[d[c].astype(bool)]
        r[k]=f'{m.man.mean()*100-base:+.0f}({len(m)})' if len(m)>=30 else '-'
    rows.append(r)
print(pd.DataFrame(rows).set_index('場').T.to_string())
# 今のスコア(4以上)の場ごとの万舟率
S['score_now'] = S[['b1B','b1ex56','wind5','mot30','init','bex1','nonwaku']].astype(int).sum(axis=1)
print('\n今の荒れ要素（7つ）ごとの万舟率 % (レース数)')
t = S.groupby(['jcd', S.score_now.clip(upper=5)]).man.agg(['mean','size'])
print(t.assign(mean=lambda x:(x['mean']*100).round(1)).unstack(0).to_string())
print('\n== 場ごとの要素（1年分で+3ポイント以上の要素だけ）で数え直し、前半8か月で選び後半4か月で確かめる')
S['d'] = S.date.astype(int)
tr = S[S.d < 20260701]; te = S[S.d >= 20260701]
pick = {}
for j, v in VEN.items():
    a = tr[tr.jcd == j]; base = a.man.mean()
    ks = [c for c in F.values() if a[a[c].astype(bool)].shape[0] >= 30 and a[a[c].astype(bool)].man.mean() - base >= 0.03]
    pick[j] = ks
    b = te[te.jcd == j].copy(); b['sc'] = b[ks].astype(int).sum(axis=1) if ks else 0
    b_now = b.score_now >= 4
    name = {v2: k2 for k2, v2 in F.items()}
    print(f'{v}: 要素 {[name[k] for k in ks]}')
    for th in (2, 3, 4):
        m = b[b.sc >= th]
        if len(m) >= 15: print(f'   {th}つ以上: 検証 {len(m)}R 万舟 {m.man.mean()*100:.1f}%  (検証期間の全体 {b.man.mean()*100:.1f}%)')
    print(f'   今の基準(7要素4つ以上): 検証 {b_now.sum()}R 万舟 {b[b_now].man.mean()*100:.1f}%')
