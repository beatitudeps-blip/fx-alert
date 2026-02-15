"""
検証モジュール
- OOS分割
- Walk-forward
- 感度分析
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple
from pathlib import Path
import json

from .backtest_v3 import run_backtest_v3
from .metrics_v3 import calculate_metrics_v3


def split_oos(
    start_date: str,
    end_date: str,
    oos_ratio: float = 0.2
) -> Tuple[Tuple[str, str], Tuple[str, str]]:
    """
    期間をIS/OOSに分割

    Args:
        start_date: 開始日
        end_date: 終了日
        oos_ratio: OOS比率（デフォルト0.2 = 20%）

    Returns:
        ((is_start, is_end), (oos_start, oos_end))
    """
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)
    total_days = (end_dt - start_dt).days

    is_days = int(total_days * (1 - oos_ratio))
    is_end_dt = start_dt + timedelta(days=is_days)
    oos_start_dt = is_end_dt + timedelta(days=1)

    is_period = (start_date, is_end_dt.strftime("%Y-%m-%d"))
    oos_period = (oos_start_dt.strftime("%Y-%m-%d"), end_date)

    return is_period, oos_period


def run_oos_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    oos_ratio: float = 0.2,
    output_dir: Path = None,
    **backtest_kwargs
) -> Dict:
    """
    OOS分割バックテストを実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        oos_ratio: OOS比率
        output_dir: 出力ディレクトリ
        **backtest_kwargs: run_backtest_v3のパラメータ

    Returns:
        比較結果辞書
    """
    # 期間分割
    is_period, oos_period = split_oos(start_date, end_date, oos_ratio)

    print(f"IS期間: {is_period[0]} ~ {is_period[1]}")
    print(f"OOS期間: {oos_period[0]} ~ {oos_period[1]}")

    # ISバックテスト
    print("\n[IS] バックテスト実行中...")
    is_trades, is_equity = run_backtest_v3(
        symbol, is_period[0], is_period[1], **backtest_kwargs
    )
    is_metrics = calculate_metrics_v3(
        is_trades,
        backtest_kwargs.get("initial_equity", 100000.0),
        is_period[0],
        is_period[1]
    )

    # OOSバックテスト
    print("\n[OOS] バックテスト実行中...")
    oos_trades, oos_equity = run_backtest_v3(
        symbol, oos_period[0], oos_period[1], **backtest_kwargs
    )
    oos_metrics = calculate_metrics_v3(
        oos_trades,
        backtest_kwargs.get("initial_equity", 100000.0),
        oos_period[0],
        oos_period[1]
    )

    # 比較
    compare = {
        "is": {
            "period": is_period,
            "trades": is_metrics["total_trades"],
            "pf_net": is_metrics["pf_net"],
            "win_rate": is_metrics["win_rate"],
            "total_pnl_net": is_metrics["total_pnl_net"],
            "max_dd": is_metrics["max_drawdown_close_based"],
            "expectancy_net": is_metrics["expectancy_net"],
            "total_cost": is_metrics["total_cost"]
        },
        "oos": {
            "period": oos_period,
            "trades": oos_metrics["total_trades"],
            "pf_net": oos_metrics["pf_net"],
            "win_rate": oos_metrics["win_rate"],
            "total_pnl_net": oos_metrics["total_pnl_net"],
            "max_dd": oos_metrics["max_drawdown_close_based"],
            "expectancy_net": oos_metrics["expectancy_net"],
            "total_cost": oos_metrics["total_cost"]
        }
    }

    # ファイル出力
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)

        # IS
        is_dir = output_dir / "is"
        is_dir.mkdir(exist_ok=True)
        with open(is_dir / "summary.json", "w") as f:
            json.dump(is_metrics, f, indent=2, default=str)

        # OOS
        oos_dir = output_dir / "oos"
        oos_dir.mkdir(exist_ok=True)
        with open(oos_dir / "summary.json", "w") as f:
            json.dump(oos_metrics, f, indent=2, default=str)

        # 比較
        with open(output_dir / "compare.json", "w") as f:
            json.dump(compare, f, indent=2)

        print(f"\n✅ OOS結果保存: {output_dir}")

    return compare


def run_walkforward(
    symbol: str,
    start_date: str,
    end_date: str,
    train_days: int = 720,
    test_days: int = 180,
    step_days: int = 180,
    output_dir: Path = None,
    **backtest_kwargs
) -> pd.DataFrame:
    """
    Walk-forward検証を実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        train_days: 学習期間（日）※使用しない（参考値）
        test_days: テスト期間（日）
        step_days: ステップ（日）
        output_dir: 出力ディレクトリ
        **backtest_kwargs: run_backtest_v3のパラメータ

    Returns:
        folds DataFrame
    """
    start_dt = datetime.fromisoformat(start_date)
    end_dt = datetime.fromisoformat(end_date)

    folds = []
    fold_id = 1
    current_start = start_dt

    while True:
        test_start = current_start + timedelta(days=train_days)
        test_end = test_start + timedelta(days=test_days)

        if test_end > end_dt:
            break

        print(f"\n[Fold {fold_id}] Test: {test_start.date()} ~ {test_end.date()}")

        # テスト期間でバックテスト
        trades, equity = run_backtest_v3(
            symbol,
            test_start.strftime("%Y-%m-%d"),
            test_end.strftime("%Y-%m-%d"),
            **backtest_kwargs
        )

        metrics = calculate_metrics_v3(
            trades,
            backtest_kwargs.get("initial_equity", 100000.0),
            test_start.strftime("%Y-%m-%d"),
            test_end.strftime("%Y-%m-%d")
        )

        folds.append({
            "fold_id": fold_id,
            "train_start": start_dt.strftime("%Y-%m-%d"),
            "train_end": test_start.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
            "trades": metrics["total_trades"],
            "pf_net": metrics["pf_net"],
            "win_rate": metrics["win_rate"],
            "pnl_net": metrics["total_pnl_net"],
            "max_dd": metrics["max_drawdown_close_based"],
            "expectancy_net": metrics["expectancy_net"],
            "cost_total": metrics["total_cost"]
        })

        # 次のfold
        current_start += timedelta(days=step_days)
        fold_id += 1

    folds_df = pd.DataFrame(folds)

    # サマリー統計
    summary = {
        "total_folds": len(folds),
        "avg_pf_net": folds_df["pf_net"].mean() if len(folds) > 0 else 0.0,
        "median_pf_net": folds_df["pf_net"].median() if len(folds) > 0 else 0.0,
        "worst_pf_net": folds_df["pf_net"].min() if len(folds) > 0 else 0.0,
        "avg_win_rate": folds_df["win_rate"].mean() if len(folds) > 0 else 0.0,
        "avg_pnl_net": folds_df["pnl_net"].mean() if len(folds) > 0 else 0.0,
        "total_trades": folds_df["trades"].sum() if len(folds) > 0 else 0
    }

    # ファイル出力
    if output_dir:
        wf_dir = output_dir / "walkforward"
        wf_dir.mkdir(parents=True, exist_ok=True)

        folds_df.to_csv(wf_dir / "folds.csv", index=False)
        with open(wf_dir / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)

        print(f"\n✅ Walk-forward結果保存: {wf_dir}")

    return folds_df


def run_sensitivity_analysis(
    symbol: str,
    start_date: str,
    end_date: str,
    output_dir: Path = None,
    **base_kwargs
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    感度分析を実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        output_dir: 出力ディレクトリ
        **base_kwargs: 基本パラメータ

    Returns:
        (cost_grid_df, param_grid_df)
    """
    # 1) コスト感度
    print("\n=== コスト感度分析 ===")
    cost_grid = []
    spread_multipliers = [0.0, 1.0, 1.5, 2.0]
    slippages = [0.0, 0.002, 0.005, 0.01]

    for spread_mult in spread_multipliers:
        for slip in slippages:
            print(f"  spread_mult={spread_mult}, slippage={slip}...")

            kwargs = base_kwargs.copy()
            kwargs["spread_multiplier"] = spread_mult
            kwargs["slippage_pips"] = slip / 0.01  # pips変換

            trades, _ = run_backtest_v3(symbol, start_date, end_date, **kwargs)
            metrics = calculate_metrics_v3(
                trades, kwargs.get("initial_equity", 100000.0), start_date, end_date
            )

            cost_grid.append({
                "spread_multiplier": spread_mult,
                "slippage_pips": slip / 0.01,
                "trades": metrics["total_trades"],
                "pf_net": metrics["pf_net"],
                "win_rate": metrics["win_rate"],
                "pnl_net": metrics["total_pnl_net"],
                "max_dd": metrics["max_drawdown_close_based"],
                "expectancy_net": metrics["expectancy_net"],
                "cost_total": metrics["total_cost"]
            })

    cost_grid_df = pd.DataFrame(cost_grid)

    # 2) パラメータ感度（簡易版）
    print("\n=== パラメータ感度分析 ===")
    param_grid = []
    atr_mults = [1.2, 1.5, 2.0]
    tp1_rs = [0.8, 1.0, 1.2]

    for atr_mult in atr_mults:
        for tp1_r in tp1_rs:
            print(f"  atr_mult={atr_mult}, tp1_r={tp1_r}...")

            kwargs = base_kwargs.copy()
            kwargs["atr_multiplier"] = atr_mult
            kwargs["tp1_r"] = tp1_r

            trades, _ = run_backtest_v3(symbol, start_date, end_date, **kwargs)
            metrics = calculate_metrics_v3(
                trades, kwargs.get("initial_equity", 100000.0), start_date, end_date
            )

            param_grid.append({
                "atr_multiplier": atr_mult,
                "tp1_r": tp1_r,
                "trades": metrics["total_trades"],
                "pf_net": metrics["pf_net"],
                "win_rate": metrics["win_rate"],
                "pnl_net": metrics["total_pnl_net"],
                "max_dd": metrics["max_drawdown_close_based"],
                "expectancy_net": metrics["expectancy_net"],
                "cost_total": metrics["total_cost"]
            })

    param_grid_df = pd.DataFrame(param_grid)

    # ファイル出力
    if output_dir:
        sens_dir = output_dir / "sensitivity"
        sens_dir.mkdir(parents=True, exist_ok=True)

        cost_grid_df.to_csv(sens_dir / "cost_grid.csv", index=False)
        param_grid_df.to_csv(sens_dir / "param_grid.csv", index=False)

        print(f"\n✅ 感度分析結果保存: {sens_dir}")

    return cost_grid_df, param_grid_df
