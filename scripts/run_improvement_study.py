"""
D1/W1 改善検証スクリプト
- 過剰最適化を避けた限定パラメータ探索
- TP調整 / 通貨フィルター / ADXフィルター / コスト追加
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.data import fetch_data_range
from src.indicators import calculate_ema, calculate_atr, calculate_adx
from src.daily_strategy.trend import (
    calculate_ema_slope,
    determine_weekly_trend,
    determine_daily_trend,
    determine_alignment,
)
from src.daily_strategy.patterns import detect_pattern
from src.daily_strategy.filters import (
    check_ema_distance,
    check_ema_divergence,
    check_chasing,
    check_weekly_room,
)
import pandas as pd

load_dotenv_if_exists()

STRATEGY_VERSION = "D1_W1_EMA20_PULLBACK_V1"
START_DATE = "2015-01-01"
END_DATE = "2026-02-14"
EQUITY = 500000.0
RISK_PCT = 0.005


def check_signal_d1w1(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    tp1_r: float = 1.5,
    tp2_r: float = 3.0,
    adx_threshold: float = 0.0,
) -> dict:
    """D1/W1シグナル判定（ADXフィルター対応版）"""
    if len(daily_df) < 22 or len(weekly_df) < 22:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    daily_ema20 = calculate_ema(daily_df["close"], 20)
    weekly_ema20 = calculate_ema(weekly_df["close"], 20)
    atr14 = calculate_atr(daily_df, 14)

    close_price = float(daily_df["close"].iloc[-1])
    d_ema20 = float(daily_ema20.iloc[-1])
    w_ema20 = float(weekly_ema20.iloc[-1])
    w_close = float(weekly_df["close"].iloc[-1])
    atr = float(atr14.iloc[-1])

    if atr <= 0:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    # ADXフィルター
    if adx_threshold > 0:
        adx = calculate_adx(daily_df, 14)
        adx_val = float(adx.iloc[-1])
        if adx_val < adx_threshold:
            return {"decision": "SKIP", "reason_codes": ["ADX"]}

    # トレンド判定
    daily_slope = calculate_ema_slope(daily_ema20)
    weekly_slope = calculate_ema_slope(weekly_ema20)
    weekly_trend = determine_weekly_trend(w_close, w_ema20, weekly_slope)
    daily_trend = determine_daily_trend(close_price, d_ema20, daily_slope)
    alignment = determine_alignment(weekly_trend, daily_trend)

    reason_codes = []

    if weekly_trend == "WEEKLY_NEUTRAL":
        reason_codes.append("W")
    if daily_trend == "DAILY_NEUTRAL":
        reason_codes.append("D")
    if alignment == "NO_TRADE" and "W" not in reason_codes and "D" not in reason_codes:
        reason_codes.append("A")

    _, _, pullback_ok = check_ema_distance(close_price, d_ema20, atr)
    is_divergent = check_ema_divergence(close_price, d_ema20, atr)
    if is_divergent:
        reason_codes.append("X")

    today = {
        "open": float(daily_df["open"].iloc[-1]),
        "close": float(daily_df["close"].iloc[-1]),
        "high": float(daily_df["high"].iloc[-1]),
        "low": float(daily_df["low"].iloc[-1]),
    }
    prev = {
        "open": float(daily_df["open"].iloc[-2]),
        "close": float(daily_df["close"].iloc[-2]),
        "high": float(daily_df["high"].iloc[-2]),
        "low": float(daily_df["low"].iloc[-2]),
    }
    pattern_name, pattern_detected = detect_pattern(today, prev, alignment)

    if not pattern_detected and alignment != "NO_TRADE":
        reason_codes.append("P")

    is_chasing = check_chasing(today["high"], today["low"], atr)
    if is_chasing and alignment != "NO_TRADE" and "X" not in reason_codes:
        reason_codes.append("X")

    SL_ATR_BUFFER = 0.1
    entry_side = ""
    planned_entry = 0.0
    planned_sl = 0.0
    risk_price = 0.0

    if alignment == "BUY_ONLY":
        entry_side = "BUY"
        planned_entry = close_price
        planned_sl = today["low"] - SL_ATR_BUFFER * atr
        risk_price = planned_entry - planned_sl
    elif alignment == "SELL_ONLY":
        entry_side = "SELL"
        planned_entry = close_price
        planned_sl = today["high"] + SL_ATR_BUFFER * atr
        risk_price = planned_sl - planned_entry

    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price > 0:
        _, _, room_skip = check_weekly_room(weekly_df, planned_entry, alignment, risk_price)
        if room_skip:
            reason_codes.append("S")

    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price <= 0:
        reason_codes.append("R")

    if not pullback_ok and alignment != "NO_TRADE" and "X" not in reason_codes:
        reason_codes.append("X")

    if alignment == "NO_TRADE" or reason_codes:
        return {
            "decision": "SKIP",
            "reason_codes": reason_codes,
            "alignment": alignment,
            "pattern": pattern_name,
        }

    if entry_side == "BUY":
        tp1 = planned_entry + tp1_r * risk_price
        tp2 = planned_entry + tp2_r * risk_price
    else:
        tp1 = planned_entry - tp1_r * risk_price
        tp2 = planned_entry - tp2_r * risk_price

    return {
        "decision": "ENTRY_OK",
        "reason_codes": [],
        "side": entry_side,
        "entry": planned_entry,
        "sl": planned_sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_price": risk_price,
        "atr": atr,
        "alignment": alignment,
        "pattern": pattern_name,
        "signal_date": str(daily_df["datetime"].iloc[-1]),
    }


def run_backtest(
    symbol: str,
    d1: pd.DataFrame,
    w1: pd.DataFrame,
    equity: float,
    risk_pct: float,
    tp1_r: float,
    tp2_r: float,
    adx_threshold: float = 0.0,
    spread_cost_r: float = 0.0,
    slippage_r: float = 0.0,
) -> dict:
    """D1/W1バックテスト（コストモデル対応版）"""
    trades = []
    current_equity = equity
    active_trade = None
    skip_reasons_count = {}

    for i in range(30, len(d1)):
        current_date = d1["datetime"].iloc[i]
        # 確定済み週足のみ（当週の未完成バーを除外し look-ahead bias を防ぐ）
        monday = current_date - pd.Timedelta(days=current_date.weekday())
        w1_subset = w1[w1["datetime"] < monday]

        if active_trade is not None:
            bar_high = float(d1["high"].iloc[i])
            bar_low = float(d1["low"].iloc[i])
            side = active_trade["side"]
            sl = active_trade["current_sl"]

            sl_hit = False
            tp1_hit = False
            tp2_hit = False

            if side == "BUY":
                sl_hit = bar_low <= sl
                if not active_trade["tp1_done"]:
                    tp1_hit = bar_high >= active_trade["tp1"]
                else:
                    tp2_hit = bar_high >= active_trade["tp2"]
            else:
                sl_hit = bar_high >= sl
                if not active_trade["tp1_done"]:
                    tp1_hit = bar_low <= active_trade["tp1"]
                else:
                    tp2_hit = bar_low <= active_trade["tp2"]

            if sl_hit and not active_trade["tp1_done"]:
                pnl = -active_trade["risk_jpy"]
                current_equity += pnl
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "SL"
                active_trade["pnl"] = pnl
                active_trade["pnl_r"] = -1.0
                trades.append(active_trade)
                active_trade = None

            elif sl_hit and active_trade["tp1_done"]:
                pnl = active_trade["tp1_pnl"]
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "BE"
                active_trade["pnl"] = pnl
                active_trade["pnl_r"] = tp1_r * 0.5
                trades.append(active_trade)
                active_trade = None

            elif tp1_hit and not active_trade["tp1_done"]:
                tp1_pnl = active_trade["risk_jpy"] * tp1_r * 0.5
                current_equity += tp1_pnl
                active_trade["tp1_done"] = True
                active_trade["tp1_pnl"] = tp1_pnl
                active_trade["current_sl"] = active_trade["entry"]

            elif tp2_hit and active_trade["tp1_done"]:
                tp2_pnl = active_trade["risk_jpy"] * tp2_r * 0.5
                current_equity += tp2_pnl
                total_pnl = active_trade["tp1_pnl"] + tp2_pnl
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "TP2"
                active_trade["pnl"] = total_pnl
                active_trade["pnl_r"] = tp1_r * 0.5 + tp2_r * 0.5
                trades.append(active_trade)
                active_trade = None

            continue

        # 新規シグナル
        d1_subset = d1.iloc[:i+1]
        signal = check_signal_d1w1(d1_subset, w1_subset, tp1_r, tp2_r, adx_threshold)

        if signal["decision"] == "SKIP":
            for rc in signal.get("reason_codes", []):
                skip_reasons_count[rc] = skip_reasons_count.get(rc, 0) + 1
        elif signal["decision"] == "ENTRY_OK":
            risk_jpy = current_equity * risk_pct
            units = risk_jpy / signal["risk_price"] if signal["risk_price"] > 0 else 0
            units = (units // 100) * 100
            if units < 100:
                skip_reasons_count["SIZE"] = skip_reasons_count.get("SIZE", 0) + 1
                continue

            actual_risk_jpy = units * signal["risk_price"]

            # コスト適用
            cost_jpy = actual_risk_jpy * (spread_cost_r + slippage_r)

            active_trade = {
                "symbol": symbol,
                "side": signal["side"],
                "entry": signal["entry"],
                "sl": signal["sl"],
                "tp1": signal["tp1"],
                "tp2": signal["tp2"],
                "current_sl": signal["sl"],
                "risk_price": signal["risk_price"],
                "risk_jpy": actual_risk_jpy,
                "cost_jpy": cost_jpy,
                "units": units,
                "entry_date": str(current_date),
                "pattern": signal.get("pattern", ""),
                "tp1_done": False,
                "tp1_pnl": 0.0,
            }

    # 未決済
    if active_trade is not None:
        active_trade["exit_date"] = str(d1["datetime"].iloc[-1])
        active_trade["exit_reason"] = "OPEN"
        active_trade["pnl"] = 0.0
        active_trade["pnl_r"] = 0.0
        trades.append(active_trade)

    return {
        "trades": trades,
        "skip_reasons": skip_reasons_count,
        "final_equity": current_equity,
    }


def calc_metrics(trades: list, initial_equity: float, years: float) -> dict:
    """メトリクス計算"""
    closed = [t for t in trades if t.get("exit_reason") != "OPEN"]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] < 0]

    total_pnl = sum(t["pnl"] for t in closed)
    total_r = sum(t["pnl_r"] for t in closed)
    gross_win = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0
    total_cost = sum(t.get("cost_jpy", 0) for t in closed)

    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    wr = len(wins) / len(closed) * 100 if closed else 0

    # コスト込みPF
    net_win = gross_win - total_cost * 0.5  # コストを勝ち負けに分配
    net_loss = gross_loss + total_cost * 0.5
    pf_net = net_win / net_loss if net_loss > 0 else float("inf")

    # Max DD
    peak = initial_equity
    max_dd = 0
    eq = initial_equity
    for t in closed:
        eq += t["pnl"] - t.get("cost_jpy", 0)
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    # Max losing streak
    streak = 0
    max_streak = 0
    for t in closed:
        if t["pnl"] < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    return {
        "trades": len(closed),
        "trades_per_year": len(closed) / years if years > 0 else 0,
        "wr": wr,
        "pf": pf,
        "pf_net": pf_net,
        "total_pnl": total_pnl,
        "total_cost": total_cost,
        "net_pnl": total_pnl - total_cost,
        "total_r": total_r,
        "avg_r": total_r / len(closed) if closed else 0,
        "max_dd": max_dd * 100,
        "max_streak": max_streak,
        "return_pct": total_pnl / initial_equity * 100,
        "annual_return_pct": (total_pnl / initial_equity * 100) / years if years > 0 else 0,
    }


def main():
    api_key = check_api_key(required=True)
    years = (pd.to_datetime(END_DATE) - pd.to_datetime(START_DATE)).days / 365.25

    # データ取得（全通貨）
    all_pairs = ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CAD/JPY"]
    data_cache = {}

    for pair in all_pairs:
        print(f"Fetching {pair}...")
        warmup_start = (datetime.strptime(START_DATE, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")

        d1 = fetch_data_range(pair, "1day", warmup_start, END_DATE, api_key)
        try:
            w1 = fetch_data_range(pair, "1week", warmup_start, END_DATE, api_key)
        except Exception:
            # 週足取得失敗時は日足から生成
            df = d1.copy()
            df["week"] = df["datetime"].dt.isocalendar().week.astype(int)
            df["year"] = df["datetime"].dt.isocalendar().year.astype(int)
            w1 = df.groupby(["year", "week"]).agg(
                datetime=("datetime", "last"),
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
            ).reset_index(drop=True).sort_values("datetime").reset_index(drop=True)

        data_cache[pair] = {"d1": d1, "w1": w1}
        print(f"  D1: {len(d1)} bars, W1: {len(w1)} bars")

    print(f"\n{'='*80}")
    print(f"Improvement Study: {START_DATE} ~ {END_DATE} ({years:.1f} years)")
    print(f"{'='*80}\n")

    # 検証パターン定義
    tests = []

    # ベースライン
    tests.append({
        "name": "BASE (1.5R/3.0R)",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })

    # 1️⃣ TP調整
    tests.append({
        "name": "TP-A (1.0R/2.0R)",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.0, "tp2": 2.0,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })
    tests.append({
        "name": "TP-B (1.2R/2.4R)",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.2, "tp2": 2.4,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })
    tests.append({
        "name": "TP-C (1.5R/2.5R)",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 2.5,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })

    # 2️⃣ 通貨フィルター
    tests.append({
        "name": "PAIR: USD+EUR only",
        "pairs": ["USD/JPY", "EUR/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })
    tests.append({
        "name": "PAIR: +AUD+CAD",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY", "AUD/JPY", "CAD/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 0.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })

    # 3️⃣ ADXフィルター
    tests.append({
        "name": "ADX >= 20",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 20.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })
    tests.append({
        "name": "ADX >= 25",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 25.0,
        "spread_r": 0.0, "slip_r": 0.0,
    })

    # 4️⃣ コスト追加
    tests.append({
        "name": "BASE + Cost",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 0.0,
        "spread_r": 0.05, "slip_r": 0.05,
    })

    # 5️⃣ 最有力候補（ADX + TP調整 + コスト）
    tests.append({
        "name": "BEST: ADX20+TP1.5/3.0+Cost",
        "pairs": ["USD/JPY", "EUR/JPY", "GBP/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 20.0,
        "spread_r": 0.05, "slip_r": 0.05,
    })
    tests.append({
        "name": "BEST: ADX25+USD/EUR+Cost",
        "pairs": ["USD/JPY", "EUR/JPY"],
        "tp1": 1.5, "tp2": 3.0,
        "adx": 25.0,
        "spread_r": 0.05, "slip_r": 0.05,
    })

    # 実行
    results = []

    for test in tests:
        print(f"--- {test['name']} ---")
        all_trades = []

        for pair in test["pairs"]:
            if pair not in data_cache:
                print(f"  {pair}: no data, skipping")
                continue

            d1 = data_cache[pair]["d1"]
            w1 = data_cache[pair]["w1"]

            result = run_backtest(
                pair, d1, w1,
                EQUITY, RISK_PCT,
                test["tp1"], test["tp2"],
                test["adx"],
                test["spread_r"], test["slip_r"],
            )

            per_pair = calc_metrics(result["trades"], EQUITY, years)
            print(f"  {pair}: {per_pair['trades']}t WR={per_pair['wr']:.0f}% "
                  f"PF={per_pair['pf']:.2f} R={per_pair['total_r']:+.1f}")

            all_trades.extend(result["trades"])

        combined = calc_metrics(all_trades, EQUITY * len(test["pairs"]), years)
        combined["name"] = test["name"]
        combined["pairs"] = ",".join([p.replace("/", "") for p in test["pairs"]])
        results.append(combined)

        print(f"  TOTAL: {combined['trades']}t WR={combined['wr']:.0f}% "
              f"PF={combined['pf']:.2f} PF(net)={combined['pf_net']:.2f} "
              f"R={combined['total_r']:+.1f} DD={combined['max_dd']:.1f}%")
        print()

    # 最終比較テーブル
    print(f"\n{'='*100}")
    print(f"COMPARISON TABLE")
    print(f"{'='*100}")
    header = (f"{'Test':<28} {'Trades':>6} {'T/yr':>5} {'WR%':>5} "
              f"{'PF':>6} {'PFnet':>6} {'TotalR':>7} {'PnL':>10} "
              f"{'DD%':>5} {'Streak':>6} {'Ann%':>6}")
    print(header)
    print("-" * 100)

    base_r = results[0]["total_r"] if results else 0

    for r in results:
        delta_r = r["total_r"] - base_r
        flag = " " if r["name"].startswith("BASE") else ("+" if delta_r >= 0 else "-")
        print(f"{r['name']:<28} {r['trades']:>6} {r['trades_per_year']:>5.1f} "
              f"{r['wr']:>5.1f} {r['pf']:>6.2f} {r['pf_net']:>6.2f} "
              f"{r['total_r']:>+7.1f} {r['net_pnl']:>10,.0f} "
              f"{r['max_dd']:>5.1f} {r['max_streak']:>6} "
              f"{r['annual_return_pct']:>5.1f}% {flag}")

    print(f"\n{'='*100}")
    print("Notes:")
    print("  - PFnet = spread 0.05R + slippage 0.05R 込み (該当テストのみ)")
    print("  - Ann% = 年率リターン (初期資金ベース)")
    print("  - T/yr = 年間トレード数")
    print("  - Streak = 最大連敗数")

    # JSON出力
    output_dir = Path("data/results_d1w1/improvement_study")
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(output_dir / "results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nOutput: {output_dir}/results.json")


if __name__ == "__main__":
    main()
