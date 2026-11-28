"""詳細データがあるレースのオッズを取得する (約1秒に1リクエスト・キャッシュ・再開可)。

保存するもの: 3連単/2連単/単勝/3連複 の最終オッズ、3連単の時系列オッズ (締切 30/20/10/5/0 分前)。
usage: python scrape_odds.py RACES_DIR OUT_DIR
"""
import glob
import json
import os
import subprocess
import sys
import time


def post(body):
    for a in range(4):
        r = subprocess.run(['curl', '-sS', '-m', '30', '-X', 'POST', 'https://kyoteibiyori.com/request_odds_shousai.php',
                            '--data-urlencode', 'data=' + json.dumps(body)], capture_output=True, text=True)
        try:
            return json.loads(r.stdout)
        except Exception:
            time.sleep(2 ** (a + 1))
    return None


def main(src, out):
    os.makedirs(out, exist_ok=True)
    for f in sorted(glob.glob(os.path.join(src, '*.json'))):
        d, r = os.path.basename(f)[:-5].split('_')
        dst = os.path.join(out, f'{d}_{r}.json')
        if os.path.exists(dst):
            continue
        j = post({'place_no': '4', 'race_no': r, 'hiduke': d})
        time.sleep(1)
        if not j:
            print('FAIL', d, r, flush=True)
            continue
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
    main(sys.argv[1], sys.argv[2])
