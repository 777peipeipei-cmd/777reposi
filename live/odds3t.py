"""pre5.js の出力から3連単オッズを辞書で取り出す。 usage: python3 -I live/odds3t.py FILE [combo ...]"""
import sys, re
def parse(path):
    t = open(path, encoding='utf-8').read()
    t = t[t.index('===3連単'):t.index('===単勝') if '===単勝' in t else None]
    lines = [l for l in t.split('\n') if l.strip()]
    odds = {}; i = 0
    while i < len(lines):
        m = re.match(r'^([1-6])\t\S', lines[i])
        if m and i + 4 < len(lines):
            first = m.group(1)
            row0 = lines[i+1].split('\t')
            if len(row0) >= 15:
                seconds = []
                for c in range(5):
                    s, th, o = row0[c*3:c*3+3]; seconds.append(s); odds[first+s+th] = o
                for k in range(1, 4):
                    row = lines[i+1+k].split('\t')
                    for c in range(5):
                        if len(row) >= c*2+2:
                            th, o = row[c*2:c*2+2]; odds[first+seconds[c]+th] = o
                i += 5; continue
        i += 1
    return odds
if __name__ == '__main__':
    o = parse(sys.argv[1])
    combos = [c.replace('-', '') for c in sys.argv[2:]] or sorted(o)
    for c in combos: print('-'.join(c), o.get(c, '?'))
