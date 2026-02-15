"""テクニカル指標計算モジュール"""
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """
    EMA（指数移動平均）を計算

    Args:
        series: 価格データ（通常はclose）
        period: 期間

    Returns:
        EMA Series
    """
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ATR（Average True Range）を計算

    Args:
        df: OHLC DataFrame (open, high, low, close列が必要)
        period: 期間

    Returns:
        ATR Series
    """
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()
