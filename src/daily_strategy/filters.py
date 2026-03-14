"""
フィルターモジュール
strategy.md セクション8, 11, 12 準拠
"""
import pandas as pd


# --- 定数 ---
EMA_NEAR_ATR_RATIO = 0.5       # EMA20近辺: <= 0.5 * ATR14
EMA_FAR_ATR_RATIO = 1.0        # EMA乖離過大: > 1.0 * ATR14
CHASING_ATR_RATIO = 1.5        # 追いかけ: signal_range > 1.5 * ATR14
WEEKLY_ROOM_WEEKS = 12          # 直近12週の高安


def check_ema_distance(close: float, daily_ema20: float, atr14: float) -> tuple:
    """
    EMA20 との距離を判定する。

    Returns:
        (ema_distance_abs, ema_distance_atr_ratio, pullback_ok)
        pullback_ok: abs距離 <= 0.5 * ATR14 のとき True
    """
    ema_distance_abs = abs(close - daily_ema20)
    if atr14 <= 0:
        return ema_distance_abs, 0.0, False
    ema_distance_atr_ratio = ema_distance_abs / atr14
    pullback_ok = ema_distance_atr_ratio <= EMA_NEAR_ATR_RATIO
    return ema_distance_abs, ema_distance_atr_ratio, pullback_ok


def check_ema_divergence(close: float, daily_ema20: float, atr14: float) -> bool:
    """
    EMA 乖離過大かどうかを判定する。

    Returns:
        True = 乖離過大 (見送り対象、reason_code: X)
    """
    if atr14 <= 0:
        return True
    return abs(close - daily_ema20) / atr14 > EMA_FAR_ATR_RATIO


def check_chasing(signal_high: float, signal_low: float, atr14: float) -> bool:
    """
    追いかけエントリー回避を判定する。
    signal_range > 1.5 * ATR14 のとき True (見送り)。

    Returns:
        True = 追いかけ (見送り対象)
    """
    signal_range = signal_high - signal_low
    if atr14 <= 0:
        return True
    return signal_range > CHASING_ATR_RATIO * atr14


def check_weekly_room(weekly_df: pd.DataFrame, entry_price: float,
                      alignment: str, risk_price: float) -> tuple:
    """
    週足の抵抗/支持フィルターを判定する。

    BUY時: 直近12週高値までの余地が 1R 未満 → 見送り
    SELL時: 直近12週安値までの余地が 1R 未満 → 見送り

    Args:
        weekly_df: 週足OHLC DataFrame (昇順)
        entry_price: 想定エントリー価格
        alignment: "BUY_ONLY" or "SELL_ONLY"
        risk_price: 1R の価格差 (SL距離)

    Returns:
        (weekly_room_price, weekly_room_r, should_skip)
        should_skip: True のとき見送り (reason_code: S)
    """
    if risk_price <= 0:
        return 0.0, 0.0, True

    recent = weekly_df.tail(WEEKLY_ROOM_WEEKS)

    if alignment == "BUY_ONLY":
        recent_high = float(recent["high"].max())
        room = recent_high - entry_price
        room_r = room / risk_price
        return float(room), float(room_r), bool(room_r < 1.0)

    elif alignment == "SELL_ONLY":
        recent_low = float(recent["low"].min())
        room = entry_price - recent_low
        room_r = room / risk_price
        return float(room), float(room_r), bool(room_r < 1.0)

    return 0.0, 0.0, False
