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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

import config
import features as feat
import model as mdl
import results as res_tracker
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
    'calib_stats': res_tracker.calibrator.stats(),
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
    各場の締切時刻取得を並列化して高速化する。
    Returns list of (deadline_dt|None, minutes_to_close|None, jcd, venue, race_no)
    """
    with _lock:
        _state['progress'] = f'{len(venues)}場の締切時刻を確認中...'

    def _deadlines_for(jcd):
        return jcd, scraper.get_race_deadlines(jcd, date_str)

    deadline_map = {}
    workers = min(getattr(config, 'FETCH_WORKERS', 6), max(1, len(venues)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for jcd, deadlines in ex.map(_deadlines_for, venues):
            deadline_map[jcd] = deadlines

    pending = []
    for jcd in venues:
        venue_name = config.VENUES.get(jcd, jcd)
        deadlines = deadline_map.get(jcd) or {}

        if not deadlines:
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
            if -config.CLOSED_GRACE_MIN <= minutes <= config.FETCH_WINDOW_MIN:
                pending.append((ddl, minutes, jcd, venue_name, rno))
                kept += 1
        logger.info('%s: 締切前レース %d 件', venue_name, kept)

    # 締切が近い順（時刻不明は末尾）
    pending.sort(key=lambda x: (x[0] is None, x[0] or now))

    # 最大数で打ち切り（暴走防止・速度優先で締切が近い順を優先）
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
    logger.info('取得対象: %d レース。%d並列で取得開始します。',
                total, config.FETCH_WORKERS)

    # ── 並列でレース取得（締切が近い順に投入）──────────────
    done = 0
    workers = min(config.FETCH_WORKERS, max(1, total))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_build_race, item, predictor, date_str): item
                   for item in pending}
        for fut in as_completed(futures):
            done += 1
            try:
                race = fut.result()
            except Exception as e:
                item = futures[fut]
                logger.warning('%s %dR エラー: %s', item[3], item[4], e)
                race = None

            with _lock:
                if race:
                    _state['races'].append(race)
                    # 締切が近い順を保つ（時刻不明は末尾）
                    _state['races'].sort(
                        key=lambda r: (r['deadline'] is None, r['deadline'] or '99:99'))
                    _state['updated'] = datetime.now().strftime('%H:%M:%S')
                _state['progress'] = f'[{done}/{total}] 取得中...'

    with _lock:
        _state['status'] = 'done'
        _state['progress'] = ''
        logger.info('取得完了: %d レース', len(_state['races']))

    # 過去レースの結果を確認してキャリブレーションを更新
    threading.Thread(target=_update_calibration, args=(date_str,), daemon=True).start()


def _build_race(item, predictor, date_str):
    """
    1レース分のデータを取得して race dict を組み立てて返す。
    並列実行されるため、共有状態の書き込みは行わない（純粋な計算 + ファイル保存のみ）。
    Returns race dict or None.
    """
    ddl, minutes, jcd, venue_name, race_no = item

    racers = scraper.get_race_card(race_no, jcd, date_str)
    if not racers:
        return None

    before = scraper.get_before_info(race_no, jcd, date_str)
    odds_map = scraper.get_win_odds(race_no, jcd, date_str)
    odds_available = bool(odds_map)

    X = feat.build_race_matrix(racers, before, jcd)
    probs = predictor.predict_proba(X)
    all_probs = [float(p) for p in probs]

    boats = []
    has_hit = False
    for i, racer in enumerate(racers):
        boat_no = racer.get('boat_no', i + 1)
        odds = odds_map.get(boat_no) if odds_available else None
        win_prob = float(probs[i])
        raw_conf, _, breakdown = mdl.compute_confidence(
            racer, before, boat_no, win_prob, all_probs, predictor.name)
        conf_pct   = res_tracker.calibrator.calibrate(raw_conf)
        conf_label = res_tracker.calibrator.label(conf_pct)
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
            'conf_breakdown':    breakdown,
            'hit':               hit,
        })

    # 3連単予測（Harville式）
    boat_nos_list  = [b['boat_no']  for b in boats]
    win_probs_list = [b['win_prob'] for b in boats]
    trifecta = mdl.predict_trifecta(win_probs_list, boat_nos_list, top_n=6)

    mins_left = None
    if ddl is not None:
        mins_left = round((ddl - datetime.now()).total_seconds() / 60.0)

    result_data = None
    try:
        result_data = res_tracker.get_saved_result(jcd, race_no, date_str)
    except Exception:
        pass

    race = {
        'jcd':          jcd,
        'venue':        venue_name,
        'race_no':      race_no,
        'deadline':     ddl.strftime('%H:%M') if ddl else None,
        'minutes_left': mins_left,
        'imminent':     bool(mins_left is not None
                             and -config.CLOSED_GRACE_MIN <= mins_left <= config.IMMINENT_WINDOW_MIN),
        'boats':        boats,
        'has_hit':      has_hit,
        'trifecta':     trifecta,
        'result':       result_data,
    }

    try:
        res_tracker.save_prediction(jcd, race_no, date_str, boats, trifecta)
    except Exception as e2:
        logger.debug('予測保存エラー（無視）: %s', e2)

    return race


def _update_calibration(date_str):
    """バックグラウンドで結果照合 → キャリブレーション更新 → ステートのresult反映"""
    try:
        filled = res_tracker.check_pending_results(date_str)
        if filled > 0:
            logger.info('結果照合: %d 件 → キャリブレーション更新', filled)
            res_tracker.calibrator.update_from_results()
        with _lock:
            _state['calib_stats'] = res_tracker.calibrator.stats()
            # 結果が新たに取得されたレースをステートに反映
            for race in _state['races']:
                if race.get('result') is None:
                    r = res_tracker.get_saved_result(
                        race['jcd'], race['race_no'], date_str)
                    if r:
                        race['result'] = r
    except Exception as e:
        logger.warning('キャリブレーション更新エラー: %s', e)


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
            'closed_grace_min': config.CLOSED_GRACE_MIN,
            'races':           list(_state['races']),
            'error':           _state['error'],
            'calib_stats':     _state.get('calib_stats', []),
        })


@app.route('/api/debug-scraper')
def api_debug_scraper():
    """
    スクレイパーのHTML解析状況を返すデバッグ用エンドポイント。
    ブラウザで http://localhost:5000/api/debug-scraper?jcd=07&rno=1 を開いて確認。
    """
    date_str = request.args.get('date', datetime.now().strftime('%Y%m%d'))
    jcd = request.args.get('jcd', '07')
    race_no = int(request.args.get('rno', '1'))

    racelist_info = scraper.debug_scrape_racelist(race_no, jcd, date_str)
    odds_info     = scraper.debug_scrape_odds(race_no, jcd, date_str)

    # 実際のパース結果も含める
    racers = scraper.get_race_card(race_no, jcd, date_str)
    odds   = scraper.get_win_odds(race_no, jcd, date_str)

    return jsonify({
        'params':     {'jcd': jcd, 'race_no': race_no, 'date': date_str},
        'racelist':   racelist_info,
        'odds_page':  odds_info,
        'parsed_racers': racers,
        'parsed_odds':   odds,
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
