"""4H足・日足の確定判定ロジックのユニットテスト

ルックアヘッドバイアス回避のための確定判定が正しく動作することを検証:
- 4H足: bar_end_time (= datetime + 4h) <= now で確定判定
- 日足: bar_end_time (= datetime + 1day) <= now で確定判定
- 1本待ちエントリー: entry_dt = bar_dt + 8h
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pandas as pd
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


tz = ZoneInfo("Asia/Tokyo")


def make_h4_df(datetimes):
    """テスト用4H足DataFrameを生成"""
    data = []
    for dt in datetimes:
        data.append({
            "datetime": dt,
            "open": 160.0,
            "high": 161.0,
            "low": 159.0,
            "close": 160.5,
        })
    return pd.DataFrame(data)


def make_d1_df(datetimes):
    """テスト用日足DataFrameを生成"""
    data = []
    for dt in datetimes:
        data.append({
            "datetime": dt,
            "open": 160.0,
            "high": 162.0,
            "low": 158.0,
            "close": 161.0,
        })
    return pd.DataFrame(data)


def filter_confirmed_h4(h4, now):
    """signal_detector.pyと同じ4H足確定フィルタ"""
    h4_end_time = h4["datetime"] + pd.Timedelta(hours=4)
    return h4[h4_end_time <= now].copy()


def filter_confirmed_d1(d1, now):
    """signal_detector.pyと同じ日足確定フィルタ"""
    d1_end_time = d1["datetime"] + pd.Timedelta(days=1)
    return d1[d1_end_time <= now].copy()


# ========== 4H足の確定判定テスト ==========

class TestH4BarConfirmation:
    """4H足の確定判定テスト"""

    def test_confirmed_bar_included(self):
        """12:00足(12:00-16:00)は16:00以降に確定として含まれる"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 12, 0, tzinfo=tz),  # 12:00-16:00
        ])
        now = datetime(2026, 2, 16, 16, 0, 1, tzinfo=tz)  # 16:00:01
        result = filter_confirmed_h4(h4, now)
        assert len(result) == 1
        assert result.iloc[0]["datetime"] == datetime(2026, 2, 16, 12, 0, tzinfo=tz)

    def test_unconfirmed_bar_excluded(self):
        """16:00足(16:00-20:00)は19:59時点で未確定として除外される"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 16, 0, tzinfo=tz),  # 16:00-20:00
        ])
        now = datetime(2026, 2, 16, 19, 59, 59, tzinfo=tz)  # 19:59:59
        result = filter_confirmed_h4(h4, now)
        assert len(result) == 0

    def test_bar_confirmed_exactly_at_end(self):
        """16:00足(16:00-20:00)は20:00ちょうどに確定"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 16, 0, tzinfo=tz),  # 16:00-20:00
        ])
        now = datetime(2026, 2, 16, 20, 0, 0, tzinfo=tz)  # 20:00:00
        result = filter_confirmed_h4(h4, now)
        assert len(result) == 1

    def test_mixed_confirmed_and_unconfirmed(self):
        """16:56時点で12:00足は確定、16:00足は未確定"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 8, 0, tzinfo=tz),   # 08:00-12:00 → 確定
            datetime(2026, 2, 16, 12, 0, tzinfo=tz),   # 12:00-16:00 → 確定
            datetime(2026, 2, 16, 16, 0, tzinfo=tz),   # 16:00-20:00 → 未確定
            datetime(2026, 2, 16, 20, 0, tzinfo=tz),   # 20:00-00:00 → 未確定
        ])
        now = datetime(2026, 2, 16, 16, 56, 0, tzinfo=tz)  # 16:56
        result = filter_confirmed_h4(h4, now)
        assert len(result) == 2
        # 最新の確定足は12:00
        assert result.iloc[-1]["datetime"] == datetime(2026, 2, 16, 12, 0, tzinfo=tz)

    def test_old_buggy_logic_would_include_unconfirmed(self):
        """旧ロジック(datetime < now)だと16:00足が誤って含まれることを証明"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 12, 0, tzinfo=tz),   # 12:00-16:00
            datetime(2026, 2, 16, 16, 0, tzinfo=tz),   # 16:00-20:00
        ])
        now = datetime(2026, 2, 16, 16, 56, 0, tzinfo=tz)  # 16:56

        # 旧ロジック（バグ）: ラベル時刻で判定
        old_result = h4[h4["datetime"] < now].copy()
        assert len(old_result) == 2  # 16:00足を含んでしまう（バグ）

        # 新ロジック（正しい）: 終了時刻で判定
        new_result = filter_confirmed_h4(h4, now)
        assert len(new_result) == 1  # 16:00足を除外（正しい）


# ========== 日足の確定判定テスト ==========

class TestD1BarConfirmation:
    """日足の確定判定テスト"""

    def test_yesterday_bar_confirmed(self):
        """昨日の日足は今日の00:00以降に確定"""
        d1 = make_d1_df([
            datetime(2026, 2, 15, 0, 0, tzinfo=tz),  # 2/15の日足
        ])
        now = datetime(2026, 2, 16, 10, 0, 0, tzinfo=tz)  # 2/16 10:00
        result = filter_confirmed_d1(d1, now)
        assert len(result) == 1

    def test_today_bar_not_confirmed(self):
        """今日の日足は今日中は未確定"""
        d1 = make_d1_df([
            datetime(2026, 2, 16, 0, 0, tzinfo=tz),  # 2/16の日足
        ])
        now = datetime(2026, 2, 16, 23, 59, 59, tzinfo=tz)  # 2/16 23:59
        result = filter_confirmed_d1(d1, now)
        assert len(result) == 0

    def test_today_bar_confirmed_next_day(self):
        """今日の日足は翌日00:00に確定"""
        d1 = make_d1_df([
            datetime(2026, 2, 16, 0, 0, tzinfo=tz),  # 2/16の日足
        ])
        now = datetime(2026, 2, 17, 0, 0, 0, tzinfo=tz)  # 2/17 00:00
        result = filter_confirmed_d1(d1, now)
        assert len(result) == 1

    def test_old_buggy_logic_would_include_today(self):
        """旧ロジック(datetime < now)だと今日の日足が誤って含まれることを証明"""
        d1 = make_d1_df([
            datetime(2026, 2, 15, 0, 0, tzinfo=tz),  # 2/15の日足
            datetime(2026, 2, 16, 0, 0, tzinfo=tz),  # 2/16の日足（未確定）
        ])
        now = datetime(2026, 2, 16, 14, 30, 0, tzinfo=tz)  # 2/16 14:30

        # 旧ロジック（バグ）
        old_result = d1[d1["datetime"] < now].copy()
        assert len(old_result) == 2  # 今日の日足を含んでしまう（バグ）

        # 新ロジック（正しい）
        new_result = filter_confirmed_d1(d1, now)
        assert len(new_result) == 1  # 今日の日足を除外（正しい）


# ========== 1本待ちエントリー時刻テスト ==========

class TestOneBarWaitEntry:
    """1本待ちエントリー時刻の計算テスト"""

    def test_entry_is_8h_after_bar_label(self):
        """エントリー時刻 = 確定足ラベル + 8h"""
        bar_dt = datetime(2026, 2, 16, 12, 0, tzinfo=tz)  # 12:00足
        entry_dt = bar_dt + timedelta(hours=8)
        assert entry_dt == datetime(2026, 2, 16, 20, 0, tzinfo=tz)

    def test_skip_bar_is_correct(self):
        """スキップする足 = 確定足の次の4H足"""
        bar_dt = datetime(2026, 2, 16, 12, 0, tzinfo=tz)
        bar_end = bar_dt + timedelta(hours=4)   # 16:00 (確定時刻)
        skip_start = bar_end                    # 16:00 (スキップ足開始)
        skip_end = bar_end + timedelta(hours=4) # 20:00 (スキップ足終了)
        entry_dt = bar_dt + timedelta(hours=8)  # 20:00 (エントリー)

        assert bar_end == datetime(2026, 2, 16, 16, 0, tzinfo=tz)
        assert skip_start == datetime(2026, 2, 16, 16, 0, tzinfo=tz)
        assert skip_end == datetime(2026, 2, 16, 20, 0, tzinfo=tz)
        assert entry_dt == skip_end  # エントリーはスキップ足終了時

    def test_entry_timing_across_midnight(self):
        """深夜を跨ぐ場合のエントリー時刻"""
        bar_dt = datetime(2026, 2, 16, 20, 0, tzinfo=tz)  # 20:00足
        entry_dt = bar_dt + timedelta(hours=8)
        assert entry_dt == datetime(2026, 2, 17, 4, 0, tzinfo=tz)

    def test_backtest_entry_index(self):
        """バックテストのi+2エントリーが正しいことを検証"""
        h4 = make_h4_df([
            datetime(2026, 2, 16, 8, 0, tzinfo=tz),   # i=0: 確定足
            datetime(2026, 2, 16, 12, 0, tzinfo=tz),   # i=1: スキップ
            datetime(2026, 2, 16, 16, 0, tzinfo=tz),   # i=2: エントリー
        ])
        signal_bar_idx = 0
        entry_bar = h4.iloc[signal_bar_idx + 2]
        assert entry_bar["datetime"] == datetime(2026, 2, 16, 16, 0, tzinfo=tz)


# ========== check_signal ガード条件テスト ==========

class TestCheckSignalGuard:
    """check_signalのデータ不足ガードテスト"""

    def test_insufficient_h4_data(self):
        """4H足が1本しかない場合はNoneシグナルを返す"""
        from src.strategy import check_signal

        h4 = make_h4_df([
            datetime(2026, 2, 16, 12, 0, tzinfo=tz),
        ])
        d1 = make_d1_df([
            datetime(2026, 2, 15, 0, 0, tzinfo=tz),
            datetime(2026, 2, 14, 0, 0, tzinfo=tz),
        ])

        result = check_signal(h4, d1)
        assert result["signal"] is None
        assert result["reason"] == "4H足データ不足"

    def test_empty_h4_data(self):
        """4H足が空の場合"""
        from src.strategy import check_signal

        h4 = make_h4_df([])
        d1 = make_d1_df([
            datetime(2026, 2, 15, 0, 0, tzinfo=tz),
        ])

        result = check_signal(h4, d1)
        assert result["signal"] is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
