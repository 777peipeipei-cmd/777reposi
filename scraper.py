"""boatrace.jp から出走表・直前情報・単勝オッズ・レース結果を取得する"""
import re
import time
import logging
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)

_CLASS_MAP = {'A1': 4, 'A2': 3, 'B1': 2, 'B2': 1}


_session = None

def _get_session():
    global _session
    if _session is None:
        _session = requests.Session()
        # トップページでクッキーを取得
        try:
            _session.get('https://www.boatrace.jp/', headers=config.HEADERS, timeout=10)
        except Exception:
            pass
    return _session


def _fetch(url, params=None):
    time.sleep(config.REQUEST_DELAY)
    try:
        resp = _get_session().get(url, params=params, headers=config.HEADERS, timeout=15)
        if resp.status_code == 403:
            logger.error(
                '\n'
                '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n'
                '  403 Forbidden: boatrace.jp にアクセスできません。\n'
                '  クラウドサーバーのIPはブロックされています。\n'
                '  【解決策】自宅PC・Mac で実行してください:\n'
                '    pip install -r requirements.txt\n'
                '    python predict.py\n'
                '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
            )
            return None
        resp.raise_for_status()
        resp.encoding = 'utf-8'
        return BeautifulSoup(resp.text, 'lxml')
    except requests.RequestException as e:
        logger.warning('fetch failed: %s params=%s: %s', url, params, e)
        return None


def _safe_float(text):
    try:
        return float(str(text).strip().replace(',', ''))
    except ValueError:
        return None


def get_holding_venues(date_str):
    """開催中の場コードリストを返す"""
    soup = _fetch(f'{config.BASE_URL}/index', {'hd': date_str})
    if not soup:
        return []
    seen = set()
    result = []
    for a in soup.find_all('a', href=True):
        m = re.search(r'jcd=(\d{2})', a['href'])
        if m and m.group(1) in config.VENUES:
            jcd = m.group(1)
            if jcd not in seen:
                seen.add(jcd)
                result.append(jcd)
    return result


def get_race_card(race_no, jcd, date_str):
    """
    出走表をパース。
    Returns list of dict (艇1〜6):
        boat_no, racer_name, racer_no, class_rank,
        national_win_rate, national_top2_rate,
        venue_win_rate,    venue_top2_rate,
        motor_top2_rate,   boat_top2_rate
    """
    soup = _fetch(f'{config.BASE_URL}/racelist',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return []

    # メインテーブル検索（class名が変わっても対応できるよう複数候補を試す）
    table = (soup.find('table', class_=re.compile(r'is-w748'))
             or soup.find('table', class_=re.compile(r'racers'))
             or _largest_table(soup))
    if not table:
        logger.warning('race card table not found race=%s jcd=%s', race_no, jcd)
        return []

    racers = {}
    current_boat = None

    for row in table.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        texts = [c.get_text(strip=True) for c in cells]

        # --- 艇番セルの検出 ---
        first = texts[0] if texts else ''
        if first in ('1', '2', '3', '4', '5', '6'):
            current_boat = int(first)
            if current_boat not in racers:
                racers[current_boat] = {'boat_no': current_boat}

        if current_boat is None:
            continue

        d = racers[current_boat]

        # --- 選手名リンクから名前と登録番号 ---
        for cell in cells:
            a = cell.find('a', href=re.compile(r'toban=\d+'))
            if a:
                d['racer_name'] = a.get_text(strip=True)
                m = re.search(r'toban=(\d+)', a['href'])
                if m:
                    d['racer_no'] = m.group(1)

        # --- 級別 ---
        for t in texts:
            if t in _CLASS_MAP and 'class_rank' not in d:
                d['class_rank'] = _CLASS_MAP[t]

        # --- 数値系（勝率・2連率）: 列順で代入 ---
        floats = [_safe_float(t) for t in texts if re.match(r'^\d+\.\d+$', t)]
        _assign_rates(d, floats)

    return [v for k, v in sorted(racers.items())]


def _assign_rates(d, floats):
    """
    出走表の数値列から各種勝率を代入する。
    boatrace.jp の列順: 全国勝率, 全国2連率, 当地勝率, 当地2連率, モーター2連率, ボート2連率
    """
    keys = [
        ('national_win_rate',   lambda x: 0.0 < x <= 10.0),
        ('national_top2_rate',  lambda x: 0.0 < x <= 100.0),
        ('venue_win_rate',      lambda x: 0.0 < x <= 10.0),
        ('venue_top2_rate',     lambda x: 0.0 < x <= 100.0),
        ('motor_top2_rate',     lambda x: 0.0 < x <= 100.0),
        ('boat_top2_rate',      lambda x: 0.0 < x <= 100.0),
    ]
    idx = 0
    for f in floats:
        if idx >= len(keys):
            break
        key, check = keys[idx]
        if key not in d and check(f):
            # パーセント表記（例: 45.67）を率（0.4567）に変換
            if key != 'national_win_rate' and key != 'venue_win_rate' and f > 1.0:
                d[key] = f / 100.0
            else:
                d[key] = f
            idx += 1


def get_before_info(race_no, jcd, date_str):
    """
    直前情報をパース。
    Returns dict:
        exhibition_times: {boat_no: float}
        course_positions: {boat_no: int}  # 実際の進入コース
        wind_speed: float | None
        wave_height: float | None
    """
    soup = _fetch(f'{config.BASE_URL}/beforeinfo',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return _empty_before()

    result = _empty_before()

    for table in soup.find_all('table'):
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            if not texts:
                continue

            # 展示タイム: 艇番 + 6.XX or 7.XX の行
            if texts[0] in ('1','2','3','4','5','6'):
                boat_no = int(texts[0])
                for t in texts[1:]:
                    if re.match(r'^[67]\.\d{2}$', t):
                        result['exhibition_times'][boat_no] = float(t)
                        break

    # 気象情報（テキスト全体から正規表現で拾う）
    full_text = soup.get_text()
    m = re.search(r'風速[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wind_speed'] = float(m.group(1))
    m = re.search(r'波高[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wave_height'] = float(m.group(1))

    # 進入コース（コース順）
    for table in soup.find_all('table'):
        headers = [th.get_text(strip=True) for th in table.find_all('th')]
        if any('コース' in h for h in headers):
            for row in table.find_all('tr'):
                cells = row.find_all('td')
                texts = [c.get_text(strip=True) for c in cells]
                if len(texts) >= 2:
                    try:
                        course = int(texts[0])
                        boat = int(texts[1])
                        if 1 <= course <= 6 and 1 <= boat <= 6:
                            result['course_positions'][boat] = course
                    except ValueError:
                        pass

    return result


def get_win_odds(race_no, jcd, date_str):
    """
    単勝オッズをパース。
    Returns dict {boat_no: float}
    """
    soup = _fetch(f'{config.BASE_URL}/odds1t',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return {}

    odds = {}
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            for i, t in enumerate(texts):
                if t in ('1','2','3','4','5','6') and i + 1 < len(texts):
                    val = _safe_float(texts[i + 1].replace(',', ''))
                    if val and val > 0:
                        odds[int(t)] = val
    return odds


def get_race_result(race_no, jcd, date_str):
    """
    レース結果（着順）をパース。学習データ収集用。
    Returns dict {boat_no: rank}  例: {3: 1, 1: 2, ...}
    """
    soup = _fetch(f'{config.BASE_URL}/raceresult',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return {}

    result = {}
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            # "1着", "2着" ... の行
            if texts and re.match(r'^[1-6]着$', texts[0]):
                rank = int(texts[0][0])
                for t in texts[1:]:
                    if t in ('1','2','3','4','5','6'):
                        result[int(t)] = rank
                        break
    return result


def _largest_table(soup):
    best, best_rows = None, 0
    for t in soup.find_all('table'):
        n = len(t.find_all('tr'))
        if n > best_rows:
            best, best_rows = t, n
    return best


def get_race_deadlines(jcd, date_str):
    """
    その場の各レースの投票締切予定時刻を取得する。
    Returns dict {race_no: 'HH:MM'}
    """
    soup = _fetch(f'{config.BASE_URL}/raceindex', {'jcd': jcd, 'hd': date_str})
    if not soup:
        return {}

    deadlines = {}
    for table in soup.find_all('table'):
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            race_no = None
            time_str = None
            for t in texts:
                m = re.match(r'^(\d{1,2})R$', t)
                if m:
                    race_no = int(m.group(1))
                m2 = re.match(r'^(\d{1,2}):(\d{2})$', t)
                if m2:
                    time_str = t
            if race_no and time_str and 1 <= race_no <= config.MAX_RACES:
                deadlines.setdefault(race_no, time_str)

    return deadlines


def _empty_before():
    return {
        'exhibition_times': {},
        'course_positions': {},
        'wind_speed': None,
        'wave_height': None,
    }
