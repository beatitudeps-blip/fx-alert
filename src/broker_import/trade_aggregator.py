"""
トレード集約モジュール
data_spec.md セクション6 準拠

raw_fills を trade_group_id 単位で集約し trades_summary レコードを生成する。
"""
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from src.daily_strategy import STRATEGY_VERSION

UTC = timezone.utc
JST = ZoneInfo("Asia/Tokyo")

# 戦略対象通貨ペア
STRATEGY_PAIRS = {"USDJPY", "EURJPY", "GBPJPY"}


def aggregate_trades(
    fills: List[dict],
    signals: Optional[List[dict]] = None,
    strategy_pairs_only: bool = False,
) -> List[dict]:
    """raw_fills を trade_group_id 単位で集約し trades_summary を生成する。

    Args:
        fills: raw_fills レコードのリスト
        signals: signals レコードのリスト (matched_signal_id の情報取得用)
        strategy_pairs_only: True の場合、戦略対象通貨のみ集約

    Returns:
        trades_summary レコードのリスト
    """
    # trade_group_id でグループ化
    groups = defaultdict(list)  # type: Dict[str, List[dict]]
    for fill in fills:
        gid = fill.get("trade_group_id", "")
        if not gid:
            continue
        if fill.get("import_status") == "PARSE_ERROR":
            continue
        groups[gid].append(fill)

    # シグナル辞書
    sig_map = {}
    if signals:
        for sig in signals:
            sid = sig.get("signal_id", "")
            if sid:
                sig_map[sid] = sig

    trades = []
    for gid, group_fills in groups.items():
        trade = _aggregate_single_trade(gid, group_fills, sig_map)
        if trade is None:
            continue
        if strategy_pairs_only and trade["pair"] not in STRATEGY_PAIRS:
            continue
        trades.append(trade)

    # entry_time_utc でソート
    trades.sort(key=lambda t: t.get("entry_time_utc", ""))
    return trades


def _aggregate_single_trade(
    trade_group_id: str,
    fills: List[dict],
    sig_map: dict,
) -> Optional[dict]:
    """1つの trade_group_id に属する fills を集約して trades_summary レコードを返す。"""
    entry_fills = [f for f in fills if f.get("fill_type") == "ENTRY"]
    exit_fills = [f for f in fills if f.get("fill_type") in ("EXIT", "PARTIAL_EXIT", "STOP_EXIT", "TAKE_PROFIT_EXIT")]

    if not entry_fills:
        return None

    # ENTRY 行から基本情報を取得
    first_entry = entry_fills[0]
    pair = first_entry.get("pair", "")
    side = first_entry.get("side", "")
    entry_time_utc = first_entry.get("execution_time_utc", "")

    # 加重平均エントリー価格
    total_entry_qty = sum(_to_float(f.get("quantity", 0)) for f in entry_fills)
    if total_entry_qty > 0:
        entry_price_actual = sum(
            _to_float(f.get("price", 0)) * _to_float(f.get("quantity", 0))
            for f in entry_fills
        ) / total_entry_qty
    else:
        entry_price_actual = _to_float(first_entry.get("price", 0))

    # EXIT 集約
    total_exit_qty = sum(_to_float(f.get("quantity", 0)) for f in exit_fills)
    exit_time_utc = ""
    if exit_fills:
        exit_time_utc = max(f.get("execution_time_utc", "") for f in exit_fills)

    # 加重平均 EXIT 価格
    exit_price_actual = 0.0
    if total_exit_qty > 0:
        exit_price_actual = sum(
            _to_float(f.get("price", 0)) * _to_float(f.get("quantity", 0))
            for f in exit_fills
        ) / total_exit_qty

    # PnL 集約
    gross_pnl = sum(_to_float(f.get("gross_realized_pnl_jpy", 0)) for f in exit_fills)
    net_pnl = sum(_to_float(f.get("net_realized_pnl_jpy", 0)) for f in exit_fills)
    swap = sum(_to_float(f.get("swap_jpy", 0)) for f in exit_fills)
    fee = sum(_to_float(f.get("fee_jpy", 0)) for f in exit_fills)

    # ステータス
    remaining_qty = total_entry_qty - total_exit_qty
    if remaining_qty <= 0:
        status = "CLOSED"
    else:
        status = "OPEN"

    # 結果判定
    if status == "OPEN":
        result = "OPEN"
    elif net_pnl > 0:
        result = "WIN"
    elif net_pnl < 0:
        result = "LOSS"
    else:
        result = "BREAKEVEN"

    # matched_signal_id の取得
    matched_signal_id = ""
    for f in entry_fills:
        sid = f.get("matched_signal_id", "")
        if sid:
            matched_signal_id = sid
            break

    # シグナル情報の取得
    sig = sig_map.get(matched_signal_id, {})
    signal_id = matched_signal_id
    run_id = sig.get("run_id", "")
    strategy_version = sig.get("strategy_version", STRATEGY_VERSION)
    entry_price_planned = _to_float(sig.get("planned_entry_price", ""))
    initial_sl = _to_float(sig.get("planned_sl_price", ""))
    tp1 = _to_float(sig.get("planned_tp1_price", ""))
    tp2 = _to_float(sig.get("planned_tp2_price", ""))
    risk_jpy_planned = _to_float(sig.get("planned_risk_jpy", ""))

    # フォールバック: planned_risk_jpy が空だが planned_sl_price がある場合
    # risk_jpy = |entry_actual - planned_sl| * actual_qty で概算
    if not risk_jpy_planned and initial_sl and entry_price_actual and total_entry_qty:
        risk_jpy_planned = round(
            abs(entry_price_actual - initial_sl) * total_entry_qty, 2
        )

    # entry_slippage
    entry_slippage = ""
    if entry_price_planned:
        entry_slippage = round(entry_price_actual - entry_price_planned, 5)

    # pnl_r
    pnl_r = ""
    if risk_jpy_planned and risk_jpy_planned != 0 and status == "CLOSED":
        pnl_r = round(net_pnl / risk_jpy_planned, 3)

    # risk_price
    risk_price = ""
    if initial_sl:
        risk_price = round(abs(
            (entry_price_planned if entry_price_planned else entry_price_actual)
            - initial_sl
        ), 5)

    # trade_id 生成
    trade_id = f"{strategy_version}_{pair}_{entry_time_utc}_{side}"

    # pair_trade_date_jst
    pair_trade_date_jst = ""
    if entry_time_utc:
        try:
            dt = datetime.strptime(entry_time_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
            pair_trade_date_jst = dt.astimezone(JST).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    # exit_reason 推定 (個別 fill ベース)
    exit_reason_info = _estimate_exit_reason(
        status=status,
        side=side,
        exit_fills=exit_fills,
        initial_sl=initial_sl,
        tp1=tp1,
        tp2=tp2,
        entry_price=entry_price_actual,
        risk_price=_to_float(risk_price) if risk_price else 0.0,
        net_pnl=net_pnl,
    )

    now_utc = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "trade_id": trade_id,
        "signal_id": signal_id,
        "run_id": run_id,
        "strategy_version": strategy_version,
        "pair": pair,
        "side": side,
        "status": status,
        "result": result,
        "signal_generated_at_utc": sig.get("generated_at_utc", ""),
        "notification_sent_at_utc": "",
        "order_submitted_at_utc": "",
        "entry_time_utc": entry_time_utc,
        "exit_time_utc": exit_time_utc,
        "pair_trade_date_jst": pair_trade_date_jst,
        "entry_price_planned": entry_price_planned if entry_price_planned else "",
        "entry_price_actual": round(entry_price_actual, 3),
        "entry_slippage": entry_slippage,
        "exit_price_actual": round(exit_price_actual, 3) if exit_price_actual else "",
        "initial_sl_price": initial_sl if initial_sl else "",
        "tp1_price": tp1 if tp1 else "",
        "tp2_price": tp2 if tp2 else "",
        "breakeven_sl_enabled": "",
        "total_entry_quantity": total_entry_qty,
        "total_exit_quantity": total_exit_qty,
        "remaining_quantity": max(remaining_qty, 0),
        "risk_price": risk_price,
        "risk_pips": "",
        "risk_jpy_planned": risk_jpy_planned if risk_jpy_planned else "",
        "risk_jpy_actual": "",
        "gross_pnl_jpy": round(gross_pnl, 2) if gross_pnl else "",
        "net_pnl_jpy": round(net_pnl, 2),
        "pnl_r": pnl_r,
        "swap_jpy": round(swap, 2),
        "fee_jpy": round(fee, 2),
        "max_favorable_excursion": "",
        "max_adverse_excursion": "",
        "exit_reason": exit_reason_info["exit_reason"],
        "tp1_hit": exit_reason_info["tp1_hit"],
        "tp2_hit": exit_reason_info["tp2_hit"],
        "sl_hit": exit_reason_info["sl_hit"],
        "rule_violation": False,
        "violation_note": "",
        "event_risk_checked": "UNKNOWN",
        "decision_source": "",
        "notes": f"trade_group_id={trade_id}",
        "created_at_utc": now_utc,
        "updated_at_utc": now_utc,
    }


def _estimate_exit_reason(
    status: str,
    side: str,
    exit_fills: List[dict],
    initial_sl: float,
    tp1: float,
    tp2: float,
    entry_price: float,
    risk_price: float,
    net_pnl: float,
) -> dict:
    """exit_reason を個別 fill の価格から推定する。

    TP1で50%利確する戦略のため、加重平均exit_priceではなく
    個別fillごとにTP1/TP2/SL到達を判定する。

    Returns:
        {"exit_reason": str, "tp1_hit": bool/str, "tp2_hit": bool/str, "sl_hit": bool/str}
    """
    default = {"exit_reason": "", "tp1_hit": "", "tp2_hit": "", "sl_hit": ""}

    if status != "CLOSED":
        return default

    # シグナル情報がなければ判定不能
    if not initial_sl and not tp1 and not tp2:
        default["exit_reason"] = "UNKNOWN"
        return default

    if not exit_fills:
        default["exit_reason"] = "UNKNOWN"
        return default

    # 許容誤差: risk_price の 10% (最低 0.05)
    tol = max(risk_price * 0.1, 0.05) if risk_price else 0.05

    tp1_hit = False
    tp2_hit = False
    sl_hit = False
    be_hit = False  # 建値付近で決済された fill があるか

    # 個別 fill ごとに判定
    for f in exit_fills:
        price = _to_float(f.get("price", 0))
        if not price:
            continue

        if tp1 and not tp1_hit:
            if side == "BUY" and price >= tp1 - tol:
                tp1_hit = True
            elif side == "SELL" and price <= tp1 + tol:
                tp1_hit = True

        if tp2 and not tp2_hit:
            if side == "BUY" and price >= tp2 - tol:
                tp2_hit = True
            elif side == "SELL" and price <= tp2 + tol:
                tp2_hit = True

        if initial_sl and not sl_hit:
            if side == "BUY" and price <= initial_sl + tol:
                sl_hit = True
            elif side == "SELL" and price >= initial_sl - tol:
                sl_hit = True

        # 建値付近の fill 検出 (entry_price ± tol)
        if entry_price and abs(price - entry_price) <= tol:
            be_hit = True

    # TP2 到達ならTP1も通過済み
    if tp2_hit:
        tp1_hit = True

    # exit_reason 決定 (フラグ優先)
    if tp1_hit and tp2_hit:
        exit_reason = "TP1_TP2"
    elif tp1_hit and (sl_hit or be_hit):
        # TP1到達後に建値SLまたは建値付近で残り決済
        exit_reason = "TP1_BE"
    elif tp1_hit:
        exit_reason = "TP1_PARTIAL"
    elif sl_hit:
        exit_reason = "SL"
    else:
        exit_reason = "MANUAL"

    return {
        "exit_reason": exit_reason,
        "tp1_hit": tp1_hit,
        "tp2_hit": tp2_hit,
        "sl_hit": sl_hit,
    }


def _to_float(val) -> float:
    """値を float に変換する。空文字や None は 0.0。"""
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0
