import os
import json
import requests
import pandas as pd

# ====== ENV ======
OANDA_API_KEY = os.environ["OANDA_API_KEY"]
OANDA_ENV = os.getenv("OANDA_ENV", "practice")  # practice/live

LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

INSTRUMENT = "USD_JPY"
COUNT = 200
EMA_LEN = 20

# JPY: 1 pip = 0.01
PIP = 0.01
NEAR_EMA_PIPS = 15  # ±15pips以内で近い
NEAR = NEAR_EMA_PIPS * PIP


def fetch_oanda_h4() -> pd.DataFrame:
    base = "https://api-fxpractice.oanda.com" if OANDA_ENV == "practice" else "https://api-fxtrade.oanda.com"
    url = f"{base}/v3/instruments/{INSTRUMENT}/candles"
    headers = {"Authorization": f"Bearer {OANDA_API_KEY}"}
    params = {"granularity": "H4", "count": COUNT, "price": "M"}

    r = requests.get(url, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    candles = r.json()["candles"]

    rows = []
    for c in candles:
        if not c.get("complete", False):
            continue
        m = c["mid"]
        rows.append({
            "time": c["time"],
            "open": float(m["o"]),
            "high": float(m["h"]),
            "low": float(m["l"]),
            "close": float(m["c"]),
        })

    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df


def send_line(msg: str) -> None:
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
    df = fetch_oanda_h4()
    df["ema20"] = df["close"].ewm(span=EMA_LEN, adjust=False).mean()

    last = df.iloc[-1]
    prev = df.iloc[-2]

    # A版（前段スクリーニング）
    cond1 = last["close"] > last["ema20"]
    cond2 = last["ema20"] > prev["ema20"]
    cond3 = abs(last["close"] - last["ema20"]) <= NEAR

    if cond1 and cond2 and cond3:
        msg = (
            f"[USDJPY H4] 監視アラート\n"
            f"close={last['close']:.3f} ema20={last['ema20']:.3f}\n"
            f"near_ema(±{NEAR_EMA_PIPS}p)={cond3}"
        )
        send_line(msg)
        print("NOTIFIED")
    else:
        print("NO SIGNAL")


if __name__ == "__main__":
    main()
