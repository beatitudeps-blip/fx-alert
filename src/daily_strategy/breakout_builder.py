"""
Breakout シグナル生成モジュール
D1/W1 Breakout Strategy v1

週足トレンド方向に限定して、日足レンジ抜けを狙う順張り戦略。
Pullback とは完全に別ファイルとして実装。共通処理のみ流用する。
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from src.data import fetch_data
from src.indicators import calculate_ema, calculate_atr
from src.daily_strategy import BREAKOUT_VERSION
from src.daily_strategy.trend import (
    calculate_ema_slope,
    determine_weekly_trend,
)
from src.daily_strategy.bar_checker import (
    is_daily_bar_updated,
    mark_bar_processed,
    check_position_status,
    check_correlation_risk,
)

# --- デフォルト定数 ---
SL_ATR_BUFFER = 0.1
TP1_R = 1.5
TP2_R = 3.0
SPREAD_COST_R = 0.05
SLIPPAGE_R = 0.05
RISK_PCT = 0.005
BREAKOUT_LOOKBACK = 20
BODY_THRESHOLD_ATR = 0.5
DAILY_BARS = 100
WEEKLY_BARS = 50


def pair_to_csv(pair: str) -> str:
    return pair.replace("/", "")


def build_signal_id(pair: str, generated_at_utc: datetime) -> str:
    csv_pair = pair_to_csv(pair)
    ts = generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"{BREAKOUT_VERSION}_{csv_pair}_{ts}"


def check_breakout(
    daily_df: pd.DataFrame,
    weekly_trend: str,
    atr: float,
    lookback: int = BREAKOUT_LOOKBACK,
    body_threshold_atr: float = BODY_THRESHOLD_ATR,
) -> dict:
    """
    日足ブレイク条件を判定する。

    Returns:
        {"breakout": bool, "side": str, "reason": str}
    """
    if len(daily_df) < lookback + 2:
        return {"breakout": False, "side": "", "reason": "DATA_SHORT"}

    close = float(daily_df["close"].iloc[-1])
    open_ = float(daily_df["open"].iloc[-1])
    high = daily_df["high"].astype(float)
    low = daily_df["low"].astype(float)

    # 当日を除く過去20本の高値/安値（look-ahead bias 防止）
    highest_high = float(high.iloc[:-1].tail(lookback).max())
    lowest_low = float(low.iloc[:-1].tail(lookback).min())

    # 実体サイズ
    body = abs(close - open_)
    body_ok = body >= body_threshold_atr * atr

    if weekly_trend == "WEEKLY_UP":
        if close > highest_high and body_ok:
            return {"breakout": True, "side": "BUY", "reason": "daily_close_break_high"}
        if close > highest_high and not body_ok:
            return {"breakout": False, "side": "", "reason": "body_too_small"}
        return {"breakout": False, "side": "", "reason": "no_breakout"}

    elif weekly_trend == "WEEKLY_DOWN":
        if close < lowest_low and body_ok:
            return {"breakout": True, "side": "SELL", "reason": "daily_close_break_low"}
        if close < lowest_low and not body_ok:
            return {"breakout": False, "side": "", "reason": "body_too_small"}
        return {"breakout": False, "side": "", "reason": "no_breakout"}

    return {"breakout": False, "side": "", "reason": "weekly_neutral"}


def build_breakout_signal(
    pair: str,
    daily_df: pd.DataFrame,
    weekly_df: pd.DataFrame,
    run_id: str,
    generated_at_utc: datetime,
    state: dict,
    equity: float,
    risk_pct: float = RISK_PCT,
    config=None,
) -> dict:
    """1通貨の Breakout シグナルを組み立てる。"""
    csv_pair = pair_to_csv(pair)
    jst = ZoneInfo("Asia/Tokyo")
    dt_jst = generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)

    signal = {
        "signal_id": build_signal_id(pair, generated_at_utc),
        "run_id": run_id,
        "strategy_version": BREAKOUT_VERSION,
        "strategy_name": BREAKOUT_VERSION,
        "setup_type": "breakout",
        "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_date_jst": dt_jst.strftime("%Y-%m-%d"),
        "generated_datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
        "pair": csv_pair,
    }

    reason_codes = []

    # --- 指標計算 ---
    weekly_ema20_series = calculate_ema(weekly_df["close"], 20)
    atr14_series = calculate_atr(daily_df, 14)

    weekly_close = float(weekly_df["close"].iloc[-1])
    weekly_ema20 = float(weekly_ema20_series.iloc[-1])
    atr14 = float(atr14_series.iloc[-1])

    if atr14 <= 0:
        signal.update({"decision": "SKIP", "reason_codes": "DATA", "skip_reason": "atr_zero"})
        return signal

    # --- 週足トレンド ---
    weekly_ema_slope = calculate_ema_slope(weekly_ema20_series)
    weekly_trend = determine_weekly_trend(weekly_close, weekly_ema20, weekly_ema_slope)

    signal["weekly_trend"] = weekly_trend

    if weekly_trend == "WEEKLY_NEUTRAL":
        reason_codes.append("W")

    # --- ブレイク判定 ---
    bo = check_breakout(daily_df, weekly_trend, atr14)
    signal["breakout_detected"] = bo["breakout"]
    signal["signal_reason"] = bo["reason"]

    if not bo["breakout"]:
        reason_codes.append("B")  # B = Breakout不成立
        signal.update({
            "decision": "SKIP",
            "reason_codes": ";".join(sorted(set(reason_codes))),
            "skip_reason": bo["reason"],
            "atr14": atr14,
        })
        return signal

    # --- SL / TP 計算 ---
    today_high = float(daily_df["high"].iloc[-1])
    today_low = float(daily_df["low"].iloc[-1])
    close = float(daily_df["close"].iloc[-1])
    side = bo["side"]

    # エントリーは翌日始値（ライブでは次の open）
    # バックテストでは呼び出し側で next_open を設定
    # ここでは close を仮エントリーとして SL/TP を計算
    entry = close  # placeholder — backtest overrides with next_open

    if side == "BUY":
        sl = today_low - SL_ATR_BUFFER * atr14
        risk = entry - sl
    else:
        sl = today_high + SL_ATR_BUFFER * atr14
        risk = sl - entry

    if risk <= 0:
        reason_codes.append("R")
        signal.update({
            "decision": "SKIP",
            "reason_codes": ";".join(sorted(set(reason_codes))),
            "skip_reason": "negative_risk",
            "atr14": atr14,
        })
        return signal

    tp1 = entry + TP1_R * risk if side == "BUY" else entry - TP1_R * risk
    tp2 = entry + TP2_R * risk if side == "BUY" else entry - TP2_R * risk

    # --- ポジション / 相関チェック ---
    position_status = check_position_status(pair, state)
    if position_status == "POSITION_EXISTS":
        reason_codes.append("O")

    correlation_risk = check_correlation_risk(state)
    if correlation_risk == "EXCEEDED":
        reason_codes.append("C")

    # --- 最終判定 ---
    if reason_codes:
        signal.update({
            "decision": "SKIP",
            "reason_codes": ";".join(sorted(set(reason_codes))),
            "skip_reason": ";".join(sorted(set(reason_codes))),
            "atr14": atr14,
            "entry_side": side,
        })
        return signal

    # --- ポジションサイジング ---
    max_loss_jpy = equity * risk_pct
    raw_units = max_loss_jpy / risk
    planned_lot = round(raw_units / 1000, 1) * 0.1
    planned_risk_jpy = planned_lot * 10000 * risk

    estimated_cost_r = SPREAD_COST_R + SLIPPAGE_R
    estimated_cost_jpy = planned_risk_jpy * estimated_cost_r

    signal.update({
        "decision": "ENTRY_OK",
        "reason_codes": "",
        "skip_reason": "",
        "entry_side": side,
        "planned_entry_price": round(entry, 5),
        "planned_sl_price": round(sl, 5),
        "planned_tp1_price": round(tp1, 5),
        "planned_tp2_price": round(tp2, 5),
        "risk_price": round(risk, 5),
        "atr14": atr14,
        "signal_high": today_high,
        "signal_low": today_low,
        "close_price": close,
        "weekly_ema20": weekly_ema20,
        "planned_risk_jpy": round(planned_risk_jpy, 2),
        "planned_lot": round(planned_lot, 1),
        "estimated_cost_r": round(estimated_cost_r, 3),
        "estimated_cost_jpy": round(estimated_cost_jpy, 2),
        "event_risk": "manual_check",
        "signal_note": "",
    })

    return signal


def build_breakout_signals(
    pairs: list,
    run_id: str,
    state: dict,
    equity: float = 500000.0,
    risk_pct: float = RISK_PCT,
    api_key: str = None,
    config=None,
    pullback_entry_pairs: set = None,
) -> tuple:
    """
    全通貨の Breakout シグナルを生成する。

    Args:
        pullback_entry_pairs: Pullback で ENTRY_OK が出た通貨の set。
                              ここに含まれる通貨は Breakout をスキップする。
    Returns:
        (signals, errors)
    """
    generated_at_utc = datetime.utcnow()
    signals = []
    errors = []

    if pullback_entry_pairs is None:
        pullback_entry_pairs = set()

    for pair in pairs:
        csv_pair = pair_to_csv(pair)

        # 競合制御: Pullback が ENTRY_OK ならスキップ
        if csv_pair in pullback_entry_pairs or pair in pullback_entry_pairs:
            jst = ZoneInfo("Asia/Tokyo")
            dt_jst = generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)
            signals.append({
                "signal_id": build_signal_id(pair, generated_at_utc),
                "run_id": run_id,
                "strategy_version": BREAKOUT_VERSION,
                "strategy_name": BREAKOUT_VERSION,
                "setup_type": "breakout",
                "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "generated_date_jst": dt_jst.strftime("%Y-%m-%d"),
                "generated_datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "pair": csv_pair,
                "decision": "SKIP",
                "reason_codes": "PB",
                "skip_reason": "pullback_priority",
            })
            continue

        try:
            daily_df = fetch_data(pair, "1day", DAILY_BARS, api_key=api_key, use_cache=True)
            weekly_df_raw = fetch_data(pair, "1week", WEEKLY_BARS, api_key=api_key, use_cache=True)

            today = generated_at_utc.date()
            monday = today - timedelta(days=today.weekday())
            weekly_df = weekly_df_raw[weekly_df_raw["datetime"] < pd.Timestamp(monday)]

            is_updated, latest_bar_dt = is_daily_bar_updated(daily_df, pair, state)
            if not is_updated:
                jst = ZoneInfo("Asia/Tokyo")
                dt_jst = generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)
                signals.append({
                    "signal_id": build_signal_id(pair, generated_at_utc),
                    "run_id": run_id,
                    "strategy_version": BREAKOUT_VERSION,
                    "strategy_name": BREAKOUT_VERSION,
                    "setup_type": "breakout",
                    "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "generated_date_jst": dt_jst.strftime("%Y-%m-%d"),
                    "generated_datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                    "pair": csv_pair,
                    "decision": "NO_DATA",
                    "reason_codes": "",
                    "skip_reason": "日足未更新",
                })
                continue

            signal = build_breakout_signal(
                pair, daily_df, weekly_df,
                run_id, generated_at_utc,
                state, equity, risk_pct, config,
            )
            signals.append(signal)

        except Exception as e:
            errors.append({
                "error_id": f"ERR_BO_{csv_pair}_{generated_at_utc.strftime('%Y%m%dT%H%M%SZ')}",
                "run_id": run_id,
                "strategy_version": BREAKOUT_VERSION,
                "occurred_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "stage": "BREAKOUT_SIGNAL_BUILD",
                "severity": "ERROR",
                "error_type": type(e).__name__,
                "pair": csv_pair,
                "message": str(e),
            })
            jst = ZoneInfo("Asia/Tokyo")
            dt_jst = generated_at_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)
            signals.append({
                "signal_id": build_signal_id(pair, generated_at_utc),
                "run_id": run_id,
                "strategy_version": BREAKOUT_VERSION,
                "strategy_name": BREAKOUT_VERSION,
                "setup_type": "breakout",
                "generated_at_utc": generated_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "generated_date_jst": dt_jst.strftime("%Y-%m-%d"),
                "generated_datetime_jst": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "pair": csv_pair,
                "decision": "ERROR",
                "reason_codes": "",
                "skip_reason": f"ERROR: {e}",
            })

    return signals, errors
