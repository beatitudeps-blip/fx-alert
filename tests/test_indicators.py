"""インディケーター計算のテスト"""
import pandas as pd
import pytest
from src.indicators import calculate_ema, calculate_atr


def test_calculate_ema():
    """EMA計算テスト"""
    data = pd.Series([100, 102, 101, 103, 105, 104, 106, 108])
    ema = calculate_ema(data, period=3)

    assert len(ema) == len(data)
    assert not ema.isna().any()
    # EMAは元データの範囲内に収まる
    assert ema.min() >= data.min()
    assert ema.max() <= data.max()


def test_calculate_atr():
    """ATR計算テスト"""
    df = pd.DataFrame({
        "open": [100, 102, 101, 103, 105],
        "high": [101, 103, 102, 104, 106],
        "low": [99, 101, 100, 102, 104],
        "close": [100.5, 102.5, 101.5, 103.5, 105.5]
    })

    atr = calculate_atr(df, period=3)

    assert len(atr) == len(df)
    # ATRは正の値
    assert (atr >= 0).all()
    # 最初の数本はNaNの可能性があるが、後半は値がある
    assert not atr.iloc[-1] == 0


def test_atr_with_gaps():
    """ギャップがある場合のATRテスト"""
    df = pd.DataFrame({
        "open": [100, 105, 103],
        "high": [101, 106, 104],
        "low": [99, 104, 102],
        "close": [100.5, 105.5, 103.5]
    })

    atr = calculate_atr(df, period=2)
    # ギャップがある場合、ATRは大きくなる
    assert atr.iloc[-1] > 0
