"""ローソク足パターンのテスト"""
import pandas as pd
import pytest
from src.patterns import (
    is_bullish_engulfing,
    is_bearish_engulfing,
    is_bullish_hammer,
    is_bearish_hammer,
)


def test_bullish_engulfing():
    """Bullish Engulfingパターンテスト"""
    # 陰線 → 陽線（包み足）
    prev = pd.Series({"open": 150.0, "high": 150.5, "low": 149.0, "close": 149.5})
    curr = pd.Series({"open": 149.3, "high": 151.0, "low": 149.0, "close": 150.8})

    assert is_bullish_engulfing(prev, curr) is True

    # 陽線 → 陽線（包み足でない）
    prev2 = pd.Series({"open": 149.0, "high": 150.0, "low": 148.5, "close": 149.8})
    curr2 = pd.Series({"open": 149.5, "high": 151.0, "low": 149.0, "close": 150.5})

    assert is_bullish_engulfing(prev2, curr2) is False


def test_bearish_engulfing():
    """Bearish Engulfingパターンテスト"""
    # 陽線 → 陰線（包み足）
    prev = pd.Series({"open": 149.0, "high": 150.5, "low": 148.5, "close": 150.0})
    curr = pd.Series({"open": 150.5, "high": 151.0, "low": 148.0, "close": 148.5})

    assert is_bearish_engulfing(prev, curr) is True


def test_bullish_hammer():
    """Bullish Hammerパターンテスト"""
    # 長い下ヒゲ、小さな実体
    row = pd.Series({"open": 150.0, "high": 150.5, "low": 148.0, "close": 150.3})

    # 下ヒゲ = 150.0 - 148.0 = 2.0
    # 実体 = 150.3 - 150.0 = 0.3
    # 上ヒゲ = 150.5 - 150.3 = 0.2
    # 下ヒゲ >= 実体 * 1.5 かつ 下ヒゲ >= 上ヒゲ * 2.0

    assert is_bullish_hammer(row) is True

    # 実体が大きい（Hammerでない）
    row2 = pd.Series({"open": 149.0, "high": 151.0, "low": 148.0, "close": 151.0})
    assert is_bullish_hammer(row2) is False


def test_bearish_hammer():
    """Bearish Shooting Starパターンテスト"""
    # 長い上ヒゲ、小さな実体
    row = pd.Series({"open": 150.5, "high": 152.5, "low": 150.0, "close": 150.2})

    # 上ヒゲ = 152.5 - 150.5 = 2.0
    # 実体 = 150.5 - 150.2 = 0.3
    # 下ヒゲ = 150.2 - 150.0 = 0.2

    assert is_bearish_hammer(row) is True
