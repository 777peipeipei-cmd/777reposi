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
                '    python app.py\n'
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
    except (ValueError, TypeError):
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
    出走表をパース。is-boatColorN クラスを起点に艇情報を取得。
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

    racers = []

    for n in range(1, 7):
        # is-boatColorN クラスを持つ td を起点にする（艇番セル）
        anchor = soup.find('td', class_=re.compile(rf'\bis-boatColor{n}\b'))
        if not anchor:
            continue

        row1 = anchor.find_parent('tr')
        if not row1:
            continue

        d = {'boat_no': n}

        # 行1: 選手名リンク・その他情報をパース
        for cell in row1.find_all(['td', 'th']):
            a = cell.find('a', href=re.compile(r'toban=\d+'))
            if a:
                d.setdefault('racer_name', a.get_text(strip=True))
                m = re.search(r'toban=(\d+)', a['href'])
                if m:
                    d.setdefault('racer_no', m.group(1))
            t = cell.get_text(strip=True)
            if t in _CLASS_MAP and 'class_rank' not in d:
                d['class_rank'] = _CLASS_MAP[t]

        # 行2: 級別 + 全国/当地勝率 + モーター/ボート2連率
        row2 = row1.find_next_sibling('tr')
        if row2:
            for cell in row2.find_all(['td', 'th']):
                t = cell.get_text(strip=True)
                if t in _CLASS_MAP and 'class_rank' not in d:
                    d['class_rank'] = _CLASS_MAP[t]
            texts2 = [c.get_text(strip=True) for c in row2.find_all(['td', 'th'])]
            floats2 = [f for f in (_safe_float(t) for t in texts2
                                   if re.match(r'^\d+\.\d{2}$', t))
                       if f is not None]
            _assign_rates(d, floats2)

        # 行3: 追加情報（級別が未取得の場合の補完）
        row3 = row2.find_next_sibling('tr') if row2 else None
        if row3:
            texts3 = [c.get_text(strip=True) for c in row3.find_all(['td', 'th'])]
            for t in texts3:
                if t in _CLASS_MAP and 'class_rank' not in d:
                    d['class_rank'] = _CLASS_MAP[t]
            if 'national_win_rate' not in d:
                floats3 = [f for f in (_safe_float(t) for t in texts3
                                       if re.match(r'^\d+\.\d{2}$', t))
                           if f is not None]
                _assign_rates(d, floats3)

        racers.append(d)

    # is-boatColor が見つからない場合はフォールバックパーサーで補完
    if len(racers) < 6:
        racers = _parse_race_card_fallback(soup, racers)

    return racers


def _assign_rates(d, floats):
    """
    行2の数値列から各種勝率を代入する。
    boatrace.jp 列順: 全国勝率, 全国2連率, 当地勝率, 当地2連率, モーター2連率, ボート2連率
    勝率は0-9.99（整数部1桁）、2連率は0-100%（パーセント表記）。
    """
    keys = [
        ('national_win_rate',  lambda x: 0.0 < x < 10.0),
        ('national_top2_rate', lambda x: 0.0 <= x <= 100.0),
        ('venue_win_rate',     lambda x: 0.0 < x < 10.0),
        ('venue_top2_rate',    lambda x: 0.0 <= x <= 100.0),
        ('motor_top2_rate',    lambda x: 0.0 <= x <= 100.0),
        ('boat_top2_rate',     lambda x: 0.0 <= x <= 100.0),
    ]
    idx = 0
    for f in floats:
        if idx >= len(keys):
            break
        key, check = keys[idx]
        if key not in d and check(f):
            # national_win_rate / venue_win_rate 以外の 2連率はパーセントを率に変換
            if key not in ('national_win_rate', 'venue_win_rate') and f > 1.0:
                d[key] = f / 100.0
            else:
                d[key] = f
            idx += 1


def _parse_race_card_fallback(soup, existing_racers):
    """is-boatColor が見つからない場合の旧来パーサー（補完用）"""
    racers = {r['boat_no']: r for r in existing_racers}

    table = (soup.find('table', class_=re.compile(r'is-w748'))
             or soup.find('table', class_=re.compile(r'racers'))
             or _largest_table(soup))
    if not table:
        return existing_racers

    current_boat = None
    for row in table.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        first = texts[0] if texts else ''
        if first in ('1', '2', '3', '4', '5', '6'):
            current_boat = int(first)
            racers.setdefault(current_boat, {'boat_no': current_boat})
        if current_boat is None:
            continue
        d = racers[current_boat]
        for cell in cells:
            a = cell.find('a', href=re.compile(r'toban=\d+'))
            if a:
                d.setdefault('racer_name', a.get_text(strip=True))
                m = re.search(r'toban=(\d+)', a['href'])
                if m:
                    d.setdefault('racer_no', m.group(1))
        for t in texts:
            if t in _CLASS_MAP and 'class_rank' not in d:
                d['class_rank'] = _CLASS_MAP[t]
        # ST平均（0.XX）を除外するため 0.5 以上のみ対象
        floats = [f for f in (_safe_float(t) for t in texts
                               if re.match(r'^\d+\.\d{2}$', t))
                  if f is not None and f >= 0.5]
        _assign_rates(d, floats)

    return [v for k, v in sorted(racers.items())]


def get_before_info(race_no, jcd, date_str):
    """
    直前情報をパース。
    Returns dict:
        exhibition_times: {boat_no: float}
        course_positions: {boat_no: int}
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
            if texts[0] in ('1', '2', '3', '4', '5', '6'):
                boat_no = int(texts[0])
                for t in texts[1:]:
                    if re.match(r'^[67]\.\d{2}$', t):
                        result['exhibition_times'][boat_no] = float(t)
                        break

    # 気象情報
    full_text = soup.get_text()
    m = re.search(r'風速[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wind_speed'] = float(m.group(1))
    m = re.search(r'波高[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wave_height'] = float(m.group(1))

    # 進入コース
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
    単勝オッズをパース（複数戦略）。
    Returns dict {boat_no: float}
    """
    soup = _fetch(f'{config.BASE_URL}/odds1t',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return {}

    odds = {}

    # 戦略1: is-boatColorN ヘッダー行 → 次行の値（横並びテーブル）
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        col_map = {}
        for i, cell in enumerate(cells):
            cls = ' '.join(cell.get('class') or [])
            for n in range(1, 7):
                if f'is-boatColor{n}' in cls:
                    col_map[n] = i
        if len(col_map) >= 2:
            next_row = row.find_next_sibling('tr')
            if next_row:
                vcells = next_row.find_all(['td', 'th'])
                for n, ci in col_map.items():
                    if ci < len(vcells):
                        v = _safe_float(vcells[ci].get_text(strip=True).replace(',', ''))
                        if v and v > 1.0:
                            odds[n] = v
            if len(odds) >= 2:
                return odds

    # 戦略2: 「艇番 + オッズ」が縦並びの行パターン
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        texts = [c.get_text(strip=True) for c in cells]
        for i, t in enumerate(texts):
            if t in ('1', '2', '3', '4', '5', '6') and i + 1 < len(texts):
                v = _safe_float(texts[i + 1].replace(',', ''))
                if v and v > 1.0:
                    odds.setdefault(int(t), v)

    return odds


def get_race_result(race_no, jcd, date_str):
    """
    レース結果（着順）をパース。
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
            if texts and re.match(r'^[1-6]着$', texts[0]):
                rank = int(texts[0][0])
                for t in texts[1:]:
                    if t in ('1', '2', '3', '4', '5', '6'):
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
