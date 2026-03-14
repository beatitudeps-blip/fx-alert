"""
ローソク足パターン検出テスト
strategy.md セクション9 準拠
"""
import pytest
from src.daily_strategy.patterns import (
    detect_bullish_engulfing,
    detect_bearish_engulfing,
    detect_bullish_pin_bar,
    detect_bearish_pin_bar,
    detect_pattern,
)


class TestBullishEngulfing:
    def test_valid(self):
        # 前日: 陰線 open=151, close=150
        # 当日: 陽線 open=149.5, close=151.5 (前日実体を包む)
        assert detect_bullish_engulfing(
            today_open=149.5, today_close=151.5, today_high=152.0, today_low=149.0,
            prev_open=151.0, prev_close=150.0, prev_high=151.5, prev_low=149.5,
        ) is True

    def test_today_not_bullish(self):
        assert detect_bullish_engulfing(
            today_open=151.5, today_close=149.5, today_high=152.0, today_low=149.0,
            prev_open=151.0, prev_close=150.0, prev_high=151.5, prev_low=149.5,
        ) is False

    def test_prev_not_bearish(self):
        assert detect_bullish_engulfing(
            today_open=149.5, today_close=151.5, today_high=152.0, today_low=149.0,
            prev_open=150.0, prev_close=151.0, prev_high=151.5, prev_low=149.5,
        ) is False

    def test_not_engulfing(self):
        # 当日実体が前日実体を包まない
        assert detect_bullish_engulfing(
            today_open=150.2, today_close=150.8, today_high=151.0, today_low=150.0,
            prev_open=151.0, prev_close=150.0, prev_high=151.5, prev_low=149.5,
        ) is False


class TestBearishEngulfing:
    def test_valid(self):
        # 前日: 陽線 open=150, close=151
        # 当日: 陰線 open=151.5, close=149.5
        assert detect_bearish_engulfing(
            today_open=151.5, today_close=149.5, today_high=152.0, today_low=149.0,
            prev_open=150.0, prev_close=151.0, prev_high=151.5, prev_low=149.5,
        ) is True

    def test_today_not_bearish(self):
        assert detect_bearish_engulfing(
            today_open=149.5, today_close=151.5, today_high=152.0, today_low=149.0,
            prev_open=150.0, prev_close=151.0, prev_high=151.5, prev_low=149.5,
        ) is False


class TestBullishPinBar:
    def test_valid(self):
        # body = 0.5 (open=150.0, close=150.5)
        # lower_wick = 1.5 (low=148.5, min(open,close)=150.0)
        # upper_wick = 0.0 (high=150.5, max(open,close)=150.5)
        assert detect_bullish_pin_bar(
            open_price=150.0, close_price=150.5, high=150.5, low=148.5,
        ) is True

    def test_upper_wick_too_large(self):
        # upper_wick > 0.5 * body → 不成立
        assert detect_bullish_pin_bar(
            open_price=150.0, close_price=150.5, high=151.0, low=148.5,
        ) is False

    def test_lower_wick_too_small(self):
        # lower_wick < 2.0 * body → 不成立
        assert detect_bullish_pin_bar(
            open_price=150.0, close_price=150.5, high=150.5, low=149.5,
        ) is False

    def test_bearish_body(self):
        # close < open → 不成立 (陰線)
        assert detect_bullish_pin_bar(
            open_price=150.5, close_price=150.0, high=150.5, low=148.5,
        ) is False

    def test_zero_body(self):
        # body = 0 → 不成立
        assert detect_bullish_pin_bar(
            open_price=150.0, close_price=150.0, high=150.5, low=148.5,
        ) is False


class TestBearishPinBar:
    def test_valid(self):
        # body = 0.5 (open=150.5, close=150.0)
        # upper_wick = 1.5 (high=152.0, max(open,close)=150.5)
        # lower_wick = 0.0 (min(open,close)=150.0, low=150.0)
        assert detect_bearish_pin_bar(
            open_price=150.5, close_price=150.0, high=152.0, low=150.0,
        ) is True

    def test_lower_wick_too_large(self):
        assert detect_bearish_pin_bar(
            open_price=150.5, close_price=150.0, high=152.0, low=149.0,
        ) is False


class TestDetectPattern:
    def test_buy_only_bullish_engulfing(self):
        today = {"open": 149.5, "close": 151.5, "high": 152.0, "low": 149.0}
        prev = {"open": 151.0, "close": 150.0, "high": 151.5, "low": 149.5}
        name, detected = detect_pattern(today, prev, "BUY_ONLY")
        assert name == "BULLISH_ENGULFING"
        assert detected is True

    def test_sell_only_bearish_engulfing(self):
        today = {"open": 151.5, "close": 149.5, "high": 152.0, "low": 149.0}
        prev = {"open": 150.0, "close": 151.0, "high": 151.5, "low": 149.5}
        name, detected = detect_pattern(today, prev, "SELL_ONLY")
        assert name == "BEARISH_ENGULFING"
        assert detected is True

    def test_no_trade_returns_none(self):
        today = {"open": 149.5, "close": 151.5, "high": 152.0, "low": 149.0}
        prev = {"open": 151.0, "close": 150.0, "high": 151.5, "low": 149.5}
        name, detected = detect_pattern(today, prev, "NO_TRADE")
        assert name == "NONE"
        assert detected is False

    def test_no_pattern_found(self):
        # 当日も前日も陽線 → Engulfing不成立
        today = {"open": 150.0, "close": 150.5, "high": 151.0, "low": 149.5}
        prev = {"open": 149.5, "close": 150.0, "high": 150.5, "low": 149.0}
        name, detected = detect_pattern(today, prev, "BUY_ONLY")
        assert name == "NONE"
        assert detected is False
