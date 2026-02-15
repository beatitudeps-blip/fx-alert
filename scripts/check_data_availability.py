"""
Twelve Data APIで取得可能なデータ範囲を確認
"""
import os
import sys
from pathlib import Path
import requests
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

api_key = os.environ.get("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")

print("=" * 80)
print("Twelve Data API データ範囲確認")
print("=" * 80)

symbols = ["USD/JPY", "EUR/JPY", "GBP/JPY"]

for symbol in symbols:
    print(f"\n[{symbol}]")

    # 4H足（最大5000本取得）
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "4h",
        "outputsize": 5000,  # 最大
        "apikey": api_key,
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        if "values" not in data:
            print(f"  ❌ エラー: {data}")
            continue

        df = pd.DataFrame(data["values"])
        df["datetime"] = pd.to_datetime(df["datetime"])

        # タイムゾーン情報追加
        if df["datetime"].dt.tz is None:
            df["datetime"] = df["datetime"].dt.tz_localize("UTC")

        df = df.sort_values("datetime")

        oldest = df["datetime"].iloc[0]
        newest = df["datetime"].iloc[-1]
        count = len(df)

        oldest_jst = oldest.astimezone(ZoneInfo("Asia/Tokyo"))
        newest_jst = newest.astimezone(ZoneInfo("Asia/Tokyo"))

        print(f"  データ数: {count}本")
        print(f"  最古: {oldest_jst.strftime('%Y-%m-%d %H:%M JST')} (UTC: {oldest.strftime('%Y-%m-%d %H:%M')})")
        print(f"  最新: {newest_jst.strftime('%Y-%m-%d %H:%M JST')} (UTC: {newest.strftime('%Y-%m-%d %H:%M')})")

        # 期間計算
        days = (newest - oldest).days
        print(f"  期間: 約{days}日 ({days/30:.1f}ヶ月, {days/365:.1f}年)")

    except Exception as e:
        print(f"  ❌ エラー: {e}")

print("\n" + "=" * 80)
print("推奨バックテスト期間")
print("=" * 80)

# 現在から過去に遡って推奨期間を提案
now = datetime.now(ZoneInfo("Asia/Tokyo"))
print(f"\n現在: {now.strftime('%Y-%m-%d')}")
print(f"\n【推奨期間】")
print(f"  全期間（~2年）: 2024-01-01 ~ 2026-02-14")
print(f"  IS期間（70%）: 2024-01-01 ~ 2025-06-30")
print(f"  OOS期間（30%）: 2025-07-01 ~ 2026-02-14")
print(f"\n【ウォークフォワード（3ヶ月IS/1ヶ月OOS）】")
print(f"  2024-01-01 ~ 2024-03-31 (IS) → 2024-04-01 ~ 2024-04-30 (OOS)")
print(f"  2024-02-01 ~ 2024-04-30 (IS) → 2024-05-01 ~ 2024-05-31 (OOS)")
print(f"  2024-03-01 ~ 2024-05-31 (IS) → 2024-06-01 ~ 2024-06-30 (OOS)")
print(f"  ...")
print(f"  2025-11-01 ~ 2026-01-31 (IS) → 2026-02-01 ~ 2026-02-14 (OOS)")

print("\n" + "=" * 80)
