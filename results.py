"""
レース予測の保存・結果照合・信頼度キャリブレーション

流れ:
  1. save_prediction()  : レース前に予測を保存
  2. collect_result()   : レース後に結果をスクレイピング
  3. Calibrator         : 実績データから信頼度補正係数を計算
"""
import json
import logging
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import config
import scraper

logger = logging.getLogger(__name__)

_PRED_DIR    = Path(config.DATA_DIR) / 'predictions'
_RESULT_DIR  = Path(config.DATA_DIR) / 'results'
_CALIB_FILE  = Path(config.DATA_DIR) / 'calibration.json'

for _d in (_PRED_DIR, _RESULT_DIR):
    _d.mkdir(parents=True, exist_ok=True)


# ─── 予測の保存 ───────────────────────────────────────────────

def _race_key(jcd, race_no, date_str):
    return f'{date_str}_{jcd}_{race_no:02d}'


def save_prediction(jcd, race_no, date_str, boats, trifecta):
    """
    レース前に予測データを保存する。
    boats    : app.py が作る boats リスト
    trifecta : predict_trifecta() の返り値
    """
    key = _race_key(jcd, race_no, date_str)
    path = _PRED_DIR / f'{key}.json'

    payload = {
        'key':       key,
        'jcd':       jcd,
        'venue':     config.VENUES.get(jcd, jcd),
        'race_no':   race_no,
        'date':      date_str,
        'saved_at':  datetime.now().isoformat(),
        'boats': [
            {
                'boat_no':    b['boat_no'],
                'win_prob':   b['win_prob'],
                'confidence': b['confidence'],
                'conf_label': b['conf_label'],
                'odds':       b['odds'],
            }
            for b in boats
        ],
        'trifecta': trifecta,
        'result':   None,   # 後で fill_result() で埋める
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info('予測保存: %s', key)


# ─── 結果の照合 ───────────────────────────────────────────────

def fill_result(jcd, race_no, date_str):
    """
    結果ページをスクレイピングして予測ファイルに書き込む。
    Returns True if result was newly recorded, False otherwise.
    """
    key = _race_key(jcd, race_no, date_str)
    pred_path = _PRED_DIR / f'{key}.json'
    if not pred_path.exists():
        return False

    payload = json.loads(pred_path.read_text(encoding='utf-8'))
    if payload.get('result'):
        return False  # すでに結果あり

    result = scraper.get_race_result(race_no, jcd, date_str)
    if not result:
        return False

    payload['result'] = result           # {boat_no: rank}
    payload['result_at'] = datetime.now().isoformat()
    pred_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

    # calibration 用に result ディレクトリにもコピー
    res_path = _RESULT_DIR / f'{key}.json'
    res_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    logger.info('結果記録: %s → 1着=%s', key,
                next((k for k, v in result.items() if v == 1), '?'))
    return True


def check_pending_results(date_str=None):
    """
    結果未取得の予測ファイルをすべてチェックして result を埋める。
    主にバックグラウンドスレッドから呼ぶ。
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y%m%d')

    filled = 0
    for f in sorted(_PRED_DIR.glob(f'{date_str}_*.json')):
        payload = json.loads(f.read_text(encoding='utf-8'))
        if payload.get('result'):
            continue
        ok = fill_result(payload['jcd'], payload['race_no'], payload['date'])
        if ok:
            filled += 1
    return filled


# ─── Calibrator ──────────────────────────────────────────────

class Calibrator:
    """
    信頼度スコアの実績補正。

    仕組み:
      - 信頼度を 5 バケット (0-20, 20-40, 40-60, 60-80, 80-100) に分ける
      - 各バケットで「予測勝率 vs 実際勝率」のズレを計算
      - 補正係数 = 実際勝率 / 予測平均勝率（ただし0.3〜3.0に制限）
      - 補正後の信頼度 = 元の信頼度 × 補正係数（0〜100にクリップ）
    """

    _N_BUCKETS = 5
    _BUCKET_SIZE = 100.0 / _N_BUCKETS   # 20

    def __init__(self):
        self._factors = [1.0] * self._N_BUCKETS   # 初期は補正なし
        self._sample_counts = [0] * self._N_BUCKETS
        self._load()

    def _bucket(self, score):
        return min(int(score / self._BUCKET_SIZE), self._N_BUCKETS - 1)

    def calibrate(self, raw_score):
        """raw_score (0〜100) → 補正済みスコア (0〜100)"""
        b = self._bucket(raw_score)
        return round(min(max(raw_score * self._factors[b], 0.0), 100.0), 1)

    def label(self, calibrated_score):
        if calibrated_score >= 65:
            return '高'
        elif calibrated_score >= 40:
            return '中'
        else:
            return '低'

    def update_from_results(self):
        """
        全結果ファイルを読んでキャリブレーション係数を更新する。
        """
        # bucket ごとに (予測平均, 実際勝率) を集計
        bucket_pred_sum = [0.0] * self._N_BUCKETS
        bucket_act_sum  = [0.0] * self._N_BUCKETS
        bucket_count    = [0]   * self._N_BUCKETS

        for f in sorted(_RESULT_DIR.glob('*.json')):
            try:
                payload = json.loads(f.read_text(encoding='utf-8'))
            except Exception:
                continue

            result = payload.get('result')
            if not result:
                continue

            winner = next((int(k) for k, v in result.items() if v == 1), None)
            if winner is None:
                continue

            for b in payload.get('boats', []):
                score = b.get('confidence') or 0.0
                actual_win = 1.0 if b['boat_no'] == winner else 0.0
                bk = self._bucket(score)
                bucket_pred_sum[bk] += score / 100.0   # 予測確率
                bucket_act_sum[bk]  += actual_win
                bucket_count[bk]    += 1

        # 係数更新
        for i in range(self._N_BUCKETS):
            n = bucket_count[i]
            if n < 10:
                # データ不足はデフォルト（1.0）を維持
                continue
            pred_mean = bucket_pred_sum[i] / n
            act_mean  = bucket_act_sum[i]  / n
            if pred_mean > 0:
                raw_factor = act_mean / pred_mean
                # 急激な変化を抑えるため指数移動平均で更新
                alpha = 0.3
                self._factors[i] = alpha * raw_factor + (1 - alpha) * self._factors[i]
                self._factors[i] = max(0.3, min(3.0, self._factors[i]))
            self._sample_counts[i] = n

        self._save()
        logger.info('キャリブレーション更新: factors=%s samples=%s',
                    [round(f, 3) for f in self._factors], self._sample_counts)

    def stats(self):
        """精度統計を返す（UI表示用）"""
        rows = []
        labels = ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%']
        for i, (lbl, f, n) in enumerate(
                zip(labels, self._factors, self._sample_counts)):
            rows.append({
                'bucket':  lbl,
                'factor':  round(f, 3),
                'samples': n,
                'status':  '補正中' if n >= 10 else 'データ不足',
            })
        return rows

    def _load(self):
        if _CALIB_FILE.exists():
            try:
                d = json.loads(_CALIB_FILE.read_text(encoding='utf-8'))
                self._factors        = d.get('factors', self._factors)
                self._sample_counts  = d.get('sample_counts', self._sample_counts)
            except Exception:
                pass

    def _save(self):
        _CALIB_FILE.write_text(json.dumps({
            'factors':       self._factors,
            'sample_counts': self._sample_counts,
            'updated_at':    datetime.now().isoformat(),
        }, ensure_ascii=False, indent=2), encoding='utf-8')


# シングルトン
calibrator = Calibrator()
