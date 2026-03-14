"""
日足更新確認モジュール
operations.md セクション5 準拠
"""
import json
from pathlib import Path
from datetime import datetime

STATE_FILE = Path(__file__).parent.parent.parent / "data" / "daily_state.json"


def load_daily_state() -> dict:
    """日次判定状態をロードする。"""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "last_processed_bar": {},
        "open_positions": {},
        "consecutive_losses": 0,
        "last_updated_utc": None,
    }


def save_daily_state(state: dict):
    """日次判定状態を保存する。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state["last_updated_utc"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, default=str)


def is_daily_bar_updated(daily_df, pair: str, state: dict) -> tuple:
    """
    最新日足が更新済みかを確認する。

    Args:
        daily_df: 日足 OHLC DataFrame (datetime列あり、昇順)
        pair: 通貨ペア (例: "USD/JPY")
        state: daily_state の辞書

    Returns:
        (is_updated: bool, latest_bar_dt: str or None)
        is_updated: 前回処理済みバーより新しいバーがあれば True
    """
    if daily_df is None or daily_df.empty:
        return False, None

    latest_bar_dt = str(daily_df["datetime"].iloc[-1])
    last_processed = state.get("last_processed_bar", {}).get(pair)

    if last_processed is None:
        return True, latest_bar_dt

    return latest_bar_dt != last_processed, latest_bar_dt


def mark_bar_processed(pair: str, bar_dt: str, state: dict):
    """処理済みバーを記録する。"""
    if "last_processed_bar" not in state:
        state["last_processed_bar"] = {}
    state["last_processed_bar"][pair] = bar_dt


def check_position_status(pair: str, state: dict) -> str:
    """
    既存ポジションの有無を確認する。

    Returns:
        "NO_POSITION" or "POSITION_EXISTS"
    """
    pair_key = pair.replace("/", "")
    positions = state.get("open_positions", {})
    if pair_key in positions or pair in positions:
        return "POSITION_EXISTS"
    return "NO_POSITION"


def check_correlation_risk(state: dict, max_positions: int = 2) -> str:
    """
    相関リスク（同時保有上限）を確認する。

    Returns:
        "OK", "EXCEEDED", "NOT_CHECKED"
    """
    positions = state.get("open_positions", {})
    if len(positions) >= max_positions:
        return "EXCEEDED"
    return "OK"


def check_consecutive_losses(state: dict, max_losses: int = 3) -> bool:
    """
    連敗による新規停止を確認する。

    Returns:
        True = 連敗上限に達しているため新規停止
    """
    return state.get("consecutive_losses", 0) >= max_losses
