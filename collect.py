"""
過去レースデータを収集して CSV に保存する（モデル学習用）。

使い方:
    python collect.py --start 20260101 --end 20260612
"""
import argparse
import csv
import logging
import os
from datetime import datetime, timedelta

import config
import features as feat
import scraper

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def _date_range(start_str, end_str):
    d = datetime.strptime(start_str, '%Y%m%d')
    end = datetime.strptime(end_str, '%Y%m%d')
    while d <= end:
        yield d.strftime('%Y%m%d')
        d += timedelta(days=1)


def collect_day(date_str, writer, total):
    venues = scraper.get_holding_venues(date_str)
    if not venues:
        logger.info('%s: 開催なし', date_str)
        return total

    for jcd in venues:
        for race_no in range(1, config.MAX_RACES + 1):
            racers = scraper.get_race_card(race_no, jcd, date_str)
            if not racers:
                break

            before = scraper.get_before_info(race_no, jcd, date_str)
            result = scraper.get_race_result(race_no, jcd, date_str)
            if not result:
                continue  # 結果未確定

            for racer in racers:
                boat_no = racer.get('boat_no', 0)
                rank = result.get(boat_no)
                if rank is None:
                    continue

                fv = feat.build_feature_vector(racer, before, jcd)
                row = list(fv) + [1 if rank == 1 else 0]
                writer.writerow(row)
                total += 1

    logger.info('%s: 収集済み累計 %d 件', date_str, total)
    return total


def main():
    ap = argparse.ArgumentParser(description='ボートレース過去データ収集')
    ap.add_argument('--start', required=True, help='開始日 YYYYMMDD')
    ap.add_argument('--end',   required=True, help='終了日 YYYYMMDD')
    ap.add_argument('--out',   default=f'{config.DATA_DIR}/races.csv', help='出力CSVパス')
    args = ap.parse_args()

    os.makedirs(config.DATA_DIR, exist_ok=True)
    file_exists = os.path.exists(args.out)

    with open(args.out, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(feat.FEATURE_NAMES + ['win'])

        total = 0
        for date_str in _date_range(args.start, args.end):
            total = collect_day(date_str, writer, total)

    logger.info('完了: %s に %d 件保存', args.out, total)


if __name__ == '__main__':
    main()
