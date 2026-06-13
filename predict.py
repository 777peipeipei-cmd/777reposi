"""
本日のレースから「直前オッズ100倍超 かつ 予測勝率50%超」の艇を検出する。

使い方:
    python predict.py                      # 本日
    python predict.py --date 20260613      # 日付指定
    python predict.py --date 20260613 --jcd 24  # 場も指定
"""
import argparse
import logging
import sys
from datetime import datetime

import config
import features as feat
import model as mdl
import scraper

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
SEPARATOR = '─' * 60
# ─────────────────────────────────────────────────────────────────────────────


def print_header(date_str, predictor_name):
    print()
    print(SEPARATOR)
    print(f'  ボートレース予想  {date_str}  [モデル: {predictor_name}]')
    print(f'  条件: 直前単勝オッズ > {config.ODDS_THRESHOLD:.0f}倍  '
          f'かつ  予測勝率 > {config.WIN_PROB_THRESHOLD * 100:.0f}%')
    print(SEPARATOR)


def analyze_race(race_no, jcd, date_str, predictor):
    """
    1レースを分析し、条件を満たす艇の情報を返す。
    Returns: list of dict
    """
    racers = scraper.get_race_card(race_no, jcd, date_str)
    if not racers:
        return []

    before = scraper.get_before_info(race_no, jcd, date_str)
    odds_map = scraper.get_win_odds(race_no, jcd, date_str)

    if not odds_map:
        logger.debug('オッズ未発表: %s場 %dR', config.VENUES.get(jcd, jcd), race_no)
        return []

    X = feat.build_race_matrix(racers, before, jcd)
    probs = predictor.predict_proba(X)

    hits = []
    for i, racer in enumerate(racers):
        boat_no = racer.get('boat_no', i + 1)
        odds = odds_map.get(boat_no)
        if odds is None:
            continue

        win_prob = probs[i]
        course = before['course_positions'].get(boat_no, boat_no)
        ex_time = before['exhibition_times'].get(boat_no)

        if odds >= config.ODDS_THRESHOLD and win_prob >= config.WIN_PROB_THRESHOLD:
            hits.append({
                'jcd':       jcd,
                'venue':     config.VENUES.get(jcd, jcd),
                'race_no':   race_no,
                'boat_no':   boat_no,
                'racer':     racer.get('racer_name', '不明'),
                'class':     _class_label(racer.get('class_rank')),
                'nwr':       racer.get('national_win_rate'),
                'course':    course,
                'ex_time':   ex_time,
                'motor_r':   racer.get('motor_top2_rate'),
                'odds':      odds,
                'win_prob':  win_prob,
            })

    return hits


def _class_label(rank):
    return {4: 'A1', 3: 'A2', 2: 'B1', 1: 'B2'}.get(rank, '??')


def print_hit(h):
    ex = f"{h['ex_time']:.2f}" if h['ex_time'] else '--.-'
    motor = f"{h['motor_r'] * 100:.1f}%" if h['motor_r'] else '--'
    nwr = f"{h['nwr']:.2f}" if h['nwr'] else '--'

    print()
    print(f"  【 {h['venue']} {h['race_no']}R — {h['boat_no']}号艇 】")
    print(f"  選手     : {h['racer']}  ({h['class']}  全国勝率 {nwr})")
    print(f"  進入コース: {h['course']}コース  展示タイム {ex}")
    print(f"  モーター : 2連率 {motor}")
    print(f"  直前オッズ: {h['odds']:.1f}倍  ★予測勝率: {h['win_prob'] * 100:.1f}%")


def run(date_str, jcd_filter=None):
    predictor = mdl.load_predictor()
    print_header(date_str, predictor.name)

    venues = [jcd_filter] if jcd_filter else scraper.get_holding_venues(date_str)
    if not venues:
        print(f'\n  {date_str} の開催情報が取得できませんでした。')
        return

    all_hits = []
    for jcd in venues:
        venue_name = config.VENUES.get(jcd, jcd)
        logger.info('%s (%s) を確認中...', venue_name, jcd)
        for race_no in range(1, config.MAX_RACES + 1):
            try:
                hits = analyze_race(race_no, jcd, date_str, predictor)
                all_hits.extend(hits)
            except Exception as e:
                logger.warning('%s %dR エラー: %s', venue_name, race_no, e)

    if all_hits:
        print(f'\n  ★ 条件を満たす艇: {len(all_hits)} 件')
        for h in all_hits:
            print_hit(h)
    else:
        print('\n  本日は条件（オッズ100倍超 かつ 予測勝率50%超）を満たす艇は見つかりませんでした。')
        print('  ※ 直前オッズ公開前のレースはスキップされています。')

    print()
    print(SEPARATOR)
    _print_note()


def _print_note():
    print('  ⚠  本ツールの予測は参考情報です。')
    print('  ⚠  オッズ100倍超の艇が実際に50%超で勝つケースは極めてレアです。')
    print('  ⚠  モデル未学習時はルールベース推定（精度低め）を使用しています。')
    print('  ⚠  舟券購入は20歳以上・自己責任でお願いします。')
    print(SEPARATOR)


def main():
    ap = argparse.ArgumentParser(description='ボートレース 高オッズ×高予測勝率 検出')
    ap.add_argument('--date', default=datetime.now().strftime('%Y%m%d'),
                    help='対象日 YYYYMMDD（デフォルト: 今日）')
    ap.add_argument('--jcd',  default=None,
                    help='場コード 01-24（省略時は全場）')
    args = ap.parse_args()

    if args.jcd and args.jcd not in config.VENUES:
        print(f'場コード "{args.jcd}" は無効です。01〜24 の2桁コードを指定してください。')
        sys.exit(1)

    run(args.date, args.jcd)


if __name__ == '__main__':
    main()
