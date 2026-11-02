"""詳細データがあるレースのオッズを取得する (約1秒に1リクエスト・キャッシュ・再開可)。

保存するもの: 3連単/2連単/単勝/3連複 の最終オッズ、3連単の時系列オッズ (締切 30/20/10/5/0 分前)。
usage: python kb_scrape_odds.py PLACE_NO DATES_FILE OUT_DIR  (DATES_FILE: 'YYYYMMDD レース数' の行)  (2秒に1リクエスト、3回連続失敗で停止)
"""
import glob
import json
import os
import subprocess
import sys
import time


def post(body):
    for a in range(1):
        r = subprocess.run(['curl', '-sS', '-m', '30', '-X', 'POST', 'https://kyoteibiyori.com/request_odds_shousai.php',
                            '--data-urlencode', 'data=' + json.dumps(body)], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except Exception:
            time.sleep(2 ** (a + 1))
    return None


def main(place, src, out):
    fails = 0
    os.makedirs(out, exist_ok=True)
    todo = []
    for line in open(src):
        if line.strip():
            dd, n = line.split()
            todo += [(dd, str(r)) for r in range(1, int(n) + 1)]
    for d, r in todo:
        dst = os.path.join(out, f'{d}_{r}.json')
        if os.path.exists(dst):
            continue
        j = post({'place_no': str(place), 'race_no': r, 'hiduke': d})
        time.sleep(2)
        if not j:
            print('FAIL', d, r, flush=True)
            fails += 1
            if fails >= 3:
                print('STOP: 3 consecutive failures', flush=True)
                sys.exit(2)
            continue
        fails = 0
        final = {}
        for x in j.get('odds_list', []):
            if x['type'] in ('3t', '2t', 't', '3f'):
                final.setdefault(x['type'], {})[x['kumiawase']] = x['odds']
        ts = {}
        for x in j.get('jikan_odds_list', []):
            if x.get('type') == 0:
                ts.setdefault(str(x['shimekiri']), {})[str(x['kumiawase'])] = x['odds']
        json.dump({'date': d, 'race': int(r), 'final': final, 'tri_by_min': ts}, open(dst, 'w'))
    print('odds done', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
