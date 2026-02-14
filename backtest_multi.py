import os
import time
import requests
import pandas as pd
import numpy as np
from datetime import datetime

# ====== CONFIG ======
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")
CURRENCIES = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
DAYS = 720
INTERVAL = "4h"
EMA_PERIOD = 20
NEAR_EMA_PIPS = 15
PIP = 0.01
SL_PIPS = 30
TP_PIPS = 60
MIN_TRADES_THRESHOLD = 30


def fetch_data(symbol, days=720):
    """指定通貨の4H足データを取得"""
    # 4H足で720日分 = 720*24/4 = 4320本
    outputsize = min(4320, 5000)

    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": outputsize,
        "apikey": TWELVEDATA_API_KEY
    }

    print(f"  {symbol} データ取得中... ", end="", flush=True)
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    if "values" not in data:
        raise ValueError(f"APIエラー ({symbol}): {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df = df.sort_values("datetime").reset_index(drop=True)

    print(f"{len(df)}本取得完了")
    return df


def calculate_signals(df):
    """シグナルを計算（A版ロジック）"""
    df["ema20"] = df["close"].ewm(span=EMA_PERIOD, adjust=False).mean()
    df["ema20_prev"] = df["ema20"].shift(1)

    # エントリー条件
    cond1 = df["close"] > df["ema20"]
    cond2 = df["ema20"] > df["ema20_prev"]
    cond3 = (df["close"] - df["ema20"]).abs() <= (NEAR_EMA_PIPS * PIP)

    df["signal"] = cond1 & cond2 & cond3
    return df


def backtest_single(df, currency):
    """単一通貨のバックテスト実行"""
    trades = []

    for i in range(len(df) - 1):
        if not df.loc[i, "signal"]:
            continue

        # エントリー: 次足のopen
        entry_idx = i + 1
        entry_price = df.loc[entry_idx, "open"]
        entry_date = df.loc[entry_idx, "datetime"]

        sl_price = entry_price - (SL_PIPS * PIP)
        tp_price = entry_price + (TP_PIPS * PIP)

        # 決済判定
        exit_idx = None
        exit_price = None
        exit_reason = None

        # エントリー後の足をスキャン（最大100本）
        for j in range(entry_idx, min(entry_idx + 100, len(df))):
            candle = df.loc[j]

            # 同一足で両方ヒット: SL優先（保守的）
            if candle["low"] <= sl_price:
                exit_idx = j
                exit_price = sl_price
                exit_reason = "SL"
                break
            elif candle["high"] >= tp_price:
                exit_idx = j
                exit_price = tp_price
                exit_reason = "TP"
                break

        # タイムアウト
        if exit_idx is None:
            exit_idx = min(entry_idx + 100, len(df) - 1)
            exit_price = df.loc[exit_idx, "close"]
            exit_reason = "Timeout"

        pnl_pips = (exit_price - entry_price) / PIP

        trades.append({
            "currency": currency,
            "entry_date": entry_date,
            "entry_price": entry_price,
            "exit_date": df.loc[exit_idx, "datetime"],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "pnl_pips": pnl_pips
        })

    return pd.DataFrame(trades)


def calculate_stats(trades_df, currency=""):
    """統計計算"""
    if len(trades_df) == 0:
        return {
            "currency": currency,
            "total_trades": 0,
            "win_rate": 0,
            "total_pips": 0,
            "avg_pips": 0,
            "pf": 0,
            "max_dd_pips": 0,
            "warning": "トレード0回"
        }

    total = len(trades_df)
    wins = len(trades_df[trades_df["pnl_pips"] > 0])
    losses = len(trades_df[trades_df["pnl_pips"] < 0])

    win_rate = (wins / total * 100) if total > 0 else 0
    total_pips = trades_df["pnl_pips"].sum()
    avg_pips = trades_df["pnl_pips"].mean()

    # PF計算
    gross_profit = trades_df[trades_df["pnl_pips"] > 0]["pnl_pips"].sum()
    gross_loss = abs(trades_df[trades_df["pnl_pips"] < 0]["pnl_pips"].sum())
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    # DD計算（pipsベース）
    cumulative = trades_df["pnl_pips"].cumsum()
    running_max = cumulative.expanding().max()
    drawdown = cumulative - running_max
    max_dd = drawdown.min()

    warning = ""
    if total < MIN_TRADES_THRESHOLD:
        warning = f"⚠️ サンプル不足 (n={total}, 推奨≥{MIN_TRADES_THRESHOLD})"

    return {
        "currency": currency,
        "total_trades": total,
        "win_rate": win_rate,
        "total_pips": total_pips,
        "avg_pips": avg_pips,
        "pf": pf,
        "max_dd_pips": max_dd,
        "warning": warning
    }


def print_stats_table(stats_list):
    """統計テーブルを表示"""
    print("\n" + "=" * 100)
    print("バックテスト結果サマリー（720日間 / 4H足）")
    print("=" * 100)

    header = f"{'通貨':<12} {'トレード数':>10} {'勝率':>10} {'総pips':>12} {'平均pips':>12} {'PF':>8} {'最大DD':>12} {'警告'}"
    print(header)
    print("-" * 100)

    for s in stats_list:
        currency = s["currency"] if s["currency"] else "合算"
        line = (
            f"{currency:<12} "
            f"{s['total_trades']:>10} "
            f"{s['win_rate']:>9.2f}% "
            f"{s['total_pips']:>12.2f} "
            f"{s['avg_pips']:>12.2f} "
            f"{s['pf']:>8.2f} "
            f"{s['max_dd_pips']:>12.2f} "
            f"{s['warning']}"
        )
        print(line)

    print("=" * 100)


def main():
    print(f"\n{'='*60}")
    print(f"複数通貨バックテスト開始")
    print(f"対象通貨: {', '.join(CURRENCIES)}")
    print(f"期間: {DAYS}日 ({INTERVAL}足)")
    print(f"ロジック: A版（close>EMA20, EMA上向き, ±{NEAR_EMA_PIPS}pips）")
    print(f"SL/TP: -{SL_PIPS}pips / +{TP_PIPS}pips")
    print(f"{'='*60}\n")

    all_trades = []
    stats_list = []

    # 通貨ごとにバックテスト
    for currency in CURRENCIES:
        print(f"[{currency}]")

        # データ取得
        df = fetch_data(currency, DAYS)

        # シグナル計算
        df = calculate_signals(df)

        # バックテスト実行
        trades_df = backtest_single(df, currency)
        print(f"  トレード数: {len(trades_df)}")

        if len(trades_df) > 0:
            all_trades.append(trades_df)
            stats = calculate_stats(trades_df, currency)
            stats_list.append(stats)
        else:
            stats_list.append({
                "currency": currency,
                "total_trades": 0,
                "win_rate": 0,
                "total_pips": 0,
                "avg_pips": 0,
                "pf": 0,
                "max_dd_pips": 0,
                "warning": "トレード0回"
            })

        print()
        time.sleep(0.5)  # API制限配慮

    # 全通貨統合
    if all_trades:
        combined_df = pd.concat(all_trades, ignore_index=True)
        combined_stats = calculate_stats(combined_df, "")
        stats_list.append(combined_stats)

        # CSV出力
        output_path = "/Users/mitsuru/fx-alert/trades_multi.csv"
        combined_df.to_csv(output_path, index=False)
        print(f"✅ トレード一覧CSV出力: {output_path}\n")

        # 資産曲線データ
        equity_curve = combined_df["pnl_pips"].cumsum()
        equity_df = pd.DataFrame({
            "trade_num": range(len(equity_curve)),
            "cumulative_pips": equity_curve.values
        })
        equity_path = "/Users/mitsuru/fx-alert/equity_multi.csv"
        equity_df.to_csv(equity_path, index=False)
        print(f"✅ 資産曲線データ出力: {equity_path}\n")
    else:
        print("⚠️ トレードが1件も発生しませんでした\n")
        combined_stats = {
            "currency": "",
            "total_trades": 0,
            "win_rate": 0,
            "total_pips": 0,
            "avg_pips": 0,
            "pf": 0,
            "max_dd_pips": 0,
            "warning": "全通貨でトレード0回"
        }
        stats_list.append(combined_stats)

    # 統計表示
    print_stats_table(stats_list)

    # 最終評価
    combined = stats_list[-1]
    print(f"\n【総合評価】")
    if combined["total_trades"] >= MIN_TRADES_THRESHOLD:
        print(f"✅ 統計的に十分なサンプル数 (n={combined['total_trades']})")
    else:
        print(f"⚠️ サンプル不足 (n={combined['total_trades']}, 推奨≥{MIN_TRADES_THRESHOLD})")

    if combined["pf"] > 1.5:
        print(f"✅ 優秀なPF ({combined['pf']:.2f})")
    elif combined["pf"] > 1.0:
        print(f"✓ 許容範囲のPF ({combined['pf']:.2f})")
    else:
        print(f"❌ 要改善のPF ({combined['pf']:.2f})")

    print(f"\n期待値: {combined['avg_pips']:.2f} pips/トレード")
    print()


if __name__ == "__main__":
    main()
