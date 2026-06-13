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
    出走表をパース。
    Returns list of dict (艇1〜6):
        boat_no, racer_name, racer_no, class_rank,
        national_win_rate, national_top2_rate,
        venue_win_rate, venue_top2_rate,
        motor_top2_rate, boat_top2_rate
    """
    soup = _fetch(f'{config.BASE_URL}/racelist',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return []

    racers = []

    for n in range(1, 7):
        # is-boatColorN クラスを td または th で探す
        anchor = (soup.find('td', class_=re.compile(rf'\bis-boatColor{n}\b'))
                  or soup.find('th', class_=re.compile(rf'\bis-boatColor{n}\b')))

        d = {'boat_no': n}

        if anchor:
            row1 = anchor.find_parent('tr')
            if row1:
                # rowspan で何行使っているか判定（デフォルト3）
                try:
                    span = max(int(anchor.get('rowspan', 3)), 2)
                except (ValueError, TypeError):
                    span = 3

                # 該当艇の行グループを収集
                rows = [row1]
                r = row1
                for _ in range(span - 1):
                    r = r.find_next_sibling('tr')
                    if r:
                        rows.append(r)

                # 全行から選手名・クラスを抽出
                for row in rows:
                    _extract_name_class(row, d)

                # 行2（インデックス1）から勝率・2連率を抽出
                # 行1にも含まれる場合があるので両方試す
                for row in rows[1:]:
                    if 'national_win_rate' not in d:
                        _extract_rates(row, d)
                # 行1でも補完（念のため）
                if 'national_win_rate' not in d:
                    _extract_rates(rows[0], d)

        racers.append(d)

    # データ不足なら全体フォールバック
    names_found = sum(1 for r in racers if 'racer_name' in r)
    if names_found < 3:
        logger.info('racelist: is-boatColor anchor で名前取得 %d/6 → フォールバック', names_found)
        return _parse_race_card_fallback(soup, racers)

    # 名前が取れたが一部不足の場合もフォールバックで補完
    if names_found < 6:
        racers = _parse_race_card_fallback(soup, racers)

    logger.info('racelist jcd=%s race=%d: 名前=%d/6 クラス=%d/6 勝率=%d/6',
                jcd, race_no,
                sum(1 for r in racers if 'racer_name' in r),
                sum(1 for r in racers if 'class_rank' in r),
                sum(1 for r in racers if 'national_win_rate' in r))

    return racers


def _extract_name_class(row, d):
    """行から選手名リンクと級別を取得（d に書き込む）"""
    for cell in row.find_all(['td', 'th']):
        # 選手名リンク: toban= or racerprofile を含む href（大文字小文字不問）
        for a in cell.find_all('a', href=True):
            href = a.get('href', '')
            if re.search(r'toban|racerprofile', href, re.I):
                txt = a.get_text(strip=True)
                if txt and 'racer_name' not in d:
                    d['racer_name'] = txt
                m = re.search(r'toban=(\d+)', href, re.I)
                if m:
                    d.setdefault('racer_no', m.group(1))
        # 級別
        t = cell.get_text(strip=True)
        if t in _CLASS_MAP and 'class_rank' not in d:
            d['class_rank'] = _CLASS_MAP[t]


def _extract_rates(row, d):
    """
    行から勝率・2連率を取得（d に書き込む）。
    小数点表記の数値を全て収集して _assign_rates に渡す。
    """
    texts = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
    # 小数点を含む数値（桁数不問）
    floats = [f for f in (_safe_float(t) for t in texts
                           if re.match(r'^\d+\.\d+$', t))
              if f is not None]
    _assign_rates(d, floats)


def _assign_rates(d, floats):
    """
    数値列から各種勝率を代入する。
    boatrace.jp の列順: 全国勝率, 全国2連率, 当地勝率, 当地2連率, モーター2連率, ボート2連率
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
            if key not in ('national_win_rate', 'venue_win_rate') and f > 1.0:
                d[key] = f / 100.0   # パーセント → 率
            else:
                d[key] = f
            idx += 1


def _parse_race_card_fallback(soup, existing_racers):
    """is-boatColor が機能しない場合の行ベースフォールバック"""
    racers = {r['boat_no']: r for r in existing_racers}

    # テーブル候補：クラス名で探してから、最大テーブルを試す
    table = (soup.find('table', class_=re.compile(r'is-w748'))
             or soup.find('table', class_=re.compile(r'racer', re.I))
             or _largest_table(soup))
    if not table:
        return list(racers.values())

    current_boat = None
    for row in table.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        texts = [c.get_text(strip=True) for c in cells]
        first = texts[0] if texts else ''

        # 艇番セル検出（数字のみ or 先頭が数字）
        if first in ('1', '2', '3', '4', '5', '6'):
            current_boat = int(first)
            racers.setdefault(current_boat, {'boat_no': current_boat})

        if current_boat is None:
            continue

        d = racers[current_boat]

        for cell in cells:
            for a in cell.find_all('a', href=True):
                href = a.get('href', '')
                if re.search(r'toban|racerprofile', href, re.I):
                    txt = a.get_text(strip=True)
                    if txt:
                        d.setdefault('racer_name', txt)
                    m = re.search(r'toban=(\d+)', href, re.I)
                    if m:
                        d.setdefault('racer_no', m.group(1))

        for t in texts:
            if t in _CLASS_MAP and 'class_rank' not in d:
                d['class_rank'] = _CLASS_MAP[t]

        # 小数点数値を収集（ST平均 0.05〜0.35 の範囲を除外）
        floats = [f for f in (_safe_float(t) for t in texts
                               if re.match(r'^\d+\.\d+$', t))
                  if f is not None and not (0.01 <= f <= 0.49)]
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
        for row in table.find_all('tr'):
            cells = row.find_all(['td', 'th'])
            texts = [c.get_text(strip=True) for c in cells]
            if not texts:
                continue
            if texts[0] in ('1', '2', '3', '4', '5', '6'):
                boat_no = int(texts[0])
                for t in texts[1:]:
                    if re.match(r'^[67]\.\d{2}$', t):
                        result['exhibition_times'][boat_no] = float(t)
                        break

    full_text = soup.get_text()
    m = re.search(r'風速[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wind_speed'] = float(m.group(1))
    m = re.search(r'波高[^\d]*(\d+\.?\d*)', full_text)
    if m:
        result['wave_height'] = float(m.group(1))

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
    単勝オッズをパース（3戦略）。
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
                logger.info('odds jcd=%s %dR: 戦略1で%d艇取得', jcd, race_no, len(odds))
                return odds

    # 戦略2: 艇番+オッズが縦並びの行パターン
    for row in soup.find_all('tr'):
        cells = row.find_all(['td', 'th'])
        texts = [c.get_text(strip=True) for c in cells]
        for i, t in enumerate(texts):
            if t in ('1', '2', '3', '4', '5', '6') and i + 1 < len(texts):
                v = _safe_float(texts[i + 1].replace(',', ''))
                if v and v > 1.0:
                    odds.setdefault(int(t), v)

    if len(odds) >= 2:
        logger.info('odds jcd=%s %dR: 戦略2で%d艇取得', jcd, race_no, len(odds))
        return odds

    # 戦略3: 前行に艇番1〜6が全てある場合、次行をオッズ行として対応
    for row in soup.find_all('tr'):
        prev = row.find_previous_sibling('tr')
        if not prev:
            continue
        prev_texts = [c.get_text(strip=True) for c in prev.find_all(['td', 'th'])]
        if all(str(n) in prev_texts for n in range(1, 7)):
            cur_texts = [c.get_text(strip=True) for c in row.find_all(['td', 'th'])]
            for i, pt in enumerate(prev_texts):
                if pt in ('1', '2', '3', '4', '5', '6') and i < len(cur_texts):
                    v = _safe_float(cur_texts[i].replace(',', ''))
                    if v and v > 1.0:
                        odds.setdefault(int(pt), v)
            if len(odds) >= 2:
                logger.info('odds jcd=%s %dR: 戦略3で%d艇取得', jcd, race_no, len(odds))
                return odds

    if not odds:
        logger.info('odds jcd=%s %dR: オッズ未取得（発売前の可能性）', jcd, race_no)

    return odds


def get_race_result(race_no, jcd, date_str):
    """
    レース結果（着順）をパース。
    Returns dict {boat_no: rank}
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


def debug_scrape_racelist(race_no, jcd, date_str):
    """
    デバッグ用: racelist ページの HTML 構造を返す。
    /api/debug-scraper エンドポイントから呼ぶ。
    """
    soup = _fetch(f'{config.BASE_URL}/racelist',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return {'error': 'fetch failed (403 or network error)'}

    info = {
        'url': f'{config.BASE_URL}/racelist?rno={race_no}&jcd={jcd}&hd={date_str}',
        'tables': [],
        'boat_color_anchors': [],
        'toban_links': [],
        'raw_html_head': str(soup)[:2000],
    }

    for i, tbl in enumerate(soup.find_all('table')[:10]):
        rows = tbl.find_all('tr')
        first_row_texts = []
        if rows:
            first_row_texts = [c.get_text(strip=True)[:15]
                               for c in rows[0].find_all(['td', 'th'])]
        info['tables'].append({
            'idx': i,
            'class': tbl.get('class', []),
            'rows': len(rows),
            'first_row': first_row_texts,
        })

    for n in range(1, 7):
        cells = soup.find_all(class_=re.compile(rf'is-boatColor{n}'))
        info['boat_color_anchors'].append({
            'boat': n,
            'found': len(cells),
            'tag': cells[0].name if cells else None,
            'class': cells[0].get('class') if cells else None,
            'text': cells[0].get_text(strip=True)[:10] if cells else None,
            'rowspan': cells[0].get('rowspan') if cells else None,
        })

    links = soup.find_all('a', href=re.compile(r'toban|racerprofile', re.I))
    for a in links[:8]:
        info['toban_links'].append({
            'href': a.get('href', '')[:80],
            'text': a.get_text(strip=True)[:20],
        })

    return info


def debug_scrape_odds(race_no, jcd, date_str):
    """デバッグ用: odds1t ページの HTML 構造を返す"""
    soup = _fetch(f'{config.BASE_URL}/odds1t',
                  {'rno': race_no, 'jcd': jcd, 'hd': date_str})
    if not soup:
        return {'error': 'fetch failed'}

    info = {
        'tables': [],
        'raw_html_head': str(soup)[:2000],
    }

    for i, tbl in enumerate(soup.find_all('table')[:5]):
        rows = tbl.find_all('tr')
        row_data = []
        for row in rows[:4]:
            row_data.append([c.get_text(strip=True)[:10]
                             for c in row.find_all(['td', 'th'])])
        info['tables'].append({
            'idx': i,
            'class': tbl.get('class', []),
            'rows': len(rows),
            'first_4_rows': row_data,
        })

    return info


def _empty_before():
    return {
        'exhibition_times': {},
        'course_positions': {},
        'wind_speed': None,
        'wave_height': None,
    }
