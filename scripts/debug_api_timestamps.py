"""
Twelve Data APIのタイムスタンプを確認
実際の4H足の区切りを確認する
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

api_key = os.environ.get("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")

print("=" * 80)
print("Twelve Data API タイムスタンプ確認")
print("=" * 80)

# USD/JPYの4H足データを取得
url = "https://api.twelvedata.com/time_series"
params = {
    "symbol": "USD/JPY",
    "interval": "4h",
    "outputsize": 20,  # 最新20本
    "apikey": api_key,
}

print(f"\nAPI URL: {url}")
print(f"パラメータ: {params}")
print()

r = requests.get(url, params=params, timeout=25)
r.raise_for_status()
data = r.json()

if "values" not in data:
    print(f"❌ API エラー: {data}")
    sys.exit(1)

df = pd.DataFrame(data["values"])
df["datetime"] = pd.to_datetime(df["datetime"])

print("=" * 80)
print("最新20本の4H足タイムスタンプ（新しい順）")
print("=" * 80)

for i, row in df.iterrows():
    dt_utc = row["datetime"]

    # タイムゾーン情報を追加
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.tz_localize("UTC")

    dt_jst = dt_utc.astimezone(ZoneInfo("Asia/Tokyo"))

    marker = "← 最新（形成中）" if i == 0 else "← 確定足" if i == 1 else ""

    print(f"{i:2d}. UTC: {dt_utc.strftime('%Y-%m-%d %H:%M')} | JST: {dt_jst.strftime('%Y-%m-%d %H:%M')} {marker}")

print()
print("=" * 80)
print("分析結果")
print("=" * 80)

# 確定足（2本目）を確認
latest_bar = df.iloc[0]["datetime"]
confirmed_bar = df.iloc[1]["datetime"]

if latest_bar.tzinfo is None:
    latest_bar = latest_bar.tz_localize("UTC")
if confirmed_bar.tzinfo is None:
    confirmed_bar = confirmed_bar.tz_localize("UTC")

confirmed_bar_jst = confirmed_bar.astimezone(ZoneInfo("Asia/Tokyo"))

print(f"\n確定4H足（1つ前のバー）:")
print(f"  UTC: {confirmed_bar.strftime('%Y-%m-%d %H:%M')}")
print(f"  JST: {confirmed_bar_jst.strftime('%Y-%m-%d %H:%M')}")

# 時刻のパターンを判定
hour_jst = confirmed_bar_jst.hour
hour_utc = confirmed_bar.hour

print(f"\n確定足の時刻:")
print(f"  UTC時: {hour_utc:02d}:00")
print(f"  JST時: {hour_jst:02d}:00")

print()
print("=" * 80)
print("cron設定推奨")
print("=" * 80)

# UTC時刻から4H区切りのパターンを判定
utc_hours = []
for i in range(min(10, len(df))):
    dt = df.iloc[i]["datetime"]
    if dt.tzinfo is None:
        dt = dt.tz_localize("UTC")
    utc_hours.append(dt.hour)

# ユニークなUTC時刻を取得
unique_utc_hours = sorted(set(utc_hours))
print(f"\nUTC 4H足の区切り時刻: {unique_utc_hours}")

# JSTに変換
jst_hours = []
for utc_h in unique_utc_hours:
    jst_h = (utc_h + 9) % 24  # UTC + 9 = JST
    jst_hours.append(jst_h)

jst_hours = sorted(jst_hours)
print(f"JST 4H足の区切り時刻: {jst_hours}")

print()
if jst_hours == [1, 5, 9, 13, 17, 21]:
    print("✅ パターン1: JST 01:00, 05:00, 09:00, 13:00, 17:00, 21:00")
    print("   → cron設定: 5 1,5,9,13,17,21 * * *")
elif jst_hours == [3, 7, 11, 15, 19, 23]:
    print("✅ パターン2: JST 03:00, 07:00, 11:00, 15:00, 19:00, 23:00")
    print("   → cron設定: 5 3,7,11,15,19,23 * * *")
elif jst_hours == [0, 4, 8, 12, 16, 20]:
    print("✅ パターン3: JST 00:00, 04:00, 08:00, 12:00, 16:00, 20:00")
    print("   → cron設定: 5 0,4,8,12,16,20 * * *")
elif jst_hours == [2, 6, 10, 14, 18, 22]:
    print("✅ パターン4: JST 02:00, 06:00, 10:00, 14:00, 18:00, 22:00")
    print("   → cron設定: 5 2,6,10,14,18,22 * * *")
else:
    print(f"⚠️ カスタムパターン: JST {jst_hours}")
    cron_hours = ','.join(str(h) for h in jst_hours)
    print(f"   → cron設定: 5 {cron_hours} * * *")

print()
print("=" * 80)
