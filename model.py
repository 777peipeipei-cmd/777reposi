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
# モデルロード
# ---------------------------------------------------------------------------

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
