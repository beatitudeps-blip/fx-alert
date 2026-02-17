"""V5 トレード戦略ロジック（指値エントリー版）

変更点 vs V4:
- D1環境: ADX14 >= 18 条件追加
- H4セットアップ: EMAタッチ → distance_to_ema <= 0.6*ATR14
- PAトリガー: 同一（engulf/hammer）
- エントリー: 指値（EMA20 ± 0.10*ATR）、次4Hバー内限定
"""
import pandas as pd
from .indicators import calculate_ema, calculate_atr, calculate_adx
from .patterns import (
    is_bullish_engulfing,
    is_bearish_engulfing,
    is_bullish_hammer,
    is_bearish_hammer,
)


EMA_PERIOD = 20
ATR_PERIOD = 14
ADX_PERIOD = 14
ADX_THRESHOLD = 18
DISTANCE_ATR_RATIO = 0.6
LIMIT_ATR_OFFSET = 0.10


def check_daily_environment_long_v5(d1: pd.DataFrame) -> bool:
    """
    日足環境チェック（LONG用：上昇トレンド + ADX >= 18）
    """
    if len(d1) < ADX_PERIOD + 2:
        return False

    d1 = d1.copy()
    d1["ema20"] = calculate_ema(d1["close"], EMA_PERIOD)
    d1["adx14"] = calculate_adx(d1, ADX_PERIOD)
    latest = d1.iloc[-1]
    prev = d1.iloc[-2]

    return (
        latest["close"] > latest["ema20"]
        and latest["ema20"] > prev["ema20"]
        and latest["adx14"] >= ADX_THRESHOLD
    )


def check_daily_environment_short_v5(d1: pd.DataFrame) -> bool:
    """
    日足環境チェック（SHORT用：下降トレンド + ADX >= 18）
    """
    if len(d1) < ADX_PERIOD + 2:
        return False

    d1 = d1.copy()
    d1["ema20"] = calculate_ema(d1["close"], EMA_PERIOD)
    d1["adx14"] = calculate_adx(d1, ADX_PERIOD)
    latest = d1.iloc[-1]
    prev = d1.iloc[-2]

    return (
        latest["close"] < latest["ema20"]
        and latest["ema20"] < prev["ema20"]
        and latest["adx14"] >= ADX_THRESHOLD
    )


def check_signal_v5(h4: pd.DataFrame, d1: pd.DataFrame,
                    distance_atr_ratio: float = DISTANCE_ATR_RATIO,
                    limit_atr_offset: float = LIMIT_ATR_OFFSET) -> dict:
    """
    V5シグナル判定（指値エントリー版）

    変更点:
    - D1: ADX14 >= 18 追加
    - H4: distance_to_ema <= 0.6*ATR14（旧: low<=EMA<=high）
    - 指値計算情報を返す（entry_limit, signal_ema20, signal_atr）

    Returns:
        {
            "signal": "LONG" | "SHORT" | None,
            "reason": str,
            "pattern": str (optional),
            "close": float,
            "ema20": float,
            "atr": float,
            "datetime": datetime,
            "entry_limit": float (指値価格、シグナル時のみ),
        }
    """
    if len(h4) < 2:
        return {
            "signal": None, "reason": "4H足データ不足",
            "close": 0.0, "ema20": 0.0, "atr": 0.0, "datetime": None
        }

    h4 = h4.copy()
    h4["ema20"] = calculate_ema(h4["close"], EMA_PERIOD)
    h4["atr14"] = calculate_atr(h4, ATR_PERIOD)

    latest = h4.iloc[-1]
    prev = h4.iloc[-2]

    base_info = {
        "close": latest["close"],
        "ema20": latest["ema20"],
        "atr": latest["atr14"],
        "datetime": latest["datetime"]
    }

    # D1環境チェック（ADX付き）
    long_env = check_daily_environment_long_v5(d1)
    short_env = check_daily_environment_short_v5(d1)

    if not long_env and not short_env:
        return {**base_info, "signal": None, "reason": "日足環境NG（トレンドなし or ADX不足）"}

    # LONGシグナルチェック
    if long_env:
        # distance_to_ema チェック（0.6*ATR以内）
        distance = abs(latest["close"] - latest["ema20"])
        threshold = distance_atr_ratio * latest["atr14"]
        if distance > threshold:
            return {**base_info, "signal": None,
                    "reason": f"EMA距離超過（LONG）: {distance:.4f} > {threshold:.4f}"}

        # PAトリガー
        is_engulfing = is_bullish_engulfing(prev, latest)
        is_hammer = is_bullish_hammer(latest)
        if not (is_engulfing or is_hammer):
            return {**base_info, "signal": None, "reason": "トリガーパターンなし（LONG）"}

        pattern = "Bullish Engulfing" if is_engulfing else "Bullish Hammer"
        entry_limit = latest["ema20"] - limit_atr_offset * latest["atr14"]

        return {
            **base_info,
            "signal": "LONG",
            "pattern": pattern,
            "entry_limit": entry_limit,
        }

    # SHORTシグナルチェック
    if short_env:
        distance = abs(latest["close"] - latest["ema20"])
        threshold = distance_atr_ratio * latest["atr14"]
        if distance > threshold:
            return {**base_info, "signal": None,
                    "reason": f"EMA距離超過（SHORT）: {distance:.4f} > {threshold:.4f}"}

        is_engulfing = is_bearish_engulfing(prev, latest)
        is_hammer = is_bearish_hammer(latest)
        if not (is_engulfing or is_hammer):
            return {**base_info, "signal": None, "reason": "トリガーパターンなし（SHORT）"}

        pattern = "Bearish Engulfing" if is_engulfing else "Bearish Shooting Star"
        entry_limit = latest["ema20"] + limit_atr_offset * latest["atr14"]

        return {
            **base_info,
            "signal": "SHORT",
            "pattern": pattern,
            "entry_limit": entry_limit,
        }

    return {**base_info, "signal": None, "reason": "条件不成立"}
