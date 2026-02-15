"""
リアルタイムシグナル検出モジュール（GitHub Actions / Cron実行用）

既存のバックテストロジックと完全一致する検出ロジック:
- 日足EMA20フィルター
- 4H足EMAタッチ + トリガーパターン
- スプレッドフィルター
- メンテナンス時間チェック
- 厳格なポジションサイジング
"""
import pandas as pd
from typing import Optional, Dict, Any, List
from datetime import datetime
from zoneinfo import ZoneInfo

from .data import fetch_data
from .strategy import check_signal
from .config_loader import BrokerConfig
from .broker_costs.minnafx import MinnafxCostModel
from .position_sizing import calculate_position_size_strict, units_to_lots


def detect_signals(
    symbols: List[str],
    config: BrokerConfig,
    api_key: str,
    current_equity: float,
    risk_pct: float = 0.005,
    atr_multiplier: float = 1.0,
    tp1_r: float = 1.5,
    tp2_r: float = 3.0,
    use_cache: bool = False
) -> List[Dict[str, Any]]:
    """
    複数通貨ペアのシグナルを検出

    Args:
        symbols: 通貨ペアリスト（例: ["EUR/JPY", "USD/JPY"]）
        config: ブローカー設定
        api_key: TwelveData APIキー
        current_equity: 現在の口座残高（円）
        risk_pct: リスク率（0.005 = 0.5%）
        atr_multiplier: ATR倍率（SL距離）
        tp1_r: TP1のR倍数
        tp2_r: TP2のR倍数
        use_cache: キャッシュ使用（本番ではFalse推奨）

    Returns:
        シグナルリスト（検出されたエントリーシグナル）
        [
            {
                "symbol": "EUR/JPY",
                "signal": "LONG" or "SHORT",
                "pattern": "Bullish Engulfing",
                "bar_dt": datetime,  # シグナル確定時刻（4H足の終値時刻）
                "entry_price": 163.50,
                "sl_price": 162.80,
                "tp1_price": 164.55,
                "tp2_price": 165.60,
                "sl_pips": 70.0,
                "lots": 0.3,
                "units": 3000,
                "risk_jpy": 2500.0,
                "skip_reason": None  # スキップされた場合は理由文字列
            }
        ]
    """
    signals = []
    cost_model = MinnafxCostModel(config)
    tz = config.tz

    for symbol in symbols:
        try:
            signal = detect_single_signal(
                symbol=symbol,
                config=config,
                cost_model=cost_model,
                api_key=api_key,
                current_equity=current_equity,
                risk_pct=risk_pct,
                atr_multiplier=atr_multiplier,
                tp1_r=tp1_r,
                tp2_r=tp2_r,
                use_cache=use_cache,
                tz=tz
            )

            # シグナルあり・なし両方を追加（スキップ理由含む）
            if signal:
                signals.append(signal)

        except Exception as e:
            print(f"⚠️ {symbol} シグナル検出エラー: {e}")
            continue

    return signals


def detect_single_signal(
    symbol: str,
    config: BrokerConfig,
    cost_model: MinnafxCostModel,
    api_key: str,
    current_equity: float,
    risk_pct: float,
    atr_multiplier: float,
    tp1_r: float,
    tp2_r: float,
    use_cache: bool,
    tz: ZoneInfo
) -> Optional[Dict[str, Any]]:
    """
    単一通貨ペアのシグナルを検出

    Returns:
        シグナル情報 or None（シグナルなし）
    """
    # 最新データ取得（4H足と日足）
    h4 = fetch_data(symbol, "4h", 500, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 100, api_key, use_cache)

    # タイムゾーン設定
    if h4["datetime"].dt.tz is None:
        h4["datetime"] = h4["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)
    if d1["datetime"].dt.tz is None:
        d1["datetime"] = d1["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)

    # 現在時刻よりも古いデータのみ使用（確定した足のみ）
    # TwelveData APIは未来のデータも返すことがあるため、フィルタリングが必要
    now = datetime.now(tz)
    h4_past = h4[h4["datetime"] < now].copy()
    d1_past = d1[d1["datetime"] < now].copy()

    # 最新の確定足でシグナルチェック
    signal_result = check_signal(h4_past, d1_past)

    if signal_result["signal"] is None:
        # シグナルなし - スキップ理由を返す
        # 確定した最新足の時刻を使用
        bar_dt = h4_past.iloc[-1]["datetime"] if len(h4_past) > 0 else datetime.now(tz)
        return {
            "symbol": symbol,
            "signal": None,
            "bar_dt": bar_dt,
            "skip_reason": signal_result.get("reason", "条件不成立")
        }

    signal_type = signal_result["signal"]  # "LONG" or "SHORT"
    pattern = signal_result.get("pattern", "Unknown")
    bar_dt = signal_result["datetime"]  # シグナル確定時刻
    atr = signal_result["atr"]
    close_price = signal_result["close"]

    # エントリー価格：次の4H足の始値（= 現在の終値）
    entry_price = close_price

    # SL価格計算
    sl_distance_price = atr * atr_multiplier

    if signal_type == "LONG":
        sl_price = entry_price - sl_distance_price
    else:  # SHORT
        sl_price = entry_price + sl_distance_price

    # ポジションサイジング計算
    position_result = calculate_position_size_strict(
        symbol=symbol,
        side=signal_type,
        entry_price=entry_price,
        sl_price=sl_price,
        equity=current_equity,
        risk_pct=risk_pct,
        config=config
    )

    if not position_result["valid"]:
        # ポジションサイズ計算失敗
        return {
            "symbol": symbol,
            "signal": signal_type,
            "pattern": pattern,
            "bar_dt": bar_dt,
            "skip_reason": position_result["reason"]
        }

    units = position_result["units"]
    lots = units_to_lots(units, config.lot_size)
    risk_jpy = position_result["risk_jpy"]
    sl_pips = position_result["sl_pips"]

    # TP価格計算
    if signal_type == "LONG":
        tp1_price = entry_price + (sl_distance_price * tp1_r)
        tp2_price = entry_price + (sl_distance_price * tp2_r)
    else:  # SHORT
        tp1_price = entry_price - (sl_distance_price * tp1_r)
        tp2_price = entry_price - (sl_distance_price * tp2_r)

    # スプレッドフィルターチェック
    spread_ok = cost_model.check_spread_filter(
        symbol=symbol,
        entry_dt=bar_dt  # シグナル確定時刻でチェック
    )

    if not spread_ok:
        return {
            "symbol": symbol,
            "signal": signal_type,
            "pattern": pattern,
            "bar_dt": bar_dt,
            "skip_reason": "spread_filter"
        }

    # メンテナンス時間チェック（エントリー予定時刻 = 次の4H足の始値時刻）
    # シグナル確定から4時間後にエントリーすると仮定
    from datetime import timedelta
    entry_dt = bar_dt + timedelta(hours=4)

    is_maintenance = cost_model.is_maintenance_time(entry_dt)

    if is_maintenance:
        return {
            "symbol": symbol,
            "signal": signal_type,
            "pattern": pattern,
            "bar_dt": bar_dt,
            "skip_reason": "maintenance"
        }

    # 全チェック通過：有効なシグナル
    return {
        "symbol": symbol,
        "signal": signal_type,
        "pattern": pattern,
        "bar_dt": bar_dt,
        "entry_price": round(entry_price, 3),
        "sl_price": round(sl_price, 3),
        "tp1_price": round(tp1_price, 3),
        "tp2_price": round(tp2_price, 3),
        "sl_pips": round(sl_pips, 1),
        "lots": round(lots, 1),
        "units": units,
        "risk_jpy": round(risk_jpy, 0),
        "atr": round(atr, 3),
        "skip_reason": None
    }
