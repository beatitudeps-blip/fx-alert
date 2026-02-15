"""
コスト計算モジュール
spread / slippage / swap を分解して計算
"""
from datetime import datetime
from .spread_minnafx import get_spread_pips


def calculate_execution_price(
    mid_price: float,
    side: str,
    spread_pips: float,
    slippage_pips: float = 0.0
) -> float:
    """
    実行価格を計算（bid/ask + slippage）

    Args:
        mid_price: 中値価格
        side: "LONG" or "SHORT"
        spread_pips: スプレッド（pips）
        slippage_pips: スリッページ（pips）

    Returns:
        実行価格
    """
    half_spread = spread_pips * 0.01 / 2
    slip = slippage_pips * 0.01

    if side == "LONG":
        # LONGは買い = ask価格 + slippage
        return mid_price + half_spread + slip
    else:  # SHORT
        # SHORTは売り = bid価格 - slippage
        return mid_price - half_spread - slip


def calculate_exit_price(
    mid_price: float,
    side: str,
    spread_pips: float,
    slippage_pips: float = 0.0
) -> float:
    """
    決済価格を計算（bid/ask + slippage）

    Args:
        mid_price: 中値価格
        side: "LONG" or "SHORT"（エントリー時の方向）
        spread_pips: スプレッド（pips）
        slippage_pips: スリッページ（pips）

    Returns:
        決済価格
    """
    half_spread = spread_pips * 0.01 / 2
    slip = slippage_pips * 0.01

    if side == "LONG":
        # LONGの決済は売り = bid価格 - slippage
        return mid_price - half_spread - slip
    else:  # SHORT
        # SHORTの決済は買い = ask価格 + slippage
        return mid_price + half_spread + slip


def calculate_fill_costs(
    symbol: str,
    fill_time: datetime,
    mid_price: float,
    exec_price: float,
    units: float,
    spread_multiplier: float = 1.0,
    slippage_pips: float = 0.0,
    swap_jpy_per_lot: float = 0.0
) -> tuple[float, float, float, float, float]:
    """
    約定コストを計算

    Args:
        symbol: 通貨ペア
        fill_time: 約定時刻（UTC）
        mid_price: 中値価格
        exec_price: 実行価格
        units: 数量
        spread_multiplier: スプレッド倍率（感度分析用）
        slippage_pips: スリッページ（pips）
        swap_jpy_per_lot: スワップ（JPY/lot、正=受取、負=支払）

    Returns:
        (spread_pips, slippage_pips, spread_cost_jpy, slippage_cost_jpy, swap_jpy)
    """
    # スプレッド
    base_spread_pips = get_spread_pips(symbol, fill_time)
    spread_pips = base_spread_pips * spread_multiplier

    # スプレッドコスト（JPY）
    spread_cost_jpy = spread_pips * 0.01 * units

    # スリッページコスト（JPY）
    slippage_cost_jpy = slippage_pips * 0.01 * units

    # スワップ（lot単位で計算）
    lots = units / 10000.0
    swap_jpy = swap_jpy_per_lot * lots

    return spread_pips, slippage_pips, spread_cost_jpy, slippage_cost_jpy, swap_jpy


def calculate_pnl(
    side: str,
    entry_price: float,
    exit_price: float,
    units: float,
    spread_cost_jpy: float = 0.0,
    slippage_cost_jpy: float = 0.0,
    swap_jpy: float = 0.0
) -> tuple[float, float]:
    """
    損益を計算（gross/net）

    Args:
        side: "LONG" or "SHORT"
        entry_price: エントリー実行価格
        exit_price: 決済実行価格
        units: 数量
        spread_cost_jpy: スプレッドコスト（JPY）
        slippage_cost_jpy: スリッページコスト（JPY）
        swap_jpy: スワップ（JPY）

    Returns:
        (pnl_gross_jpy, pnl_net_jpy)
    """
    if side == "LONG":
        pnl_gross = (exit_price - entry_price) * units
    else:  # SHORT
        pnl_gross = (entry_price - exit_price) * units

    # net = gross - コスト + スワップ
    total_cost = spread_cost_jpy + slippage_cost_jpy
    pnl_net = pnl_gross - total_cost + swap_jpy

    return pnl_gross, pnl_net
