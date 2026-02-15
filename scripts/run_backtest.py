"""バックテスト実行スクリプト"""
import os
import sys
import json
from datetime import datetime, timedelta
from pathlib import Path

# src/ をパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.backtest import run_backtest
from src.metrics import calculate_metrics, trades_to_dataframe


def main():
    """メインバックテスト実行（3通貨対応）"""
    # 設定
    symbols = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=720)).strftime("%Y-%m-%d")

    print(f"=== V3バックテスト開始（3通貨） ===")
    print(f"期間: {start_date} ~ {end_date}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print()

    all_results = []

    # 各通貨ペアでバックテスト実行
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"【{symbol}】バックテスト実行中...")
        print(f"{'='*60}")

        try:
            trades, equity_df = run_backtest(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                atr_multiplier=1.5,
                risk_pct=0.005,
                use_cache=True
            )

            print(f"✅ バックテスト完了: {len(trades)}トレード")

            # メトリクス計算
            metrics = calculate_metrics(trades, initial_balance=100000.0)
            metrics["symbol"] = symbol

            # 結果表示
            print(f"\n=== {symbol} パフォーマンスサマリー ===")
            print(f"総トレード数: {metrics['total_trades']}")
            print(f"勝率: {metrics['win_rate']*100:.2f}%")
            print(f"Profit Factor: {metrics['profit_factor']:.2f}")
            print(f"総損益: {metrics['total_pnl']:,.0f} JPY ({metrics['total_pnl_pct']:.2f}%)")
            print(f"平均勝ち: {metrics['avg_win']:,.0f} JPY")
            print(f"平均負け: {metrics['avg_loss']:,.0f} JPY")
            print(f"平均R倍数: {metrics['r_multiple']:.2f}R")
            print(f"最大ドローダウン: {metrics['max_drawdown']*100:.2f}%")

            all_results.append(metrics)

            # ファイル出力
            output_dir = Path(__file__).parent.parent / "data" / "results"
            output_dir.mkdir(parents=True, exist_ok=True)

            # 通貨ペア別ファイル
            symbol_safe = symbol.replace("/", "_")

            # trades.csv
            if trades:
                trades_df = trades_to_dataframe(trades)
                trades_csv = output_dir / f"trades_{symbol_safe}.csv"
                trades_df.to_csv(trades_csv, index=False)
                print(f"✅ トレード記録保存: {trades_csv.name}")

            # equity_curve.csv
            if not equity_df.empty:
                equity_csv = output_dir / f"equity_curve_{symbol_safe}.csv"
                equity_df.to_csv(equity_csv, index=False)
                print(f"✅ 資産曲線保存: {equity_csv.name}")

            # summary.json
            summary_json = output_dir / f"summary_{symbol_safe}.json"
            with open(summary_json, "w") as f:
                json.dump(metrics, f, indent=2)
            print(f"✅ サマリー保存: {summary_json.name}")

        except Exception as e:
            print(f"❌ {symbol} エラー: {e}")
            import traceback
            traceback.print_exc()

    # 全体サマリー
    if all_results:
        print(f"\n\n{'='*60}")
        print("【全通貨ペア比較】")
        print(f"{'='*60}")
        print(f"{'通貨ペア':<12} {'トレード':<8} {'勝率':<8} {'PF':<6} {'総損益':<12} {'R倍数':<8} {'最大DD':<8}")
        print("-" * 60)

        for r in all_results:
            print(f"{r['symbol']:<12} "
                  f"{r['total_trades']:<8} "
                  f"{r['win_rate']*100:>6.2f}% "
                  f"{r['profit_factor']:>6.2f} "
                  f"{r['total_pnl']:>10,.0f}円 "
                  f"{r['r_multiple']:>6.2f}R "
                  f"{r['max_drawdown']*100:>6.2f}%")

        # 合計
        total_trades = sum(r['total_trades'] for r in all_results)
        total_pnl = sum(r['total_pnl'] for r in all_results)
        print("-" * 60)
        print(f"{'合計':<12} {total_trades:<8} {'':<8} {'':<6} {total_pnl:>10,.0f}円")
        print()

        # 統合サマリー保存
        output_dir = Path(__file__).parent.parent / "data" / "results"
        all_summary_json = output_dir / "summary_all.json"
        with open(all_summary_json, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"✅ 統合サマリー保存: {all_summary_json}")

    else:
        print("\n❌ すべての通貨ペアでエラーが発生しました")
        sys.exit(1)


if __name__ == "__main__":
    main()
