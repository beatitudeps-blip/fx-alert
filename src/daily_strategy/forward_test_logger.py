"""
フォワードテスト専用ロギングモジュール

シグナルのライフサイクルを追跡:
  signal issued → filled/not filled/expired → exit (SL/BE/TP2/TIME_STOP) → pnl記録
"""
import csv
from pathlib import Path
from datetime import datetime

DATA_DIR = Path(__file__).parent.parent.parent / "data"

FORWARD_TEST_COLUMNS = [
    "signal_id", "pair", "signal_date",
    "entry_side", "planned_entry_price", "planned_sl_price",
    "planned_tp1_price", "planned_tp2_price",
    "order_status",         # PENDING / FILLED / EXPIRED / CANCELLED
    "filled_date", "filled_price",
    "exit_date", "exit_price", "exit_reason",
    "holding_days",
    "pnl_r", "pnl_jpy",
    "risk_jpy", "lot",
    "tp1_reached", "tp1_date",
    "notes",
]

# フォワードテスト停止ルール
FORWARD_TEST_RULES = {
    "consecutive_loss_pause": 6,    # 6連敗で一時停止
    "max_dd_pct_pause": 10.0,       # DD 10%超で一時停止
    "min_trades_before_change": 20, # 最初の20トレードはパラメータ変更禁止
}


def append_forward_test_log(record: dict, output_dir: Path = None):
    """
    forward_test_log.csv にレコードを追記する。
    """
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "forward_test_log.csv"

    file_exists = filepath.exists() and filepath.stat().st_size > 0

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FORWARD_TEST_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        row = {col: record.get(col, "") for col in FORWARD_TEST_COLUMNS}
        writer.writerow(row)


def create_pending_record(signal: dict) -> dict:
    """
    ENTRY_OK シグナルから PENDING レコードを作成する。
    """
    return {
        "signal_id": signal.get("signal_id", ""),
        "pair": signal.get("pair", ""),
        "signal_date": signal.get("generated_date_jst", ""),
        "entry_side": signal.get("entry_side", ""),
        "planned_entry_price": signal.get("planned_entry_price", ""),
        "planned_sl_price": signal.get("planned_sl_price", ""),
        "planned_tp1_price": signal.get("planned_tp1_price", ""),
        "planned_tp2_price": signal.get("planned_tp2_price", ""),
        "order_status": "PENDING",
        "risk_jpy": signal.get("planned_risk_jpy", ""),
        "lot": signal.get("planned_lot", ""),
        "notes": "",
    }


def update_record_filled(record: dict, filled_date: str, filled_price: float) -> dict:
    """PENDING → FILLED に更新する。"""
    record["order_status"] = "FILLED"
    record["filled_date"] = filled_date
    record["filled_price"] = filled_price
    return record


def update_record_expired(record: dict, notes: str = "") -> dict:
    """PENDING → EXPIRED に更新する（1-bar expiry で未約定）。"""
    record["order_status"] = "EXPIRED"
    record["notes"] = notes or "1-bar limit order expired"
    return record


def update_record_exit(
    record: dict,
    exit_date: str,
    exit_price: float,
    exit_reason: str,
    holding_days: int,
    pnl_r: float,
    pnl_jpy: float,
    tp1_reached: bool = False,
    tp1_date: str = "",
) -> dict:
    """FILLED → 決済情報を記録する。"""
    record["exit_date"] = exit_date
    record["exit_price"] = exit_price
    record["exit_reason"] = exit_reason
    record["holding_days"] = holding_days
    record["pnl_r"] = round(pnl_r, 4)
    record["pnl_jpy"] = round(pnl_jpy, 2)
    record["tp1_reached"] = "TRUE" if tp1_reached else "FALSE"
    record["tp1_date"] = tp1_date
    return record


def check_forward_test_pause(state: dict, equity: float, initial_equity: float) -> tuple:
    """
    フォワードテスト停止ルールを確認する。

    Returns:
        (should_pause: bool, reason: str)
    """
    # 連敗チェック
    consec = state.get("consecutive_losses", 0)
    if consec >= FORWARD_TEST_RULES["consecutive_loss_pause"]:
        return True, f"consecutive_losses={consec} >= {FORWARD_TEST_RULES['consecutive_loss_pause']}"

    # DD チェック
    if initial_equity > 0:
        dd_pct = (initial_equity - equity) / initial_equity * 100
        if dd_pct > FORWARD_TEST_RULES["max_dd_pct_pause"]:
            return True, f"drawdown={dd_pct:.1f}% > {FORWARD_TEST_RULES['max_dd_pct_pause']}%"

    return False, ""
