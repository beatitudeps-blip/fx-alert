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


def calculate_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    ADX（Average Directional Index）を計算

    Args:
        df: OHLC DataFrame (high, low, close列が必要)
        period: 期間

    Returns:
        ADX Series
    """
    high = df["high"]
    low = df["low"]

    # +DM / -DM
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    # ATR（内部計算用）
    atr = calculate_atr(df, period)

    # Smoothed +DI / -DI
    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr)

    # DX → ADX
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    dx = dx.fillna(0.0)
    adx = dx.ewm(alpha=1 / period, adjust=False).mean()

    return adx
