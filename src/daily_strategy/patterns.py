"""
ローソク足パターン検出モジュール
strategy.md セクション9 準拠
"""


def detect_bullish_engulfing(today_open: float, today_close: float, today_high: float, today_low: float,
                             prev_open: float, prev_close: float, prev_high: float, prev_low: float) -> bool:
    """
    Bullish Engulfing を検出する。

    条件:
        - 当日足が陽線 (today_close > today_open)
        - 前日足が陰線 (prev_close < prev_open)
        - 当日実体が前日実体を完全に包む
          (today_open <= prev_close AND today_close >= prev_open)
    """
    today_bullish = today_close > today_open
    prev_bearish = prev_close < prev_open
    engulfs = today_open <= prev_close and today_close >= prev_open
    return today_bullish and prev_bearish and engulfs


def detect_bearish_engulfing(today_open: float, today_close: float, today_high: float, today_low: float,
                             prev_open: float, prev_close: float, prev_high: float, prev_low: float) -> bool:
    """
    Bearish Engulfing を検出する。

    条件:
        - 当日足が陰線 (today_close < today_open)
        - 前日足が陽線 (prev_close > prev_open)
        - 当日実体が前日実体を完全に包む
          (today_open >= prev_close AND today_close <= prev_open)
    """
    today_bearish = today_close < today_open
    prev_bullish = prev_close > prev_open
    engulfs = today_open >= prev_close and today_close <= prev_open
    return today_bearish and prev_bullish and engulfs


def detect_bullish_pin_bar(open_price: float, close_price: float, high: float, low: float) -> bool:
    """
    Bullish Pin Bar を検出する。

    条件:
        - close > open (陽線、実体がローソク上部)
        - 下ヒゲ >= 実体の 2.0 倍
        - 上ヒゲ <= 実体の 0.5 倍
        - body > 0 (ゼロ除算回避)
    """
    body = abs(close_price - open_price)
    if body <= 0:
        return False
    upper_wick = high - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low
    return (close_price > open_price
            and lower_wick >= 2.0 * body
            and upper_wick <= 0.5 * body)


def detect_bearish_pin_bar(open_price: float, close_price: float, high: float, low: float) -> bool:
    """
    Bearish Pin Bar を検出する。

    条件:
        - close < open (陰線、実体がローソク下部)
        - 上ヒゲ >= 実体の 2.0 倍
        - 下ヒゲ <= 実体の 0.5 倍
        - body > 0 (ゼロ除算回避)
    """
    body = abs(close_price - open_price)
    if body <= 0:
        return False
    upper_wick = high - max(open_price, close_price)
    lower_wick = min(open_price, close_price) - low
    return (close_price < open_price
            and upper_wick >= 2.0 * body
            and lower_wick <= 0.5 * body)


def detect_pattern(today: dict, prev: dict, alignment: str) -> tuple:
    """
    alignment に応じてパターンを検出する。

    Args:
        today: {"open", "close", "high", "low"} の辞書
        prev: {"open", "close", "high", "low"} の辞書
        alignment: "BUY_ONLY", "SELL_ONLY", "NO_TRADE"

    Returns:
        (pattern_name: str, pattern_detected: bool)
        pattern_name は "BULLISH_ENGULFING", "BEARISH_ENGULFING",
                       "BULLISH_PIN_BAR", "BEARISH_PIN_BAR", "NONE"
    """
    if alignment == "BUY_ONLY":
        if detect_bullish_engulfing(
            today["open"], today["close"], today["high"], today["low"],
            prev["open"], prev["close"], prev["high"], prev["low"],
        ):
            return "BULLISH_ENGULFING", True
        if detect_bullish_pin_bar(today["open"], today["close"], today["high"], today["low"]):
            return "BULLISH_PIN_BAR", True

    elif alignment == "SELL_ONLY":
        if detect_bearish_engulfing(
            today["open"], today["close"], today["high"], today["low"],
            prev["open"], prev["close"], prev["high"], prev["low"],
        ):
            return "BEARISH_ENGULFING", True
        if detect_bearish_pin_bar(today["open"], today["close"], today["high"], today["low"]):
            return "BEARISH_PIN_BAR", True

    return "NONE", False
