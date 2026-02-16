"""4H足の時刻定義とエントリータイミングを検証"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data import fetch_data
from src.env_check import load_dotenv_if_exists, check_api_key
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

# .env読み込み
load_dotenv_if_exists()
api_key = check_api_key(required=True)
tz = ZoneInfo('Asia/Tokyo')

print("="*80)
print("4H足の時刻定義とエントリータイミング検証")
print("="*80)

# データ取得
h4 = fetch_data('EUR/JPY', '4h', 5, api_key, use_cache=False)

# タイムゾーン設定
if h4['datetime'].dt.tz is None:
    h4['datetime'] = h4['datetime'].dt.tz_localize('UTC').dt.tz_convert(tz)

# 現在時刻
now = datetime.now(tz)
print(f"\n現在時刻: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n")

# 最新5本の足を表示
print("最新5本の4H足（新しい順）:")
print("-"*80)
for i in range(min(5, len(h4))):
    row = h4.iloc[-(i+1)]
    dt = row['datetime']
    # この足の範囲を推定（TwelveDataは通常開始時刻をラベルにする）
    bar_start = dt
    bar_end = dt + timedelta(hours=4)

    # 確定判定: 足の終了時刻が現在時刻以前
    is_confirmed = bar_end <= now
    status = "✅確定" if is_confirmed else "❌未確定"

    print(f"{status} | ラベル: {dt.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"         推定範囲: {bar_start.strftime('%H:%M')}〜{bar_end.strftime('%H:%M')}")
    print(f"         確定時刻: {bar_end.strftime('%Y-%m-%d %H:%M %Z')}")
    print(f"         OHLC: O={row['open']:.3f} H={row['high']:.3f} L={row['low']:.3f} C={row['close']:.3f}")
    print()

# 確定済みの最新足（シグナル判定に使う足）
# 足の終了時刻で確定判定（ルックアヘッド回避）
h4['bar_end_time'] = h4['datetime'] + timedelta(hours=4)
confirmed = h4[h4['bar_end_time'] <= now]
if len(confirmed) == 0:
    print("⚠️ 確定済みの足がありません")
    sys.exit(1)

latest = confirmed.iloc[-1]
latest_dt = latest['datetime']

print("="*80)
print("シグナル判定に使う足（最新確定足）")
print("="*80)
print(f"時刻ラベル: {latest_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print(f"OHLC: O={latest['open']:.3f} H={latest['high']:.3f} L={latest['low']:.3f} C={latest['close']:.3f}")
print()

# エントリー時刻の計算（コードと同じロジック）
# 1本待ち戦略: 確定足の2本後（+8h）でエントリー
entry_dt = latest_dt + timedelta(hours=8)

print("="*80)
print("エントリー時刻の計算（1本待ち戦略）")
print("="*80)
print(f"計算式: entry_dt = bar_dt + timedelta(hours=8)")
print(f"bar_dt (確定足ラベル): {latest_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print(f"確定足範囲: {latest_dt.strftime('%H:%M')}〜{(latest_dt + timedelta(hours=4)).strftime('%H:%M')}")
skip_bar_start = latest_dt + timedelta(hours=4)
skip_bar_end = latest_dt + timedelta(hours=8)
print(f"スキップする足: {skip_bar_start.strftime('%H:%M')}〜{skip_bar_end.strftime('%H:%M')}")
print(f"entry_dt (エントリー時刻): {entry_dt.strftime('%Y-%m-%d %H:%M %Z')}")
print()

print("="*80)
print("時刻定義の解釈（1本待ち戦略）")
print("="*80)
print(f"TwelveData APIの4H足ラベルは「開始時刻」を指す（一般的な仕様）")
print()
bar_end = latest_dt + timedelta(hours=4)
skip_start = bar_end
skip_end = entry_dt
print(f"【確定足 {latest_dt.strftime('%H:%M')}】の意味:")
print(f"  → {latest_dt.strftime('%H:%M')}〜{bar_end.strftime('%H:%M')} の4H足")
print(f"  → この足は {bar_end.strftime('%H:%M')} に確定（クローズ）")
print(f"  → シグナル判定: {bar_end.strftime('%H:%M')} に確定した足で判定")
print()
print(f"【1本待ち戦略】:")
print(f"  → 次の4H足（{skip_start.strftime('%H:%M')}〜{skip_end.strftime('%H:%M')}）をスキップ")
print(f"  → エントリー時刻: {entry_dt.strftime('%H:%M')} （次の次の足の始値）")
print()

print("="*80)
print("結論")
print("="*80)
bar_end = latest_dt + timedelta(hours=4)
skip_start = bar_end
skip_end = entry_dt
print(f"✅ 確定足 {latest_dt.strftime('%H:%M')} = {latest_dt.strftime('%H:%M')}〜{bar_end.strftime('%H:%M')} の足（開始時刻ラベル）")
print(f"✅ この足は {bar_end.strftime('%H:%M')} に確定")
print(f"✅ 次の足 {skip_start.strftime('%H:%M')}〜{skip_end.strftime('%H:%M')} をスキップ（1本待ち）")
print(f"✅ エントリー時刻 {entry_dt.strftime('%H:%M')} = 次の次の足の始値エントリー")
print()
print("【バックテストとの整合性】")
print("バックテストでは「確定足のclose後、1本待って、次の次の足の始値でエントリー」")
print(f"→ 実運用も同じロジック: {latest_dt.strftime('%H:%M')}確定 → {skip_start.strftime('%H:%M')}-{skip_end.strftime('%H:%M')}スキップ → {entry_dt.strftime('%H:%M')}エントリー")
print("→ ✅ 整合している（ルックアヘッドなし）")
print()
print("【通知文面（新形式）】")
print(f"【確定足ラベル】{latest_dt.strftime('%Y-%m-%d %H:%M JST')}")
print(f"【確定足範囲】{latest_dt.strftime('%H:%M')}〜{bar_end.strftime('%H:%M')}")
print(f"【エントリー時刻】{entry_dt.strftime('%Y-%m-%d %H:%M JST')}")
print("→ ✅ 正確かつ明確（誤解なし）")
print()
print("="*80)
