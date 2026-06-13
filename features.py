"""特徴量エンジニアリング"""
import numpy as np
import config

FEATURE_NAMES = [
    'boat_no',
    'course',           # 進入コース (1-6)
    'class_rank',       # A1=4, A2=3, B1=2, B2=1
    'national_win_rate',
    'national_top2_rate',
    'venue_win_rate',
    'venue_top2_rate',
    'motor_top2_rate',
    'boat_top2_rate',
    'exhibition_time',
    'wind_speed',
    'wave_height',
    'course1_venue_rate',   # その場の1コース1着率
]

# 各特徴量の欠損時デフォルト値
_DEFAULTS = {
    'boat_no':           3.5,
    'course':            3.5,
    'class_rank':        2.0,
    'national_win_rate': 4.5,
    'national_top2_rate': 0.35,
    'venue_win_rate':    4.5,
    'venue_top2_rate':   0.35,
    'motor_top2_rate':   0.35,
    'boat_top2_rate':    0.35,
    'exhibition_time':   6.80,
    'wind_speed':        2.0,
    'wave_height':       5.0,
    'course1_venue_rate': 0.55,
}


def build_feature_vector(racer: dict, before: dict, jcd: str) -> np.ndarray:
    """
    1艇分の特徴量ベクトル (shape: [len(FEATURE_NAMES)]) を生成する。
    racer    : scraper.get_race_card() の1要素
    before   : scraper.get_before_info() の返り値
    jcd      : 場コード
    """
    boat_no = racer.get('boat_no', 1)
    course = before['course_positions'].get(boat_no, boat_no)  # コース不明→枠番で代替
    ex_time = before['exhibition_times'].get(boat_no, None)

    vals = {
        'boat_no':            float(boat_no),
        'course':             float(course),
        'class_rank':         float(racer.get('class_rank', _DEFAULTS['class_rank'])),
        'national_win_rate':  float(racer.get('national_win_rate', _DEFAULTS['national_win_rate'])),
        'national_top2_rate': float(racer.get('national_top2_rate', _DEFAULTS['national_top2_rate'])),
        'venue_win_rate':     float(racer.get('venue_win_rate', _DEFAULTS['venue_win_rate'])),
        'venue_top2_rate':    float(racer.get('venue_top2_rate', _DEFAULTS['venue_top2_rate'])),
        'motor_top2_rate':    float(racer.get('motor_top2_rate', _DEFAULTS['motor_top2_rate'])),
        'boat_top2_rate':     float(racer.get('boat_top2_rate', _DEFAULTS['boat_top2_rate'])),
        'exhibition_time':    float(ex_time) if ex_time else _DEFAULTS['exhibition_time'],
        'wind_speed':         float(before.get('wind_speed') or _DEFAULTS['wind_speed']),
        'wave_height':        float(before.get('wave_height') or _DEFAULTS['wave_height']),
        'course1_venue_rate': config.COURSE1_WIN_RATES.get(jcd, 0.55),
    }

    return np.array([vals[k] for k in FEATURE_NAMES], dtype=np.float32)


def build_race_matrix(racers, before, jcd):
    """6艇分の特徴量行列を返す (shape: [6, n_features])"""
    return np.vstack([build_feature_vector(r, before, jcd) for r in racers])
