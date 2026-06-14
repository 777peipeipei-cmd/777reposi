"""
バックテスト: 平和島 過去N日分の予想精度を検証する

使い方:
    python backtest.py              # 過去90日（目安 10〜20分）
    python backtest.py --days 365   # 過去1年（目安 30〜60分）
    python backtest.py --resume     # 前回の続きから再開

制限事項:
    過去データのため「展示タイム・進入コース」は取得できません。
    実際の予想精度より低めになります（これらは重要な特徴量のため）。
"""
import argparse
import json
import logging
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import config
import scraper
import features as feat
import model as mdl

logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(levelname)s %(message)s')

JCD = '04'          # 平和島
VENUE = config.VENUES[JCD]
WORKERS = 4         # 並列数（boatrace.jp への負荷を考慮）
OUTPUT_FILE = Path(config.DATA_DIR) / 'backtest_heiwajima.json'


def _empty_before():
    return {
        'exhibition_times': {},
        'course_positions': {},
        'wind_speed': None,
        'wave_height': None,
    }


def _fetch_race(date_str, race_no):
    """1レース分を取得して (racers, result, winner) を返す"""
    racers = scraper.get_race_card(race_no, JCD, date_str)
    if not racers:
        return None
    result = scraper.get_race_result(race_no, JCD, date_str)
    if not result:
        return None
    winner = next((int(k) for k, v in result.items() if v == 1), None)
    if winner is None:
        return None
    return {'date': date_str, 'race_no': race_no, 'racers': racers, 'winner': winner}


def _analyze(data, predictor):
    """予測と実結果を比較して dict を返す"""
    racers = data['racers']
    winner = data['winner']

    X = feat.build_race_matrix(racers, _empty_before(), JCD)
    probs = predictor.predict_proba(X)

    boat_probs = sorted(
        [(racers[i].get('boat_no', i + 1), float(probs[i])) for i in range(len(racers))],
        key=lambda x: -x[1],
    )
    ranked_boats = [x[0] for x in boat_probs]
    pred_rank = next((i + 1 for i, b in enumerate(ranked_boats) if b == winner), None)

    return {
        'date':          data['date'],
        'race_no':       data['race_no'],
        'winner':        winner,
        'predicted_rank': pred_rank,
        'top1_correct':  ranked_boats[0] == winner if ranked_boats else False,
        'top2_correct':  winner in ranked_boats[:2],
        'top3_correct':  winner in ranked_boats[:3],
        'predicted_top3': ranked_boats[:3],
        'probs':         [(ranked_boats[i], round(boat_probs[i][1] * 100, 1))
                          for i in range(len(boat_probs))],
    }


def _save(races, model_name, days_back):
    total = len(races)
    top1 = sum(1 for r in races if r['top1_correct'])
    top2 = sum(1 for r in races if r['top2_correct'])
    top3 = sum(1 for r in races if r['top3_correct'])
    payload = {
        'venue':       VENUE,
        'jcd':         JCD,
        'model':       model_name,
        'days_back':   days_back,
        'total_races': total,
        'top1_correct': top1, 'top1_rate': round(top1 / total * 100, 1) if total else 0,
        'top2_correct': top2, 'top2_rate': round(top2 / total * 100, 1) if total else 0,
        'top3_correct': top3, 'top3_rate': round(top3 / total * 100, 1) if total else 0,
        'note': '展示タイム・進入コース情報なし（過去データのため）',
        'races':       races,
        'updated_at':  datetime.now().isoformat(),
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def _print_summary(races, model_name, days_back):
    total = len(races)
    if total == 0:
        print('\n取得できたレースがありませんでした。')
        return

    top1 = sum(1 for r in races if r['top1_correct'])
    top2 = sum(1 for r in races if r['top2_correct'])
    top3 = sum(1 for r in races if r['top3_correct'])

    rank_dist = {}
    for r in races:
        rank = r.get('predicted_rank') or 7
        rank_dist[rank] = rank_dist.get(rank, 0) + 1

    print()
    print('=' * 60)
    print(f'【バックテスト結果】{VENUE}  過去{days_back}日間')
    print(f'モデル: {model_name}')
    print(f'有効レース数: {total}')
    print()
    print(f'1位予測 = 1着:  {top1:4d}/{total} ({top1/total*100:.1f}%)')
    print(f'2位以内 = 1着:  {top2:4d}/{total} ({top2/total*100:.1f}%)')
    print(f'3位以内 = 1着:  {top3:4d}/{total} ({top3/total*100:.1f}%)')
    print()
    print('--- 参考ベースライン ---')
    print(f'ランダム (1/6):    16.7%')
    c1_rate = config.COURSE1_WIN_RATES.get(JCD, 0.5)
    print(f'常に1コースを予測: {c1_rate*100:.1f}%')
    print()
    print('予測順位の分布（実際の1着は予測の何位だったか）:')
    for rank in range(1, 8):
        n = rank_dist.get(rank, 0)
        pct = n / total * 100 if total > 0 else 0
        bar = '█' * int(pct / 2)
        label = f'{rank}位' if rank <= 6 else '不明'
        print(f'  {label}: {bar:<20} {n:4d}件 ({pct:.1f}%)')
    print()
    print('※ 展示タイム・進入コース情報なしのため、実際の精度より低めです')
    print(f'結果を保存: {OUTPUT_FILE}')


def run_backtest(days_back: int, resume: bool):
    predictor = mdl.load_predictor()
    print(f'モデル: {predictor.name}')
    print(f'対象:   {VENUE} (jcd={JCD})  過去{days_back}日間  {WORKERS}並列')
    print('※ 過去データのため展示タイム・コース進入は使用しません')
    print('-' * 60)

    # 前回の結果を読み込む（再開用）
    existing = {}
    if resume and OUTPUT_FILE.exists():
        try:
            prev = json.loads(OUTPUT_FILE.read_text(encoding='utf-8'))
            for r in prev.get('races', []):
                existing[f"{r['date']}_{r['race_no']}"] = r
            print(f'前回の結果を読み込み: {len(existing)}レース → 続きから再開します')
        except Exception:
            pass

    today = datetime.now()
    dates = [(today - timedelta(days=d)).strftime('%Y%m%d')
             for d in range(1, days_back + 1)]

    all_results = list(existing.values())

    racing_days = 0
    for date_str in dates:
        deadlines = scraper.get_race_deadlines(JCD, date_str)
        if not deadlines:
            continue
        racing_days += 1

        pending = [(date_str, rno) for rno in sorted(deadlines.keys())
                   if f'{date_str}_{rno}' not in existing]
        if not pending:
            print(f'{date_str}: スキップ（取得済み）')
            continue

        print(f'{date_str}: {len(deadlines)}R', end='', flush=True)

        day_results = []
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(_fetch_race, d, r): (d, r) for d, r in pending}
            for fut in as_completed(futures):
                data = fut.result()
                if data:
                    analyzed = _analyze(data, predictor)
                    day_results.append(analyzed)
                    print('.', end='', flush=True)

        all_results.extend(day_results)
        # 日ごとに中間保存（途中で止めても --resume で再開可能）
        _save(all_results, predictor.name, days_back)
        print(f'  {len(day_results)}件取得')

    print(f'\n開催日: {racing_days}日  有効レース: {len(all_results)}レース')
    _print_summary(all_results, predictor.name, days_back)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='平和島バックテスト')
    parser.add_argument('--days', type=int, default=90,
                        help='過去何日分を検証するか (デフォルト: 90)')
    parser.add_argument('--resume', action='store_true',
                        help='前回の続きから再開する')
    args = parser.parse_args()
    run_backtest(args.days, args.resume)
