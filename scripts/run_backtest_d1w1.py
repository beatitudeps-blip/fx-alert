"""
D1/W1 EMA20 Pullback Strategy バックテスト
- 週足フィルター + 日足EMA20押し戻り
- エントリー: 日足終値ベース
- SL/TP判定: 翌日以降の日足 high/low
- 4H足は使用しない
"""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.data import fetch_data_range
from src.indicators import calculate_ema, calculate_atr
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


def generate_weekly_from_daily(d1: pd.DataFrame) -> pd.DataFrame:
    """日足データから週足OHLCを生成する"""
    df = d1.copy()
    df["week"] = df["datetime"].dt.isocalendar().week.astype(int)
    df["year"] = df["datetime"].dt.isocalendar().year.astype(int)

    weekly = df.groupby(["year", "week"]).agg(
        datetime=("datetime", "last"),
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    ).reset_index(drop=True).sort_values("datetime").reset_index(drop=True)

    return weekly


def check_signal_d1w1(
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    atr_mult: float = 1.0,
    tp1_r: float = 1.5,
    tp2_r: float = 3.0,
) -> dict:
    """
    D1/W1シグナル判定（build_single_signal の簡易バックテスト版）

    Returns:
        signal dict with decision, side, entry, sl, tp1, tp2, reason_codes
    """
    if len(daily_df) < 22 or len(weekly_df) < 22:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    # 指標計算
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

    # EMA距離
    _, _, pullback_ok = check_ema_distance(close_price, d_ema20, atr)
    is_divergent = check_ema_divergence(close_price, d_ema20, atr)
    if is_divergent:
        reason_codes.append("X")

    # パターン検出
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

    # 追いかけエントリー回避
    is_chasing = check_chasing(today["high"], today["low"], atr)
    if is_chasing and alignment != "NO_TRADE" and "X" not in reason_codes:
        reason_codes.append("X")

    # SL/TP計算
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

    # 週足抵抗/支持フィルター
    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price > 0:
        _, _, room_skip = check_weekly_room(weekly_df, planned_entry, alignment, risk_price)
        if room_skip:
            reason_codes.append("S")

    # RR不足
    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price <= 0:
        reason_codes.append("R")

    # pullback_ok
    if not pullback_ok and alignment != "NO_TRADE" and "X" not in reason_codes:
        reason_codes.append("X")

    # 最終判定
    if alignment == "NO_TRADE" or reason_codes:
        return {
            "decision": "SKIP",
            "reason_codes": reason_codes,
            "alignment": alignment,
            "pattern": pattern_name,
        }

    # TP計算
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
    atr_mult: float,
    tp1_r: float,
    tp2_r: float,
) -> dict:
    """
    D1/W1バックテスト実行

    - エントリー: シグナル日の終値
    - SL/TP: 翌日以降の日足 high/low で判定
    - TP1: 50% 利確 → SL を建値へ
    - TP2: 残り 50% 利確
    """
    trades = []
    equity_curve = [{"date": str(d1["datetime"].iloc[0]), "equity": equity}]
    current_equity = equity

    active_trade = None
    skip_reasons_count = {}

    # EMA/ATR ウォームアップのため i=30 から開始
    for i in range(30, len(d1)):
        current_date = d1["datetime"].iloc[i]

        # 確定済み週足 = current_date 以前の週足
        w1_subset = w1[w1["datetime"] <= current_date]

        # アクティブトレードの SL/TP チェック（当日の high/low で判定）
        if active_trade is not None:
            bar_high = float(d1["high"].iloc[i])
            bar_low = float(d1["low"].iloc[i])

            side = active_trade["side"]
            sl = active_trade["current_sl"]
            tp1_hit = False
            tp2_hit = False
            sl_hit = False

            if side == "BUY":
                sl_hit = bar_low <= sl
                if not active_trade["tp1_done"]:
                    tp1_hit = bar_high >= active_trade["tp1"]
                else:
                    tp2_hit = bar_high >= active_trade["tp2"]
            else:  # SELL
                sl_hit = bar_high >= sl
                if not active_trade["tp1_done"]:
                    tp1_hit = bar_low <= active_trade["tp1"]
                else:
                    tp2_hit = bar_low <= active_trade["tp2"]

            # SL 優先判定
            if sl_hit and not active_trade["tp1_done"]:
                # SL hit (full loss)
                pnl = -active_trade["risk_jpy"]
                current_equity += pnl
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "SL"
                active_trade["pnl"] = pnl
                active_trade["pnl_r"] = -1.0
                trades.append(active_trade)
                active_trade = None

            elif sl_hit and active_trade["tp1_done"]:
                # SL at breakeven (after TP1)
                pnl = 0.0  # BE
                current_equity += pnl
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "BE"
                active_trade["pnl"] = active_trade["tp1_pnl"]  # TP1 profit only
                active_trade["pnl_r"] = tp1_r * 0.5  # half position at TP1
                trades.append(active_trade)
                active_trade = None

            elif tp1_hit and not active_trade["tp1_done"]:
                # TP1 hit: close 50%, move SL to breakeven
                tp1_pnl = active_trade["risk_jpy"] * tp1_r * 0.5
                current_equity += tp1_pnl
                active_trade["tp1_done"] = True
                active_trade["tp1_pnl"] = tp1_pnl
                active_trade["current_sl"] = active_trade["entry"]  # BE

            elif tp2_hit and active_trade["tp1_done"]:
                # TP2 hit: close remaining 50%
                tp2_pnl = active_trade["risk_jpy"] * tp2_r * 0.5
                current_equity += tp2_pnl
                total_pnl = active_trade["tp1_pnl"] + tp2_pnl
                active_trade["exit_date"] = str(current_date)
                active_trade["exit_reason"] = "TP2"
                active_trade["pnl"] = total_pnl
                active_trade["pnl_r"] = tp1_r * 0.5 + tp2_r * 0.5
                trades.append(active_trade)
                active_trade = None

            equity_curve.append({"date": str(current_date), "equity": current_equity})
            continue  # アクティブトレードがある間は新規シグナルを見ない

        # 新規シグナル判定
        d1_subset = d1.iloc[:i+1]  # 当日まで（確定済み）
        signal = check_signal_d1w1(d1_subset, w1_subset, atr_mult, tp1_r, tp2_r)

        if signal["decision"] == "SKIP":
            for rc in signal.get("reason_codes", []):
                skip_reasons_count[rc] = skip_reasons_count.get(rc, 0) + 1
        elif signal["decision"] == "ENTRY_OK":
            # ポジションサイジング
            risk_jpy = current_equity * risk_pct
            units = risk_jpy / signal["risk_price"] if signal["risk_price"] > 0 else 0
            lot_step = 100
            units = (units // lot_step) * lot_step
            if units < 100:
                skip_reasons_count["SIZE"] = skip_reasons_count.get("SIZE", 0) + 1
                equity_curve.append({"date": str(current_date), "equity": current_equity})
                continue

            actual_risk_jpy = units * signal["risk_price"]

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
                "units": units,
                "entry_date": str(current_date),
                "signal_date": signal.get("signal_date", str(current_date)),
                "pattern": signal.get("pattern", ""),
                "alignment": signal.get("alignment", ""),
                "tp1_done": False,
                "tp1_pnl": 0.0,
            }

        equity_curve.append({"date": str(current_date), "equity": current_equity})

    # 未決済トレードの処理
    if active_trade is not None:
        active_trade["exit_date"] = str(d1["datetime"].iloc[-1])
        active_trade["exit_reason"] = "OPEN"
        active_trade["pnl"] = 0.0
        active_trade["pnl_r"] = 0.0
        trades.append(active_trade)

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "skip_reasons": skip_reasons_count,
        "final_equity": current_equity,
    }


def calculate_metrics(trades: list, initial_equity: float) -> dict:
    """トレードリストからメトリクスを計算"""
    closed = [t for t in trades if t["exit_reason"] != "OPEN"]
    wins = [t for t in closed if t["pnl"] > 0]
    losses = [t for t in closed if t["pnl"] < 0]
    breakeven = [t for t in closed if t["pnl"] == 0]

    total_pnl = sum(t["pnl"] for t in closed)
    total_r = sum(t["pnl_r"] for t in closed)
    gross_win = sum(t["pnl"] for t in wins) if wins else 0
    gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0

    pf = gross_win / gross_loss if gross_loss > 0 else float("inf")
    win_rate = len(wins) / len(closed) if closed else 0

    # Max drawdown
    peak = initial_equity
    max_dd = 0
    eq = initial_equity
    for t in closed:
        eq += t["pnl"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Max losing streak
    streak = 0
    max_streak = 0
    for t in closed:
        if t["pnl"] < 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0

    # Exit reason breakdown
    exit_reasons = {}
    for t in closed:
        r = t["exit_reason"]
        exit_reasons[r] = exit_reasons.get(r, 0) + 1

    return {
        "total_trades": len(closed),
        "open_trades": len([t for t in trades if t["exit_reason"] == "OPEN"]),
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": len(breakeven),
        "win_rate": win_rate,
        "profit_factor": pf,
        "total_pnl": total_pnl,
        "total_r": total_r,
        "avg_r": total_r / len(closed) if closed else 0,
        "avg_win": gross_win / len(wins) if wins else 0,
        "avg_loss": -gross_loss / len(losses) if losses else 0,
        "max_drawdown": max_dd,
        "max_losing_streak": max_streak,
        "exit_reasons": exit_reasons,
        "return_pct": total_pnl / initial_equity * 100,
    }


def main():
    parser = argparse.ArgumentParser(description="D1/W1 EMA20 Pullback バックテスト")
    parser.add_argument("--symbols", type=str, default="USD/JPY,EUR/JPY,GBP/JPY")
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--equity", type=float, default=500000.0)
    parser.add_argument("--risk-pct", type=float, default=0.005)
    parser.add_argument("--atr-mult", type=float, default=1.0)
    parser.add_argument("--tp1-r", type=float, default=1.5)
    parser.add_argument("--tp2-r", type=float, default=3.0)
    parser.add_argument("--output", type=str, default="data/results_d1w1")
    parser.add_argument("--run-id", type=str, default=None)

    args = parser.parse_args()
    if args.run_id is None:
        args.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    api_key = check_api_key(required=True)
    symbols = [s.strip() for s in args.symbols.split(",")]

    print(f"\n{'='*60}")
    print(f"D1/W1 EMA20 Pullback バックテスト")
    print(f"{'='*60}")
    print(f"Version: {STRATEGY_VERSION}")
    print(f"Run ID: {args.run_id}")
    print(f"Period: {args.start_date} ~ {args.end_date}")
    print(f"Pairs: {', '.join(symbols)}")
    print(f"Equity: {args.equity:,.0f} JPY")
    print(f"Risk: {args.risk_pct*100:.1f}%")
    print(f"Params: ATR {args.atr_mult} / TP1 {args.tp1_r}R / TP2 {args.tp2_r}R")
    print(f"{'='*60}\n")

    all_results = {}

    for symbol in symbols:
        print(f"[{symbol}] Fetching data...")

        # EMAウォームアップのため開始日の60日前から取得
        start_dt = datetime.strptime(args.start_date, "%Y-%m-%d")
        warmup_start = (start_dt - timedelta(days=90)).strftime("%Y-%m-%d")

        d1 = fetch_data_range(symbol, "1day", warmup_start, args.end_date, api_key)
        print(f"  D1: {len(d1)} bars")

        # 週足はAPIから取得（より正確）
        try:
            w1 = fetch_data_range(symbol, "1week", warmup_start, args.end_date, api_key)
            print(f"  W1: {len(w1)} bars (API)")
        except Exception:
            w1 = generate_weekly_from_daily(d1)
            print(f"  W1: {len(w1)} bars (generated from D1)")

        print(f"[{symbol}] Running backtest...")

        result = run_backtest(
            symbol, d1, w1,
            args.equity, args.risk_pct,
            args.atr_mult, args.tp1_r, args.tp2_r,
        )

        metrics = calculate_metrics(result["trades"], args.equity)

        print(f"  Trades: {metrics['total_trades']} "
              f"(Open: {metrics['open_trades']})")
        print(f"  Win Rate: {metrics['win_rate']*100:.1f}%")
        print(f"  PF: {metrics['profit_factor']:.2f}")
        print(f"  PnL: {metrics['total_pnl']:,.0f} JPY "
              f"({metrics['return_pct']:+.1f}%)")
        print(f"  Total R: {metrics['total_r']:.1f}")
        print(f"  Max DD: {metrics['max_drawdown']*100:.2f}%")
        print(f"  Max Losing Streak: {metrics['max_losing_streak']}")
        print(f"  Exit Reasons: {metrics['exit_reasons']}")
        print(f"  Skip Reasons: {result['skip_reasons']}")
        print()

        # 出力
        output_dir = Path(args.output) / args.run_id / symbol.replace("/", "_")
        output_dir.mkdir(parents=True, exist_ok=True)

        # trades.csv
        if result["trades"]:
            pd.DataFrame(result["trades"]).to_csv(
                output_dir / "trades.csv", index=False
            )

        # equity_curve.csv
        pd.DataFrame(result["equity_curve"]).to_csv(
            output_dir / "equity_curve.csv", index=False
        )

        # summary.json
        summary = {
            "symbol": symbol,
            "version": STRATEGY_VERSION,
            "run_id": args.run_id,
            "period": f"{args.start_date} ~ {args.end_date}",
            "parameters": {
                "equity": args.equity,
                "risk_pct": args.risk_pct,
                "atr_mult": args.atr_mult,
                "tp1_r": args.tp1_r,
                "tp2_r": args.tp2_r,
            },
            "metrics": metrics,
            "skip_reasons": result["skip_reasons"],
        }
        with open(output_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2, default=str)

        all_results[symbol] = metrics

    # 全体サマリー
    print(f"\n{'='*60}")
    print(f"Summary")
    print(f"{'='*60}")
    print(f"{'Pair':<12} {'Trades':>7} {'WR':>7} {'PF':>7} {'PnL':>12} {'DD':>7} {'R':>8}")
    print("-" * 62)

    total_pnl = 0
    total_trades = 0
    total_wins = 0
    for sym, m in all_results.items():
        pair_short = sym.replace("/", "")
        print(f"{pair_short:<12} {m['total_trades']:>7} "
              f"{m['win_rate']*100:>6.1f}% {m['profit_factor']:>6.2f} "
              f"{m['total_pnl']:>11,.0f} {m['max_drawdown']*100:>6.2f}% "
              f"{m['total_r']:>7.1f}")
        total_pnl += m["total_pnl"]
        total_trades += m["total_trades"]
        total_wins += m["wins"]

    print("-" * 62)
    overall_wr = total_wins / total_trades * 100 if total_trades > 0 else 0
    print(f"{'TOTAL':<12} {total_trades:>7} {overall_wr:>6.1f}%         "
          f"{total_pnl:>11,.0f}")
    print(f"\nOutput: {args.output}/{args.run_id}/")


if __name__ == "__main__":
    main()
