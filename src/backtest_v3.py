"""
V3 バックテストエンジン
- 監査可能なfills.csv生成
- 0.5%動的サイジング
- コスト分解（spread/slippage/swap）
- OOS/Walk-forward対応
"""
import pandas as pd
from typing import List, Tuple, Optional
from datetime import datetime, timedelta

from .data import fetch_data
from .strategy import check_signal
from .spread_minnafx import add_bid_ask, get_spread_pips
from .trade_v3 import Trade, Fill, calculate_position_size
from .costs import (
    calculate_execution_price,
    calculate_exit_price,
    calculate_fill_costs,
    calculate_pnl
)


def run_backtest_v3(
    symbol: str,
    start_date: str,
    end_date: str,
    api_key: Optional[str] = None,
    initial_equity: float = 100000.0,
    risk_pct: float = 0.005,
    atr_multiplier: float = 1.5,
    tp1_r: float = 1.0,
    tp2_r: float = 2.0,
    tp1_close_pct: float = 0.5,
    spread_multiplier: float = 1.0,
    slippage_pips: float = 0.0,
    swap_jpy_per_lot: float = 0.0,
    use_cache: bool = True,
    sl_priority: bool = True  # 同一バーでSL/TP両方成立時、SL優先
) -> Tuple[List[Trade], pd.DataFrame]:
    """
    V3バックテスト実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        api_key: APIキー
        initial_equity: 初期資金（JPY）
        risk_pct: リスク率（デフォルト0.005 = 0.5%）
        atr_multiplier: ATR倍率（SL距離）
        tp1_r: TP1のR倍数
        tp2_r: TP2のR倍数
        tp1_close_pct: TP1で決済する割合（0.5 = 50%）
        spread_multiplier: スプレッド倍率（感度分析用）
        slippage_pips: スリッページ（pips）
        swap_jpy_per_lot: スワップ（JPY/lot/日）
        use_cache: キャッシュ使用
        sl_priority: SL優先（保守的）

    Returns:
        (trades, equity_df)
    """
    # データ取得
    h4 = fetch_data(symbol, "4h", 5000, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 1000, api_key, use_cache)

    # 日付フィルタリング
    h4 = h4[(h4["datetime"] >= start_date) & (h4["datetime"] <= end_date)].reset_index(drop=True)
    d1 = d1[(d1["datetime"] >= start_date) & (d1["datetime"] <= end_date)].reset_index(drop=True)

    # bid/ask追加（スプレッド計算用）
    h4 = add_bid_ask(h4, symbol)

    trades: List[Trade] = []
    active_trade: Optional[Trade] = None
    equity = initial_equity
    equity_curve = [{"datetime": h4.iloc[0]["datetime"], "equity": equity}]
    trade_id_counter = 1

    for i in range(len(h4)):
        current_bar = h4.iloc[i]
        current_time = current_bar["datetime"]

        # アクティブトレードの決済チェック
        if active_trade is not None:
            direction = active_trade.side
            current_sl = active_trade.current_sl
            tp1 = active_trade.tp1_price_mid
            tp2 = active_trade.tp2_price_mid

            # SL/TP判定用のmid価格
            bar_high_mid = current_bar["high"]
            bar_low_mid = current_bar["low"]

            sl_hit = False
            tp1_hit = False
            tp2_hit = False

            # SL判定
            if direction == "LONG":
                sl_hit = bar_low_mid <= current_sl
            else:  # SHORT
                sl_hit = bar_high_mid >= current_sl

            # TP1判定（まだヒットしていない場合）
            if not active_trade.tp1_hit:
                if direction == "LONG":
                    tp1_hit = bar_high_mid >= tp1
                else:
                    tp1_hit = bar_low_mid <= tp1

            # TP2判定（TP1ヒット済みの場合）
            if active_trade.tp1_hit:
                if direction == "LONG":
                    tp2_hit = bar_high_mid >= tp2
                else:
                    tp2_hit = bar_low_mid <= tp2

            # 決済処理（SL優先）
            if sl_hit and sl_priority:
                # SL決済
                exit_reason = "SL" if not active_trade.tp1_hit else "BE"
                exit_price_mid = current_sl
                exit_units = active_trade.remaining_units

                # スプレッド取得
                spread_pips_exit = get_spread_pips(symbol, current_time) * spread_multiplier

                # 実行価格計算
                exit_price_exec = calculate_exit_price(
                    exit_price_mid, direction, spread_pips_exit, slippage_pips
                )

                # コスト計算
                _, _, spread_cost, slip_cost, swap = calculate_fill_costs(
                    symbol, current_time, exit_price_mid, exit_price_exec,
                    exit_units, spread_multiplier, slippage_pips, swap_jpy_per_lot
                )

                # PnL計算
                pnl_gross, pnl_net = calculate_pnl(
                    direction, active_trade.entry_price_exec, exit_price_exec,
                    exit_units, spread_cost, slip_cost, swap
                )

                # Fill記録
                fill = Fill(
                    trade_id=active_trade.trade_id,
                    symbol=symbol,
                    side=direction,
                    fill_type=exit_reason,
                    fill_time=current_time,
                    fill_price_mid=exit_price_mid,
                    fill_price_exec=exit_price_exec,
                    units=exit_units,
                    spread_pips=spread_pips_exit,
                    slippage_pips=slippage_pips,
                    spread_cost_jpy=spread_cost,
                    slippage_cost_jpy=slip_cost,
                    swap_jpy=swap,
                    pnl_gross_jpy=pnl_gross,
                    pnl_net_jpy=pnl_net
                )

                active_trade.add_fill(fill)
                active_trade.close(current_time, exit_reason)
                equity += pnl_net
                equity_curve.append({"datetime": current_time, "equity": equity})
                active_trade = None
                continue

            # TP1判定
            if tp1_hit and not active_trade.tp1_hit:
                active_trade.tp1_hit = True
                exit_price_mid = tp1
                exit_units = active_trade.tp1_units

                # スプレッド取得
                spread_pips_exit = get_spread_pips(symbol, current_time) * spread_multiplier

                # 実行価格計算
                exit_price_exec = calculate_exit_price(
                    exit_price_mid, direction, spread_pips_exit, slippage_pips
                )

                # コスト計算
                _, _, spread_cost, slip_cost, swap = calculate_fill_costs(
                    symbol, current_time, exit_price_mid, exit_price_exec,
                    exit_units, spread_multiplier, slippage_pips, swap_jpy_per_lot
                )

                # PnL計算
                pnl_gross, pnl_net = calculate_pnl(
                    direction, active_trade.entry_price_exec, exit_price_exec,
                    exit_units, spread_cost, slip_cost, swap
                )

                # Fill記録
                fill = Fill(
                    trade_id=active_trade.trade_id,
                    symbol=symbol,
                    side=direction,
                    fill_type="TP1",
                    fill_time=current_time,
                    fill_price_mid=exit_price_mid,
                    fill_price_exec=exit_price_exec,
                    units=exit_units,
                    spread_pips=spread_pips_exit,
                    slippage_pips=slippage_pips,
                    spread_cost_jpy=spread_cost,
                    slippage_cost_jpy=slip_cost,
                    swap_jpy=swap,
                    pnl_gross_jpy=pnl_gross,
                    pnl_net_jpy=pnl_net
                )

                active_trade.add_fill(fill)
                equity += pnl_net
                equity_curve.append({"datetime": current_time, "equity": equity})

                # SLをBEに移動
                active_trade.move_sl_to_be()

            # TP2判定
            if tp2_hit and active_trade.tp1_hit:
                exit_price_mid = tp2
                exit_units = active_trade.remaining_units

                # スプレッド取得
                spread_pips_exit = get_spread_pips(symbol, current_time) * spread_multiplier

                # 実行価格計算
                exit_price_exec = calculate_exit_price(
                    exit_price_mid, direction, spread_pips_exit, slippage_pips
                )

                # コスト計算
                _, _, spread_cost, slip_cost, swap = calculate_fill_costs(
                    symbol, current_time, exit_price_mid, exit_price_exec,
                    exit_units, spread_multiplier, slippage_pips, swap_jpy_per_lot
                )

                # PnL計算
                pnl_gross, pnl_net = calculate_pnl(
                    direction, active_trade.entry_price_exec, exit_price_exec,
                    exit_units, spread_cost, slip_cost, swap
                )

                # Fill記録
                fill = Fill(
                    trade_id=active_trade.trade_id,
                    symbol=symbol,
                    side=direction,
                    fill_type="TP2",
                    fill_time=current_time,
                    fill_price_mid=exit_price_mid,
                    fill_price_exec=exit_price_exec,
                    units=exit_units,
                    spread_pips=spread_pips_exit,
                    slippage_pips=slippage_pips,
                    spread_cost_jpy=spread_cost,
                    slippage_cost_jpy=slip_cost,
                    swap_jpy=swap,
                    pnl_gross_jpy=pnl_gross,
                    pnl_net_jpy=pnl_net
                )

                active_trade.add_fill(fill)
                active_trade.close(current_time, "TP2")
                equity += pnl_net
                equity_curve.append({"datetime": current_time, "equity": equity})
                active_trade = None
                continue

        # 新規シグナルチェック
        if active_trade is None and i >= 20:
            h4_past = h4.iloc[:i+1].copy()
            d1_past = d1[d1["datetime"] <= current_time].copy()

            if len(d1_past) >= 20:
                signal = check_signal(h4_past, d1_past)

                if signal["signal"] in ["LONG", "SHORT"]:
                    # 次の足の始値でエントリー
                    if i + 1 < len(h4):
                        next_bar = h4.iloc[i + 1]
                        entry_time = next_bar["datetime"]
                        entry_price_mid = next_bar["open"]
                        direction = signal["signal"]
                        atr = signal["atr"]

                        # SL/TP設定（mid価格ベース）
                        if direction == "LONG":
                            sl_price_mid = entry_price_mid - atr * atr_multiplier
                            tp1_price_mid = entry_price_mid + atr * tp1_r
                            tp2_price_mid = entry_price_mid + atr * tp2_r
                        else:  # SHORT
                            sl_price_mid = entry_price_mid + atr * atr_multiplier
                            tp1_price_mid = entry_price_mid - atr * tp1_r
                            tp2_price_mid = entry_price_mid - atr * tp2_r

                        # スプレッド取得
                        spread_pips_entry = get_spread_pips(symbol, entry_time) * spread_multiplier

                        # エントリー実行価格
                        entry_price_exec = calculate_execution_price(
                            entry_price_mid, direction, spread_pips_entry, slippage_pips
                        )

                        # SL実行価格
                        sl_price_exec = calculate_exit_price(
                            sl_price_mid, direction, spread_pips_entry, slippage_pips
                        )

                        # ポジションサイジング（0.5%リスク）
                        units, risk_jpy = calculate_position_size(
                            equity, entry_price_exec, sl_price_exec, risk_pct
                        )

                        # units=0ならスキップ
                        if units == 0:
                            continue

                        # TP数量配分
                        tp1_units = units * tp1_close_pct
                        tp2_units = units * (1 - tp1_close_pct)

                        # Trade作成
                        trade = Trade(
                            trade_id=trade_id_counter,
                            symbol=symbol,
                            side=direction,
                            pattern=signal["pattern"],
                            entry_time=entry_time,
                            entry_price_mid=entry_price_mid,
                            entry_price_exec=entry_price_exec,
                            units=units,
                            initial_sl_price_mid=sl_price_mid,
                            initial_sl_price_exec=sl_price_exec,
                            initial_r_per_unit_jpy=abs(entry_price_exec - sl_price_exec),
                            initial_risk_jpy=risk_jpy,
                            tp1_price_mid=tp1_price_mid,
                            tp2_price_mid=tp2_price_mid,
                            tp1_units=tp1_units,
                            tp2_units=tp2_units,
                            atr=atr
                        )

                        # ENTRY Fill記録
                        _, _, spread_cost, slip_cost, swap = calculate_fill_costs(
                            symbol, entry_time, entry_price_mid, entry_price_exec,
                            units, spread_multiplier, slippage_pips, 0.0
                        )

                        entry_fill = Fill(
                            trade_id=trade.trade_id,
                            symbol=symbol,
                            side=direction,
                            fill_type="ENTRY",
                            fill_time=entry_time,
                            fill_price_mid=entry_price_mid,
                            fill_price_exec=entry_price_exec,
                            units=units,
                            spread_pips=spread_pips_entry,
                            slippage_pips=slippage_pips,
                            spread_cost_jpy=spread_cost,
                            slippage_cost_jpy=slip_cost,
                            swap_jpy=0.0,
                            pnl_gross_jpy=0.0,
                            pnl_net_jpy=-spread_cost - slip_cost  # エントリーコスト
                        )

                        trade.add_fill(entry_fill)
                        trades.append(trade)
                        active_trade = trade
                        trade_id_counter += 1

    equity_df = pd.DataFrame(equity_curve)
    return trades, equity_df
