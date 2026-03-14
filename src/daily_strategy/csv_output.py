"""
CSV出力モジュール
data_spec.md セクション4, 11, 15 準拠
"""
import csv
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"

# signals.csv 初期版必須列 (data_spec.md セクション15)
SIGNALS_COLUMNS = [
    "signal_id", "run_id", "strategy_version",
    "generated_at_utc", "generated_date_jst", "pair",
    "weekly_trend", "daily_trend", "alignment",
    "close_price", "daily_ema20", "weekly_ema20", "atr14",
    "ema_distance_abs", "ema_distance_atr_ratio", "pullback_ok",
    "pattern_name", "pattern_detected",
    "signal_high", "signal_low", "signal_range", "signal_range_atr_ratio",
    "weekly_room_price", "weekly_room_r",
    "event_risk", "position_status", "correlation_risk",
    "decision", "reason_codes",
    "entry_side", "planned_entry_price", "planned_sl_price",
    "planned_tp1_price", "planned_tp2_price",
    "planned_risk_jpy", "planned_lot",
    "signal_note",
]

# error_log.csv 列 (data_spec.md セクション11)
ERROR_LOG_COLUMNS = [
    "error_id", "run_id", "strategy_version",
    "occurred_at_utc", "stage", "severity",
    "error_type", "pair", "message", "detail",
    "retry_count", "resolved", "created_by",
]


def append_signals_csv(signals: list, output_dir: Path = None):
    """
    signals.csv にシグナルレコードを追記する。
    ファイルが存在しない場合はヘッダー付きで作成する。
    """
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "signals.csv"

    file_exists = filepath.exists() and filepath.stat().st_size > 0

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SIGNALS_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for signal in signals:
            row = {}
            for col in SIGNALS_COLUMNS:
                val = signal.get(col, "")
                if isinstance(val, bool):
                    row[col] = "TRUE" if val else "FALSE"
                else:
                    row[col] = val
            writer.writerow(row)


def append_error_log(errors: list, output_dir: Path = None):
    """
    error_log.csv にエラーレコードを追記する。
    ファイルが存在しない場合はヘッダー付きで作成する。
    """
    if not errors:
        return

    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "error_log.csv"

    file_exists = filepath.exists() and filepath.stat().st_size > 0

    with open(filepath, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ERROR_LOG_COLUMNS, extrasaction="ignore")
        if not file_exists:
            writer.writeheader()
        for error in errors:
            row = {col: error.get(col, "") for col in ERROR_LOG_COLUMNS}
            writer.writerow(row)
