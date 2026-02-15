"""みんなのFXスプレッドモデル"""
from datetime import datetime, time, timedelta, timezone
import pandas as pd


# スプレッド設定（pips）
SPREAD_CONFIG = {
    "USD/JPY": {"normal": 0.2, "early": 3.9},
    "EUR/JPY": {"normal": 0.4, "early": 9.9},
    "GBP/JPY": {"normal": 0.9, "early": 14.9},
}

# 早朝時間帯の定義（JST）
EARLY_MORNING_START = time(5, 0)  # 05:00
EARLY_MORNING_END = time(8, 0)    # 08:00

# JST = UTC+9
JST = timezone(timedelta(hours=9))


def utc_to_jst(dt: datetime) -> datetime:
    """
    UTC datetimeをJSTに変換

    Args:
        dt: UTC datetime（timezone-naive または timezone-aware）

    Returns:
        JST datetime
    """
    # timezone-naiveな場合、UTCとして扱う
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # JSTに変換
    return dt.astimezone(JST)


def is_early_morning_jst(dt: datetime) -> bool:
    """
    早朝時間帯（JST 05:00-08:00）かどうか判定

    CRITICAL: Twelve Data APIはUTCタイムスタンプを返すため、
    必ずUTC→JST変換を行ってから時刻判定する

    Args:
        dt: datetime（UTCタイムスタンプ想定）

    Returns:
        早朝時間帯ならTrue
    """
    # UTC → JST変換
    dt_jst = utc_to_jst(dt)
    t = dt_jst.time()
    return EARLY_MORNING_START <= t < EARLY_MORNING_END


def get_spread_pips(symbol: str, dt: datetime) -> float:
    """
    指定時刻のスプレッド（pips）を取得

    CRITICAL: Twelve Data APIはUTCタイムスタンプを返すため、
    内部でUTC→JST変換を行ってスプレッドを決定する

    Args:
        symbol: 通貨ペア（例: "USD/JPY"）
        dt: datetime（UTCタイムスタンプ想定）

    Returns:
        スプレッド（pips）
    """
    if symbol not in SPREAD_CONFIG:
        raise ValueError(f"Unknown symbol: {symbol}")

    cfg = SPREAD_CONFIG[symbol]
    return cfg["early"] if is_early_morning_jst(dt) else cfg["normal"]


def add_bid_ask(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    mid価格からbid/askを生成してDataFrameに追加

    Args:
        df: OHLC DataFrame（datetime, open, high, low, close列が必要）
        symbol: 通貨ペア

    Returns:
        bid_open, bid_high, bid_low, bid_close, ask_open, ask_high, ask_low, ask_close列を追加したDataFrame
    """
    df = df.copy()

    # 各行のスプレッド（pips）を計算
    df["spread_pips"] = df["datetime"].apply(lambda dt: get_spread_pips(symbol, dt))

    # pips → 価格差（JPYペアは0.01 = 1pip）
    df["half_spread"] = df["spread_pips"] * 0.01 / 2

    # bid/ask生成
    for col in ["open", "high", "low", "close"]:
        df[f"bid_{col}"] = df[col] - df["half_spread"]
        df[f"ask_{col}"] = df[col] + df["half_spread"]

    return df
