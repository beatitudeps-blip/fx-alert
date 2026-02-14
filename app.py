import os
import json
import requests
import pandas as pd

# ====== CONFIG ======
TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

SYMBOL = "USD/JPY"
EMA_PERIOD = 20
ATR_PERIOD = 14


def fetch_data(symbol: str, interval: str, outputsize: int) -> pd.DataFrame:
    """Twelve Data APIからOHLCデータ取得"""
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY,
    }
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()

    if "values" not in data:
        raise ValueError(f"API error: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return df


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """EMA計算"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR計算"""
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def is_bullish_engulfing(prev_row: pd.Series, curr_row: pd.Series) -> bool:
    """Bullish Engulfingパターン判定"""
    prev_bearish = prev_row["close"] < prev_row["open"]
    curr_bullish = curr_row["close"] > curr_row["open"]
    engulfing = (
        curr_row["close"] >= prev_row["open"] and
        curr_row["open"] <= prev_row["close"]
    )
    return prev_bearish and curr_bullish and engulfing


def is_bullish_hammer(row: pd.Series) -> bool:
    """Hammerパターン判定（長い下ヒゲ）"""
    body = abs(row["close"] - row["open"])
    if body <= 0:
        return False

    lower_wick = min(row["open"], row["close"]) - row["low"]
    upper_wick = row["high"] - max(row["open"], row["close"])

    return (
        row["close"] > row["open"] and
        lower_wick >= body * 1.5 and
        lower_wick >= upper_wick * 2.0
    )


def check_daily_environment(d1: pd.DataFrame) -> bool:
    """日足環境チェック（EMA20上昇トレンド）"""
    d1["ema20"] = calculate_ema(d1["close"], EMA_PERIOD)
    latest = d1.iloc[-1]
    prev = d1.iloc[-2]

    # close > EMA20 かつ EMA20上向き
    return latest["close"] > latest["ema20"] and latest["ema20"] > prev["ema20"]


def check_signal(h4: pd.DataFrame, d1: pd.DataFrame) -> dict:
    """V2ロジックでシグナル判定"""
    # 日足環境チェック
    env_ok = check_daily_environment(d1)
    if not env_ok:
        return {"signal": False, "reason": "日足環境NG"}

    # 4H足の計算
    h4["ema20"] = calculate_ema(h4["close"], EMA_PERIOD)
    h4["atr14"] = calculate_atr(h4, ATR_PERIOD)

    # 最新2本の足
    latest = h4.iloc[-1]
    prev = h4.iloc[-2]

    # EMAタッチチェック
    touch_ema = latest["low"] <= latest["ema20"] <= latest["high"]
    if not touch_ema:
        return {"signal": False, "reason": "EMAタッチなし"}

    # トリガーチェック（Engulfing or Hammer）
    is_engulfing = is_bullish_engulfing(prev, latest)
    is_hammer = is_bullish_hammer(latest)

    if not (is_engulfing or is_hammer):
        return {"signal": False, "reason": "トリガーパターンなし"}

    # シグナル成立
    pattern = "Engulfing" if is_engulfing else "Hammer"
    atr = latest["atr14"]

    return {
        "signal": True,
        "pattern": pattern,
        "close": latest["close"],
        "ema20": latest["ema20"],
        "atr": atr,
        "datetime": latest["datetime"]
    }


def send_line(msg: str):
    """LINE通知送信"""
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}",
    }
    body = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}],
    }
    r = requests.post(url, headers=headers, data=json.dumps(body), timeout=20)
    r.raise_for_status()


def main():
    print(f"[{SYMBOL}] シグナルチェック開始...")

    # データ取得
    h4 = fetch_data(SYMBOL, "4h", 200)
    d1 = fetch_data(SYMBOL, "1day", 100)

    print(f"4H足: {len(h4)}本, 日足: {len(d1)}本取得")

    # シグナル判定
    result = check_signal(h4, d1)

    if result["signal"]:
        # シグナル成立 - LINE通知
        msg = (
            f"🚨 {SYMBOL} V2シグナル検出\n"
            f"パターン: {result['pattern']}\n"
            f"価格: {result['close']:.3f}\n"
            f"EMA20: {result['ema20']:.3f}\n"
            f"ATR: {result['atr']:.3f}\n"
            f"時刻: {result['datetime']}"
        )
        send_line(msg)
        print("✅ シグナル成立 - 通知送信")
        print(msg)
    else:
        print(f"❌ シグナルなし - {result['reason']}")


if __name__ == "__main__":
    main()
