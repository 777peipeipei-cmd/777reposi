"""kyoteibiyori から、過去レースの直前情報（周回・周り足・直線・展示・展示ST・展示進入・チルト）と
3連単オッズ（締切 30/20/10/5/0 分前と最終）を取る。1レース2リクエスト、毎回 SLEEP 秒あける。キャッシュあり・再開可。

usage: python3 -I venues/kb_scrape_lap_odds.py PLACE_NO RACES_CSV FROM_YYYYMMDD OUT_DIR
  (RACES_CSV は venues/parse.py の races.csv。そこにある日付とレース番号だけ取る)
"""
import json
import os
import subprocess
import sys
import time

import pandas as pd

SLEEP = 2.5
KEEP = ('course', 'shinnyuu', 'start', 'display', 'chiruto', 'tenji', 'shukai', 'mawariashi', 'chokusen',
        'wind_speed', 'wave', 'weather', 'taiju', 'tyousei', 'slow_dash', 'player_no')


def post(ep, body):
    r = subprocess.run(['curl', '-sS', '-m', '30', '-X', 'POST', f'https://kyoteibiyori.com/{ep}',
                        '--data-urlencode', 'data=' + json.dumps(body)], capture_output=True, text=True)
    time.sleep(SLEEP)
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def main(place, races_csv, since, out):
    os.makedirs(out, exist_ok=True)
    r = pd.read_csv(races_csv)
    r = r[(r.jcd == int(place)) & (r.date >= int(since))].sort_values(['date', 'race'])
    fails = 0
    for d, rn in zip(r.date, r.race):
        dst = os.path.join(out, f'{d}_{rn}.json')
        if os.path.exists(dst):
            continue
        body = {'place_no': str(int(place)), 'race_no': str(rn), 'hiduke': str(d)}
        ch = post('request_chokuzen_info_v2.php', body)
        od = post('request_odds_shousai.php', body)
        if not isinstance(ch, list) or not isinstance(od, dict):
            print('FAIL', d, rn, flush=True)
            fails += 1
            if fails >= 3:
                print('STOP: 3 consecutive failures', flush=True)
                sys.exit(2)
            time.sleep(30)
            continue
        fails = 0
        final = {x['kumiawase']: x['odds'] for x in od.get('odds_list', []) if x.get('type') == '3t'}
        ts = {}
        for x in od.get('jikan_odds_list', []):
            if x.get('type') == 0:
                ts.setdefault(str(x['shimekiri']), {})[str(x['kumiawase'])] = x['odds']
        json.dump({'date': int(d), 'race': int(rn), 'chokuzen': [{k: x.get(k) for k in KEEP} for x in ch],
                   'tri_final': final, 'tri_by_min': ts}, open(dst, 'w'))
    print('done', place, flush=True)


if __name__ == '__main__':
    main(*sys.argv[1:5])
