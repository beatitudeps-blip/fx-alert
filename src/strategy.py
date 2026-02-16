"""トレード戦略ロジック"""
import pandas as pd
from .indicators import calculate_ema, calculate_atr
from .patterns import (
    is_bullish_engulfing,
    is_bearish_engulfing,
    is_bullish_hammer,
    is_bearish_hammer,
)


EMA_PERIOD = 20
ATR_PERIOD = 14


def check_daily_environment_long(d1: pd.DataFrame) -> bool:
    """
    日足環境チェック（LONG用：上昇トレンド）

    Args:
        d1: 日足DataFrame

    Returns:
        環境OKならTrue
    """
    if len(d1) < 2:
        return False

    d1 = d1.copy()
    d1["ema20"] = calculate_ema(d1["close"], EMA_PERIOD)
    latest = d1.iloc[-1]
    prev = d1.iloc[-2]

    # close > EMA20 かつ EMA20上向き
    return latest["close"] > latest["ema20"] and latest["ema20"] > prev["ema20"]


def check_daily_environment_short(d1: pd.DataFrame) -> bool:
    """
    日足環境チェック（SHORT用：下降トレンド）

    Args:
        d1: 日足DataFrame

    Returns:
        環境OKならTrue
    """
    if len(d1) < 2:
        return False

    d1 = d1.copy()
    d1["ema20"] = calculate_ema(d1["close"], EMA_PERIOD)
    latest = d1.iloc[-1]
    prev = d1.iloc[-2]

    # close < EMA20 かつ EMA20下向き
    return latest["close"] < latest["ema20"] and latest["ema20"] < prev["ema20"]


def check_signal(h4: pd.DataFrame, d1: pd.DataFrame) -> dict:
    """
    シグナル判定（LONG/SHORT両対応）

    Args:
        h4: 4時間足DataFrame
        d1: 日足DataFrame

    Returns:
        {
            "signal": "LONG" | "SHORT" | None,
            "reason": str,
            "pattern": str (optional),
            "close": float (always),
            "ema20": float (always),
            "atr": float (always),
            "datetime": datetime (always)
        }
    """
    # 最低2本必要（latest + prev）
    if len(h4) < 2:
        return {"signal": None, "reason": "4H足データ不足", "close": 0.0, "ema20": 0.0, "atr": 0.0, "datetime": None}

    # 4H足の計算（見送り時にも必要なので最初に実行）
    h4 = h4.copy()
    h4["ema20"] = calculate_ema(h4["close"], EMA_PERIOD)
    h4["atr14"] = calculate_atr(h4, ATR_PERIOD)

    latest = h4.iloc[-1]
    prev = h4.iloc[-2]

    # 基本情報（常に返す）
    base_info = {
        "close": latest["close"],
        "ema20": latest["ema20"],
        "atr": latest["atr14"],
        "datetime": latest["datetime"]
    }

    # LONG環境チェック
    long_env = check_daily_environment_long(d1)
    short_env = check_daily_environment_short(d1)

    if not long_env and not short_env:
        return {**base_info, "signal": None, "reason": "日足環境NG（トレンドなし）"}

    # LONGシグナルチェック
    if long_env:
        # EMAタッチチェック
        touch_ema = latest["low"] <= latest["ema20"] <= latest["high"]
        if not touch_ema:
            return {**base_info, "signal": None, "reason": "EMAタッチなし（LONG）"}

        # トリガーチェック
        is_engulfing = is_bullish_engulfing(prev, latest)
        is_hammer = is_bullish_hammer(latest)

        if not (is_engulfing or is_hammer):
            return {**base_info, "signal": None, "reason": "トリガーパターンなし（LONG）"}

        pattern = "Bullish Engulfing" if is_engulfing else "Bullish Hammer"
        return {
            **base_info,
            "signal": "LONG",
            "pattern": pattern
        }

    # SHORTシグナルチェック
    if short_env:
        # EMAタッチチェック
        touch_ema = latest["low"] <= latest["ema20"] <= latest["high"]
        if not touch_ema:
            return {**base_info, "signal": None, "reason": "EMAタッチなし（SHORT）"}

        # トリガーチェック
        is_engulfing = is_bearish_engulfing(prev, latest)
        is_hammer = is_bearish_hammer(latest)

        if not (is_engulfing or is_hammer):
            return {**base_info, "signal": None, "reason": "トリガーパターンなし（SHORT）"}

        pattern = "Bearish Engulfing" if is_engulfing else "Bearish Shooting Star"
        return {
            **base_info,
            "signal": "SHORT",
            "pattern": pattern
        }

    return {**base_info, "signal": None, "reason": "条件不成立"}
