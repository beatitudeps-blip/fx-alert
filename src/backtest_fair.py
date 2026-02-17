"""
V4 vs V5 公平比較バックテストエンジン

目的：エントリー方式（成行 vs 指値）と退出方式（固定R vs EMAクロス）の
    純粋比較。シグナル検出は共通。

共通:
- D1環境: Close>EMA20 & EMA20傾き>0 & ADX14>=18
- H4セットアップ: distance_to_ema <= 0.6*ATR14 + PA(engulf/hammer)
- SL: 1.0*ATR(signal_bar)
- TP1: +1.5Rで50%利確 → SL→BE
- バー内優先順位: SL/TP同一バー → SL優先（保守的）
- ポジションサイズ: 連続量（risk_yen / R_pips）、ロット丸めなし

V4（ベースライン）:
- エントリー: 1本待ち → signal_bar + 2 のOpen で成行
- 残り50%: 固定 3.0R でTP2

V5（改善案）:
- エントリー: 次4Hバー中のみ有効な指値
  long: EMA20(signal_bar) - 0.10*ATR(signal_bar)
  short: EMA20(signal_bar) + 0.10*ATR(signal_bar)
  fill: long Low<=limit / short High>=limit
  失効: 次4Hで刺さらなければノートレ
- 残り50%: EMAクロス退出（確定後、次バーOpenで決済）

ルックアヘッド排除:
- datetime = バー開始時刻(open_time)
- 4H確定: bar_end = datetime + 4h、bar_end <= now
- D1確定: bar_end = datetime + 1day、bar_end <= now
"""
import pandas as pd
import numpy as np
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from .data import fetch_data
from .strategy_v5 import check_signal_v5
from .indicators import calculate_ema


EMA_PERIOD = 20


# ==================== 簡易トレードモデル ====================

@dataclass
class SimpleFill:
    fill_type: str  # ENTRY, TP1, TP2, SL, BE, EMA_CROSS
    fill_time: Any
    fill_price: float
    units: float
    pnl: float = 0.0


@dataclass
class SimpleTrade:
    trade_id: int
    symbol: str
    side: str
    pattern: str
    entry_time: Any
    entry_price: float
    units: float
    sl_price: float
    tp1_price: float
    tp2_price: float  # V4用、V5は0
    atr: float
    risk_jpy: float
    tp1_units: float
    tp2_units: float

    tp1_hit: bool = False
    current_sl: float = None
    remaining_units: float = None
    exit_time: Any = None
    exit_reason: str = None
    total_pnl: float = 0.0
    fills: list = field(default_factory=list)

    def __post_init__(self):
        if self.current_sl is None:
            self.current_sl = self.sl_price
        if self.remaining_units is None:
            self.remaining_units = self.units


# ==================== 連続ポジションサイズ ====================

def calc_position_continuous(equity: float, risk_pct: float,
                             entry_price: float, sl_price: float) -> Tuple[float, float]:
    """
    ロット丸めなし連続量ポジションサイジング

    Returns: (units, risk_jpy)
    """
    risk_jpy = equity * risk_pct
    r_pips = abs(entry_price - sl_price)
    if r_pips <= 0:
        return 0.0, 0.0
    units = risk_jpy / r_pips
    return units, risk_jpy


# ==================== EMAクロス退出判定 ====================

def _check_ema_cross(h4_slice: pd.DataFrame, side: str) -> bool:
    if len(h4_slice) < 2:
        return False
    h4_c = h4_slice.copy()
    h4_c["ema20"] = calculate_ema(h4_c["close"], EMA_PERIOD)
    latest = h4_c.iloc[-1]
    if side == "LONG":
        return latest["close"] < latest["ema20"]
    else:
        return latest["close"] > latest["ema20"]


# ==================== メインエンジン ====================

def run_backtest_fair(
    symbol: str,
    start_date: str,
    end_date: str,
    mode: str,  # "V4" or "V5"
    api_key: Optional[str] = None,
    initial_equity: float = 500000.0,
    risk_pct: float = 0.005,
    use_cache: bool = True,
) -> Tuple[List[SimpleTrade], pd.DataFrame, Dict[str, Any]]:
    """
    公平比較バックテスト

    Args:
        mode: "V4" (1本待ち成行+TP2=3R) or "V5" (指値+EMAクロス退出)

    Returns:
        (trades, equity_df, stats)
    """
    # パラメータ（共通）
    atr_mult = 1.0
    tp1_r = 1.5
    tp1_pct = 0.5
    tp2_r = 3.0  # V4のみ使用

    # データ取得
    h4 = fetch_data(symbol, "4h", 5000, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 1000, api_key, use_cache)

    tz = ZoneInfo("Asia/Tokyo")

    # 日付フィルタリング
    h4 = h4[(h4["datetime"] >= start_date) & (h4["datetime"] <= end_date)].reset_index(drop=True)
    d1 = d1[(d1["datetime"] >= start_date) & (d1["datetime"] <= end_date)].reset_index(drop=True)

    if h4["datetime"].dt.tz is None:
        h4["datetime"] = h4["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)
    if d1["datetime"].dt.tz is None:
        d1["datetime"] = d1["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)

    trades: List[SimpleTrade] = []
    active_trade: Optional[SimpleTrade] = None
    equity = initial_equity
    equity_curve = [{"datetime": h4.iloc[0]["datetime"] if len(h4) > 0 else None,
                     "equity": equity}]
    trade_id = 1

    # スキップ記録
    skipped = []
    limit_expired = 0

    # V5: 指値ペンディング
    pending = None

    # V5: EMAクロスペンディング
    ema_cross_pending = False

    for i in range(len(h4)):
        bar = h4.iloc[i]
        t = bar["datetime"]
        if isinstance(t, pd.Timestamp):
            t = t.to_pydatetime()

        # ==================== 決済チェック ====================
        if active_trade is not None:
            side = active_trade.side
            sl = active_trade.current_sl
            tp1 = active_trade.tp1_price
            hi = bar["high"]
            lo = bar["low"]

            # --- V5: EMAクロス退出実行（前バーで検出→今バーOpen）---
            if mode == "V5" and ema_cross_pending and active_trade.tp1_hit:
                exit_p = bar["open"]
                exit_u = active_trade.remaining_units
                if exit_u > 0:
                    if side == "LONG":
                        pnl = (exit_p - active_trade.entry_price) * exit_u
                    else:
                        pnl = (active_trade.entry_price - exit_p) * exit_u
                    active_trade.fills.append(SimpleFill("EMA_CROSS", t, exit_p, exit_u, pnl))
                    active_trade.total_pnl += pnl
                    active_trade.remaining_units = 0
                    active_trade.exit_time = t
                    active_trade.exit_reason = "EMA_CROSS"
                    equity += pnl
                    equity_curve.append({"datetime": t, "equity": equity})
                    trades.append(active_trade)
                    active_trade = None
                    ema_cross_pending = False
                    continue

            # --- SL判定 ---
            sl_hit = (lo <= sl) if side == "LONG" else (hi >= sl)

            # --- TP1判定 ---
            tp1_hit = False
            if not active_trade.tp1_hit:
                tp1_hit = (hi >= tp1) if side == "LONG" else (lo <= tp1)

            # --- V4: TP2判定（TP1済み） ---
            tp2_hit = False
            if mode == "V4" and active_trade.tp1_hit:
                tp2 = active_trade.tp2_price
                tp2_hit = (hi >= tp2) if side == "LONG" else (lo <= tp2)

            # --- SL優先（保守的）---
            # 同一バーでSL/TP両方触れたらSL優先
            if sl_hit:
                reason = "SL" if not active_trade.tp1_hit else "BE"
                exit_u = active_trade.remaining_units
                if side == "LONG":
                    pnl = (sl - active_trade.entry_price) * exit_u
                else:
                    pnl = (active_trade.entry_price - sl) * exit_u
                active_trade.fills.append(SimpleFill(reason, t, sl, exit_u, pnl))
                active_trade.total_pnl += pnl
                active_trade.remaining_units = 0
                active_trade.exit_time = t
                active_trade.exit_reason = reason
                equity += pnl
                equity_curve.append({"datetime": t, "equity": equity})
                trades.append(active_trade)
                active_trade = None
                ema_cross_pending = False
                continue

            # --- TP1（SL非ヒット時のみ到達）---
            if tp1_hit and not active_trade.tp1_hit:
                active_trade.tp1_hit = True
                exit_u = active_trade.tp1_units
                if side == "LONG":
                    pnl = (tp1 - active_trade.entry_price) * exit_u
                else:
                    pnl = (active_trade.entry_price - tp1) * exit_u
                active_trade.fills.append(SimpleFill("TP1", t, tp1, exit_u, pnl))
                active_trade.total_pnl += pnl
                active_trade.remaining_units -= exit_u
                equity += pnl
                equity_curve.append({"datetime": t, "equity": equity})
                # SL→BE
                active_trade.current_sl = active_trade.entry_price

            # --- V4: TP2（SL非ヒット時のみ）---
            if tp2_hit and active_trade.tp1_hit:
                exit_u = active_trade.remaining_units
                tp2 = active_trade.tp2_price
                if side == "LONG":
                    pnl = (tp2 - active_trade.entry_price) * exit_u
                else:
                    pnl = (active_trade.entry_price - tp2) * exit_u
                active_trade.fills.append(SimpleFill("TP2", t, tp2, exit_u, pnl))
                active_trade.total_pnl += pnl
                active_trade.remaining_units = 0
                active_trade.exit_time = t
                active_trade.exit_reason = "TP2"
                equity += pnl
                equity_curve.append({"datetime": t, "equity": equity})
                trades.append(active_trade)
                active_trade = None
                continue

            # --- V5: EMAクロス検出（TP1後のみ、フラグ立てるだけ）---
            if mode == "V5" and active_trade is not None and active_trade.tp1_hit and not ema_cross_pending:
                h4_slice = h4.iloc[max(0, i - 50):i + 1]
                if _check_ema_cross(h4_slice, side):
                    ema_cross_pending = True

        # ==================== V5: 指値fill判定 ====================
        if mode == "V5" and pending is not None and active_trade is None:
            if i == pending["target_idx"]:
                filled = False
                if pending["side"] == "LONG":
                    filled = bar["low"] <= pending["limit"]
                else:
                    filled = bar["high"] >= pending["limit"]

                if filled:
                    entry_p = pending["limit"]
                    side = pending["side"]
                    atr = pending["atr"]

                    # SL/TP
                    if side == "LONG":
                        sl_p = entry_p - atr * atr_mult
                        tp1_p = entry_p + abs(entry_p - sl_p) * tp1_r
                    else:
                        sl_p = entry_p + atr * atr_mult
                        tp1_p = entry_p - abs(entry_p - sl_p) * tp1_r

                    # バー内SL判定（保守的：同バーでfillとSL両方→ノートレ）
                    bar_sl = (bar["low"] <= sl_p) if side == "LONG" else (bar["high"] >= sl_p)
                    if bar_sl:
                        skipped.append({"time": t, "side": side,
                                        "reason": "intra_bar_sl"})
                        pending = None
                        continue

                    # ポジションサイズ（連続量）
                    units, risk_jpy = calc_position_continuous(equity, risk_pct, entry_p, sl_p)

                    tp1_u = units * tp1_pct
                    tp2_u = units * (1 - tp1_pct)

                    trade = SimpleTrade(
                        trade_id=trade_id, symbol=symbol, side=side,
                        pattern=pending["pattern"], entry_time=t,
                        entry_price=entry_p, units=units,
                        sl_price=sl_p, tp1_price=tp1_p, tp2_price=0.0,
                        atr=atr, risk_jpy=risk_jpy,
                        tp1_units=tp1_u, tp2_units=tp2_u
                    )
                    trade.fills.append(SimpleFill("ENTRY", t, entry_p, units))
                    active_trade = trade
                    ema_cross_pending = False
                    trade_id += 1
                    pending = None
                else:
                    skipped.append({"time": t, "side": pending["side"],
                                    "reason": f"limit_expired({pending['limit']:.3f})"})
                    limit_expired += 1
                    pending = None

            elif i > pending["target_idx"]:
                pending = None

        # ==================== 新規シグナル ====================
        if active_trade is None and (mode == "V4" or pending is None):
            # V4: i+2が必要、V5: i+1が必要
            need_ahead = 2 if mode == "V4" else 1
            if i < len(h4) - need_ahead:
                # D1確定判定: bar_end = datetime + 1day <= current_time
                d1_end = d1["datetime"] + pd.Timedelta(days=1)
                d1_sub = d1[d1_end <= t]

                sig = check_signal_v5(
                    h4.iloc[max(0, i - 50):i + 1],
                    d1_sub
                )

                if sig["signal"]:
                    side = sig["signal"]
                    atr = sig["atr"]

                    if mode == "V4":
                        # 1本待ち成行: bar[i+2].open
                        entry_bar = h4.iloc[i + 2]
                        entry_t = entry_bar["datetime"]
                        if isinstance(entry_t, pd.Timestamp):
                            entry_t = entry_t.to_pydatetime()
                        entry_p = entry_bar["open"]

                        if side == "LONG":
                            sl_p = entry_p - atr * atr_mult
                            tp1_p = entry_p + abs(entry_p - sl_p) * tp1_r
                            tp2_p = entry_p + abs(entry_p - sl_p) * tp2_r
                        else:
                            sl_p = entry_p + atr * atr_mult
                            tp1_p = entry_p - abs(entry_p - sl_p) * tp1_r
                            tp2_p = entry_p - abs(entry_p - sl_p) * tp2_r

                        units, risk_jpy = calc_position_continuous(equity, risk_pct, entry_p, sl_p)

                        tp1_u = units * tp1_pct
                        tp2_u = units * (1 - tp1_pct)

                        trade = SimpleTrade(
                            trade_id=trade_id, symbol=symbol, side=side,
                            pattern=sig["pattern"], entry_time=entry_t,
                            entry_price=entry_p, units=units,
                            sl_price=sl_p, tp1_price=tp1_p, tp2_price=tp2_p,
                            atr=atr, risk_jpy=risk_jpy,
                            tp1_units=tp1_u, tp2_units=tp2_u
                        )
                        trade.fills.append(SimpleFill("ENTRY", entry_t, entry_p, units))
                        active_trade = trade
                        trade_id += 1

                    elif mode == "V5":
                        # 指値ペンディング
                        pending = {
                            "side": side,
                            "limit": sig["entry_limit"],
                            "target_idx": i + 1,
                            "pattern": sig["pattern"],
                            "atr": atr,
                            "signal_time": t,
                        }

    # 未決済は記録（exit_reason=None）
    if active_trade is not None:
        trades.append(active_trade)

    stats = {
        "mode": mode,
        "total_signals": len(trades) + len(skipped),
        "executed_trades": len(trades),
        "skipped_count": len(skipped),
        "limit_expired": limit_expired,
        "skipped_details": skipped,
        "position_size_invalid": 0,  # 連続量なので常に0
    }

    eq_df = pd.DataFrame(equity_curve)
    return trades, eq_df, stats
