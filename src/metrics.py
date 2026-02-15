"""パフォーマンス指標計算"""
import pandas as pd
from typing import List
from .backtest import Trade


def calculate_metrics(trades: List[Trade], initial_balance: float = 100000.0) -> dict:
    """
    バックテスト結果から各種指標を計算

    Args:
        trades: トレードリスト
        initial_balance: 初期資金

    Returns:
        メトリクス辞書
    """
    if not trades:
        return {
            "total_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_drawdown": 0.0,
            "r_multiple": 0.0
        }

    # 決済済みトレードのみ
    closed_trades = [t for t in trades if t.exit_time is not None]
    if not closed_trades:
        return {
            "total_trades": len(trades),
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "total_pnl": 0.0,
            "total_pnl_pct": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_drawdown": 0.0,
            "r_multiple": 0.0
        }

    # PnL計算
    pnls = [t.pnl for t in closed_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    win_rate = len(wins) / len(closed_trades) if closed_trades else 0.0

    # Profit Factor
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0.0)

    # 平均勝ち/負け
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0

    # R倍数（平均）- 初期リスク（ATR × multiplier）を使用
    # SLはBEに移動される可能性があるため、ATRから計算
    r_multiples = []
    for t in closed_trades:
        # 初期リスク = ATR × 1.5 (atr_multiplier)
        atr_multiplier = 1.5
        lot_size = 10000
        initial_risk_jpy = t.atr * atr_multiplier * lot_size
        if initial_risk_jpy > 0:
            r_multiples.append(t.pnl / initial_risk_jpy)
    avg_r_multiple = sum(r_multiples) / len(r_multiples) if r_multiples else 0.0

    # 最大ドローダウン
    balance = initial_balance
    peak = initial_balance
    max_dd = 0.0
    for p in pnls:
        balance += p
        if balance > peak:
            peak = balance
        dd = (peak - balance) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    return {
        "total_trades": len(closed_trades),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "total_pnl": total_pnl,
        "total_pnl_pct": (total_pnl / initial_balance) * 100,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": max_dd,
        "r_multiple": avg_r_multiple
    }


def trades_to_dataframe(trades: List[Trade]) -> pd.DataFrame:
    """
    トレードリストをDataFrameに変換

    Args:
        trades: トレードリスト

    Returns:
        トレードDataFrame
    """
    records = []
    for t in trades:
        records.append({
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "direction": t.direction,
            "pattern": t.pattern,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "sl": t.sl,
            "tp1": t.tp1,
            "tp2": t.tp2,
            "exit_reason": t.exit_reason,
            "pnl": t.pnl,
            "atr": t.atr
        })
    return pd.DataFrame(records)
