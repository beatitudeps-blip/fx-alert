"""
raw_fills.csv / trades_summary.csv 出力モジュール
data_spec.md セクション5, 6, 15 準拠
"""
import csv
from pathlib import Path
from typing import List, Set

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# raw_fills.csv 初期版必須列 (data_spec.md セクション15)
RAW_FILLS_COLUMNS = [
    "fill_id", "broker", "broker_account_name",
    "broker_raw_file_name", "broker_raw_row_no",
    "imported_at_utc", "execution_time_utc", "execution_time_jst",
    "pair", "side", "fill_type", "quantity", "price",
    "gross_realized_pnl_jpy", "net_realized_pnl_jpy",
    "swap_jpy", "fee_jpy", "commission_jpy",
    "order_type",
    "broker_position_id", "broker_order_id", "broker_deal_id",
    "trade_group_id", "matched_signal_id",
    "strategy_version", "import_status", "import_note",
    "created_by", "updated_at_utc",
]

# trades_summary.csv 初期版必須列 (data_spec.md セクション15)
TRADES_SUMMARY_COLUMNS = [
    "trade_id", "signal_id", "run_id", "strategy_version",
    "pair", "side", "status", "result",
    "signal_generated_at_utc", "notification_sent_at_utc",
    "order_submitted_at_utc",
    "entry_time_utc", "exit_time_utc", "pair_trade_date_jst",
    "entry_price_planned", "entry_price_actual", "entry_slippage",
    "exit_price_actual",
    "initial_sl_price", "tp1_price", "tp2_price",
    "breakeven_sl_enabled",
    "total_entry_quantity", "total_exit_quantity", "remaining_quantity",
    "risk_price", "risk_pips", "risk_jpy_planned", "risk_jpy_actual",
    "gross_pnl_jpy", "net_pnl_jpy", "pnl_r",
    "swap_jpy", "fee_jpy",
    "max_favorable_excursion", "max_adverse_excursion",
    "exit_reason",
    "tp1_hit", "tp2_hit", "sl_hit",
    "rule_violation", "violation_note",
    "event_risk_checked", "decision_source",
    "notes", "created_at_utc", "updated_at_utc",
]


def _format_value(val) -> str:
    if isinstance(val, bool):
        return "TRUE" if val else "FALSE"
    if val is None:
        return ""
    return str(val)


def write_raw_fills_csv(fills: List[dict], output_dir: Path = None):
    """raw_fills.csv を書き出す (全件上書き)。"""
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "raw_fills.csv"

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FILLS_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for fill in fills:
            row = {col: _format_value(fill.get(col, "")) for col in RAW_FILLS_COLUMNS}
            writer.writerow(row)


def append_raw_fills_csv(fills: List[dict], output_dir: Path = None):
    """raw_fills.csv にレコードを追記する。"""
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "raw_fills.csv"

    file_exists = filepath.exists() and filepath.stat().st_size > 0

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=RAW_FILLS_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for fill in fills:
            row = {col: _format_value(fill.get(col, "")) for col in RAW_FILLS_COLUMNS}
            writer.writerow(row)


def load_existing_fill_ids(output_dir: Path = None) -> Set[str]:
    """既存の raw_fills.csv から fill_id の集合を読み込む。"""
    if output_dir is None:
        output_dir = DATA_DIR
    filepath = output_dir / "raw_fills.csv"

    if not filepath.exists():
        return set()

    ids = set()
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            fid = row.get("fill_id", "").strip()
            if fid:
                ids.add(fid)
    return ids


def write_trades_summary_csv(trades: List[dict], output_dir: Path = None):
    """trades_summary.csv を書き出す (全件上書き)。"""
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "trades_summary.csv"

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=TRADES_SUMMARY_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for trade in trades:
            row = {col: _format_value(trade.get(col, "")) for col in TRADES_SUMMARY_COLUMNS}
            writer.writerow(row)
