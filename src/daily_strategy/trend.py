"""
週足/日足トレンド判定モジュール
strategy.md セクション6, 7 準拠
"""
import pandas as pd


def calculate_ema_slope(ema_series: pd.Series) -> float:
    """
    EMA slope を計算する。
    定義: ema20_today - ema20_yesterday

    Args:
        ema_series: EMA20 の Series（昇順、末尾が最新）

    Returns:
        slope 値（正=上向き、負=下向き、0=横ばい）
    """
    if len(ema_series) < 2:
        return 0.0
    return float(ema_series.iloc[-1] - ema_series.iloc[-2])


def determine_weekly_trend(weekly_close: float, weekly_ema20: float, weekly_ema_slope: float) -> str:
    """
    週足トレンドを判定する。

    WEEKLY_UP:
        - Weekly Close > Weekly EMA20
        - Weekly EMA20 slope > 0

    WEEKLY_DOWN:
        - Weekly Close < Weekly EMA20
        - Weekly EMA20 slope < 0

    WEEKLY_NEUTRAL:
        - 上記以外

    Returns:
        "WEEKLY_UP", "WEEKLY_DOWN", "WEEKLY_NEUTRAL"
    """
    if weekly_close > weekly_ema20 and weekly_ema_slope > 0:
        return "WEEKLY_UP"
    if weekly_close < weekly_ema20 and weekly_ema_slope < 0:
        return "WEEKLY_DOWN"
    return "WEEKLY_NEUTRAL"


def determine_daily_trend(daily_close: float, daily_ema20: float, daily_ema_slope: float) -> str:
    """
    日足トレンドを判定する。

    DAILY_UP:
        - Daily Close > Daily EMA20
        - Daily EMA20 slope > 0

    DAILY_DOWN:
        - Daily Close < Daily EMA20
        - Daily EMA20 slope < 0

    DAILY_NEUTRAL:
        - 上記以外

    Returns:
        "DAILY_UP", "DAILY_DOWN", "DAILY_NEUTRAL"
    """
    if daily_close > daily_ema20 and daily_ema_slope > 0:
        return "DAILY_UP"
    if daily_close < daily_ema20 and daily_ema_slope < 0:
        return "DAILY_DOWN"
    return "DAILY_NEUTRAL"


def determine_alignment(weekly_trend: str, daily_trend: str) -> str:
    """
    週足/日足の整合性を判定する。

    BUY_ONLY: WEEKLY_UP + DAILY_UP
    SELL_ONLY: WEEKLY_DOWN + DAILY_DOWN
    NO_TRADE: 上記以外

    Returns:
        "BUY_ONLY", "SELL_ONLY", "NO_TRADE"
    """
    if weekly_trend == "WEEKLY_UP" and daily_trend == "DAILY_UP":
        return "BUY_ONLY"
    if weekly_trend == "WEEKLY_DOWN" and daily_trend == "DAILY_DOWN":
        return "SELL_ONLY"
    return "NO_TRADE"
