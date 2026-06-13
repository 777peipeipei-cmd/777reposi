"""
収集したデータで RandomForest モデルを学習・保存する。

使い方:
    python train.py --data data/races.csv
"""
import argparse
import logging
import os

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

import config
import features as feat

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def load_data(csv_path):
    df = pd.read_csv(csv_path)
    X = df[feat.FEATURE_NAMES].values.astype(np.float32)
    y = df['win'].values.astype(int)
    logger.info('データ読み込み: %d 件 (1着: %d / %.1f%%)',
                len(y), y.sum(), y.mean() * 100)
    return X, y


def build_pipeline():
    rf = RandomForestClassifier(
        n_estimators=300,
        max_depth=8,
        min_samples_leaf=20,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1,
    )
    calibrated = CalibratedClassifierCV(rf, cv=5, method='isotonic')
    return Pipeline([
        ('scaler', StandardScaler()),
        ('clf', calibrated),
    ])


def main():
    ap = argparse.ArgumentParser(description='モデル学習')
    ap.add_argument('--data', default=f'{config.DATA_DIR}/races.csv')
    args = ap.parse_args()

    if not os.path.exists(args.data):
        logger.error('データファイルが見つかりません: %s', args.data)
        logger.error('先に collect.py を実行してください。')
        return

    X, y = load_data(args.data)

    if len(y) < 500:
        logger.warning('データが少なすぎます (%d 件)。精度が低い可能性があります。', len(y))

    pipe = build_pipeline()

    # クロスバリデーションで ROC-AUC を確認
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    scores = cross_val_score(pipe, X, y, cv=cv, scoring='roc_auc', n_jobs=-1)
    logger.info('CV ROC-AUC: %.4f ± %.4f', scores.mean(), scores.std())

    # 全データで最終学習
    pipe.fit(X, y)

    os.makedirs(os.path.dirname(config.MODEL_PATH), exist_ok=True)
    joblib.dump(pipe, config.MODEL_PATH)
    logger.info('モデル保存: %s', config.MODEL_PATH)


if __name__ == '__main__':
    main()
