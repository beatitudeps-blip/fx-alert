"""
フィルターモジュールテスト
strategy.md セクション8, 11, 12 準拠
"""
import pytest
import pandas as pd
from src.daily_strategy.filters import (
    check_ema_distance,
    check_ema_divergence,
    check_chasing,
    check_weekly_room,
)


class TestEmaDistance:
    def test_pullback_ok(self):
        # 距離 = 0.3, ATR = 1.0 → ratio = 0.3 <= 0.5 → OK
        dist_abs, ratio, ok = check_ema_distance(150.3, 150.0, 1.0)
        assert abs(dist_abs - 0.3) < 1e-6
        assert abs(ratio - 0.3) < 1e-6
        assert ok is True

    def test_pullback_not_ok(self):
        # 距離 = 0.8, ATR = 1.0 → ratio = 0.8 > 0.5 → NG
        dist_abs, ratio, ok = check_ema_distance(150.8, 150.0, 1.0)
        assert ok is False

    def test_exactly_at_threshold(self):
        # 距離 = 0.5, ATR = 1.0 → ratio = 0.5 <= 0.5 → OK
        _, ratio, ok = check_ema_distance(150.5, 150.0, 1.0)
        assert abs(ratio - 0.5) < 1e-6
        assert ok is True

    def test_zero_atr(self):
        _, _, ok = check_ema_distance(150.5, 150.0, 0.0)
        assert ok is False


class TestEmaDivergence:
    def test_divergent(self):
        # 距離 = 1.5, ATR = 1.0 → ratio = 1.5 > 1.0 → 乖離過大
        assert check_ema_divergence(151.5, 150.0, 1.0) is True

    def test_not_divergent(self):
        # 距離 = 0.8, ATR = 1.0 → ratio = 0.8 <= 1.0 → OK
        assert check_ema_divergence(150.8, 150.0, 1.0) is False

    def test_exactly_at_threshold(self):
        # 距離 = 1.0, ATR = 1.0 → ratio = 1.0, not > 1.0 → OK
        assert check_ema_divergence(151.0, 150.0, 1.0) is False


class TestChasing:
    def test_chasing(self):
        # signal_range = 2.0, ATR = 1.0 → 2.0 > 1.5 → 追いかけ
        assert check_chasing(152.0, 150.0, 1.0) is True

    def test_not_chasing(self):
        # signal_range = 1.0, ATR = 1.0 → 1.0 <= 1.5 → OK
        assert check_chasing(151.0, 150.0, 1.0) is False

    def test_at_threshold(self):
        # signal_range = 1.5, ATR = 1.0 → 1.5 not > 1.5 → OK
        assert check_chasing(151.5, 150.0, 1.0) is False


class TestWeeklyRoom:
    def _make_weekly_df(self, highs, lows):
        """テスト用の週足DataFrameを生成する。"""
        n = len(highs)
        return pd.DataFrame({
            "datetime": pd.date_range("2026-01-01", periods=n, freq="W"),
            "open": [150.0] * n,
            "high": highs,
            "low": lows,
            "close": [150.0] * n,
        })

    def test_buy_room_sufficient(self):
        # 12週高値 = 155, entry = 150, risk = 1.0
        # room = 5.0, room_r = 5.0 >= 1.0 → OK
        weekly_df = self._make_weekly_df([155.0] * 12, [145.0] * 12)
        room, room_r, skip = check_weekly_room(weekly_df, 150.0, "BUY_ONLY", 1.0)
        assert room == 5.0
        assert room_r == 5.0
        assert skip is False

    def test_buy_room_insufficient(self):
        # 12週高値 = 150.5, entry = 150.0, risk = 1.0
        # room = 0.5, room_r = 0.5 < 1.0 → SKIP
        weekly_df = self._make_weekly_df([150.5] * 12, [145.0] * 12)
        _, room_r, skip = check_weekly_room(weekly_df, 150.0, "BUY_ONLY", 1.0)
        assert room_r < 1.0
        assert skip is True

    def test_sell_room_sufficient(self):
        # 12週安値 = 145, entry = 150, risk = 1.0
        # room = 5.0 >= 1.0 → OK
        weekly_df = self._make_weekly_df([155.0] * 12, [145.0] * 12)
        _, room_r, skip = check_weekly_room(weekly_df, 150.0, "SELL_ONLY", 1.0)
        assert room_r >= 1.0
        assert skip is False

    def test_sell_room_insufficient(self):
        # 12週安値 = 149.5, entry = 150.0, risk = 1.0
        # room = 0.5 < 1.0 → SKIP
        weekly_df = self._make_weekly_df([155.0] * 12, [149.5] * 12)
        _, room_r, skip = check_weekly_room(weekly_df, 150.0, "SELL_ONLY", 1.0)
        assert skip is True

    def test_no_trade_no_skip(self):
        weekly_df = self._make_weekly_df([155.0] * 12, [145.0] * 12)
        _, _, skip = check_weekly_room(weekly_df, 150.0, "NO_TRADE", 1.0)
        assert skip is False
