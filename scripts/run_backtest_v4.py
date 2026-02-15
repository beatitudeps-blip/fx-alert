"""
V4統合バックテスト実行スクリプト（みんなのFX対応）

run_idで出力を分離:
results/{run_id}/{symbol}/
  ├── summary.json
  ├── trades.csv
  ├── fills.csv
  ├── equity_curve.csv
  └── skipped_signals.csv
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
from src.config_loader import load_broker_config
from src.metrics_v3 import calculate_metrics_v3, trades_to_dataframe, fills_to_dataframe
import pandas as pd

# .env ファイルを読み込み（存在すれば）
load_dotenv_if_exists()


def main():
    parser = argparse.ArgumentParser(description="V4統合バックテスト")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml", help="設定ファイル")
    parser.add_argument("--symbols", type=str, default="USD/JPY,EUR/JPY,GBP/JPY", help="通貨ペア（カンマ区切り）")
    parser.add_argument("--start-date", type=str, required=True, help="開始日 (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, required=True, help="終了日 (YYYY-MM-DD)")
    parser.add_argument("--equity", type=float, default=100000.0, help="初期資金")
    parser.add_argument("--risk-pct", type=float, default=0.005, help="リスク率")
    parser.add_argument("--atr-mult", type=float, default=1.2, help="ATR倍率")
    parser.add_argument("--tp1-r", type=float, default=1.2, help="TP1のR倍数")
    parser.add_argument("--tp2-r", type=float, default=2.4, help="TP2のR倍数（FIXED_Rモード時のみ使用）")
    parser.add_argument("--tp2-mode", type=str, default="FIXED_R", choices=["FIXED_R", "STRUCTURE"], help="TP2計算モード")
    parser.add_argument("--tp2-lookback-days", type=int, default=20, help="構造型TP2の検索期間（日数）")
    parser.add_argument("--output", type=str, default="data/results_v4", help="出力ベースディレクトリ")
    parser.add_argument("--run-id", type=str, default=None, help="実行ID（省略時は自動生成）")
    parser.add_argument("--use-daylight", action="store_true", help="米国夏時間適用")

    args = parser.parse_args()

    # run_id生成（省略時はタイムスタンプ）
    if args.run_id is None:
        args.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    # 設定読み込み
    config = load_broker_config(args.config)
    print(f"✅ 設定読み込み: {args.config}")

    # API Key（必須）
    api_key = check_api_key(required=True)

    # 通貨ペアリスト
    symbols = [s.strip() for s in args.symbols.split(",")]

    print(f"\n{'='*60}")
    print(f"V4統合バックテスト開始")
    print(f"{'='*60}")
    print(f"Run ID: {args.run_id}")
    print(f"期間: {args.start_date} ~ {args.end_date}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print(f"初期資金: {args.equity:,.0f}円")
    print(f"リスク設定: {args.risk_pct*100:.1f}%")
    tp2_desc = f"{args.tp2_mode}" if args.tp2_mode == "STRUCTURE" else f"{args.tp2_r}R"
    print(f"パラメータ: ATR {args.atr_mult} × TP1 {args.tp1_r}R × TP2 {tp2_desc}")
    if args.tp2_mode == "STRUCTURE":
        print(f"  TP2構造型: 日足スイング（直近{args.tp2_lookback_days}日、最大{args.tp2_r}Rキャップ）")
    print(f"出力先: {args.output}/{args.run_id}/")
    print(f"{'='*60}\n")

    for symbol in symbols:
        print(f"[{symbol}] バックテスト実行中...")

        try:
            # バックテスト実行
            trades, equity_df, stats = run_backtest_v4_integrated(
                symbol=symbol,
                start_date=args.start_date,
                end_date=args.end_date,
                config=config,
                api_key=api_key,
                initial_equity=args.equity,
                risk_pct=args.risk_pct,
                atr_multiplier=args.atr_mult,
                tp1_r=args.tp1_r,
                tp2_r=args.tp2_r,
                tp1_close_pct=0.5,
                use_cache=True,
                sl_priority=True,
                use_daylight=args.use_daylight,
                run_id=args.run_id,
                tp2_mode=args.tp2_mode,
                tp2_lookback_days=args.tp2_lookback_days
            )

            print(f"  ✅ 完了: {stats['executed_trades']}トレード")
            print(f"     スキップ: {stats['skipped_signals']}件 " +
                  f"(メンテ {stats['maintenance_skips']}, " +
                  f"スプレッド {stats['spread_filter_skips']}, " +
                  f"サイズ {stats['position_size_skips']})")

            # メトリクス計算
            metrics = calculate_metrics_v3(
                trades, args.equity, args.start_date, args.end_date
            )

            # パフォーマンス表示
            print(f"     PF (net): {metrics['pf_net']:.2f}")
            print(f"     勝率: {metrics['win_rate']*100:.1f}%")
            print(f"     損益 (net): {metrics['total_pnl_net']:,.0f}円")
            print(f"     最大DD: {metrics['max_drawdown_close_based']*100:.2f}%")
            print(f"     リスク違反: {metrics['risk_violations_count']}件")

            # violations=0確認
            if metrics['risk_violations_count'] > 0:
                print(f"     ⚠️ WARNING: リスク違反が検出されました！")
            else:
                print(f"     ✅ Violations=0 確認")

            # 出力ディレクトリ作成
            output_dir = Path(args.output) / args.run_id / symbol.replace("/", "_")
            output_dir.mkdir(parents=True, exist_ok=True)

            # ファイル出力
            trades_df = trades_to_dataframe(trades)
            fills_df = fills_to_dataframe(trades)

            trades_df.to_csv(output_dir / "trades.csv", index=False)
            fills_df.to_csv(output_dir / "fills.csv", index=False)
            equity_df.to_csv(output_dir / "equity_curve.csv", index=False)

            # スキップ記録
            if stats['skipped_details']:
                skipped_df = pd.DataFrame(stats['skipped_details'])
                skipped_df.to_csv(output_dir / "skipped_signals.csv", index=False)

            # サマリー（メトリクス + 統計）
            summary = {
                **metrics,
                "run_id": args.run_id,
                "symbol": symbol,
                "start_date": args.start_date,
                "end_date": args.end_date,
                "config_file": args.config,
                "parameters": {
                    "initial_equity": args.equity,
                    "risk_pct": args.risk_pct,
                    "atr_multiplier": args.atr_mult,
                    "tp1_r": args.tp1_r,
                    "tp2_r": args.tp2_r,
                },
                "stats": stats
            }

            with open(output_dir / "summary.json", "w") as f:
                json.dump(summary, f, indent=2, default=str)

            print(f"     📁 出力: {output_dir}/\n")

        except Exception as e:
            print(f"  ❌ エラー: {e}\n")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print(f"✅ V4統合バックテスト完了")
    print(f"{'='*60}")
    print(f"出力: {args.output}/{args.run_id}/")
    print(f"\n各通貨ペアの詳細:")
    for symbol in symbols:
        output_dir = Path(args.output) / args.run_id / symbol.replace("/", "_")
        if (output_dir / "summary.json").exists():
            print(f"  - {symbol}: {output_dir}/")


if __name__ == "__main__":
    main()
