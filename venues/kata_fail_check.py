"""固いの土台（1号艇A1・風5m未満・枠なり）に、モーター・展示順位・A1の人数を重ねた時の1号艇1着率（公式1年分、5場）。usage: python3 -I venues/kata_fail_check.py"""
import pandas as pd
S = pd.read_pickle('/tmp/mbrace/manshu.pkl')
A = S[(S.b1cls == 'A1') & (S.wind < 5) & S.wakunari.fillna(True).astype(bool)]
def show(n, m):
    d = A[m]; print(f'{n:44s} R={len(d):5d} 1号艇1着 {(d.win.str[0]=="1").mean()*100:5.1f}%  万舟 {d.man.mean()*100:5.1f}%')
show('1号艇A1・風5m未満・枠なり（固いの土台）', A.index == A.index)
show('  + モーター30%未満', A.b1mot < 30)
show('  + モーター40%以上', A.b1mot >= 40)
show('  + 展示5〜6位', A.b1exr >= 5)
show('  + 展示1〜2位', A.b1exr <= 2)
show('  + モーター30%未満 & 展示5〜6位', (A.b1mot < 30) & (A.b1exr >= 5))
show('  + 他にA1が2人以上（A1が3人以上）', A.nA1 >= 3)
show('  + A1が3人以上 & モーター30%未満', (A.nA1 >= 3) & (A.b1mot < 30))
show('  + A1が1人（1号艇だけ）', A.nA1 == 1)
