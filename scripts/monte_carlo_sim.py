"""
モンテカルロシミュレーション: トレード結果のランダム並べ替えで破産確率を推定

Usage:
    python scripts/monte_carlo_sim.py --results data/results_v4/structure_tp2 --runs 1000
"""
import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple


def load_trades_from_csv(symbol_dir: Path) -> List[float]:
    """
    trades.csvから個別トレード結果（純損益）を読み込む
    """
    trades_csv = symbol_dir / "trades.csv"
    if not trades_csv.exists():
        return []

    df = pd.read_csv(trades_csv)

    # total_pnl_net_jpy列を取得
    if 'total_pnl_net_jpy' not in df.columns:
        print(f"  警告: {symbol_dir.name}/trades.csv に total_pnl_net_jpy列がありません")
        return []

    return df['total_pnl_net_jpy'].tolist()


def run_monte_carlo(
    trades_pnl: List[float],
    initial_equity: float,
    n_runs: int,
    ruin_threshold: float = 0.9
) -> Dict:
    """
    モンテカルロシミュレーション実行

    Args:
        trades_pnl: トレード損益リスト
        initial_equity: 初期資金
        n_runs: 試行回数
        ruin_threshold: 破産閾値（初期資金の何%未満で破産とするか）

    Returns:
        シミュレーション結果の統計
    """
    final_equities = []
    ruin_count = 0
    ruin_threshold_equity = initial_equity * ruin_threshold

    for _ in range(n_runs):
        # トレードをランダムに並べ替え
        shuffled_trades = np.random.permutation(trades_pnl)

        # 資産推移をシミュレート
        equity = initial_equity
        for pnl in shuffled_trades:
            equity += pnl

            # 破産チェック
            if equity < ruin_threshold_equity:
                ruin_count += 1
                break

        final_equities.append(equity)

    # 統計計算
    final_equities = np.array(final_equities)

    return {
        'n_runs': n_runs,
        'initial_equity': initial_equity,
        'ruin_threshold': ruin_threshold,
        'ruin_threshold_equity': ruin_threshold_equity,
        'ruin_count': ruin_count,
        'ruin_probability': ruin_count / n_runs,
        'mean_final_equity': float(np.mean(final_equities)),
        'median_final_equity': float(np.median(final_equities)),
        'std_final_equity': float(np.std(final_equities)),
        'min_final_equity': float(np.min(final_equities)),
        'max_final_equity': float(np.max(final_equities)),
        'percentile_5': float(np.percentile(final_equities, 5)),
        'percentile_25': float(np.percentile(final_equities, 25)),
        'percentile_75': float(np.percentile(final_equities, 75)),
        'percentile_95': float(np.percentile(final_equities, 95)),
    }


def main():
    parser = argparse.ArgumentParser(description="モンテカルロシミュレーション")
    parser.add_argument("--results", type=str, required=True, help="結果ディレクトリ")
    parser.add_argument("--runs", type=int, default=1000, help="試行回数")
    parser.add_argument("--initial-equity", type=float, default=100000.0, help="初期資金")
    parser.add_argument("--ruin-threshold", type=float, default=0.9, help="破産閾値（初期資金の%）")

    args = parser.parse_args()

    results_dir = Path(args.results)

    print(f"{'='*80}")
    print(f"モンテカルロシミュレーション")
    print(f"{'='*80}")
    print(f"結果ディレクトリ: {results_dir}")
    print(f"試行回数: {args.runs:,}")
    print(f"初期資金: {args.initial_equity:,.0f}円")
    print(f"破産閾値: {args.ruin_threshold*100:.0f}% (< {args.initial_equity * args.ruin_threshold:,.0f}円)")
    print()

    # 全通貨ペアのトレードを統合
    all_trades = []

    for symbol_dir in sorted(results_dir.iterdir()):
        if not symbol_dir.is_dir():
            continue

        trades_csv = symbol_dir / "trades.csv"
        if not trades_csv.exists():
            continue

        symbol = symbol_dir.name
        trades = load_trades_from_csv(symbol_dir)
        all_trades.extend(trades)

        print(f"  {symbol}: {len(trades)}トレード")

    print(f"\n総トレード数: {len(all_trades)}")

    # シミュレーション実行
    print(f"\nシミュレーション実行中...")
    np.random.seed(42)  # 再現性のため
    results = run_monte_carlo(
        all_trades,
        args.initial_equity,
        args.runs,
        args.ruin_threshold
    )

    # 結果表示
    print(f"\n{'='*80}")
    print(f"シミュレーション結果")
    print(f"{'='*80}")
    print(f"試行回数: {results['n_runs']:,}")
    print(f"破産回数: {results['ruin_count']:,}")
    print(f"破産確率: {results['ruin_probability']*100:.2f}%")
    print()
    print(f"最終資産統計:")
    print(f"  平均: {results['mean_final_equity']:,.0f}円")
    print(f"  中央値: {results['median_final_equity']:,.0f}円")
    print(f"  標準偏差: ±{results['std_final_equity']:,.0f}円")
    print(f"  最小: {results['min_final_equity']:,.0f}円")
    print(f"  最大: {results['max_final_equity']:,.0f}円")
    print()
    print(f"パーセンタイル:")
    print(f"  5%:  {results['percentile_5']:,.0f}円")
    print(f"  25%: {results['percentile_25']:,.0f}円")
    print(f"  75%: {results['percentile_75']:,.0f}円")
    print(f"  95%: {results['percentile_95']:,.0f}円")
    print()
    print(f"95%信頼区間: {results['percentile_5']:,.0f}円 ~ {results['percentile_95']:,.0f}円")
    print(f"{'='*80}")

    # 結果を保存
    output_path = results_dir / "monte_carlo_results.json"
    with open(output_path, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n結果を保存: {output_path}")


if __name__ == "__main__":
    main()
