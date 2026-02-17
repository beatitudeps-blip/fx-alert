"""
V5指値 vs V4成行 バックテスト比較スクリプト

同一期間・同一通貨で両エンジンを実行し、比較表を出力
"""
import os
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.backtest_v4_integrated import run_backtest_v4_integrated
from src.backtest_v5_limit import run_backtest_v5_limit
from src.config_loader import load_broker_config
from src.metrics_v3 import calculate_metrics_v3, trades_to_dataframe, fills_to_dataframe
import pandas as pd
import numpy as np

load_dotenv_if_exists()


def calculate_cagr(initial: float, final: float, start_date: str, end_date: str) -> float:
    """CAGR計算"""
    from datetime import datetime as dt
    start = dt.strptime(start_date, "%Y-%m-%d")
    end = dt.strptime(end_date, "%Y-%m-%d")
    years = (end - start).days / 365.25
    if years <= 0 or final <= 0:
        return 0.0
    return (final / initial) ** (1 / years) - 1


def run_comparison(args):
    config = load_broker_config(args.config)
    api_key = check_api_key(required=True)
    symbols = [s.strip() for s in args.symbols.split(",")]

    run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(args.output) / run_id

    print(f"\n{'='*70}")
    print(f"V5指値 vs V4成行 バックテスト比較")
    print(f"{'='*70}")
    print(f"Run ID: {run_id}")
    print(f"期間: {args.start_date} ~ {args.end_date}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print(f"初期資金: {args.equity:,.0f}円")
    print(f"{'='*70}\n")

    all_results = []

    for symbol in symbols:
        print(f"\n{'─'*60}")
        print(f"[{symbol}]")
        print(f"{'─'*60}")

        # ========== V4 (旧: 1本待ち成行) ==========
        print(f"  V4(成行) 実行中...")
        try:
            trades_v4, eq_v4, stats_v4 = run_backtest_v4_integrated(
                symbol=symbol,
                start_date=args.start_date,
                end_date=args.end_date,
                config=config,
                api_key=api_key,
                initial_equity=args.equity,
                risk_pct=args.risk_pct,
                atr_multiplier=1.2,    # V4デフォルト
                tp1_r=1.2,             # V4デフォルト
                tp2_r=2.4,             # V4デフォルト
                tp1_close_pct=0.5,
                use_cache=True,
                sl_priority=True,
                use_daylight=args.use_daylight,
                run_id=run_id,
                tp2_mode="FIXED_R",
            )
            metrics_v4 = calculate_metrics_v3(trades_v4, args.equity, args.start_date, args.end_date)
            print(f"    完了: {stats_v4['executed_trades']}トレード, PF={metrics_v4.get('pf_net', 0):.2f}")
        except Exception as e:
            print(f"    エラー: {e}")
            metrics_v4 = None
            trades_v4 = []
            stats_v4 = {"executed_trades": 0}

        # ========== V5 (新: 指値) ==========
        print(f"  V5(指値) 実行中...")
        try:
            trades_v5, eq_v5, stats_v5 = run_backtest_v5_limit(
                symbol=symbol,
                start_date=args.start_date,
                end_date=args.end_date,
                config=config,
                api_key=api_key,
                initial_equity=args.equity,
                risk_pct=args.risk_pct,
                atr_multiplier=1.0,    # V5仕様
                tp1_r=1.5,             # V5仕様
                tp1_close_pct=0.5,
                use_cache=True,
                sl_priority=True,
                use_daylight=args.use_daylight,
                run_id=run_id,
            )
            metrics_v5 = calculate_metrics_v3(trades_v5, args.equity, args.start_date, args.end_date)
            print(f"    完了: {stats_v5['executed_trades']}トレード, PF={metrics_v5.get('pf_net', 0):.2f}")
        except Exception as e:
            print(f"    エラー: {e}")
            metrics_v5 = None
            trades_v5 = []
            stats_v5 = {"executed_trades": 0}

        # 結果保存
        for version, trades_list, metrics, stats, eq_df in [
            ("v4_market", trades_v4, metrics_v4, stats_v4, eq_v4 if metrics_v4 else pd.DataFrame()),
            ("v5_limit", trades_v5, metrics_v5, stats_v5, eq_v5 if metrics_v5 else pd.DataFrame()),
        ]:
            out_dir = output_base / version / symbol.replace("/", "_")
            out_dir.mkdir(parents=True, exist_ok=True)

            if trades_list:
                trades_to_dataframe(trades_list).to_csv(out_dir / "trades.csv", index=False)
                fills_to_dataframe(trades_list).to_csv(out_dir / "fills.csv", index=False)
            if not eq_df.empty:
                eq_df.to_csv(out_dir / "equity_curve.csv", index=False)
            if metrics:
                with open(out_dir / "summary.json", "w") as f:
                    json.dump({**metrics, "stats": stats}, f, indent=2, default=str)
            if stats.get("skipped_details"):
                pd.DataFrame(stats["skipped_details"]).to_csv(out_dir / "skipped_signals.csv", index=False)

        # 比較レコード
        for version_tag, m, s in [("V4(成行)", metrics_v4, stats_v4), ("V5(指値)", metrics_v5, stats_v5)]:
            if m:
                cagr = calculate_cagr(args.equity, m.get("final_equity", args.equity),
                                      args.start_date, args.end_date)
                all_results.append({
                    "Symbol": symbol,
                    "Version": version_tag,
                    "Trades": m.get("total_trades", 0),
                    "WinRate": f"{m.get('win_rate', 0)*100:.1f}%",
                    "PF(net)": f"{m.get('pf_net', 0):.2f}",
                    "PnL(net)": f"{m.get('total_pnl_net', 0):,.0f}",
                    "CAGR": f"{cagr*100:.1f}%",
                    "MaxDD": f"{m.get('max_drawdown_close_based', 0)*100:.2f}%",
                    "AvgR": f"{m.get('avg_r_multiple', 0):.2f}",
                    "Skips": s.get("skipped_signals", 0),
                })

                # V5固有のスキップ詳細
                if version_tag == "V5(指値)" and s:
                    print(f"    V5スキップ詳細:")
                    print(f"      指値失効: {s.get('limit_expired_skips', 0)}")
                    print(f"      連敗ガード: {s.get('streak_guard_skips', 0)}")
                    print(f"      メンテ: {s.get('maintenance_skips', 0)}")
                    print(f"      スプレッド: {s.get('spread_filter_skips', 0)}")

    # ==================== 比較表出力 ====================
    print(f"\n\n{'='*90}")
    print(f"比較結果サマリー")
    print(f"{'='*90}")

    if all_results:
        df_compare = pd.DataFrame(all_results)

        # テーブル表示
        header = f"{'Symbol':<10} {'Version':<12} {'Trades':>6} {'WinRate':>8} {'PF(net)':>8} {'PnL(net)':>12} {'CAGR':>7} {'MaxDD':>8} {'AvgR':>6} {'Skips':>6}"
        print(header)
        print("─" * 90)
        for _, row in df_compare.iterrows():
            line = f"{row['Symbol']:<10} {row['Version']:<12} {row['Trades']:>6} {row['WinRate']:>8} {row['PF(net)']:>8} {row['PnL(net)']:>12} {row['CAGR']:>7} {row['MaxDD']:>8} {row['AvgR']:>6} {row['Skips']:>6}"
            print(line)
        print("─" * 90)

        # CSV保存
        compare_csv = output_base / "comparison_table.csv"
        df_compare.to_csv(compare_csv, index=False)
        print(f"\n比較表CSV: {compare_csv}")

    # 証拠ログ出力
    evidence_log = output_base / "evidence_log.txt"
    with open(evidence_log, "w") as f:
        f.write(f"V5指値 vs V4成行 バックテスト比較証拠ログ\n")
        f.write(f"{'='*70}\n")
        f.write(f"実行日時: {datetime.now().isoformat()}\n")
        f.write(f"Run ID: {run_id}\n")
        f.write(f"期間: {args.start_date} ~ {args.end_date}\n")
        f.write(f"通貨ペア: {', '.join(symbols)}\n")
        f.write(f"初期資金: {args.equity:,.0f}円\n")
        f.write(f"リスク率: {args.risk_pct*100:.1f}%\n\n")
        f.write(f"V4パラメータ: ATR×1.2, TP1=1.2R, TP2=2.4R, 1本待ち成行\n")
        f.write(f"V5パラメータ: ATR×1.0, TP1=1.5R, EMAクロス退出, 指値(EMA±0.10ATR), ADX>=18, 連敗ガード(3連敗→2スキップ)\n\n")
        if all_results:
            f.write(f"{'Symbol':<10} {'Version':<12} {'Trades':>6} {'WinRate':>8} {'PF(net)':>8} {'PnL(net)':>12} {'CAGR':>7} {'MaxDD':>8}\n")
            f.write("─" * 75 + "\n")
            for r in all_results:
                f.write(f"{r['Symbol']:<10} {r['Version']:<12} {r['Trades']:>6} {r['WinRate']:>8} {r['PF(net)']:>8} {r['PnL(net)']:>12} {r['CAGR']:>7} {r['MaxDD']:>8}\n")

    print(f"証拠ログ: {evidence_log}")
    print(f"\n出力ディレクトリ: {output_base}/")
    print(f"{'='*90}")


def main():
    parser = argparse.ArgumentParser(description="V5指値 vs V4成行 バックテスト比較")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml")
    parser.add_argument("--symbols", type=str, default="USD/JPY,EUR/JPY,GBP/JPY")
    parser.add_argument("--start-date", type=str, required=True)
    parser.add_argument("--end-date", type=str, required=True)
    parser.add_argument("--equity", type=float, default=100000.0)
    parser.add_argument("--risk-pct", type=float, default=0.005)
    parser.add_argument("--output", type=str, default="data/results_v5_compare")
    parser.add_argument("--run-id", type=str, default=None)
    parser.add_argument("--use-daylight", action="store_true")

    args = parser.parse_args()
    run_comparison(args)


if __name__ == "__main__":
    main()
