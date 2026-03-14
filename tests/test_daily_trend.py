"""
日足/週足トレンド判定テスト
strategy.md セクション6, 7 準拠
"""
import pytest
import pandas as pd
from src.daily_strategy.trend import (
    calculate_ema_slope,
    determine_weekly_trend,
    determine_daily_trend,
    determine_alignment,
)


class TestEmaSlope:
    def test_positive_slope(self):
        s = pd.Series([100.0, 101.0, 102.0])
        assert calculate_ema_slope(s) == 1.0

    def test_negative_slope(self):
        s = pd.Series([102.0, 101.0, 100.0])
        assert calculate_ema_slope(s) == -1.0

    def test_zero_slope(self):
        s = pd.Series([100.0, 100.0, 100.0])
        assert calculate_ema_slope(s) == 0.0

    def test_single_value(self):
        s = pd.Series([100.0])
        assert calculate_ema_slope(s) == 0.0


class TestWeeklyTrend:
    def test_weekly_up(self):
        assert determine_weekly_trend(155.0, 150.0, 0.5) == "WEEKLY_UP"

    def test_weekly_down(self):
        assert determine_weekly_trend(148.0, 150.0, -0.5) == "WEEKLY_DOWN"

    def test_weekly_neutral_close_above_slope_negative(self):
        # Close > EMA だが slope < 0
        assert determine_weekly_trend(155.0, 150.0, -0.5) == "WEEKLY_NEUTRAL"

    def test_weekly_neutral_close_below_slope_positive(self):
        # Close < EMA だが slope > 0
        assert determine_weekly_trend(148.0, 150.0, 0.5) == "WEEKLY_NEUTRAL"

    def test_weekly_neutral_close_equal(self):
        assert determine_weekly_trend(150.0, 150.0, 0.5) == "WEEKLY_NEUTRAL"

    def test_weekly_neutral_slope_zero(self):
        assert determine_weekly_trend(155.0, 150.0, 0.0) == "WEEKLY_NEUTRAL"


class TestDailyTrend:
    def test_daily_up(self):
        assert determine_daily_trend(155.0, 150.0, 0.3) == "DAILY_UP"

    def test_daily_down(self):
        assert determine_daily_trend(148.0, 150.0, -0.3) == "DAILY_DOWN"

    def test_daily_neutral(self):
        assert determine_daily_trend(155.0, 150.0, -0.3) == "DAILY_NEUTRAL"


class TestAlignment:
    def test_buy_only(self):
        assert determine_alignment("WEEKLY_UP", "DAILY_UP") == "BUY_ONLY"

    def test_sell_only(self):
        assert determine_alignment("WEEKLY_DOWN", "DAILY_DOWN") == "SELL_ONLY"

    def test_no_trade_mismatch(self):
        assert determine_alignment("WEEKLY_UP", "DAILY_DOWN") == "NO_TRADE"

    def test_no_trade_weekly_neutral(self):
        assert determine_alignment("WEEKLY_NEUTRAL", "DAILY_UP") == "NO_TRADE"

    def test_no_trade_daily_neutral(self):
        assert determine_alignment("WEEKLY_UP", "DAILY_NEUTRAL") == "NO_TRADE"

    def test_no_trade_both_neutral(self):
        assert determine_alignment("WEEKLY_NEUTRAL", "DAILY_NEUTRAL") == "NO_TRADE"
