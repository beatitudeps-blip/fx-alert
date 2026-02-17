"""スプレッドモデルのテスト"""
import pandas as pd
from datetime import datetime
import pytest
from src.spread_minnafx import (
    get_spread_pips,
    is_early_morning_jst,
    utc_to_jst,
    add_bid_ask,
)


def test_utc_to_jst_conversion():
    """UTC→JST変換テスト"""
    # UTC 2024-01-01 00:00 = JST 2024-01-01 09:00
    utc_dt = datetime(2024, 1, 1, 0, 0, 0)
    jst_dt = utc_to_jst(utc_dt)
    assert jst_dt.hour == 9
    assert jst_dt.day == 1

    # UTC 2024-01-01 20:00 = JST 2024-01-02 05:00 (早朝)
    utc_dt = datetime(2024, 1, 1, 20, 0, 0)
    jst_dt = utc_to_jst(utc_dt)
    assert jst_dt.hour == 5
    assert jst_dt.day == 2


def test_get_spread_normal_time():
    """通常時間帯のスプレッドテスト（UTCタイムスタンプ想定）"""
    # UTC 03:00 = JST 12:00 → 通常時間帯
    dt = datetime(2024, 1, 1, 3, 0, 0)
    spread = get_spread_pips("USD/JPY", dt)
    assert spread == 0.2


def test_get_spread_early_morning():
    """早朝時間帯のスプレッドテスト（UTCタイムスタンプ想定）"""
    # UTC 21:00 = JST 06:00 → 早朝時間帯
    dt = datetime(2024, 1, 1, 21, 0, 0)
    spread = get_spread_pips("USD/JPY", dt)
    assert spread == 3.9

    # UTC 20:00 = JST 05:00 → 早朝開始
    dt = datetime(2024, 1, 1, 20, 0, 0)
    spread = get_spread_pips("USD/JPY", dt)
    assert spread == 3.9

    # UTC 23:00 = JST 08:00 → 早朝終了（通常時間に戻る）
    dt = datetime(2024, 1, 1, 23, 0, 0)
    spread = get_spread_pips("USD/JPY", dt)
    assert spread == 0.2


def test_is_early_morning():
    """早朝判定テスト（UTCタイムスタンプ想定）"""
    # UTC 20:00 = JST 05:00 → 早朝
    assert is_early_morning_jst(datetime(2024, 1, 1, 20, 0, 0)) is True
    # UTC 21:30 = JST 06:30 → 早朝
    assert is_early_morning_jst(datetime(2024, 1, 1, 21, 30, 0)) is True
    # UTC 22:59 = JST 07:59 → 早朝
    assert is_early_morning_jst(datetime(2024, 1, 1, 22, 59, 0)) is True
    # UTC 23:00 = JST 08:00 → 通常時間
    assert is_early_morning_jst(datetime(2024, 1, 1, 23, 0, 0)) is False
    # UTC 19:59 = JST 04:59 → 通常時間
    assert is_early_morning_jst(datetime(2024, 1, 1, 19, 59, 0)) is False


def test_add_bid_ask():
    """bid/ask追加テスト（UTCタイムスタンプ想定）"""
    # UTC 03:00 = JST 12:00 → 通常時間帯（0.2 pips）
    df = pd.DataFrame({
        "datetime": [datetime(2024, 1, 1, 3, 0, 0)],
        "open": [150.0],
        "high": [150.5],
        "low": [149.5],
        "close": [150.2]
    })

    result = add_bid_ask(df, "USD/JPY")

    # カラムが追加されている
    assert "bid_open" in result.columns
    assert "ask_open" in result.columns
    assert "spread_pips" in result.columns

    # bid < mid < ask
    assert result["bid_open"].iloc[0] < result["open"].iloc[0]
    assert result["ask_open"].iloc[0] > result["open"].iloc[0]

    # スプレッドが正しい（通常時間 = 0.2 pips）
    assert result["spread_pips"].iloc[0] == 0.2
    spread_price = result["ask_open"].iloc[0] - result["bid_open"].iloc[0]
    expected_spread = 0.2 * 0.01  # 0.2 pips
    assert abs(spread_price - expected_spread) < 0.0001


def test_add_bid_ask_early_morning():
    """bid/ask追加テスト（早朝時間帯）"""
    # UTC 21:00 = JST 06:00 → 早朝時間帯（3.9 pips）
    df = pd.DataFrame({
        "datetime": [datetime(2024, 1, 1, 21, 0, 0)],
        "open": [150.0],
        "high": [150.5],
        "low": [149.5],
        "close": [150.2]
    })

    result = add_bid_ask(df, "USD/JPY")

    # スプレッドが早朝料金
    assert result["spread_pips"].iloc[0] == 3.9
    spread_price = result["ask_open"].iloc[0] - result["bid_open"].iloc[0]
    expected_spread = 3.9 * 0.01  # 3.9 pips
    assert abs(spread_price - expected_spread) < 0.0001
