"""
日足戦略用LINE通知モジュール
operations.md セクション7 準拠
"""
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

from src.daily_strategy import STRATEGY_VERSION


def format_daily_notification(signals: list, run_id: str) -> str:
    """
    日次シグナルの LINE 通知メッセージを生成する。

    operations.md 通知ルール:
    - ENTRY_OK がある場合はエントリー候補価格を含めて通知
    - SKIP のみの場合は一覧サマリー通知
    - NO_DATA / ERROR は障害通知として扱う
    - 複数通貨はサマリー通知を優先
    """
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)

    entry_ok = [s for s in signals if s.get("decision") == "ENTRY_OK"]
    skips = [s for s in signals if s.get("decision") == "SKIP"]
    no_data = [s for s in signals if s.get("decision") == "NO_DATA"]
    errors = [s for s in signals if s.get("decision") == "ERROR"]

    msg = f"Daily Signal Report ({now_jst.strftime('%Y-%m-%d %H:%M JST')})\n"
    msg += f"Version: {STRATEGY_VERSION}\n"
    msg += f"Run ID: {run_id}\n\n"

    # ENTRY_OK 詳細
    if entry_ok:
        for s in entry_ok:
            pair = s["pair"]
            side = s.get("entry_side", "")
            direction = "BUY" if side == "BUY" else "SELL"
            emoji = "+" if side == "BUY" else "-"

            msg += f"[{emoji}] {pair} {direction} ENTRY_OK\n"
            msg += f"  Pattern: {s.get('pattern_name', '')}\n"
            msg += f"  Entry: {s.get('planned_entry_price', '')}\n"
            msg += f"  SL: {s.get('planned_sl_price', '')}\n"
            msg += f"  TP1: {s.get('planned_tp1_price', '')}\n"
            msg += f"  TP2: {s.get('planned_tp2_price', '')}\n"
            msg += f"  Risk: {s.get('planned_risk_jpy', '')} JPY\n"
            msg += f"  Lot: {s.get('planned_lot', '')}\n"
            msg += f"  EMA20: {s.get('daily_ema20', '')}\n"
            msg += f"  ATR14: {s.get('atr14', '')}\n"
            msg += f"  Event Risk: {s.get('event_risk', 'manual_check')}\n"
            msg += "\n"

    # SKIP サマリー
    if skips:
        msg += "[SKIP]\n"
        for s in skips:
            pair = s["pair"]
            reasons = s.get("reason_codes", "")
            alignment = s.get("alignment", "")
            msg += f"  {pair}: [{reasons}] {alignment}\n"
        msg += "\n"

    # NO_DATA / ERROR
    if no_data:
        msg += "[NO_DATA]\n"
        for s in no_data:
            msg += f"  {s['pair']}: {s.get('signal_note', '')}\n"
        msg += "\n"

    if errors:
        msg += "[ERROR]\n"
        for s in errors:
            msg += f"  {s['pair']}: {s.get('signal_note', '')}\n"
        msg += "\n"

    # サマリー
    msg += f"Summary: ENTRY={len(entry_ok)} SKIP={len(skips)} NO_DATA={len(no_data)} ERROR={len(errors)}\n"
    msg += "event_risk=manual_check (confirm before order)"

    return msg


def send_line_push(token: str, user_id: str, message: str) -> bool:
    """
    LINE Messaging API で push メッセージを送信する。

    Returns:
        成功時 True
    """
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    body = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    r = requests.post(url, headers=headers, data=json.dumps(body), timeout=20)
    r.raise_for_status()
    return True


def send_daily_notification(
    signals: list,
    run_id: str,
    line_token: str,
    line_user_id: str,
    dry_run: bool = False,
) -> bool:
    """
    日次シグナル通知を送信する。

    Returns:
        成功時 True
    """
    message = format_daily_notification(signals, run_id)

    if dry_run:
        print("=== LINE通知 (dry-run) ===")
        print(message)
        print("=" * 40)
        return True

    return send_line_push(line_token, line_user_id, message)
