import os
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

# ====== CONFIG ======
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")
INITIAL_CAPITAL = 436000  # 円
RISK_PER_TRADE = 0.01  # 1.0%
EMA_PERIOD = 20
PIP = 0.01  # JPY: 1 pip = 0.01
SL_PIPS = 25  # -25 pips
LOOKBACK_CANDLES = 10  # Higher Highs/Lows確認期間


def fetch_historical_data(days=180):
    """過去180日分の4H足データを取得"""
    url = "https://api.twelvedata.com/time_series"
    # 4H足で180日分 = 180*24/4 = 1080本（max 5000まで可能）
    outputsize = min(1080, 5000)

    params = {
        "symbol": "USD/JPY",
        "interval": "4h",
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY
    }

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "values" not in data:
        raise ValueError(f"APIエラー: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)

    # 古い順にソート（バックテスト用）
    df = df.sort_values("datetime").reset_index(drop=True)
    return df


def calculate_ema(series, period):
    """EMAを計算"""
    return series.ewm(span=period, adjust=False).mean()


def is_higher_highs_lows(df, idx, lookback):
    """Higher Highs and Higher Lowsを確認"""
    if idx < lookback:
        return False

    highs = df.loc[idx-lookback:idx, "high"].values
    lows = df.loc[idx-lookback:idx, "low"].values

    # 簡易判定: 最高値と最安値が右肩上がり傾向
    high_trend = np.polyfit(range(len(highs)), highs, 1)[0] > 0
    low_trend = np.polyfit(range(len(lows)), lows, 1)[0] > 0

    return high_trend and low_trend


def is_bullish_engulfing(df, idx):
    """Bullish Engulfingパターン"""
    if idx < 1:
        return False

    prev = df.iloc[idx-1]
    curr = df.iloc[idx]

    # 前の足が陰線、現在の足が陽線で前の足を包む
    prev_bearish = prev["close"] < prev["open"]
    curr_bullish = curr["close"] > curr["open"]
    engulfing = curr["open"] <= prev["close"] and curr["close"] >= prev["open"]

    return prev_bearish and curr_bullish and engulfing


def is_hammer(df, idx):
    """Hammerパターン（長い下ヒゲ）"""
    candle = df.iloc[idx]

    body = abs(candle["close"] - candle["open"])
    lower_wick = min(candle["open"], candle["close"]) - candle["low"]
    upper_wick = candle["high"] - max(candle["open"], candle["close"])

    # 下ヒゲが実体の2倍以上、上ヒゲが小さい
    return lower_wick >= 2 * body and upper_wick < body


def find_recent_swing_low(df, idx, lookback=10):
    """直近のスイングローを見つける"""
    if idx < lookback:
        return df.loc[:idx, "low"].min()
    return df.loc[idx-lookback:idx, "low"].min()


def backtest_strategy(df):
    """バックテスト実行"""
    # EMA計算
    df["ema20"] = calculate_ema(df["close"], EMA_PERIOD)

    trades = []
    equity = INITIAL_CAPITAL
    equity_curve = [INITIAL_CAPITAL]

    i = EMA_PERIOD + LOOKBACK_CANDLES  # 十分なデータが揃ってから開始

    while i < len(df):
        row = df.iloc[i]

        # === エントリー条件チェック ===
        # 1. Higher Highs and Higher Lows
        if not is_higher_highs_lows(df, i, LOOKBACK_CANDLES):
            i += 1
            continue

        # 2. Price > 20EMA
        if row["close"] <= row["ema20"]:
            i += 1
            continue

        # 3. Retracement: 価格がEMAに近い（±15pips以内）
        if abs(row["close"] - row["ema20"]) > 15 * PIP:
            i += 1
            continue

        # 4. Trigger: Bullish Engulfing or Hammer
        if not (is_bullish_engulfing(df, i) or is_hammer(df, i)):
            i += 1
            continue

        # === エントリー ===
        entry_price = df.iloc[i+1]["open"] if i+1 < len(df) else row["close"]
        entry_idx = i + 1

        # SL設定: 直近スイングローまたは-25pips
        swing_low = find_recent_swing_low(df, i, LOOKBACK_CANDLES)
        sl_swing = swing_low
        sl_fixed = entry_price - SL_PIPS * PIP
        stop_loss = max(sl_swing, sl_fixed)  # より浅い方を採用

        risk_pips = (entry_price - stop_loss) / PIP
        risk_amount = equity * RISK_PER_TRADE

        # TP1: RR 1:1
        tp1_price = entry_price + risk_pips * PIP

        # TP2: 前回高値（簡易実装: entry前の高値）
        tp2_price = df.loc[i-LOOKBACK_CANDLES:i, "high"].max()

        # ポジションサイズ計算（1lotあたりのpips価値を1000円と仮定）
        position_size = risk_amount / (risk_pips * PIP * 1000)

        # === トレード実行 ===
        exit_idx = None
        exit_price = None
        exit_reason = ""

        # エントリー後の足をスキャン
        for j in range(entry_idx, min(entry_idx + 50, len(df))):  # 最大50本先まで
            candle = df.iloc[j]

            # SL判定
            if candle["low"] <= stop_loss:
                exit_idx = j
                exit_price = stop_loss
                exit_reason = "SL"
                break

            # TP1判定（50%決済、SLをBEへ）
            if candle["high"] >= tp1_price:
                # 簡易実装: TP1で全決済
                exit_idx = j
                exit_price = tp1_price
                exit_reason = "TP1"
                break

            # TP2判定
            if candle["high"] >= tp2_price:
                exit_idx = j
                exit_price = tp2_price
                exit_reason = "TP2"
                break

        # タイムアウト（50本以内に決済されなかった場合）
        if exit_idx is None:
            exit_idx = min(entry_idx + 50, len(df) - 1)
            exit_price = df.iloc[exit_idx]["close"]
            exit_reason = "Timeout"

        # 損益計算
        pnl_pips = (exit_price - entry_price) / PIP
        pnl_amount = pnl_pips * PIP * 1000 * position_size
        equity += pnl_amount

        trades.append({
            "entry_date": df.iloc[entry_idx]["datetime"],
            "entry_price": entry_price,
            "exit_date": df.iloc[exit_idx]["datetime"],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl_pips": pnl_pips,
            "pnl_amount": pnl_amount,
            "equity": equity
        })

        equity_curve.append(equity)

        # 次のエントリーチャンスを探す（エグジット後から）
        i = exit_idx + 1

    return pd.DataFrame(trades), equity_curve


def analyze_results(trades_df, equity_curve):
    """バックテスト結果を分析"""
    if len(trades_df) == 0:
        print("トレードが発生しませんでした。")
        return

    total_trades = len(trades_df)
    winning_trades = len(trades_df[trades_df["pnl_pips"] > 0])
    losing_trades = len(trades_df[trades_df["pnl_pips"] < 0])

    win_rate = winning_trades / total_trades * 100

    total_profit = trades_df[trades_df["pnl_amount"] > 0]["pnl_amount"].sum()
    total_loss = abs(trades_df[trades_df["pnl_amount"] < 0]["pnl_amount"].sum())

    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

    avg_win = trades_df[trades_df["pnl_pips"] > 0]["pnl_pips"].mean()
    avg_loss = trades_df[trades_df["pnl_pips"] < 0]["pnl_pips"].mean()

    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

    final_equity = equity_curve[-1]
    total_return = (final_equity - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # ドローダウン計算
    equity_array = np.array(equity_curve)
    running_max = np.maximum.accumulate(equity_array)
    drawdown = (equity_array - running_max) / running_max * 100
    max_drawdown = drawdown.min()

    print("=" * 60)
    print("バックテスト結果レポート")
    print("=" * 60)
    print(f"初期資金: ¥{INITIAL_CAPITAL:,.0f}")
    print(f"最終資金: ¥{final_equity:,.0f}")
    print(f"総リターン: {total_return:.2f}%")
    print(f"最大ドローダウン: {max_drawdown:.2f}%")
    print("-" * 60)
    print(f"総トレード数: {total_trades}")
    print(f"勝ちトレード: {winning_trades}")
    print(f"負けトレード: {losing_trades}")
    print(f"勝率: {win_rate:.2f}%")
    print("-" * 60)
    print(f"平均利益: {avg_win:.2f} pips")
    print(f"平均損失: {avg_loss:.2f} pips")
    print(f"期待値: {expectancy:.2f} pips")
    print(f"プロフィットファクター: {profit_factor:.2f}")
    print("=" * 60)

    # 資産曲線グラフ
    plt.figure(figsize=(12, 6))
    plt.plot(equity_curve, linewidth=2)
    plt.title("Equity Curve", fontsize=16)
    plt.xlabel("Trade Number", fontsize=12)
    plt.ylabel("Equity (JPY)", fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("/Users/mitsuru/fx-alert/equity_curve.png", dpi=150)
    print("\n資産曲線グラフを保存しました: equity_curve.png")

    # トレード詳細をCSV出力
    trades_df.to_csv("/Users/mitsuru/fx-alert/trades.csv", index=False)
    print("トレード詳細を保存しました: trades.csv")


def main():
    print("データ取得中...")
    df = fetch_historical_data(days=180)
    print(f"データ取得完了: {len(df)}本のローソク足")

    print("\nバックテスト実行中...")
    trades_df, equity_curve = backtest_strategy(df)

    print("\n結果分析中...")
    analyze_results(trades_df, equity_curve)


if __name__ == "__main__":
    main()
