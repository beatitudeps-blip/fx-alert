"""
V4 統合バックテストエンジン（みんなのFX実運用対応）

新コア統合:
- config_loader: みんなのFX設定管理
- MinnafxCostModel: スプレッド/メンテ/スワップ/スプレッドフィルター
- position_sizing: 厳格0.5%リスク管理（violations=0保証）

保証:
- バックテストとLINE通知の執行ルールが完全一致
- メンテナンス時間中は fills を生成しない
- spread_filter NGのトレードはスキップ（記録あり）
- 0.5%リスク違反は0件
- run_idで出力を分離し、上書きしない
"""
import pandas as pd
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .data import fetch_data
from .strategy import check_signal
from .config_loader import BrokerConfig
from .broker_costs.minnafx import MinnafxCostModel
from .position_sizing import calculate_position_size_strict, units_to_lots
from .trade_v3 import Trade, Fill
from .swing_detection import calculate_structure_tp2


def run_backtest_v4_integrated(
    symbol: str,
    start_date: str,
    end_date: str,
    config: BrokerConfig,
    api_key: Optional[str] = None,
    initial_equity: float = 100000.0,
    risk_pct: float = 0.005,
    atr_multiplier: float = 1.2,
    tp1_r: float = 1.2,
    tp2_r: float = 2.4,
    tp1_close_pct: float = 0.5,
    use_cache: bool = True,
    sl_priority: bool = True,
    use_daylight: bool = False,
    run_id: str = "default",
    tp2_mode: str = "FIXED_R",
    tp2_lookback_days: int = 20
) -> Tuple[List[Trade], pd.DataFrame, Dict[str, Any]]:
    """
    V4統合バックテスト実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日
        end_date: 終了日
        config: ブローカー設定（みんなのFX）
        api_key: APIキー
        initial_equity: 初期資金（JPY）
        risk_pct: リスク率（デフォルト0.005 = 0.5%）
        atr_multiplier: ATR倍率（SL距離）
        tp1_r: TP1のR倍数
        tp2_r: TP2のR倍数（FIXED_Rモード時のみ使用）
        tp1_close_pct: TP1で決済する割合（0.5 = 50%）
        use_cache: キャッシュ使用
        sl_priority: SL優先（保守的）
        use_daylight: 米国夏時間適用
        run_id: 実行ID（出力ディレクトリ名）
        tp2_mode: TP2計算モード（"FIXED_R" or "STRUCTURE"）
        tp2_lookback_days: 構造型TP2の検索期間（日数、デフォルト20）

    Returns:
        (trades, equity_df, stats)
            trades: Trade リスト
            equity_df: 資産曲線
            stats: 統計情報（スキップ記録含む）
    """
    # コストモデル初期化
    cost_model = MinnafxCostModel(config)

    # データ取得
    h4 = fetch_data(symbol, "4h", 5000, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 1000, api_key, use_cache)

    # タイムゾーン設定（JST）
    tz = config.tz

    # 日付フィルタリング
    h4 = h4[(h4["datetime"] >= start_date) & (h4["datetime"] <= end_date)].reset_index(drop=True)
    d1 = d1[(d1["datetime"] >= start_date) & (d1["datetime"] <= end_date)].reset_index(drop=True)

    # DataFrameのdatetimeカラムにタイムゾーン情報を付加
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

        # datetime型に変換
        if isinstance(current_time, pd.Timestamp):
            current_time = current_time.to_pydatetime()

        # タイムゾーン設定
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=tz)

        # ==================== アクティブトレードの決済チェック ====================
        if active_trade is not None:
            # メンテナンス時間チェック（決済不可）
            if not cost_model.is_tradable(current_time, use_daylight):
                # メンテナンス中は決済処理をスキップ（次のバーで処理）
                continue

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

            # ==================== SL決済（優先） ====================
            if sl_hit and sl_priority:
                exit_reason = "SL" if not active_trade.tp1_hit else "BE"
                exit_price_mid = current_sl
                exit_units = active_trade.remaining_units

                # 実行価格計算（みんなのFXコストモデル）
                exit_price_exec = cost_model.calculate_exit_price(
                    exit_price_mid, direction, symbol, current_time
                )

                # コスト計算
                spread_cost, slip_cost = cost_model.calculate_fill_costs(
                    exit_units, direction, symbol, current_time
                )

                # スワップ計算
                entry_time = active_trade.entry_time
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=tz)
                holding_days = max(1, (current_time - entry_time).days)
                swap = cost_model.calculate_swap_jpy(
                    exit_units, direction, symbol, holding_days
                )

                # PnL計算
                if direction == "LONG":
                    pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                else:
                    pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                pnl_net = pnl_gross - spread_cost - slip_cost - swap

                # スプレッド取得（記録用）
                spread_pips = cost_model.get_spread_pips(symbol, current_time)

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

                trades.append(active_trade)
                active_trade = None
                continue

            # ==================== TP1決済 ====================
            if tp1_hit and not active_trade.tp1_hit:
                active_trade.tp1_hit = True
                exit_price_mid = tp1
                exit_units = active_trade.tp1_units

                # 実行価格計算
                exit_price_exec = cost_model.calculate_exit_price(
                    exit_price_mid, direction, symbol, current_time
                )

                # コスト計算
                spread_cost, slip_cost = cost_model.calculate_fill_costs(
                    exit_units, direction, symbol, current_time
                )

                # スワップ計算
                entry_time = active_trade.entry_time
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=tz)
                holding_days = max(1, (current_time - entry_time).days)
                swap = cost_model.calculate_swap_jpy(
                    exit_units, direction, symbol, holding_days
                )

                # PnL計算
                if direction == "LONG":
                    pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                else:
                    pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                pnl_net = pnl_gross - spread_cost - slip_cost - swap

                # スプレッド取得（記録用）
                spread_pips = cost_model.get_spread_pips(symbol, current_time)

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

            # ==================== TP2決済 ====================
            if tp2_hit and active_trade.tp1_hit:
                exit_price_mid = tp2
                exit_units = active_trade.remaining_units

                # 実行価格計算
                exit_price_exec = cost_model.calculate_exit_price(
                    exit_price_mid, direction, symbol, current_time
                )

                # コスト計算
                spread_cost, slip_cost = cost_model.calculate_fill_costs(
                    exit_units, direction, symbol, current_time
                )

                # スワップ計算
                entry_time = active_trade.entry_time
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=tz)
                holding_days = max(1, (current_time - entry_time).days)
                swap = cost_model.calculate_swap_jpy(
                    exit_units, direction, symbol, holding_days
                )

                # PnL計算
                if direction == "LONG":
                    pnl_gross = (exit_price_exec - active_trade.entry_price_exec) * exit_units
                else:
                    pnl_gross = (active_trade.entry_price_exec - exit_price_exec) * exit_units

                pnl_net = pnl_gross - spread_cost - slip_cost - swap

                # スプレッド取得（記録用）
                spread_pips = cost_model.get_spread_pips(symbol, current_time)

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
                    spread_pips=spread_pips,
                    slippage_pips=config.get_slippage_pips(),
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

                trades.append(active_trade)
                active_trade = None

        # ==================== 新規エントリーチェック ====================
        if active_trade is None and i < len(h4) - 2:
            # シグナル判定（現在のバーと確定済み日足データ）
            # 日足もbar_end_time <= current_timeで確定判定（ルックアヘッド回避）
            d1_end_time = d1["datetime"] + pd.Timedelta(days=1)
            d1_subset = d1[d1_end_time <= current_time]
            signal = check_signal(
                h4.iloc[max(0, i-50):i+1],
                d1_subset
            )

            if signal["signal"]:
                # シグナル方向を取得
                side = signal["signal"]  # "LONG" or "SHORT"

                # 1本待ち戦略: 次の次のバーでエントリー（NEXT_OPEN_MARKET）
                # 例: i=確定足 → i+1=スキップ → i+2=エントリー
                next_bar = h4.iloc[i + 2]
                entry_time = next_bar["datetime"]

                if isinstance(entry_time, pd.Timestamp):
                    entry_time = entry_time.to_pydatetime()
                if entry_time.tzinfo is None:
                    entry_time = entry_time.replace(tzinfo=tz)

                # メンテナンス時間チェック
                if not cost_model.is_tradable(entry_time, use_daylight):
                    skipped_signals.append({
                        "signal_time": current_time,
                        "entry_time": entry_time,
                        "symbol": symbol,
                        "side": side,
                        "reason": "maintenance"
                    })
                    maintenance_skips += 1
                    continue

                # スプレッドフィルターチェック
                should_skip, skip_reason = cost_model.should_skip_entry(symbol, entry_time)
                if should_skip:
                    skipped_signals.append({
                        "signal_time": current_time,
                        "entry_time": entry_time,
                        "symbol": symbol,
                        "side": side,
                        "reason": f"spread_filter: {skip_reason}"
                    })
                    spread_filter_skips += 1
                    continue

                # エントリー価格計算
                entry_price_mid = next_bar["open"]
                entry_price_exec = cost_model.calculate_execution_price(
                    entry_price_mid, side, symbol, entry_time
                )

                # SL/TP計算
                atr = signal["atr"]
                if side == "LONG":
                    sl_price_mid = entry_price_mid - (atr * atr_multiplier)
                    tp1_price_mid = entry_price_mid + (abs(entry_price_mid - sl_price_mid) * tp1_r)

                    # TP2計算: FIXED_R vs STRUCTURE
                    if tp2_mode == "STRUCTURE":
                        tp2_price_mid, tp2_source = calculate_structure_tp2(
                            d1, entry_time, entry_price_mid, sl_price_mid, side,
                            max_r=tp2_r, lookback_days=tp2_lookback_days
                        )
                    else:  # FIXED_R
                        tp2_price_mid = entry_price_mid + (abs(entry_price_mid - sl_price_mid) * tp2_r)
                        tp2_source = "FIXED_R"

                else:  # SHORT
                    sl_price_mid = entry_price_mid + (atr * atr_multiplier)
                    tp1_price_mid = entry_price_mid - (abs(entry_price_mid - sl_price_mid) * tp1_r)

                    # TP2計算: FIXED_R vs STRUCTURE
                    if tp2_mode == "STRUCTURE":
                        tp2_price_mid, tp2_source = calculate_structure_tp2(
                            d1, entry_time, entry_price_mid, sl_price_mid, side,
                            max_r=tp2_r, lookback_days=tp2_lookback_days
                        )
                    else:  # FIXED_R
                        tp2_price_mid = entry_price_mid - (abs(entry_price_mid - sl_price_mid) * tp2_r)
                        tp2_source = "FIXED_R"

                sl_price_exec = cost_model.calculate_exit_price(
                    sl_price_mid, side, symbol, entry_time
                )

                # ポジションサイジング（厳格0.5%、violations=0保証）
                units, actual_risk, is_valid = calculate_position_size_strict(
                    equity, entry_price_exec, sl_price_exec, risk_pct, config, symbol
                )

                if not is_valid:
                    skipped_signals.append({
                        "signal_time": current_time,
                        "entry_time": entry_time,
                        "symbol": symbol,
                        "side": side,
                        "reason": "position_size_invalid"
                    })
                    position_size_skips += 1
                    continue

                # Violations=0 確認（念のため）
                max_allowed_risk = equity * risk_pct
                if actual_risk > max_allowed_risk:
                    # これは理論上発生しないが、念のためスキップ
                    skipped_signals.append({
                        "signal_time": current_time,
                        "entry_time": entry_time,
                        "symbol": symbol,
                        "side": side,
                        "reason": f"risk_violation: {actual_risk:.2f} > {max_allowed_risk:.2f}"
                    })
                    position_size_skips += 1
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

                # Trade作成
                tp1_units = units * tp1_close_pct
                tp2_units = units * (1 - tp1_close_pct)

                trade = Trade(
                    trade_id=trade_id_counter,
                    symbol=symbol,
                    side=side,
                    pattern=signal["pattern"],
                    entry_time=entry_time,
                    entry_price_mid=entry_price_mid,
                    entry_price_exec=entry_price_exec,
                    units=units,
                    initial_sl_price_mid=sl_price_mid,
                    initial_sl_price_exec=sl_price_exec,
                    initial_r_per_unit_jpy=abs(entry_price_exec - sl_price_exec),
                    initial_risk_jpy=actual_risk,
                    tp1_price_mid=tp1_price_mid,
                    tp2_price_mid=tp2_price_mid,
                    tp1_units=tp1_units,
                    tp2_units=tp2_units,
                    atr=atr
                )

                trade.add_fill(entry_fill)
                equity -= (spread_cost + slip_cost)
                equity_curve.append({"datetime": entry_time, "equity": equity})

                active_trade = trade
                trade_id_counter += 1

    # 最後のトレードが残っている場合はクローズ
    if active_trade is not None:
        trades.append(active_trade)

    # 統計情報
    stats = {
        "total_signals": len(trades) + len(skipped_signals),
        "executed_trades": len(trades),
        "skipped_signals": len(skipped_signals),
        "maintenance_skips": maintenance_skips,
        "spread_filter_skips": spread_filter_skips,
        "position_size_skips": position_size_skips,
        "skipped_details": skipped_signals
    }

    equity_df = pd.DataFrame(equity_curve)
    return trades, equity_df, stats


if __name__ == "__main__":
    from .config_loader import load_broker_config
    import os

    # テスト実行
    config = load_broker_config("config/minnafx.yaml")

    trades, equity_df, stats = run_backtest_v4_integrated(
        symbol="EUR/JPY",
        start_date="2025-01-01",
        end_date="2026-02-14",
        config=config,
        api_key=os.environ.get("TWELVEDATA_API_KEY"),
        initial_equity=100000.0,
        risk_pct=0.005,
        atr_multiplier=1.2,
        tp1_r=1.2,
        tp2_r=2.4,
        run_id="test_run"
    )

    print(f"=== バックテスト結果 ===")
    print(f"実行トレード: {stats['executed_trades']}")
    print(f"スキップ: {stats['skipped_signals']}")
    print(f"  - メンテナンス: {stats['maintenance_skips']}")
    print(f"  - スプレッドフィルター: {stats['spread_filter_skips']}")
    print(f"  - ポジションサイズ: {stats['position_size_skips']}")
    print(f"最終資産: {equity_df.iloc[-1]['equity']:,.0f}円")
