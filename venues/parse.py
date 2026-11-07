"""公式オープンデータの番組表 (B) と競走成績 (K) を、指定した場だけ 1艇1行 / 1レース1行の CSV にする。

- 文字コード cp932、固定長テキスト。場ごとに "24BBGN"〜"24BEND" / "24KBGN"〜"24KEND" で区切られる。
- 番組表 (レース前に分かる情報): 登番・名前・年齢・支部・体重・級別・全国/当地 勝率と2連率・モーター/ボート番号と2連率
- 競走成績 (結果): 着順・進入・展示タイム・ST・決まり手・天候/風/波・全券種の払戻と人気

usage: python parse.py RAW_DIR OUT_DIR JCD [JCD ...]
"""
import glob
import os
import re
import sys
import unicodedata

import lhafile
import pandas as pd

Z2H = str.maketrans('０１２３４５６７８９ＲＨｍ：', '0123456789RHm:')


def read_lzh(path):
    z = lhafile.Lhafile(path)
    info = z.infolist()[0]
    return z.read(info.filename).decode('cp932', errors='replace')


def blocks(text, jcd, kind):
    """場コード jcd の BGN〜END ブロックを返す。"""
    m = re.search(rf'^{jcd}{kind}BGN\s*$(.*?)^{jcd}{kind}END', text, flags=re.S | re.M)
    return m.group(1) if m else None


# ---------------- 番組表 ----------------
B_ROW = re.compile(r'^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12]) +([\d.]+) +([\d.]+) +([\d.]+) +([\d.]+) +(\d+) +([\d.]+) +(\d+) +([\d.]+)')
B_RACE = re.compile(r'^[\s　]*([０-９\d]+)Ｒ\s+(\S+)')


def parse_b(block, date, jcd):
    lines = block.split('\n')
    title = ''
    seen_hdr = False
    for l in lines[:12]:
        s = l.strip().replace('\u3000', '')
        if '番組表' in s:
            seen_hdr = True
            continue
        if seen_hdr and s:      # 「番組表」の次の空でない行が大会名
            title = s
            break
    rows, race, rtype = [], None, None
    for l in lines:
        m = B_RACE.match(l)
        if m and 'Ｒ' in l[:8]:
            race = int(m.group(1).translate(Z2H))
            rtype = m.group(2).replace('　', '')
            continue
        m = B_ROW.match(l)
        if m and race:
            g = m.groups()
            try:
                [float(v) for v in g[7:11]]; float(g[12]); float(g[14])
            except ValueError:  # 2連率100%で欄がくっついた行は飛ばす（まれ）
                continue
            rows.append(dict(date=date, jcd=jcd, race=race, title=title, race_type=rtype,
                             waku=int(g[0]), racer=int(g[1]), name=g[2].replace('　', ''),
                             age=int(g[3]), branch=g[4], weight=int(g[5]), cls=g[6],
                             nat_win=float(g[7]), nat_2=float(g[8]), loc_win=float(g[9]), loc_2=float(g[10]),
                             motor_no=int(g[11]), motor_2=float(g[12]), boat_no=int(g[13]), boat_2=float(g[14])))
    return rows


# ---------------- 競走成績 ----------------
K_RACE = re.compile(r'^\s+(\d{1,2})R\s+(\S+)\s+.*?H(\d+)m\s+(\S+)\s+風\s+(\S+)\s+(\d+)m\s+波\s+(\d+)cm')
K_ROW = re.compile(r'^\s+(\S{2})\s+([1-6])\s+(\d{4})\s+(.{8})\s*(\d+)\s+(\d+)\s+([\d.]+)?\s+(\d)?\s+([FL]?[\d.]+|[A-ZＫＦＬ]\S*)?')
PAY_KIND = {'単勝': 'tan', '複勝': 'fuku', '２連単': 'exa', '２連複': 'qui', '拡連複': 'wide', '３連単': 'tri', '３連複': 'trio'}


def parse_k(block, date, jcd):
    lines = block.split('\n')
    boats, races = [], []
    i = 0
    while i < len(lines):
        m = K_RACE.match(lines[i])
        if not m:
            i += 1
            continue
        race = int(m.group(1))
        hdr = lines[i + 1]
        kimete = hdr.split()[-1].replace('　', '') if len(hdr.split()) else None
        meta = dict(date=date, jcd=jcd, race=race, race_type_k=m.group(2).replace('　', ''),
                    weather=m.group(4).replace('　', ''), wind_dir=m.group(5).replace('　', ''),
                    wind=int(m.group(6)), wave=int(m.group(7)), kimete=kimete)
        j = i + 3
        while j < len(lines) and lines[j].strip():
            l = lines[j]
            parts = l.split()
            # 着 艇 登番 名前(空白入り) ﾓｰﾀｰ ﾎﾞｰﾄ 展示 進入 ST タイム
            mm = re.match(r'^\s+(\S+)\s+([1-6])\s+(\d{4})\s', l)
            if mm:
                rest = l[mm.end():]
                nums = re.findall(r'[FLK]?\d+\.\d+|[FLK]?\.\d+|\d+\.\d+\.\d+|\d+|[FLK]', rest)
                # rest = 名前 + motor boat ex entry st time
                toks = rest.split()
                # 名前は全角なので数字トークンだけ後ろから拾う
                tail = [t for t in toks if re.match(r'^[\dFLK.]', t)]
                motor = boat = ex = entry = st = None
                if len(tail) >= 2:
                    motor, boat = int(tail[0]), int(tail[1])
                if len(tail) >= 3 and re.match(r'^\d\.\d\d$', tail[2]):
                    ex = float(tail[2])
                if len(tail) >= 4 and re.match(r'^[1-6]$', tail[3]):
                    entry = int(tail[3])
                if len(tail) >= 5:
                    st = tail[4]
                fin = mm.group(1)
                boats.append(dict(date=date, jcd=jcd, race=race, waku=int(mm.group(2)), racer=int(mm.group(3)),
                                  finish=int(fin) if fin.isdigit() else None, finish_raw=fin,
                                  ex_time=ex, entry=entry, st_raw=st))
            j += 1
        # 払戻
        pay = dict(meta)
        k = j
        cur = None
        while k < len(lines) and not K_RACE.match(lines[k]):
            l = lines[k]
            s = l.strip()
            for jp, key in PAY_KIND.items():
                if s.startswith(jp):
                    cur = key
                    s = s[len(jp):].strip()
                    break
            if cur and s:
                for combo, amt, pop in re.findall(r'([\d-]+)\s+(\d+)(?:\s+人気\s+(\d+))?', s):
                    pay.setdefault(f'{cur}_combo', []).append(combo)
                    pay.setdefault(f'{cur}_pay', []).append(int(amt))
                    pay.setdefault(f'{cur}_pop', []).append(int(pop) if pop else None)
            k += 1
        for key in list(pay):
            if isinstance(pay[key], list):
                pay[key] = '|'.join('' if v is None else str(v) for v in pay[key])
        races.append(pay)
        i = k
    return boats, races


def main(raw, out, jcds):
    os.makedirs(out, exist_ok=True)
    B, KB, KR = [], [], []
    for f in sorted(glob.glob(os.path.join(raw, 'k*.lzh'))):
        ymd = os.path.basename(f)[1:7]
        date = int('20' + ymd)
        tk = read_lzh(f)
        bf = os.path.join(raw, f'b{ymd}.lzh')
        tb = read_lzh(bf) if os.path.exists(bf) else ''
        for jcd in jcds:
            kb = blocks(tk, jcd, 'K')
            if kb:
                b, r = parse_k(kb, date, jcd)
                KB += b
                KR += r
            bb = blocks(tb, jcd, 'B') if tb else None
            if bb:
                B += parse_b(bb, date, jcd)
    b = pd.DataFrame(B)
    kb = pd.DataFrame(KB)
    kr = pd.DataFrame(KR)
    boats = b.merge(kb, on=['date', 'jcd', 'race', 'waku', 'racer'], how='inner')
    boats.to_csv(os.path.join(out, 'boats.csv'), index=False)
    kr.to_csv(os.path.join(out, 'races.csv'), index=False)
    print(f'B rows {len(b)}, K rows {len(kb)}, merged {len(boats)}, races {len(kr)}')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
