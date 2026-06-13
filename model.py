"""
予測モデル。
- 学習済みモデルがあれば RandomForest + 確率キャリブレーション を使用。
- なければルールベースモデルで代替。
"""
import os
import logging

import numpy as np
import joblib

import config
import features as feat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ルールベースモデル（学習データ不要）
# ---------------------------------------------------------------------------

# コース別期待値重み（全国平均1着率を基準）
_COURSE_WEIGHT = {1: 4.50, 2: 0.89, 3: 0.76, 4: 0.68, 5: 0.70, 6: 0.71}


class RuleBasedPredictor:
    """
    ドメイン知識をベースにした確率スコアリング。
    出力は6艇の予測勝率（合計≒1）。
    """

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        X: shape [6, n_features]
        Returns: shape [6] — 各艇の推定勝率
        """
        scores = []
        for row in X:
            idx = {k: i for i, k in enumerate(feat.FEATURE_NAMES)}
            course       = int(row[idx['course']])
            cls          = row[idx['class_rank']]
            nwr          = row[idx['national_win_rate']]
            motor        = row[idx['motor_top2_rate']]
            ex_time      = row[idx['exhibition_time']]
            c1_rate      = row[idx['course1_venue_rate']]

            # コース係数（1コースは場によって重みを調整）
            base = _COURSE_WEIGHT.get(course, 0.70)
            if course == 1:
                # その場の1コース1着率を反映
                base = base * (c1_rate / 0.546)

            # 選手力（クラスと全国勝率）
            skill = (cls / 4.0) * 0.5 + (min(nwr, 8.0) / 8.0) * 0.5

            # モーター
            motor_factor = 0.8 + (motor / 0.5) * 0.4  # 50%基準

            # 展示タイム（速いほど有利、6.70が基準）
            ex_factor = 1.0 + (6.80 - ex_time) * 0.5  # 0.05秒速いごとに+2.5%

            score = base * (0.4 + skill * 0.6) * motor_factor * ex_factor
            scores.append(max(score, 0.01))

        arr = np.array(scores, dtype=np.float64)
        return arr / arr.sum()

    @property
    def name(self):
        return 'RuleBased'


# ---------------------------------------------------------------------------
# MLモデル（RandomForest + CalibratedClassifier）
# ---------------------------------------------------------------------------

class MLPredictor:
    """joblib でシリアライズされた sklearn パイプラインをラップする"""

    def __init__(self, pipeline):
        self._pipe = pipeline

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        X: shape [6, n_features]
        Returns: shape [6] — 各艇の推定勝率（レース内で正規化）
        """
        probs = self._pipe.predict_proba(X)[:, 1]  # P(win=1)
        total = probs.sum()
        if total == 0:
            return np.ones(len(probs)) / len(probs)
        return probs / total

    @property
    def name(self):
        return 'RandomForest'


# ---------------------------------------------------------------------------
# 3連単予測（Harville式）
# ---------------------------------------------------------------------------

def predict_trifecta(win_probs, boat_nos, top_n=6):
    """
    Harville式で3連単の組み合わせ確率を計算し、上位 top_n を返す。

    win_probs : list[float] — 各艇の予測勝率（合計≒1）
    boat_nos  : list[int]   — 対応する艇番（同インデックス）
    Returns   : list of dict {combo, prob, label}
    """
    n = len(win_probs)
    results = []

    for i in range(n):
        p1 = win_probs[i]
        if p1 <= 0:
            continue
        rem1 = 1.0 - p1
        if rem1 <= 0:
            continue
        for j in range(n):
            if j == i:
                continue
            p2 = win_probs[j] / rem1
            rem2 = rem1 - win_probs[j]
            if rem2 <= 0:
                continue
            for k in range(n):
                if k == i or k == j:
                    continue
                p3 = win_probs[k] / rem2
                prob = p1 * p2 * p3
                results.append({
                    'combo': [boat_nos[i], boat_nos[j], boat_nos[k]],
                    'prob':  round(prob * 100, 2),
                })

    results.sort(key=lambda x: -x['prob'])
    top = results[:top_n]

    # ラベル：最有力/有力/参考
    for idx, r in enumerate(top):
        if idx == 0:
            r['label'] = '最有力'
        elif idx <= 1:
            r['label'] = '有力'
        else:
            r['label'] = '参考'

    return top


# ---------------------------------------------------------------------------
# モデルロード
# ---------------------------------------------------------------------------

def compute_confidence(racer, before, boat_no, win_prob, all_probs, model_name):
    """
    予測の信頼確度（0〜100）とラベル（高/中/低）とブレークダウンを返す。

    評価要素:
      1. データ完全性  : 展示タイム・モーター・勝率・進入コースが揃っているか
      2. 予測の余裕    : 予測勝率が50%からどれだけ離れているか
      3. 支配度        : 1番手と2番手の予測勝率差
      4. モデル係数    : 学習済みML > ルールベース
    """
    # 1. データ完全性（4項目）
    present = 0
    if before['exhibition_times'].get(boat_no) is not None:
        present += 1
    if racer.get('motor_top2_rate') is not None:
        present += 1
    if racer.get('national_win_rate') is not None:
        present += 1
    if before['course_positions'].get(boat_no) is not None:
        present += 1
    completeness = present / 4.0

    # 2. 予測の余裕（勝率0.5→0, 1.0→1.0）
    margin = min(max(win_prob - 0.5, 0.0) / 0.5, 1.0)

    # 3. 支配度（1位と2位の差。0.4差で満点）
    sorted_p = sorted(all_probs, reverse=True)
    top = sorted_p[0]
    second = sorted_p[1] if len(sorted_p) > 1 else 0.0
    dominance = min(max(top - second, 0.0) / 0.4, 1.0)

    # 4. モデル係数
    base = 1.0 if model_name == 'RandomForest' else 0.75

    score = base * (0.35 * completeness + 0.35 * margin + 0.30 * dominance)
    pct = round(score * 100, 1)

    label = '高' if pct >= 65 else ('中' if pct >= 40 else '低')

    breakdown = {
        'completeness_items': present,
        'completeness_score': round(0.35 * completeness * 100, 1),
        'margin_score':       round(0.35 * margin * 100, 1),
        'win_prob_pct':       round(win_prob * 100, 1),
        'dominance_score':    round(0.30 * dominance * 100, 1),
        'gap_pct':            round((top - second) * 100, 1),
        'model_base':         base,
        'model_name':         model_name,
        'raw_score':          pct,
    }

    return pct, label, breakdown


def load_predictor():
    """学習済みモデルがあれば MLPredictor、なければ RuleBasedPredictor を返す"""
    if os.path.exists(config.MODEL_PATH):
        try:
            pipe = joblib.load(config.MODEL_PATH)
            logger.info('Loaded ML model from %s', config.MODEL_PATH)
            return MLPredictor(pipe)
        except Exception as e:
            logger.warning('Failed to load model: %s — falling back to rule-based', e)
    logger.info('Using rule-based predictor (no trained model found)')
    return RuleBasedPredictor()
