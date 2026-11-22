"""場ごとの1着コース・決まり手（公式1年分、5場）。usage: python3 -I venues/course_kimete_check.py"""
import pandas as pd, numpy as np
R = pd.read_csv('/tmp/mbrace/out_all/races.csv', low_memory=False)
B = pd.read_csv('/tmp/mbrace/out_all/boats.csv', low_memory=False, usecols=['date','jcd','race','waku','entry','finish'])
R = R[R.jcd.isin([1,4,12,15,24])]
B = B[B.jcd.isin([1,4,12,15,24])]
VEN={1:'桐生',4:'平和島',12:'住之江',15:'丸亀',24:'大村'}
w = B[B.finish==1]
print('== 1着のコース（進入）%')
print((pd.crosstab(w.jcd.map(VEN), w.entry, normalize='index')*100).round(1).to_string())
print('\n== 1着の枠番 %')
print((pd.crosstab(w.jcd.map(VEN), w.waku, normalize='index')*100).round(1).to_string())
print('\n== 決まり手 %')
print((pd.crosstab(R.jcd.map(VEN), R.kimete, normalize='index')*100).round(1).to_string())
# 平和島: コース別の決まり手
m = w.merge(R[['date','jcd','race','kimete','tri_pay']], on=['date','jcd','race'])
print('\n== 平和島・1着コース別の決まり手（件数）')
print(pd.crosstab(m[m.jcd==4].entry, m[m.jcd==4].kimete).to_string())
print('\n== 2・4・6コースの1着 % (平和島 vs 5場平均)')
for c in (2,4,6):
    print(c, 'コース', round((w[w.jcd==4].entry==c).mean()*100,1), '/', round((w.entry==c).mean()*100,1))
