"""
V3 パフォーマンス指標計算
- gross/net分離
- ペア別/方向別/退出理由別メトリクス
- 月次損益
- リスク遵守チェック
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from collections import defaultdict
from .trade_v3 import Trade, Fill


def trades_to_dataframe(trades: List[Trade]) -> pd.DataFrame:
    """トレードリストをDataFrameに変換"""
    records = []
    for t in trades:
        records.append({
            "trade_id": t.trade_id,
            "symbol": t.symbol,
            "side": t.side,
            "pattern": t.pattern,
            "entry_time": t.entry_time,
            "entry_price_mid": t.entry_price_mid,
            "entry_price_exec": t.entry_price_exec,
            "units": t.units,
            "initial_sl_price_mid": t.initial_sl_price_mid,
            "initial_sl_price_exec": t.initial_sl_price_exec,
            "initial_risk_jpy": t.initial_risk_jpy,
            "tp1_price_mid": t.tp1_price_mid,
            "tp2_price_mid": t.tp2_price_mid,
            "final_exit_time": t.final_exit_time,
            "final_exit_reason": t.final_exit_reason,
            "total_pnl_gross_jpy": t.total_pnl_gross_jpy,
            "total_pnl_net_jpy": t.total_pnl_net_jpy,
            "total_cost_jpy": t.total_cost_jpy,
            "holding_hours": t.holding_hours,
            "fills_count": len(t.fills)
        })
    return pd.DataFrame(records)


def fills_to_dataframe(trades: List[Trade]) -> pd.DataFrame:
    """全Fillsを展開してDataFrameに変換"""
    records = []
    for trade in trades:
        for fill in trade.fills:
            records.append({
                "trade_id": fill.trade_id,
                "symbol": fill.symbol,
                "side": fill.side,
                "fill_type": fill.fill_type,
                "fill_time": fill.fill_time,
                "fill_price_mid": fill.fill_price_mid,
                "fill_price_exec": fill.fill_price_exec,
                "units": fill.units,
                "spread_pips": fill.spread_pips,
                "slippage_pips": fill.slippage_pips,
                "spread_cost_jpy": fill.spread_cost_jpy,
                "slippage_cost_jpy": fill.slippage_cost_jpy,
                "swap_jpy": fill.swap_jpy,
                "pnl_gross_jpy": fill.pnl_gross_jpy,
                "pnl_net_jpy": fill.pnl_net_jpy
            })
    return pd.DataFrame(records)


def calculate_metrics_v3(
    trades: List[Trade],
    initial_equity: float,
    start_date: str,
    end_date: str
) -> Dict:
    """
    V3メトリクス計算

    Returns:
        拡張メトリクス辞書
    """
    if not trades:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "initial_equity": initial_equity,
            "final_equity": initial_equity,
            "total_trades": 0,
            "total_pnl_gross": 0.0,
            "total_pnl_net": 0.0,
            "total_cost": 0.0
        }

    # 決済済みトレード
    closed_trades = [t for t in trades if t.final_exit_time is not None]

    if not closed_trades:
        return {
            "start_date": start_date,
            "end_date": end_date,
            "initial_equity": initial_equity,
            "final_equity": initial_equity,
            "total_trades": len(trades),
            "closed_trades": 0
        }

    # 基本集計
    total_pnl_gross = sum(t.total_pnl_gross_jpy for t in closed_trades)
    total_pnl_net = sum(t.total_pnl_net_jpy for t in closed_trades)
    total_cost = sum(t.total_cost_jpy for t in closed_trades)
    final_equity = initial_equity + total_pnl_net

    # 勝敗
    wins_gross = [t.total_pnl_gross_jpy for t in closed_trades if t.total_pnl_gross_jpy > 0]
    losses_gross = [t.total_pnl_gross_jpy for t in closed_trades if t.total_pnl_gross_jpy < 0]
    wins_net = [t.total_pnl_net_jpy for t in closed_trades if t.total_pnl_net_jpy > 0]
    losses_net = [t.total_pnl_net_jpy for t in closed_trades if t.total_pnl_net_jpy < 0]

    # Profit Factor
    gross_profit_gross = sum(wins_gross) if wins_gross else 0.0
    gross_loss_gross = abs(sum(losses_gross)) if losses_gross else 0.0
    pf_gross = gross_profit_gross / gross_loss_gross if gross_loss_gross > 0 else (np.inf if gross_profit_gross > 0 else 0.0)

    gross_profit_net = sum(wins_net) if wins_net else 0.0
    gross_loss_net = abs(sum(losses_net)) if losses_net else 0.0
    pf_net = gross_profit_net / gross_loss_net if gross_loss_net > 0 else (np.inf if gross_profit_net > 0 else 0.0)

    # 勝率
    win_rate = len(wins_net) / len(closed_trades) if closed_trades else 0.0

    # 平均勝ち/負け
    avg_win_net = sum(wins_net) / len(wins_net) if wins_net else 0.0
    avg_loss_net = sum(losses_net) / len(losses_net) if losses_net else 0.0

    # 期待値
    expectancy_net = (win_rate * avg_win_net) + ((1 - win_rate) * avg_loss_net)

    # R倍数
    r_multiples = []
    for t in closed_trades:
        if t.initial_risk_jpy > 0:
            r_multiples.append(t.total_pnl_net_jpy / t.initial_risk_jpy)
    avg_r_multiple = np.mean(r_multiples) if r_multiples else 0.0

    # 最大ドローダウン（クローズベース）
    equity_curve = [initial_equity]
    for t in closed_trades:
        equity_curve.append(equity_curve[-1] + t.total_pnl_net_jpy)

    peak = initial_equity
    max_dd = 0.0
    for eq in equity_curve:
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd = dd

    # ペア別メトリクス
    per_symbol = {}
    for symbol in set(t.symbol for t in closed_trades):
        symbol_trades = [t for t in closed_trades if t.symbol == symbol]
        per_symbol[symbol] = _calculate_subset_metrics(symbol_trades)

    # 方向別メトリクス
    per_side = {}
    for side in ["LONG", "SHORT"]:
        side_trades = [t for t in closed_trades if t.side == side]
        if side_trades:
            per_side[side] = _calculate_subset_metrics(side_trades)

    # 退出理由別メトリクス
    per_exit_reason = {}
    for reason in set(t.final_exit_reason for t in closed_trades if t.final_exit_reason):
        reason_trades = [t for t in closed_trades if t.final_exit_reason == reason]
        per_exit_reason[reason] = _calculate_subset_metrics(reason_trades)

    # リスク遵守チェック
    risk_violations = []
    for t in closed_trades:
        if t.initial_risk_jpy > 0:
            max_allowed_risk = initial_equity * 0.005 * 1.01  # 1%マージン
            if t.initial_risk_jpy > max_allowed_risk:
                excess_pct = (t.initial_risk_jpy / (initial_equity * 0.005) - 1.0) * 100
                risk_violations.append({
                    "trade_id": t.trade_id,
                    "risk_jpy": t.initial_risk_jpy,
                    "max_allowed": max_allowed_risk,
                    "excess_pct": excess_pct
                })

    # 月次損益
    monthly_returns = _calculate_monthly_returns(closed_trades, initial_equity)

    return {
        "start_date": start_date,
        "end_date": end_date,
        "initial_equity": initial_equity,
        "final_equity": final_equity,
        "total_trades": len(closed_trades),
        "wins": len(wins_net),
        "losses": len(losses_net),
        "win_rate": win_rate,
        "total_pnl_gross": total_pnl_gross,
        "total_pnl_net": total_pnl_net,
        "total_cost": total_cost,
        "pf_gross": pf_gross,
        "pf_net": pf_net,
        "avg_win_net": avg_win_net,
        "avg_loss_net": avg_loss_net,
        "expectancy_net": expectancy_net,
        "avg_r_multiple": avg_r_multiple,
        "max_drawdown_close_based": max_dd,
        "per_symbol": per_symbol,
        "per_side": per_side,
        "per_exit_reason": per_exit_reason,
        "risk_violations_count": len(risk_violations),
        "risk_violations": risk_violations,
        "monthly_returns": monthly_returns
    }


def _calculate_subset_metrics(trades: List[Trade]) -> Dict:
    """サブセット（ペア別/方向別/理由別）のメトリクス計算"""
    if not trades:
        return {}

    pnls_net = [t.total_pnl_net_jpy for t in trades]
    wins = [p for p in pnls_net if p > 0]
    losses = [p for p in pnls_net if p < 0]

    return {
        "count": len(trades),
        "total_pnl_net": sum(pnls_net),
        "win_rate": len(wins) / len(trades) if trades else 0.0,
        "avg_pnl_net": np.mean(pnls_net) if pnls_net else 0.0,
        "avg_win": np.mean(wins) if wins else 0.0,
        "avg_loss": np.mean(losses) if losses else 0.0
    }


def _calculate_monthly_returns(trades: List[Trade], initial_equity: float) -> List[Dict]:
    """月次損益を計算"""
    if not trades:
        return []

    # 月別にグループ化
    monthly = defaultdict(list)
    for t in trades:
        if t.final_exit_time:
            month_key = t.final_exit_time.strftime("%Y-%m")
            monthly[month_key].append(t.total_pnl_net_jpy)

    results = []
    equity = initial_equity
    for month in sorted(monthly.keys()):
        pnls = monthly[month]
        month_pnl = sum(pnls)
        equity += month_pnl
        results.append({
            "month": month,
            "trades": len(pnls),
            "pnl_net": month_pnl,
            "equity": equity,
            "return_pct": (month_pnl / initial_equity) * 100
        })

    return results
