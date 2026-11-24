"""1日の結果を、場ごと・レースごとの表と、場ごとの合計表（Markdown）で出す。
usage: python3 -I live/day_summary.py YYYYMMDD [YYYYMMDD ...]
  notes/picks/<日付>*.tsv を読む（列は見出しの名前で探すので、日によって列が違っても読める）。
  日付を複数渡すと、場ごとの合計はその期間の合計になる。
"""
import csv, glob, os, sys

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dates = sys.argv[1:]
if not dates:
    sys.exit(__doc__)


def num(x):
    try:
        return int(float(str(x).replace(',', '').strip() or 0))
    except ValueError:
        return 0


rows = []
for d in dates:
    for f in sorted(glob.glob(os.path.join(root, 'notes', 'picks', f'{d}*.tsv'))):
        with open(f, encoding='utf-8') as fh:
            for r in csv.DictReader(fh, delimiter='\t'):
                if not r.get('場'):
                    continue
                r['_date'] = d
                rows.append(r)

if not rows:
    sys.exit('記録が見つからない: ' + ' '.join(dates))

order = []
for r in rows:
    if r['場'] not in order:
        order.append(r['場'])

tot = {}
for v in order:
    vr = [r for r in rows if r['場'] == v]
    print(f'### {v}' + (f'（{vr[0].get("節の日", "")}）' if len(dates) == 1 and vr[0].get('節の日') else ''))
    print('| ' + ('日 | ' if len(dates) > 1 else '') + 'R | 分類 | 結果 | 3連単 | 投資 | 払戻 | 収支 |')
    print('|' + ('---|' if len(dates) > 1 else '') + '---|---|---|---|---|---|---|')
    inv = ret = hit = n = man = 0
    for r in sorted(vr, key=lambda r: (r['_date'], num(r['R']))):
        i, p = num(r.get('投資')), num(r.get('払戻'))
        pay = num(r.get('3連単配当'))
        cls = r.get('分類', '')
        if r.get('荒れ要素数'):
            cls += f'（要素{r["荒れ要素数"]}）'
        mark = '○' if p > 0 else ('見送り' if i == 0 else '×')
        res = r.get('1着-2着-3着', '')
        print('| ' + (f'{r["_date"][4:6]}/{r["_date"][6:]} | ' if len(dates) > 1 else '')
              + f'{r["R"]} | {cls} | {res} {mark} | {pay:,}{"（万舟）" if pay >= 10000 else ""} | {i:,} | {p:,} | {p - i:+,} |')
        inv += i; ret += p; hit += p > 0; n += i > 0; man += pay >= 10000
    print(f'| **計** | | {hit}/{n} 的中 | 万舟{man}本 | **{inv:,}** | **{ret:,}** | **{ret - inv:+,}** |' if len(dates) == 1 else
          f'| **計** | | | {hit}/{n} 的中 | 万舟{man}本 | **{inv:,}** | **{ret:,}** | **{ret - inv:+,}** |')
    print()
    tot[v] = (n, hit, inv, ret, man)

print('### 場ごとの合計' + (f'（{dates[0]}〜{dates[-1]}）' if len(dates) > 1 else ''))
print('| 場 | 購入R | 的中 | 投資 | 払戻 | 収支 | 回収率 | 万舟 |')
print('|---|---|---|---|---|---|---|---|')
T = [0, 0, 0, 0, 0]
for v, (n, hit, inv, ret, man) in tot.items():
    print(f'| {v} | {n} | {hit} | {inv:,} | {ret:,} | {ret - inv:+,} | {ret / inv * 100 if inv else 0:.0f}% | {man} |')
    T = [a + b for a, b in zip(T, (n, hit, inv, ret, man))]
print(f'| **合計** | {T[0]} | {T[1]} | {T[2]:,} | {T[3]:,} | **{T[3] - T[2]:+,}** | {T[3] / T[2] * 100 if T[2] else 0:.0f}% | {T[4]} |')
