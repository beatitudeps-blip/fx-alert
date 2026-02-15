"""
V3バックテスト実行スクリプト
- 監査可能なfills.csv生成
- 0.5%動的サイジング
- コスト分解
- OOS/Walk-forward/感度分析
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# src/ をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest_v3 import run_backtest_v3
from src.metrics_v3 import (
    calculate_metrics_v3,
    trades_to_dataframe,
    fills_to_dataframe
)
from src.validation import (
    run_oos_backtest,
    run_walkforward,
    run_sensitivity_analysis
)


def main():
    parser = argparse.ArgumentParser(description="V3 Backtest Engine")
    parser.add_argument("--symbol", type=str, default="USD/JPY", help="通貨ペア")
    parser.add_argument("--days", type=int, default=720, help="バックテスト期間（日）")
    parser.add_argument("--mode", type=str, default="standard",
                       choices=["standard", "oos", "walkforward", "sensitivity"],
                       help="実行モード")
    parser.add_argument("--oos-ratio", type=float, default=0.2, help="OOS比率")
    parser.add_argument("--spread-mult", type=float, default=1.0, help="スプレッド倍率")
    parser.add_argument("--slippage", type=float, default=0.0, help="スリッページ（pips）")
    parser.add_argument("--output", type=str, default="data/results_v3", help="出力ディレクトリ")

    args = parser.parse_args()

    # 期間設定
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    # 出力ディレクトリ
    output_dir = Path(__file__).parent.parent / args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    # 基本パラメータ
    base_kwargs = {
        "api_key": os.environ.get("TWELVEDATA_API_KEY"),
        "initial_equity": 100000.0,
        "risk_pct": 0.005,
        "atr_multiplier": 1.5,
        "tp1_r": 1.0,
        "tp2_r": 2.0,
        "tp1_close_pct": 0.5,
        "spread_multiplier": args.spread_mult,
        "slippage_pips": args.slippage,
        "swap_jpy_per_lot": 0.0,
        "use_cache": True,
        "sl_priority": True
    }

    if args.mode == "standard":
        print(f"=== V3バックテスト（標準） ===")
        print(f"通貨ペア: {args.symbol}")
        print(f"期間: {start_date} ~ {end_date}")
        print(f"スプレッド倍率: {args.spread_mult}")
        print(f"スリッページ: {args.slippage} pips\n")

        # バックテスト実行
        trades, equity_df = run_backtest_v3(
            args.symbol, start_date, end_date, **base_kwargs
        )

        print(f"✅ バックテスト完了: {len(trades)}トレード\n")

        # メトリクス計算
        metrics = calculate_metrics_v3(
            trades, base_kwargs["initial_equity"], start_date, end_date
        )

        # 結果表示
        print("=== パフォーマンスサマリー ===")
        print(f"総トレード数: {metrics['total_trades']}")
        print(f"勝率: {metrics['win_rate']*100:.2f}%")
        print(f"Profit Factor (net): {metrics['pf_net']:.2f}")
        print(f"総損益 (gross): {metrics['total_pnl_gross']:,.0f} JPY")
        print(f"総損益 (net): {metrics['total_pnl_net']:,.0f} JPY")
        print(f"総コスト: {metrics['total_cost']:,.0f} JPY")
        print(f"期待値 (net): {metrics['expectancy_net']:,.0f} JPY")
        print(f"平均R倍数: {metrics['avg_r_multiple']:.2f}R")
        print(f"最大DD: {metrics['max_drawdown_close_based']*100:.2f}%")
        print(f"リスク超過: {metrics['risk_violations_count']}件\n")

        # ファイル出力
        trades_df = trades_to_dataframe(trades)
        fills_df = fills_to_dataframe(trades)

        trades_df.to_csv(output_dir / f"trades_{args.symbol.replace('/', '_')}.csv", index=False)
        fills_df.to_csv(output_dir / f"fills_{args.symbol.replace('/', '_')}.csv", index=False)
        equity_df.to_csv(output_dir / f"equity_curve_{args.symbol.replace('/', '_')}.csv", index=False)

        with open(output_dir / f"summary_{args.symbol.replace('/', '_')}.json", "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        print(f"✅ 結果保存: {output_dir}")

    elif args.mode == "oos":
        print(f"=== OOS分割バックテスト ===\n")
        compare = run_oos_backtest(
            args.symbol, start_date, end_date,
            oos_ratio=args.oos_ratio,
            output_dir=output_dir,
            **base_kwargs
        )

        print("\n=== IS vs OOS 比較 ===")
        print(f"{'指標':<20} {'IS':>15} {'OOS':>15}")
        print("-" * 50)
        print(f"{'トレード数':<20} {compare['is']['trades']:>15} {compare['oos']['trades']:>15}")
        print(f"{'PF (net)':<20} {compare['is']['pf_net']:>15.2f} {compare['oos']['pf_net']:>15.2f}")
        print(f"{'勝率':<20} {compare['is']['win_rate']*100:>14.2f}% {compare['oos']['win_rate']*100:>14.2f}%")
        print(f"{'損益 (net)':<20} {compare['is']['total_pnl_net']:>14,.0f} {compare['oos']['total_pnl_net']:>14,.0f}")
        print(f"{'最大DD':<20} {compare['is']['max_dd']*100:>14.2f}% {compare['oos']['max_dd']*100:>14.2f}%")

    elif args.mode == "walkforward":
        print(f"=== Walk-forward検証 ===\n")
        folds_df = run_walkforward(
            args.symbol, start_date, end_date,
            train_days=720,
            test_days=180,
            step_days=180,
            output_dir=output_dir,
            **base_kwargs
        )

        print("\n=== Folds サマリー ===")
        print(folds_df.to_string(index=False))

    elif args.mode == "sensitivity":
        print(f"=== 感度分析 ===\n")
        cost_grid, param_grid = run_sensitivity_analysis(
            args.symbol, start_date, end_date,
            output_dir=output_dir,
            **base_kwargs
        )

        print("\n=== コスト感度 (上位5件) ===")
        print(cost_grid.sort_values("pf_net", ascending=False).head().to_string(index=False))

        print("\n=== パラメータ感度 (上位5件) ===")
        print(param_grid.sort_values("pf_net", ascending=False).head().to_string(index=False))


if __name__ == "__main__":
    main()
