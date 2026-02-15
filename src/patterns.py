"""ローソク足パターン検出モジュール"""
import pandas as pd


def is_bullish_engulfing(prev_row: pd.Series, curr_row: pd.Series) -> bool:
    """
    Bullish Engulfingパターン判定

    Args:
        prev_row: 1本前の足（open, high, low, close）
        curr_row: 現在の足（open, high, low, close）

    Returns:
        パターン成立ならTrue
    """
    prev_bearish = prev_row["close"] < prev_row["open"]
    curr_bullish = curr_row["close"] > curr_row["open"]
    engulfing = (
        curr_row["close"] >= prev_row["open"] and
        curr_row["open"] <= prev_row["close"]
    )
    return prev_bearish and curr_bullish and engulfing


def is_bearish_engulfing(prev_row: pd.Series, curr_row: pd.Series) -> bool:
    """
    Bearish Engulfingパターン判定

    Args:
        prev_row: 1本前の足
        curr_row: 現在の足

    Returns:
        パターン成立ならTrue
    """
    prev_bullish = prev_row["close"] > prev_row["open"]
    curr_bearish = curr_row["close"] < curr_row["open"]
    engulfing = (
        curr_row["close"] <= prev_row["open"] and
        curr_row["open"] >= prev_row["close"]
    )
    return prev_bullish and curr_bearish and engulfing


def is_bullish_hammer(row: pd.Series) -> bool:
    """
    Bullish Hammerパターン判定（長い下ヒゲ）

    Args:
        row: 対象の足（open, high, low, close）

    Returns:
        パターン成立ならTrue
    """
    body = abs(row["close"] - row["open"])
    if body <= 0:
        return False

    lower_wick = min(row["open"], row["close"]) - row["low"]
    upper_wick = row["high"] - max(row["open"], row["close"])

    return (
        row["close"] > row["open"] and
        lower_wick >= body * 1.5 and
        lower_wick >= upper_wick * 2.0
    )


def is_bearish_hammer(row: pd.Series) -> bool:
    """
    Bearish Shooting Star/Hammer判定（長い上ヒゲ）

    Args:
        row: 対象の足

    Returns:
        パターン成立ならTrue
    """
    body = abs(row["close"] - row["open"])
    if body <= 0:
        return False

    lower_wick = min(row["open"], row["close"]) - row["low"]
    upper_wick = row["high"] - max(row["open"], row["close"])

    return (
        row["close"] < row["open"] and
        upper_wick >= body * 1.5 and
        upper_wick >= lower_wick * 2.0
    )
