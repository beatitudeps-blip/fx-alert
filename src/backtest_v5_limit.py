"""
V5 指値エントリーバックテストエンジン

V4（1本待ち成行）との差分:
- エントリー: 指値（EMA20 ± 0.10*ATR）、次4Hバー中のみ有効
  fill条件: long Low<=limit / short High>=limit
  失効: 次4Hで刺さらなければノートレ
- D1環境: ADX14 >= 18 追加
- H4セットアップ: distance_to_ema <= 0.6*ATR14
- SL: 1.0*ATR（旧 1.2*ATR）
- TP1: +1.5R で 50% 利確
- 残り: EMAクロス退出（確定後、次バーOpenで決済）
- 連敗ガード: 3連敗→次2シグナルスキップ
- バー内優先順位: SL/TP同一バー → SL優先（保守的）
"""
import pandas as pd
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import fetch_data
from .strategy_v5 import check_signal_v5
from .indicators import calculate_ema
from .config_loader import BrokerConfig
from .broker_costs.minnafx import MinnafxCostModel
from .position_sizing import calculate_position_size_strict, units_to_lots
from .trade_v3 import Trade, Fill


EMA_PERIOD = 20
CONSECUTIVE_LOSS_LIMIT = 3
SKIP_AFTER_STREAK = 2


def _check_ema_cross_exit(h4_slice: pd.DataFrame, side: str) -> bool:
    """
    EMAクロス退出判定（確定足ベース）

    LONG: close < EMA20 で退出シグナル
    SHORT: close > EMA20 で退出シグナル
    """
    if len(h4_slice) < 2:
        return False

    h4_calc = h4_slice.copy()
    h4_calc["ema20"] = calculate_ema(h4_calc["close"], EMA_PERIOD)
    latest = h4_calc.iloc[-1]

    if side == "LONG":
        return latest["close"] < latest["ema20"]
    else:  # SHORT
        return latest["close"] > latest["ema20"]


def run_backtest_v5_limit(
    symbol: str,
    start_date: str,
    end_date: str,
    config: BrokerConfig,
    api_key: Optional[str] = None,
    initial_equity: float = 100000.0,
    risk_pct: float = 0.005,
    atr_multiplier: float = 1.0,
    tp1_r: float = 1.5,
    tp1_close_pct: float = 0.5,
    use_cache: bool = True,
    sl_priority: bool = True,
    use_daylight: bool = False,
    run_id: str = "default",
) -> Tuple[List[Trade], pd.DataFrame, Dict[str, Any]]:
    """
    V5指値エントリーバックテスト実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        config: ブローカー設定
        api_key: APIキー
        initial_equity: 初期資金（JPY）
        risk_pct: リスク率
        atr_multiplier: ATR倍率（SL距離）= 1.0
        tp1_r: TP1のR倍数 = 1.5
        tp1_close_pct: TP1で決済する割合 = 0.5
        use_cache: キャッシュ使用
        sl_priority: SL優先（保守的）
        use_daylight: 米国夏時間適用
        run_id: 実行ID

    Returns:
        (trades, equity_df, stats)
    """
    cost_model = MinnafxCostModel(config)

    # データ取得
    h4 = fetch_data(symbol, "4h", 5000, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 1000, api_key, use_cache)

    tz = config.tz

    # 日付フィルタリング
    h4 = h4[(h4["datetime"] >= start_date) & (h4["datetime"] <= end_date)].reset_index(drop=True)
    d1 = d1[(d1["datetime"] >= start_date) & (d1["datetime"] <= end_date)].reset_index(drop=True)

    if h4["datetime"].dt.tz is None:
        h4["datetime"] = h4["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)
    if d1["datetime"].dt.tz is None:
        d1["datetime"] = d1["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)

    trades: List[Trade] = []
    active_trade: Optional[Trade] = None
    equity = initial_equity
    equity_curve = []
    trade_id_counter = 1

    # スキップ記録
    skipped_signals = []
    maintenance_skips = 0
    spread_filter_skips = 0
    position_size_skips = 0
    limit_expired_skips = 0
    streak_guard_skips = 0

    # 連敗ガード状態
    consecutive_losses = 0
    signals_to_skip = 0

    # 指値ペンディング状態
    pending_limit = None  # {signal, limit_price, signal_bar_idx, side, pattern, atr, ema20}

    # EMAクロス退出ペンディング（確定後、次バーOpenで決済）
    ema_cross_pending = False

    # 初期資産曲線
    if len(h4) > 0:
        first_dt = h4.iloc[0]["datetime"]
        if isinstance(first_dt, pd.Timestamp):
            first_dt = first_dt.to_pydatetime()
        if first_dt.tzinfo is None:
            first_dt = first_dt.replace(tzinfo=tz)
        equity_curve.append({"datetime": first_dt, "equity": equity})

    for i in range(len(h4)):
        current_bar = h4.iloc[i]
        current_time = current_bar["datetime"]

        if isinstance(current_time, pd.Timestamp):
            current_time = current_time.to_pydatetime()
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=tz)

        # ==================== アクティブトレードの決済チェック ====================
        if active_trade is not None:
            if not cost_model.is_tradable(current_time, use_daylight):
                continue

            direction = active_trade.side
            current_sl = active_trade.current_sl
            tp1 = active_trade.tp1_price_mid

            bar_high_mid = current_bar["high"]
            bar_low_mid = current_bar["low"]

            sl_hit = False
            tp1_hit = False

            # SL判定
            if direction == "LONG":
                sl_hit = bar_low_mid <= current_sl
            else:
                sl_hit = bar_high_mid >= current_sl

            # TP1判定（まだヒットしていない場合）
            if not active_trade.tp1_hit:
                if direction == "LONG":
                    tp1_hit = bar_high_mid >= tp1
                else:
                    tp1_hit = bar_low_mid <= tp1

            # ==================== EMAクロス退出（次バーOpenで決済）====================
            if ema_cross_pending and active_trade.tp1_hit:
                exit_price_mid = current_bar["open"]
                exit_units = active_trade.remaining_units

                if exit_units > 0:
                    exit_price_exec = cost_model.calculate_exit_price(
                        exit_price_mid, direction, symbol, current_time
                    )
                    spread_cost, slip_cost = cost_model.calculate_fill_costs(
                        exit_units, direction, symbol, current_time
                    )
                    entry_time_val = active_trade.entry_time
                    if entry_time_val.tzinfo is None:
                        entry_time_val = entry_time_val.replace(tzinfo=tz)
                    holding_days = max(1, (current_time - entry_time_val).days)
                    swap = cost_model.calculate_swap_jpy(exit_units, direction, symbol, holding_days)

                    if direction == "LONG":
                        pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                    else:
                        pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                    pnl_net = pnl_gross - spread_cost - slip_cost - swap
                    spread_pips = cost_model.get_spread_pips(symbol, current_time)

                    fill = Fill(
                        trade_id=active_trade.trade_id,
                        symbol=symbol,
                        side=direction,
                        fill_type="EMA_CROSS",
                        fill_time=current_time,
                        fill_price_mid=exit_price_mid,
                        fill_price_exec=exit_price_exec,
                        units=exit_units,
                        spread_pips=spread_pips,
                        slippage_pips=config.get_slippage_pips(),
                        spread_cost_jpy=spread_cost,
                        slippage_cost_jpy=slip_cost,
                        swap_jpy=swap,
                        pnl_gross_jpy=pnl_gross,
                        pnl_net_jpy=pnl_net
                    )

                    active_trade.add_fill(fill)
                    active_trade.close(current_time, "EMA_CROSS")
                    equity += pnl_net
                    equity_curve.append({"datetime": current_time, "equity": equity})

                    # 連敗カウント更新
                    if active_trade.total_pnl_net_jpy < 0:
                        consecutive_losses += 1
                        if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                            signals_to_skip = SKIP_AFTER_STREAK
                            consecutive_losses = 0
                    else:
                        consecutive_losses = 0

                    trades.append(active_trade)
                    active_trade = None
                    ema_cross_pending = False
                    continue

            # ==================== SL決済（優先）====================
            if sl_hit and sl_priority:
                exit_reason = "SL" if not active_trade.tp1_hit else "BE"
                exit_price_mid = current_sl
                exit_units = active_trade.remaining_units

                exit_price_exec = cost_model.calculate_exit_price(
                    exit_price_mid, direction, symbol, current_time
                )
                spread_cost, slip_cost = cost_model.calculate_fill_costs(
                    exit_units, direction, symbol, current_time
                )
                entry_time_val = active_trade.entry_time
                if entry_time_val.tzinfo is None:
                    entry_time_val = entry_time_val.replace(tzinfo=tz)
                holding_days = max(1, (current_time - entry_time_val).days)
                swap = cost_model.calculate_swap_jpy(exit_units, direction, symbol, holding_days)

                if direction == "LONG":
                    pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                else:
                    pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                pnl_net = pnl_gross - spread_cost - slip_cost - swap
                spread_pips = cost_model.get_spread_pips(symbol, current_time)

                fill = Fill(
                    trade_id=active_trade.trade_id,
                    symbol=symbol,
                    side=direction,
                    fill_type=exit_reason,
                    fill_time=current_time,
                    fill_price_mid=exit_price_mid,
                    fill_price_exec=exit_price_exec,
                    units=exit_units,
                    spread_pips=spread_pips,
                    slippage_pips=config.get_slippage_pips(),
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

                # 連敗カウント更新
                if active_trade.total_pnl_net_jpy < 0:
                    consecutive_losses += 1
                    if consecutive_losses >= CONSECUTIVE_LOSS_LIMIT:
                        signals_to_skip = SKIP_AFTER_STREAK
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0

                trades.append(active_trade)
                active_trade = None
                ema_cross_pending = False
                continue

            # ==================== TP1決済 ====================
            if tp1_hit and not active_trade.tp1_hit:
                active_trade.tp1_hit = True
                exit_price_mid = tp1
                exit_units = active_trade.tp1_units

                exit_price_exec = cost_model.calculate_exit_price(
                    exit_price_mid, direction, symbol, current_time
                )
                spread_cost, slip_cost = cost_model.calculate_fill_costs(
                    exit_units, direction, symbol, current_time
                )
                entry_time_val = active_trade.entry_time
                if entry_time_val.tzinfo is None:
                    entry_time_val = entry_time_val.replace(tzinfo=tz)
                holding_days = max(1, (current_time - entry_time_val).days)
                swap = cost_model.calculate_swap_jpy(exit_units, direction, symbol, holding_days)

                if direction == "LONG":
                    pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                else:
                    pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                pnl_net = pnl_gross - spread_cost - slip_cost - swap
                spread_pips = cost_model.get_spread_pips(symbol, current_time)

                fill = Fill(
                    trade_id=active_trade.trade_id,
                    symbol=symbol,
                    side=direction,
                    fill_type="TP1",
                    fill_time=current_time,
                    fill_price_mid=exit_price_mid,
                    fill_price_exec=exit_price_exec,
                    units=exit_units,
                    spread_pips=spread_pips,
                    slippage_pips=config.get_slippage_pips(),
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

            # ==================== EMAクロス退出チェック（TP1後のみ）====================
            if active_trade is not None and active_trade.tp1_hit and not ema_cross_pending:
                # 確定足でEMAクロスを判定
                h4_up_to_now = h4.iloc[max(0, i - 50):i + 1]
                if _check_ema_cross_exit(h4_up_to_now, direction):
                    # 次バーOpenで決済するフラグを立てる
                    ema_cross_pending = True

        # ==================== 指値ペンディングのfill判定 ====================
        if pending_limit is not None and active_trade is None:
            pl = pending_limit
            # 次の4Hバー = signal_bar_idx + 1 のバーでのみ有効
            if i == pl["target_bar_idx"]:
                filled = False
                if pl["side"] == "LONG":
                    filled = current_bar["low"] <= pl["limit_price"]
                else:  # SHORT
                    filled = current_bar["high"] >= pl["limit_price"]

                if filled:
                    entry_time = current_time
                    entry_price_mid = pl["limit_price"]

                    # メンテナンス時間チェック
                    if not cost_model.is_tradable(entry_time, use_daylight):
                        skipped_signals.append({
                            "signal_time": pl["signal_time"],
                            "entry_time": entry_time,
                            "symbol": symbol,
                            "side": pl["side"],
                            "reason": "maintenance (limit fill)"
                        })
                        maintenance_skips += 1
                        pending_limit = None
                        continue

                    # スプレッドフィルターチェック
                    should_skip, skip_reason = cost_model.should_skip_entry(symbol, entry_time)
                    if should_skip:
                        skipped_signals.append({
                            "signal_time": pl["signal_time"],
                            "entry_time": entry_time,
                            "symbol": symbol,
                            "side": pl["side"],
                            "reason": f"spread_filter: {skip_reason}"
                        })
                        spread_filter_skips += 1
                        pending_limit = None
                        continue

                    side = pl["side"]
                    entry_price_exec = cost_model.calculate_execution_price(
                        entry_price_mid, side, symbol, entry_time
                    )

                    # SL/TP計算（指値エントリー価格基準）
                    atr = pl["atr"]
                    if side == "LONG":
                        sl_price_mid = entry_price_mid - (atr * atr_multiplier)
                        tp1_price_mid = entry_price_mid + (abs(entry_price_mid - sl_price_mid) * tp1_r)
                    else:
                        sl_price_mid = entry_price_mid + (atr * atr_multiplier)
                        tp1_price_mid = entry_price_mid - (abs(entry_price_mid - sl_price_mid) * tp1_r)

                    sl_price_exec = cost_model.calculate_exit_price(
                        sl_price_mid, side, symbol, entry_time
                    )

                    # ポジションサイジング
                    units, actual_risk, is_valid = calculate_position_size_strict(
                        equity, entry_price_exec, sl_price_exec, risk_pct, config, symbol
                    )

                    if not is_valid:
                        skipped_signals.append({
                            "signal_time": pl["signal_time"],
                            "entry_time": entry_time,
                            "symbol": symbol,
                            "side": side,
                            "reason": "position_size_invalid"
                        })
                        position_size_skips += 1
                        pending_limit = None
                        continue

                    max_allowed_risk = equity * risk_pct
                    if actual_risk > max_allowed_risk:
                        skipped_signals.append({
                            "signal_time": pl["signal_time"],
                            "entry_time": entry_time,
                            "symbol": symbol,
                            "side": side,
                            "reason": f"risk_violation: {actual_risk:.2f} > {max_allowed_risk:.2f}"
                        })
                        position_size_skips += 1
                        pending_limit = None
                        continue

                    # --- バー内SL判定（保守的：同バーでSLも触れていたらSL優先）---
                    bar_sl_hit = False
                    if side == "LONG":
                        bar_sl_hit = current_bar["low"] <= sl_price_mid
                    else:
                        bar_sl_hit = current_bar["high"] >= sl_price_mid

                    if bar_sl_hit:
                        # 同バーでfillとSLの両方 → SL優先（保守的にノートレ扱い）
                        skipped_signals.append({
                            "signal_time": pl["signal_time"],
                            "entry_time": entry_time,
                            "symbol": symbol,
                            "side": side,
                            "reason": "intra_bar_sl_hit (conservative skip)"
                        })
                        pending_limit = None
                        continue

                    # エントリーFill記録
                    spread_cost, slip_cost = cost_model.calculate_fill_costs(
                        units, side, symbol, entry_time
                    )
                    spread_pips = cost_model.get_spread_pips(symbol, entry_time)

                    entry_fill = Fill(
                        trade_id=trade_id_counter,
                        symbol=symbol,
                        side=side,
                        fill_type="ENTRY",
                        fill_time=entry_time,
                        fill_price_mid=entry_price_mid,
                        fill_price_exec=entry_price_exec,
                        units=units,
                        spread_pips=spread_pips,
                        slippage_pips=config.get_slippage_pips(),
                        spread_cost_jpy=spread_cost,
                        slippage_cost_jpy=slip_cost,
                        swap_jpy=0.0,
                        pnl_gross_jpy=0.0,
                        pnl_net_jpy=-(spread_cost + slip_cost)
                    )

                    tp1_units = units * tp1_close_pct
                    tp2_units = units * (1 - tp1_close_pct)

                    trade = Trade(
                        trade_id=trade_id_counter,
                        symbol=symbol,
                        side=side,
                        pattern=pl["pattern"],
                        entry_time=entry_time,
                        entry_price_mid=entry_price_mid,
                        entry_price_exec=entry_price_exec,
                        units=units,
                        initial_sl_price_mid=sl_price_mid,
                        initial_sl_price_exec=sl_price_exec,
                        initial_r_per_unit_jpy=abs(entry_price_exec - sl_price_exec),
                        initial_risk_jpy=actual_risk,
                        tp1_price_mid=tp1_price_mid,
                        tp2_price_mid=0.0,  # V5はTP2なし（EMAクロス退出）
                        tp1_units=tp1_units,
                        tp2_units=tp2_units,
                        atr=atr
                    )

                    trade.add_fill(entry_fill)
                    equity -= (spread_cost + slip_cost)
                    equity_curve.append({"datetime": entry_time, "equity": equity})

                    active_trade = trade
                    ema_cross_pending = False
                    trade_id_counter += 1
                    pending_limit = None
                else:
                    # 指値刺さらず → 失効
                    skipped_signals.append({
                        "signal_time": pl["signal_time"],
                        "entry_time": current_time,
                        "symbol": symbol,
                        "side": pl["side"],
                        "reason": f"limit_expired ({pl['limit_price']:.3f})"
                    })
                    limit_expired_skips += 1
                    pending_limit = None

            elif i > pl["target_bar_idx"]:
                # 対象バーを過ぎた → 失効
                pending_limit = None

        # ==================== 新規シグナルチェック ====================
        if active_trade is None and pending_limit is None and i < len(h4) - 1:
            # 日足もbar_end_time <= current_timeで確定判定
            d1_end_time = d1["datetime"] + pd.Timedelta(days=1)
            d1_subset = d1[d1_end_time <= current_time]
            signal = check_signal_v5(
                h4.iloc[max(0, i - 50):i + 1],
                d1_subset
            )

            if signal["signal"]:
                # 連敗ガードチェック
                if signals_to_skip > 0:
                    skipped_signals.append({
                        "signal_time": current_time,
                        "entry_time": None,
                        "symbol": symbol,
                        "side": signal["signal"],
                        "reason": f"streak_guard (remaining_skip={signals_to_skip})"
                    })
                    streak_guard_skips += 1
                    signals_to_skip -= 1
                    continue

                # 指値ペンディング設定（次の4Hバーで判定）
                pending_limit = {
                    "side": signal["signal"],
                    "limit_price": signal["entry_limit"],
                    "signal_bar_idx": i,
                    "target_bar_idx": i + 1,  # 次の4Hバー
                    "pattern": signal["pattern"],
                    "atr": signal["atr"],
                    "ema20": signal["ema20"],
                    "signal_time": current_time,
                }

    # 最後のトレードが残っている場合
    if active_trade is not None:
        trades.append(active_trade)

    stats = {
        "total_signals": len(trades) + len(skipped_signals),
        "executed_trades": len(trades),
        "skipped_signals": len(skipped_signals),
        "maintenance_skips": maintenance_skips,
        "spread_filter_skips": spread_filter_skips,
        "position_size_skips": position_size_skips,
        "limit_expired_skips": limit_expired_skips,
        "streak_guard_skips": streak_guard_skips,
        "skipped_details": skipped_signals
    }

    equity_df = pd.DataFrame(equity_curve)
    return trades, equity_df, stats
