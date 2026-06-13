"""
ボートレース予想 Webアプリ（バックグラウンド取得版）

- サーバー起動時にバックグラウンドでデータ取得開始
- APIは取得済みデータをすぐに返す（取得中のレースはスキップ）
- 3分ごとに自動更新

使い方（自宅PC/Macで実行）:
    python app.py
スマホから: http://<PCのIPアドレス>:5000
"""
import logging
import re
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

import config
import features as feat
import model as mdl
import scraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ─── グローバルキャッシュ ───────────────────────────────────────
_state = {
    'races': [],          # 取得済みレース一覧
    'status': 'idle',     # idle / fetching / done / error
    'progress': '',       # 「○○場 3R取得中...」
    'updated': None,
    'date': None,
    'model': None,
    'error': None,
}
_lock = threading.Lock()
_fetch_thread = None


def _cls(rank):
    return {4: 'A1', 3: 'A2', 2: 'B1', 1: 'B2'}.get(rank, '??')


def _parse_deadline(time_str, now):
    """'HH:MM' を今日の datetime に変換。失敗時 None"""
    m = re.match(r'^(\d{1,2}):(\d{2})$', time_str or '')
    if not m:
        return None
    try:
        return now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                           second=0, microsecond=0)
    except ValueError:
        return None


def _collect_pending_races(venues, date_str, now):
    """
    実施中の場の「締切前かつ近い」レースを締切時刻順に並べて返す。
    Returns list of (deadline_dt|None, minutes_to_close|None, jcd, venue, race_no)
    """
    pending = []
    for jcd in venues:
        venue_name = config.VENUES.get(jcd, jcd)
        with _lock:
            _state['progress'] = f'{venue_name} の締切時刻を確認中...'

        deadlines = scraper.get_race_deadlines(jcd, date_str)

        if not deadlines:
            # 締切時刻が取れない場合は先頭数レースのみ（暴走防止）
            logger.warning('%s: 締切時刻を取得できず。先頭%dレースのみ対象。',
                           venue_name, config.FALLBACK_RACES)
            for rno in range(1, config.FALLBACK_RACES + 1):
                pending.append((None, None, jcd, venue_name, rno))
            continue

        kept = 0
        for rno, tstr in deadlines.items():
            ddl = _parse_deadline(tstr, now)
            if ddl is None:
                continue
            minutes = (ddl - now).total_seconds() / 60.0
            # 締切前(GRACE考慮)かつ FETCH_WINDOW 分以内のレースだけ
            if -config.CLOSED_GRACE_MIN <= minutes <= config.FETCH_WINDOW_MIN:
                pending.append((ddl, minutes, jcd, venue_name, rno))
                kept += 1
        logger.info('%s: 締切前レース %d 件', venue_name, kept)

    # 締切が近い順（時刻不明は末尾）
    pending.sort(key=lambda x: (x[0] is None, x[0] or now))

    # 最大数で打ち切り（暴走防止）
    if len(pending) > config.MAX_FETCH_RACES:
        logger.info('対象レースが多いため %d 件に制限', config.MAX_FETCH_RACES)
        pending = pending[:config.MAX_FETCH_RACES]

    return pending


def _fetch_all(date_str):
    """バックグラウンドスレッドで、実施中レースを締切が近い順に取得する"""
    predictor = mdl.load_predictor()

    with _lock:
        _state.update({'status': 'fetching', 'date': date_str,
                       'model': predictor.name, 'races': [], 'error': None})

    venues = scraper.get_holding_venues(date_str)
    if not venues:
        with _lock:
            _state['status'] = 'error'
            _state['error'] = 'boatrace.jp から開催情報を取得できませんでした。'
        return

    logger.info('開催中の場: %d 件 → 締切時刻を確認します', len(venues))
    now = datetime.now()
    pending = _collect_pending_races(venues, date_str, now)

    if not pending:
        with _lock:
            _state['status'] = 'done'
            _state['progress'] = ''
            _state['error'] = '実施中（締切前）のレースがありません。本日の開催が終了している可能性があります。'
        logger.info('対象レースなし（開催終了の可能性）')
        return

    total = len(pending)
    logger.info('取得対象: %d レース。締切が近い順に取得開始します。', total)

    for idx, (ddl, minutes, jcd, venue_name, race_no) in enumerate(pending, 1):
        with _lock:
            _state['progress'] = f'[{idx}/{total}] {venue_name} {race_no}R 取得中...'
        logger.info('[%d/%d] %s %dR 取得中...', idx, total, venue_name, race_no)

        try:
            racers = scraper.get_race_card(race_no, jcd, date_str)
            if not racers:
                continue

            before = scraper.get_before_info(race_no, jcd, date_str)
            odds_map = scraper.get_win_odds(race_no, jcd, date_str)
            odds_available = bool(odds_map)
            if not odds_available:
                logger.info('  → オッズ未公開（出走表のみ表示）')

            X = feat.build_race_matrix(racers, before, jcd)
            probs = predictor.predict_proba(X)
            all_probs = [float(p) for p in probs]

            boats = []
            has_hit = False
            for i, racer in enumerate(racers):
                boat_no = racer.get('boat_no', i + 1)
                odds = odds_map.get(boat_no) if odds_available else None
                win_prob = float(probs[i])
                conf_pct, conf_label = mdl.compute_confidence(
                    racer, before, boat_no, win_prob, all_probs, predictor.name)
                hit = bool(odds and odds >= config.ODDS_THRESHOLD
                           and win_prob >= config.WIN_PROB_THRESHOLD)
                if hit:
                    has_hit = True

                boats.append({
                    'boat_no':           boat_no,
                    'racer':             racer.get('racer_name', '不明'),
                    'class':             _cls(racer.get('class_rank')),
                    'national_win_rate': racer.get('national_win_rate'),
                    'course':            before['course_positions'].get(boat_no, boat_no),
                    'ex_time':           before['exhibition_times'].get(boat_no),
                    'motor_rate':        racer.get('motor_top2_rate'),
                    'odds':              odds,
                    'odds_available':    odds_available,
                    'win_prob':          win_prob,
                    'confidence':        conf_pct,
                    'conf_label':        conf_label,
                    'hit':               hit,
                })

            # 締切までの残り分（取得時点で再計算）
            mins_left = None
            if ddl is not None:
                mins_left = round((ddl - datetime.now()).total_seconds() / 60.0)

            race = {
                'jcd':         jcd,
                'venue':       venue_name,
                'race_no':     race_no,
                'deadline':    ddl.strftime('%H:%M') if ddl else None,
                'minutes_left': mins_left,
                'imminent':    bool(mins_left is not None
                                    and -config.CLOSED_GRACE_MIN <= mins_left <= config.IMMINENT_WINDOW_MIN),
                'boats':       boats,
                'has_hit':     has_hit,
            }
            with _lock:
                _state['races'].append(race)
                _state['updated'] = datetime.now().strftime('%H:%M:%S')

        except Exception as e:
            logger.warning('%s %dR エラー: %s', venue_name, race_no, e)

    with _lock:
        _state['status'] = 'done'
        _state['progress'] = ''
        logger.info('取得完了: %d レース', len(_state['races']))


def _start_fetch(date_str, force=False):
    global _fetch_thread
    with _lock:
        if not force and _state['date'] == date_str and _state['status'] in ('fetching', 'done'):
            return
    if _fetch_thread and _fetch_thread.is_alive():
        return  # すでに実行中
    _fetch_thread = threading.Thread(target=_fetch_all, args=(date_str,), daemon=True)
    _fetch_thread.start()


# ─── ルート ────────────────────────────────────────────────────

@app.route('/')
def index():
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    _start_fetch(date_str)
    return render_template('index.html', date=date_str)


@app.route('/manifest.json')
def manifest():
    return jsonify({
        'name': 'ボートレース予想',
        'short_name': '競艇予想',
        'start_url': '/',
        'display': 'standalone',
        'background_color': '#0d47a1',
        'theme_color': '#0d47a1',
        'icons': [
            {'src': '/icon.svg', 'sizes': '192x192', 'type': 'image/svg+xml'},
            {'src': '/icon.svg', 'sizes': '512x512', 'type': 'image/svg+xml'},
        ],
    })


@app.route('/icon.svg')
def icon():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">'
        '<rect width="512" height="512" rx="96" fill="#0d47a1"/>'
        '<text x="50%" y="50%" font-size="300" text-anchor="middle" '
        'dominant-baseline="central">🚤</text></svg>'
    )
    return Response(svg, mimetype='image/svg+xml')


@app.route('/api/predictions')
def api_predictions():
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    force = request.args.get('force', '0') == '1'
    _start_fetch(date_str, force=force)

    with _lock:
        return jsonify({
            'date':            _state['date'] or date_str,
            'model':           _state['model'] or '...',
            'updated':         _state['updated'] or '--:--:--',
            'status':          _state['status'],
            'progress':        _state['progress'],
            'odds_threshold':  config.ODDS_THRESHOLD,
            'prob_threshold':  config.WIN_PROB_THRESHOLD,
            'imminent_window': config.IMMINENT_WINDOW_MIN,
            'races':           list(_state['races']),
            'error':           _state['error'],
        })


if __name__ == '__main__':
    import socket
    hostname = socket.gethostname()
    try:
        local_ip = socket.gethostbyname(hostname)
    except Exception:
        local_ip = '127.0.0.1'

    print()
    print('=' * 52)
    print('  ボートレース予想アプリ 起動中')
    print(f'  PC:     http://localhost:5000')
    print(f'  スマホ: http://{local_ip}:5000')
    print('  ※ スマホとPCが同じWi-Fiに接続していること')
    print('  ※ ブラウザで開くと自動でデータ取得開始します')
    print('=' * 52)
    print()

    app.run(host='0.0.0.0', port=5000, debug=False)
