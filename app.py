"""
ボートレース予想 Webアプリ

使い方（自宅PC/Macで実行）:
    pip install -r requirements.txt
    python app.py

スマホから: http://<PCのIPアドレス>:5000
"""
import logging
import threading
import time
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
import features as feat
import model as mdl
import scraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# シンプルなメモリキャッシュ（5分間有効）
_cache = {}
_cache_lock = threading.Lock()
_CACHE_TTL = 300


def _cached_predictions(date_str):
    now = time.time()
    with _cache_lock:
        entry = _cache.get(date_str)
        if entry and now - entry['ts'] < _CACHE_TTL:
            return entry['data']

    data = _build_predictions(date_str)

    with _cache_lock:
        _cache[date_str] = {'data': data, 'ts': time.time()}
    return data


def _build_predictions(date_str):
    predictor = mdl.load_predictor()
    venues = scraper.get_holding_venues(date_str)

    if not venues:
        return {
            'date': date_str,
            'model': predictor.name,
            'updated': _now_str(),
            'odds_threshold': config.ODDS_THRESHOLD,
            'prob_threshold': config.WIN_PROB_THRESHOLD,
            'races': [],
            'error': 'boatrace.jpに接続できません。自宅PCで実行してください。',
        }

    races = []
    for jcd in venues:
        for race_no in range(1, config.MAX_RACES + 1):
            racers = scraper.get_race_card(race_no, jcd, date_str)
            if not racers:
                break

            before = scraper.get_before_info(race_no, jcd, date_str)
            odds_map = scraper.get_win_odds(race_no, jcd, date_str)
            if not odds_map:
                continue

            X = feat.build_race_matrix(racers, before, jcd)
            probs = predictor.predict_proba(X)

            boats = []
            has_hit = False
            for i, racer in enumerate(racers):
                boat_no = racer.get('boat_no', i + 1)
                odds = odds_map.get(boat_no)
                win_prob = float(probs[i])
                hit = bool(odds and odds >= config.ODDS_THRESHOLD
                           and win_prob >= config.WIN_PROB_THRESHOLD)
                if hit:
                    has_hit = True

                boats.append({
                    'boat_no': boat_no,
                    'racer': racer.get('racer_name', '不明'),
                    'class': _cls(racer.get('class_rank')),
                    'national_win_rate': racer.get('national_win_rate'),
                    'course': before['course_positions'].get(boat_no, boat_no),
                    'ex_time': before['exhibition_times'].get(boat_no),
                    'motor_rate': racer.get('motor_top2_rate'),
                    'odds': odds,
                    'win_prob': win_prob,
                    'hit': hit,
                })

            races.append({
                'jcd': jcd,
                'venue': config.VENUES.get(jcd, jcd),
                'race_no': race_no,
                'boats': boats,
                'has_hit': has_hit,
            })

    return {
        'date': date_str,
        'model': predictor.name,
        'updated': _now_str(),
        'odds_threshold': config.ODDS_THRESHOLD,
        'prob_threshold': config.WIN_PROB_THRESHOLD,
        'races': races,
    }


def _cls(rank):
    return {4: 'A1', 3: 'A2', 2: 'B1', 1: 'B2'}.get(rank, '??')


def _now_str():
    return datetime.now().strftime('%H:%M:%S')


# ─── ルート ───────────────────────────────────────────────────

@app.route('/')
def index():
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    return render_template('index.html', date=date_str)


@app.route('/api/predictions')
def api_predictions():
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    force = request.args.get('force', '0') == '1'
    if force:
        with _cache_lock:
            _cache.pop(date_str, None)
    try:
        data = _cached_predictions(date_str)
        return jsonify(data)
    except Exception as e:
        logger.exception('prediction error')
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = '127.0.0.1'

    print()
    print('=' * 50)
    print('  ボートレース予想アプリ 起動中')
    print(f'  PC:     http://localhost:5000')
    print(f'  スマホ: http://{local_ip}:5000')
    print('  ※ スマホとPCが同じWi-Fiに接続していること')
    print('=' * 50)
    print()

    app.run(host='0.0.0.0', port=5000, debug=False)
