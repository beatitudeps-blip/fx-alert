import os
import json
import requests
import pandas as pd

TWELVEDATA_API_KEY = os.environ["TWELVEDATA_API_KEY"]
LINE_TOKEN = os.environ["LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["LINE_USER_ID"]

EMA_LEN = 20
PIP = 0.01
NEAR_EMA_PIPS = 15
NEAR = NEAR_EMA_PIPS * PIP


def fetch_h4():
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "USD/JPY",
        "interval": "4h",
        "outputsize": 200,
        "apikey": TWELVEDATA_API_KEY
    }

    r = requests.get(url, params=params, timeout=20)
    data = r.json()

    df = pd.DataFrame(data["values"])
    df = df.astype(float)
    df = df.sort_index(ascending=False)
    return df


def send_line(msg):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    body = {
        "to": LINE_USER_ID,
        "messages": [{"type": "text", "text": msg}]
    }
    requests.post(url, headers=headers, data=json.dumps(body))


def main():
    df = fetch_h4()
    df["ema20"] = df["close"].ewm(span=EMA_LEN).mean()

    last = df.iloc[0]
    prev = df.iloc[1]

    cond1 = last["close"] > last["ema20"]
    cond2 = last["ema20"] > prev["ema20"]
    cond3 = abs(last["close"] - last["ema20"]) <= NEAR

    if cond1 and cond2 and cond3:
        send_line("USDJPY H4 押し目監視アラート")
        print("NOTIFIED")
    else:
        print("NO SIGNAL")


if __name__ == "__main__":
    main()
