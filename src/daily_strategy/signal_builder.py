"""
シグナル組み立てモジュール
strategy.md / data_spec.md 準拠
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.data import fetch_data
from src.indicators import calculate_ema, calculate_atr
from src.daily_strategy import STRATEGY_VERSION
from src.daily_strategy.trend import (
    calculate_ema_slope,
    determine_weekly_trend,
    determine_daily_trend,
    determine_alignment,
)
from src.daily_strategy.patterns import detect_pattern
from src.daily_strategy.filters import (
    check_ema_distance,
    check_ema_divergence,
    check_chasing,
    check_weekly_room,
)
from src.daily_strategy.bar_checker import (
    is_daily_bar_updated,
    mark_bar_processed,
    check_position_status,
    check_correlation_risk,
    check_consecutive_losses,
)

# --- デフォルト定数（config 未指定時のフォールバック） ---
SL_ATR_BUFFER = 0.1    # SL = signal_low/high ± 0.1 * ATR14
TP1_R = 1.5            # TP1 = 1.5R (50%利確)
TP2_R = 3.0            # TP2 = 3.0R (残50%利確)
SPREAD_COST_R = 0.05   # spread 0.2pip ≈ 0.05R
SLIPPAGE_R = 0.05      # slippage ≈ 0.05R
RISK_PCT = 0.005       # 0.5% リスク
ENTRY_OFFSET_ATR = 0.25  # 指値エントリー: close ∓ 0.25*ATR14
EMA_DIST_MIN_ATR = 0.2   # EMA距離下限: 0.2*ATR14
EMA_DIST_MAX_ATR = 1.2   # EMA距離上限: 1.2*ATR14
DAILY_BARS = 100       # 日足取得本数
WEEKLY_BARS = 50       # 週足取得本数


def _get_strategy_params(config) -> dict:
    """config.config['strategy'] から戦略パラメータを取得。未設定ならデフォルト値を返す。"""
    defaults = {
        "sl_atr_buffer": SL_ATR_BUFFER,
        "tp1_r": TP1_R,
        "tp2_r": TP2_R,
        "spread_cost_r": SPREAD_COST_R,
        "slippage_r": SLIPPAGE_R,
        "risk_pct": RISK_PCT,
        "entry_offset_atr": ENTRY_OFFSET_ATR,
        "ema_dist_min_atr": EMA_DIST_MIN_ATR,
        "ema_dist_max_atr": EMA_DIST_MAX_ATR,
    }
    if config is None:
        return defaults
    strategy = getattr(config, 'config', {}).get('strategy', {})
    if not strategy:
        return defaults
    return {k: strategy.get(k, v) for k, v in defaults.items()}


def pair_to_csv(pair: str) -> str:
    """USD/JPY → USDJPY"""
    return pair.replace("/", "")


def build_signal_id(pair: str, generated_at_utc: datetime) -> str:
    """signal_id を生成する。"""
    csv_pair = pair_to_csv(pair)
    ts = generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{STRATEGY_VERSION}_{csv_pair}_{ts}"


def build_single_signal(
    pair: str,
    daily_df,
    weekly_df,
    run_id: str,
    generated_at_utc: datetime,
    state: dict,
    equity: float,
    risk_pct: float,
    config=None,
) -> dict:
    """
    1通貨のシグナルを組み立てる。

    Returns:
        signal レコード辞書 (data_spec.md signals.csv 列に対応)
    """
    # config から戦略パラメータを取得（未設定ならデフォルト値）
    sp = _get_strategy_params(config)
    sl_atr_buffer = sp["sl_atr_buffer"]
    tp1_r = sp["tp1_r"]
    tp2_r = sp["tp2_r"]
    spread_cost_r = sp["spread_cost_r"]
    slippage_r = sp["slippage_r"]
    entry_offset_atr = sp["entry_offset_atr"]
    ema_dist_min_atr = sp["ema_dist_min_atr"]
    ema_dist_max_atr = sp["ema_dist_max_atr"]

    csv_pair = pair_to_csv(pair)
    jst = ZoneInfo("Asia/Tokyo")
    generated_date_jst = generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst).strftime("%Y-%m-%d")

    signal = {
        "signal_id": build_signal_id(pair, generated_at_utc),
        "run_id": run_id,
        "strategy_version": STRATEGY_VERSION,
        "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_date_jst": generated_date_jst,
        "pair": csv_pair,
    }

    reason_codes = []

    # --- 指標計算 ---
    daily_ema20_series = calculate_ema(daily_df["close"], 20)
    weekly_ema20_series = calculate_ema(weekly_df["close"], 20)
    atr14_series = calculate_atr(daily_df, 14)

    close_price = float(daily_df["close"].iloc[-1])
    daily_ema20 = float(daily_ema20_series.iloc[-1])
    weekly_ema20 = float(weekly_ema20_series.iloc[-1])
    weekly_close = float(weekly_df["close"].iloc[-1])
    atr14 = float(atr14_series.iloc[-1])

    signal.update({
        "close_price": close_price,
        "daily_ema20": daily_ema20,
        "weekly_ema20": weekly_ema20,
        "atr14": atr14,
    })

    # --- トレンド判定 ---
    daily_ema_slope = calculate_ema_slope(daily_ema20_series)
    weekly_ema_slope = calculate_ema_slope(weekly_ema20_series)

    weekly_trend = determine_weekly_trend(weekly_close, weekly_ema20, weekly_ema_slope)
    daily_trend = determine_daily_trend(close_price, daily_ema20, daily_ema_slope)
    alignment = determine_alignment(weekly_trend, daily_trend)

    signal.update({
        "weekly_trend": weekly_trend,
        "daily_trend": daily_trend,
        "alignment": alignment,
    })

    # --- 理由コード: W, D, A ---
    if weekly_trend == "WEEKLY_NEUTRAL":
        reason_codes.append("W")
    if daily_trend == "DAILY_NEUTRAL":
        reason_codes.append("D")
    if alignment == "NO_TRADE" and "W" not in reason_codes and "D" not in reason_codes:
        reason_codes.append("A")

    # --- EMA 距離判定（カスタム範囲: min_atr < |price - EMA20| < max_atr） ---
    ema_dist_abs = abs(close_price - daily_ema20)
    ema_dist_ratio = ema_dist_abs / atr14 if atr14 > 0 else 0.0
    pullback_ok = ema_dist_min_atr <= ema_dist_ratio <= ema_dist_max_atr

    signal.update({
        "ema_distance_abs": round(ema_dist_abs, 5),
        "ema_distance_atr_ratio": round(ema_dist_ratio, 4),
        "pullback_ok": pullback_ok,
    })

    if ema_dist_ratio > ema_dist_max_atr:
        reason_codes.append("X")

    # --- パターン検出 ---
    today = {
        "open": float(daily_df["open"].iloc[-1]),
        "close": float(daily_df["close"].iloc[-1]),
        "high": float(daily_df["high"].iloc[-1]),
        "low": float(daily_df["low"].iloc[-1]),
    }
    prev = {
        "open": float(daily_df["open"].iloc[-2]),
        "close": float(daily_df["close"].iloc[-2]),
        "high": float(daily_df["high"].iloc[-2]),
        "low": float(daily_df["low"].iloc[-2]),
    }
    pattern_name, pattern_detected = detect_pattern(today, prev, alignment)

    signal.update({
        "pattern_name": pattern_name,
        "pattern_detected": pattern_detected,
        "signal_high": today["high"],
        "signal_low": today["low"],
    })

    if not pattern_detected and alignment != "NO_TRADE":
        reason_codes.append("P")

    # --- 追いかけエントリー回避 ---
    signal_range = today["high"] - today["low"]
    signal_range_atr_ratio = signal_range / atr14 if atr14 > 0 else 0.0
    is_chasing = check_chasing(today["high"], today["low"], atr14)

    signal.update({
        "signal_range": round(signal_range, 5),
        "signal_range_atr_ratio": round(signal_range_atr_ratio, 4),
    })

    if is_chasing and alignment != "NO_TRADE":
        if "X" not in reason_codes:
            reason_codes.append("X")

    # --- 損切り・利確計算 ---
    entry_side = ""
    planned_entry = 0.0
    planned_sl = 0.0
    planned_tp1 = 0.0
    planned_tp2 = 0.0
    risk_price = 0.0

    if alignment == "BUY_ONLY":
        entry_side = "BUY"
        planned_entry = close_price - entry_offset_atr * atr14  # 指値エントリー
        planned_sl = today["low"] - sl_atr_buffer * atr14
        risk_price = planned_entry - planned_sl
        planned_tp1 = planned_entry + tp1_r * risk_price
        planned_tp2 = planned_entry + tp2_r * risk_price
    elif alignment == "SELL_ONLY":
        entry_side = "SELL"
        planned_entry = close_price + entry_offset_atr * atr14  # 指値エントリー
        planned_sl = today["high"] + sl_atr_buffer * atr14
        risk_price = planned_sl - planned_entry
        planned_tp1 = planned_entry - tp1_r * risk_price
        planned_tp2 = planned_entry - tp2_r * risk_price

    # --- 週足抵抗/支持フィルター ---
    weekly_room_price = 0.0
    weekly_room_r = 0.0
    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price > 0:
        weekly_room_price, weekly_room_r, room_skip = check_weekly_room(
            weekly_df, planned_entry, alignment, risk_price
        )
        if room_skip:
            reason_codes.append("S")

    signal.update({
        "weekly_room_price": round(weekly_room_price, 5),
        "weekly_room_r": round(weekly_room_r, 4),
    })

    # --- RR 不足チェック ---
    if alignment in ("BUY_ONLY", "SELL_ONLY") and risk_price <= 0:
        reason_codes.append("R")

    # --- ポジション・相関チェック ---
    position_status = check_position_status(pair, state)
    correlation_risk = check_correlation_risk(state)

    signal.update({
        "position_status": position_status,
        "correlation_risk": correlation_risk,
    })

    if position_status == "POSITION_EXISTS":
        reason_codes.append("O")
    if correlation_risk == "EXCEEDED":
        reason_codes.append("C")

    # --- 連敗チェック ---
    if check_consecutive_losses(state):
        if "C" not in reason_codes:
            reason_codes.append("C")

    # --- event_risk ---
    signal["event_risk"] = "manual_check"

    # --- 最終判定 ---
    if alignment == "NO_TRADE" or reason_codes:
        decision = "SKIP"
    elif not pullback_ok:
        decision = "SKIP"
        if "X" not in reason_codes:
            reason_codes.append("X")
    else:
        decision = "ENTRY_OK"

    # --- ポジションサイジング ---
    planned_risk_jpy = 0.0
    planned_lot = 0.0
    if decision == "ENTRY_OK" and risk_price > 0:
        max_loss_jpy = equity * risk_pct
        planned_risk_jpy = max_loss_jpy
        if config is not None:
            from src.position_sizing import calculate_position_size_strict, units_to_lots
            units, actual_risk_jpy, is_valid = calculate_position_size_strict(
                equity, planned_entry, planned_sl, risk_pct, config, pair
            )
            if is_valid:
                planned_lot = units_to_lots(units, config, pair)
                planned_risk_jpy = actual_risk_jpy
            else:
                decision = "SKIP"
                reason_codes.append("R")
        else:
            raw_units = max_loss_jpy / risk_price
            planned_lot = round(raw_units / 1000, 1) * 0.1
            planned_risk_jpy = planned_lot * 10000 * risk_price

    # --- コスト見積もり ---
    estimated_cost_r = spread_cost_r + slippage_r if decision == "ENTRY_OK" else 0.0
    estimated_cost_jpy = planned_risk_jpy * estimated_cost_r if decision == "ENTRY_OK" else 0.0

    signal.update({
        "decision": decision,
        "reason_codes": ";".join(reason_codes) if reason_codes else "",
        "entry_side": entry_side if decision == "ENTRY_OK" else "",
        "planned_entry_price": round(planned_entry, 3) if decision == "ENTRY_OK" else "",
        "planned_sl_price": round(planned_sl, 3) if decision == "ENTRY_OK" else "",
        "planned_tp1_price": round(planned_tp1, 3) if decision == "ENTRY_OK" else "",
        "planned_tp2_price": round(planned_tp2, 3) if decision == "ENTRY_OK" else "",
        "planned_risk_jpy": round(planned_risk_jpy, 2) if decision == "ENTRY_OK" else "",
        "planned_lot": round(planned_lot, 1) if decision == "ENTRY_OK" else "",
        "estimated_cost_r": round(estimated_cost_r, 3) if decision == "ENTRY_OK" else "",
        "estimated_cost_jpy": round(estimated_cost_jpy, 2) if decision == "ENTRY_OK" else "",
        "signal_note": "",
    })

    return signal


def build_daily_signals(
    pairs: list,
    run_id: str,
    state: dict,
    equity: float = 500000.0,
    risk_pct: float = RISK_PCT,
    api_key: str = None,
    config=None,
) -> tuple:
    """
    全通貨のシグナルを生成する。

    Returns:
        (signals: list[dict], errors: list[dict])
    """
    generated_at_utc = datetime.utcnow()
    signals = []
    errors = []

    for pair in pairs:
        try:
            daily_df = fetch_data(pair, "1day", DAILY_BARS, api_key=api_key, use_cache=True)
            weekly_df_raw = fetch_data(pair, "1week", WEEKLY_BARS, api_key=api_key, use_cache=True)

            # 当週の未完成バーを除外（前週の確定済み週足のみ使用）
            today = generated_at_utc.date()
            monday = today - timedelta(days=today.weekday())
            weekly_df = weekly_df_raw[weekly_df_raw["datetime"] < pd.Timestamp(monday)]

            is_updated, latest_bar_dt = is_daily_bar_updated(daily_df, pair, state)
            if not is_updated:
                signal = _build_no_data_signal(pair, run_id, generated_at_utc, "日足未更新")
                signals.append(signal)
                continue

            signal = build_single_signal(
                pair, daily_df, weekly_df,
                run_id, generated_at_utc,
                state, equity, risk_pct, config,
            )
            signals.append(signal)
            mark_bar_processed(pair, latest_bar_dt, state)

        except Exception as e:
            error = {
                "error_id": f"ERR_{pair_to_csv(pair)}_{generated_at_utc.strftime('%Y%m%dT%H%M%SZ')}",
                "run_id": run_id,
                "strategy_version": STRATEGY_VERSION,
                "occurred_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stage": "SIGNAL_BUILD",
                "severity": "ERROR",
                "error_type": type(e).__name__,
                "pair": pair_to_csv(pair),
                "message": str(e),
            }
            errors.append(error)

            signal = _build_error_signal(pair, run_id, generated_at_utc, str(e))
            signals.append(signal)

    return signals, errors


def _build_no_data_signal(pair: str, run_id: str, generated_at_utc: datetime, note: str) -> dict:
    """NO_DATA シグナルを生成する。"""
    jst = ZoneInfo("Asia/Tokyo")
    return {
        "signal_id": build_signal_id(pair, generated_at_utc),
        "run_id": run_id,
        "strategy_version": STRATEGY_VERSION,
        "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_date_jst": generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst).strftime("%Y-%m-%d"),
        "pair": pair_to_csv(pair),
        "weekly_trend": "", "daily_trend": "", "alignment": "",
        "close_price": "", "daily_ema20": "", "weekly_ema20": "", "atr14": "",
        "ema_distance_abs": "", "ema_distance_atr_ratio": "", "pullback_ok": "",
        "pattern_name": "NONE", "pattern_detected": False,
        "signal_high": "", "signal_low": "", "signal_range": "", "signal_range_atr_ratio": "",
        "weekly_room_price": "", "weekly_room_r": "",
        "event_risk": "manual_check",
        "position_status": "", "correlation_risk": "",
        "decision": "NO_DATA",
        "reason_codes": "",
        "entry_side": "", "planned_entry_price": "", "planned_sl_price": "",
        "planned_tp1_price": "", "planned_tp2_price": "",
        "planned_risk_jpy": "", "planned_lot": "",
        "estimated_cost_r": "", "estimated_cost_jpy": "",
        "signal_note": note,
    }


def _build_error_signal(pair: str, run_id: str, generated_at_utc: datetime, error_msg: str) -> dict:
    """ERROR シグナルを生成する。"""
    sig = _build_no_data_signal(pair, run_id, generated_at_utc, f"ERROR: {error_msg}")
    sig["decision"] = "ERROR"
    return sig
