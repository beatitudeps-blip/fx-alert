"""
V3システムのユニットテスト
- ポジションサイジング
- コスト計算
- Fill記録
- リスク遵守
"""
import pytest
from datetime import datetime
from src.trade_v3 import calculate_position_size, Trade, Fill
from src.costs import (
    calculate_execution_price,
    calculate_exit_price,
    calculate_fill_costs,
    calculate_pnl
)


def test_position_sizing_normal():
    """0.5%リスクでの正常なポジションサイジング"""
    equity = 100000.0
    entry = 150.0
    sl = 149.0
    risk_pct = 0.005

    units, risk_jpy = calculate_position_size(equity, entry, sl, risk_pct)

    # 想定最大損失 = equity * 0.005 = 500円
    # リスク/unit = |150 - 149| = 1.0
    # 理論units = 500 / 1.0 = 500
    # 0.1lot刻み = 1000で切り捨て → 0（最小1000未満でスキップ）
    # あれ、これだとunits=0になってしまう。ATRが小さすぎるケース。

    # より現実的なケース
    entry2 = 150.0
    sl2 = 148.5  # 1.5のリスク
    units2, risk_jpy2 = calculate_position_size(equity, entry2, sl2, risk_pct)

    # リスク/unit = 1.5
    # 理論units = 500 / 1.5 = 333.33
    # 0でスキップされる
    assert units2 == 0  # 1000未満なのでスキップ

    # さらに大きなリスク
    entry3 = 150.0
    sl3 = 147.5  # 2.5のリスク
    units3, risk_jpy3 = calculate_position_size(equity, entry3, sl3, risk_pct)

    # リスク/unit = 2.5
    # 理論units = 500 / 2.5 = 200
    # これも1000未満でスキップ
    assert units3 == 0

    # LOT刻みに合うケース
    entry4 = 150.0
    sl4 = 149.95  # 0.05のリスク（小さいリスク）
    units4, risk_jpy4 = calculate_position_size(equity, entry4, sl4, risk_pct)

    # リスク/unit = 0.05
    # 理論units = 500 / 0.05 = 10000
    # 1000刻みで切り捨て = 10000
    assert units4 == 10000.0
    # 実際のリスク = 10000 * 0.05 = 500
    assert risk_jpy4 == 500.0


def test_position_sizing_no_exceed_risk():
    """リスク超過しないこと"""
    equity = 100000.0
    entry = 150.0
    sl = 149.95
    risk_pct = 0.005
    max_risk = equity * risk_pct  # 500円

    units, risk_jpy = calculate_position_size(equity, entry, sl, risk_pct)

    # リスク超過しないこと
    assert risk_jpy <= max_risk * 1.001  # 丸め誤差許容


def test_position_sizing_min_lot():
    """最小ロット未満はスキップ"""
    equity = 100000.0
    entry = 150.0
    sl = 149.0  # 大きなリスク
    risk_pct = 0.005

    units, risk_jpy = calculate_position_size(equity, entry, sl, risk_pct)

    # 理論units = 500 / 1.0 = 500
    # 1000未満なのでスキップ
    assert units == 0.0
    assert risk_jpy == 0.0


def test_execution_price_long():
    """LONG実行価格計算"""
    mid = 150.0
    spread_pips = 0.2
    slippage_pips = 0.1

    exec_price = calculate_execution_price(mid, "LONG", spread_pips, slippage_pips)

    # LONG = ask + slippage
    # ask = mid + half_spread = 150.0 + 0.001 = 150.001
    # exec = ask + slip = 150.001 + 0.001 = 150.002
    expected = 150.0 + (0.2 * 0.01 / 2) + (0.1 * 0.01)
    assert abs(exec_price - expected) < 0.0001


def test_execution_price_short():
    """SHORT実行価格計算"""
    mid = 150.0
    spread_pips = 0.2
    slippage_pips = 0.1

    exec_price = calculate_execution_price(mid, "SHORT", spread_pips, slippage_pips)

    # SHORT = bid - slippage
    # bid = mid - half_spread = 150.0 - 0.001 = 149.999
    # exec = bid - slip = 149.999 - 0.001 = 149.998
    expected = 150.0 - (0.2 * 0.01 / 2) - (0.1 * 0.01)
    assert abs(exec_price - expected) < 0.0001


def test_pnl_calculation_long():
    """LONG損益計算"""
    entry = 150.0
    exit = 150.5
    units = 10000.0
    spread_cost = 20.0
    slip_cost = 10.0

    pnl_gross, pnl_net = calculate_pnl("LONG", entry, exit, units, spread_cost, slip_cost)

    # gross = (150.5 - 150.0) * 10000 = 5000
    assert abs(pnl_gross - 5000.0) < 0.01

    # net = gross - cost = 5000 - 30 = 4970
    assert abs(pnl_net - 4970.0) < 0.01


def test_pnl_calculation_short():
    """SHORT損益計算"""
    entry = 150.0
    exit = 149.5
    units = 10000.0
    spread_cost = 20.0
    slip_cost = 10.0

    pnl_gross, pnl_net = calculate_pnl("SHORT", entry, exit, units, spread_cost, slip_cost)

    # gross = (150.0 - 149.5) * 10000 = 5000
    assert abs(pnl_gross - 5000.0) < 0.01

    # net = gross - cost = 5000 - 30 = 4970
    assert abs(pnl_net - 4970.0) < 0.01


def test_trade_fill_accumulation():
    """Trade/Fill の損益累積"""
    trade = Trade(
        trade_id=1,
        symbol="USD/JPY",
        side="LONG",
        pattern="Test",
        entry_time=datetime(2024, 1, 1),
        entry_price_mid=150.0,
        entry_price_exec=150.001,
        units=10000.0,
        initial_sl_price_mid=149.0,
        initial_sl_price_exec=148.999,
        initial_r_per_unit_jpy=1.0,
        initial_risk_jpy=1000.0,
        tp1_price_mid=151.0,
        tp2_price_mid=152.0,
        tp1_units=5000.0,
        tp2_units=5000.0,
        atr=0.5
    )

    # TP1 Fill
    tp1_fill = Fill(
        trade_id=1,
        symbol="USD/JPY",
        side="LONG",
        fill_type="TP1",
        fill_time=datetime(2024, 1, 2),
        fill_price_mid=151.0,
        fill_price_exec=150.999,
        units=5000.0,
        spread_pips=0.2,
        slippage_pips=0.0,
        spread_cost_jpy=10.0,
        slippage_cost_jpy=0.0,
        pnl_gross_jpy=4990.0,  # (150.999 - 150.001) * 5000
        pnl_net_jpy=4980.0      # gross - cost
    )

    trade.add_fill(tp1_fill)

    assert abs(trade.total_pnl_gross_jpy - 4990.0) < 0.01
    assert abs(trade.total_pnl_net_jpy - 4980.0) < 0.01
    assert abs(trade.total_cost_jpy - 10.0) < 0.01
    assert trade.remaining_units == 5000.0  # 50%決済

    # TP2 Fill
    tp2_fill = Fill(
        trade_id=1,
        symbol="USD/JPY",
        side="LONG",
        fill_type="TP2",
        fill_time=datetime(2024, 1, 3),
        fill_price_mid=152.0,
        fill_price_exec=151.999,
        units=5000.0,
        spread_pips=0.2,
        slippage_pips=0.0,
        spread_cost_jpy=10.0,
        slippage_cost_jpy=0.0,
        pnl_gross_jpy=9990.0,  # (151.999 - 150.001) * 5000
        pnl_net_jpy=9980.0
    )

    trade.add_fill(tp2_fill)

    # 累積
    assert abs(trade.total_pnl_gross_jpy - (4990.0 + 9990.0)) < 0.01
    assert abs(trade.total_pnl_net_jpy - (4980.0 + 9980.0)) < 0.01
    assert abs(trade.total_cost_jpy - 20.0) < 0.01
    assert trade.remaining_units == 0.0


def test_initial_sl_preservation():
    """initial_slが上書きされないこと"""
    trade = Trade(
        trade_id=1,
        symbol="USD/JPY",
        side="LONG",
        pattern="Test",
        entry_time=datetime(2024, 1, 1),
        entry_price_mid=150.0,
        entry_price_exec=150.001,
        units=10000.0,
        initial_sl_price_mid=149.0,
        initial_sl_price_exec=148.999,
        initial_r_per_unit_jpy=1.0,
        initial_risk_jpy=1000.0,
        tp1_price_mid=151.0,
        tp2_price_mid=152.0,
        tp1_units=5000.0,
        tp2_units=5000.0,
        atr=0.5
    )

    # 初期SL
    assert trade.initial_sl_price_exec == 148.999
    assert trade.current_sl == 148.999

    # BEに移動
    trade.move_sl_to_be()

    # current_slはBEに移動
    assert trade.current_sl == 150.001

    # initial_slは保持
    assert trade.initial_sl_price_exec == 148.999
