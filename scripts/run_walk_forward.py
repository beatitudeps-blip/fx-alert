"""
ウォークフォワード分析スクリプト

3ヶ月IS / 1ヶ月OOS窓を1ヶ月ごとにローリング
"""
import os
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest_v4_integrated import run_backtest_v4_integrated
from src.config_loader import load_broker_config


def generate_walk_forward_windows(
    start_date: str,
    end_date: str,
    is_months: int = 3,
    oos_months: int = 1,
    roll_months: int = 1
):
    """
    ウォークフォワード窓を生成

    Args:
        start_date: 開始日 (YYYY-MM-DD)
        end_date: 終了日 (YYYY-MM-DD)
        is_months: IS期間（月）
        oos_months: OOS期間（月）
        roll_months: ローリング間隔（月）

    Returns:
        [(is_start, is_end, oos_start, oos_end), ...]
    """
    windows = []
    current_start = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    while True:
        is_end = current_start + relativedelta(months=is_months) - timedelta(days=1)
        oos_start = is_end + timedelta(days=1)
        oos_end = oos_start + relativedelta(months=oos_months) - timedelta(days=1)

        # 終了日を超えたら終了
        if oos_end > end_dt:
            break

        windows.append((
            current_start.strftime("%Y-%m-%d"),
            is_end.strftime("%Y-%m-%d"),
            oos_start.strftime("%Y-%m-%d"),
            min(oos_end, end_dt).strftime("%Y-%m-%d")
        ))

        # 次の窓へロール
        current_start += relativedelta(months=roll_months)

    return windows


def run_walk_forward_analysis(
    symbols: list,
    start_date: str,
    end_date: str,
    config_path: str = "config/minnafx.yaml",
    api_key: str = None,
    initial_equity: float = 100000.0,
    risk_pct: float = 0.005,
    atr_mult: float = 1.2,
    tp1_r: float = 1.2,
    tp2_r: float = 2.4,
    is_months: int = 3,
    oos_months: int = 1,
    roll_months: int = 1,
    output_base: str = "data/walk_forward"
):
    """
    ウォークフォワード分析実行

    Args:
        symbols: 通貨ペアリスト
        start_date: 開始日
        end_date: 終了日
        config_path: 設定ファイルパス
        api_key: APIキー
        initial_equity: 初期資金
        risk_pct: リスク率
        atr_mult: ATR倍率
        tp1_r: TP1のR倍数
        tp2_r: TP2のR倍数
        is_months: IS期間（月）
        oos_months: OOS期間（月）
        roll_months: ローリング間隔（月）
        output_base: 出力ベースディレクトリ

    Returns:
        結果DataFrame
    """
    config = load_broker_config(config_path)

    # 窓生成
    windows = generate_walk_forward_windows(
        start_date, end_date, is_months, oos_months, roll_months
    )

    print("=" * 80)
    print("ウォークフォワード分析")
    print("=" * 80)
    print(f"期間: {start_date} ~ {end_date}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print(f"窓設定: IS {is_months}ヶ月 / OOS {oos_months}ヶ月 / Roll {roll_months}ヶ月")
    print(f"窓数: {len(windows)}")
    print("=" * 80)
    print()

    results = []

    for idx, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
        print(f"\n[窓 {idx}/{len(windows)}]")
        print(f"  IS:  {is_start} ~ {is_end}")
        print(f"  OOS: {oos_start} ~ {oos_end}")

        for symbol in symbols:
            print(f"    [{symbol}] 実行中...", end="", flush=True)

            try:
                # OOS期間のバックテスト
                trades, equity_df, stats = run_backtest_v4_integrated(
                    symbol=symbol,
                    start_date=oos_start,
                    end_date=oos_end,
                    config=config,
                    api_key=api_key,
                    initial_equity=initial_equity,
                    risk_pct=risk_pct,
                    atr_multiplier=atr_mult,
                    tp1_r=tp1_r,
                    tp2_r=tp2_r,
                    tp1_close_pct=0.5,
                    use_cache=True,
                    sl_priority=True,
                    use_daylight=False,
                    run_id=f"wf_{idx}_{symbol.replace('/', '_')}"
                )

                # 結果集計
                total_pnl = sum(t.total_pnl_net_jpy for t in trades)
                winning_trades = [t for t in trades if t.total_pnl_net_jpy > 0]
                losing_trades = [t for t in trades if t.total_pnl_net_jpy < 0]
                win_rate = len(winning_trades) / len(trades) if len(trades) > 0 else 0

                total_wins = sum(t.total_pnl_net_jpy for t in winning_trades)
                total_losses = abs(sum(t.total_pnl_net_jpy for t in losing_trades))
                pf = total_wins / total_losses if total_losses > 0 else 0

                # violations計算（0.5%超過トレードをカウント）
                violations_count = 0
                for t in trades:
                    if t.initial_risk_jpy > initial_equity * risk_pct:
                        violations_count += 1

                results.append({
                    "window": idx,
                    "is_start": is_start,
                    "is_end": is_end,
                    "oos_start": oos_start,
                    "oos_end": oos_end,
                    "symbol": symbol,
                    "trades": len(trades),
                    "win_rate": win_rate,
                    "pf": pf,
                    "net_pnl": total_pnl,
                    "return_pct": (total_pnl / initial_equity) * 100,
                    "violations": violations_count
                })

                print(f" ✅ {len(trades)}T, PF {pf:.2f}, {win_rate*100:.1f}%, {total_pnl:+.0f}円")

            except Exception as e:
                print(f" ❌ エラー: {e}")
                results.append({
                    "window": idx,
                    "is_start": is_start,
                    "is_end": is_end,
                    "oos_start": oos_start,
                    "oos_end": oos_end,
                    "symbol": symbol,
                    "trades": 0,
                    "win_rate": 0,
                    "pf": 0,
                    "net_pnl": 0,
                    "return_pct": 0,
                    "violations": 0
                })

    # 結果をDataFrameに変換
    df_results = pd.DataFrame(results)

    # 出力ディレクトリ作成
    output_dir = Path(output_base)
    output_dir.mkdir(parents=True, exist_ok=True)

    # CSV保存
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"walk_forward_{timestamp}.csv"
    df_results.to_csv(csv_path, index=False)

    # サマリー表示
    print("\n" + "=" * 80)
    print("ウォークフォワード分析完了")
    print("=" * 80)
    print(f"📁 結果: {csv_path}")
    print()

    # 通貨ペア別サマリー
    for symbol in symbols:
        symbol_results = df_results[df_results["symbol"] == symbol]
        avg_pf = symbol_results["pf"].mean()
        avg_win_rate = symbol_results["win_rate"].mean() * 100
        total_pnl = symbol_results["net_pnl"].sum()
        total_trades = symbol_results["trades"].sum()
        violations = symbol_results["violations"].sum()

        print(f"[{symbol}]")
        print(f"  窓数: {len(symbol_results)}")
        print(f"  合計トレード: {total_trades}")
        print(f"  平均PF: {avg_pf:.2f}")
        print(f"  平均勝率: {avg_win_rate:.1f}%")
        print(f"  合計損益: {total_pnl:+,.0f}円")
        print(f"  Violations: {violations}件")
        print()

    return df_results


if __name__ == "__main__":
    api_key = os.environ.get("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")

    df = run_walk_forward_analysis(
        symbols=["EUR/JPY", "USD/JPY", "GBP/JPY"],
        start_date="2024-01-01",
        end_date="2026-02-14",
        api_key=api_key,
        initial_equity=100000.0,
        risk_pct=0.005,
        atr_mult=1.2,
        tp1_r=1.2,
        tp2_r=2.4,
        is_months=3,
        oos_months=1,
        roll_months=1
    )

    print("✅ ウォークフォワード分析完了")
