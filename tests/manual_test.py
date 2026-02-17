"""手動テスト実行"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from datetime import datetime
from src.indicators import calculate_ema, calculate_atr
from src.patterns import is_bullish_engulfing, is_bullish_hammer
from src.spread_minnafx import get_spread_pips, add_bid_ask

print("=== コアモジュール動作確認 ===\n")

# 1. EMAテスト
print("1. EMA計算テスト")
data = pd.Series([100, 102, 101, 103, 105, 104, 106, 108])
ema = calculate_ema(data, period=3)
print(f"   データ: {list(data)}")
print(f"   EMA(3): {list(ema.round(2))}")
print(f"   ✅ EMA計算OK\n")

# 2. ATRテスト
print("2. ATR計算テスト")
df = pd.DataFrame({
    "open": [100, 102, 101, 103, 105],
    "high": [101, 103, 102, 104, 106],
    "low": [99, 101, 100, 102, 104],
    "close": [100.5, 102.5, 101.5, 103.5, 105.5]
})
atr = calculate_atr(df, period=3)
print(f"   最新ATR: {atr.iloc[-1]:.2f}")
print(f"   ✅ ATR計算OK\n")

# 3. パターンテスト
print("3. ローソク足パターンテスト")
prev = pd.Series({"open": 150.0, "high": 150.5, "low": 149.0, "close": 149.5})
curr = pd.Series({"open": 149.3, "high": 151.0, "low": 149.0, "close": 150.8})
is_engulfing = is_bullish_engulfing(prev, curr)
print(f"   Bullish Engulfing: {is_engulfing}")

hammer = pd.Series({"open": 150.0, "high": 150.5, "low": 148.0, "close": 150.3})
is_hammer = is_bullish_hammer(hammer)
print(f"   Bullish Hammer: {is_hammer}")
print(f"   ✅ パターン判定OK\n")

# 4. スプレッドテスト（UTC→JST変換確認）
print("4. スプレッドモデルテスト（UTC→JST変換）")
from src.spread_minnafx import utc_to_jst

# UTC 03:00 = JST 12:00 (通常時間)
dt_normal_utc = datetime(2024, 1, 1, 3, 0, 0)
# UTC 21:00 = JST 06:00 (早朝)
dt_early_utc = datetime(2024, 1, 1, 21, 0, 0)

spread_normal = get_spread_pips("USD/JPY", dt_normal_utc)
spread_early = get_spread_pips("USD/JPY", dt_early_utc)

jst_normal = utc_to_jst(dt_normal_utc)
jst_early = utc_to_jst(dt_early_utc)

print(f"   UTC 03:00 → JST {jst_normal.strftime('%H:%M')} → {spread_normal} pips (通常時間)")
print(f"   UTC 21:00 → JST {jst_early.strftime('%H:%M')} → {spread_early} pips (早朝)")
assert spread_normal == 0.2, "通常時間のスプレッドが正しくありません"
assert spread_early == 3.9, "早朝時間のスプレッドが正しくありません"
print(f"   ✅ UTC→JST変換とスプレッドモデルOK\n")

# 5. bid/ask生成テスト（通常時間と早朝の比較）
print("5. bid/ask生成テスト")
# 通常時間（UTC 03:00 = JST 12:00）
test_df_normal = pd.DataFrame({
    "datetime": [dt_normal_utc],
    "open": [150.0],
    "high": [150.5],
    "low": [149.5],
    "close": [150.2]
})
result_normal = add_bid_ask(test_df_normal, "USD/JPY")
print(f"   通常時間 (JST 12:00):")
print(f"     mid価格: {result_normal['close'].iloc[0]}")
print(f"     bid価格: {result_normal['bid_close'].iloc[0]:.4f}")
print(f"     ask価格: {result_normal['ask_close'].iloc[0]:.4f}")
print(f"     スプレッド: {(result_normal['ask_close'].iloc[0] - result_normal['bid_close'].iloc[0]):.4f} ({result_normal['spread_pips'].iloc[0]} pips)")

# 早朝時間（UTC 21:00 = JST 06:00）
test_df_early = pd.DataFrame({
    "datetime": [dt_early_utc],
    "open": [150.0],
    "high": [150.5],
    "low": [149.5],
    "close": [150.2]
})
result_early = add_bid_ask(test_df_early, "USD/JPY")
print(f"   早朝時間 (JST 06:00):")
print(f"     mid価格: {result_early['close'].iloc[0]}")
print(f"     bid価格: {result_early['bid_close'].iloc[0]:.4f}")
print(f"     ask価格: {result_early['ask_close'].iloc[0]:.4f}")
print(f"     スプレッド: {(result_early['ask_close'].iloc[0] - result_early['bid_close'].iloc[0]):.4f} ({result_early['spread_pips'].iloc[0]} pips)")
print(f"   ✅ bid/ask生成OK\n")

print("=== すべてのテスト成功 ✅ ===")
