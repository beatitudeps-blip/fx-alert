"""
CSV出力モジュール
data_spec.md セクション4, 11, 15 準拠
"""
import csv
import logging
import os
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent.parent / "data"

logger = logging.getLogger(__name__)

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
    "estimated_cost_r", "estimated_cost_jpy",
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


# daily_signal_log.csv 列定義
DAILY_SIGNAL_LOG_COLUMNS = [
    "date_jst", "run_id", "version", "pair",
    "status", "reason_code", "reason_text",
    "direction", "entry", "sl", "tp1", "tp2",
    "atr", "ema20", "event_risk",
]

# reason_code → 日本語テキストマッピング
_REASON_TEXT = {
    "W": "週足環境NG",
    "D": "日足環境NG",
    "A": "週足/日足不整合",
    "P": "パターン不成立",
    "R": "RR不足",
    "X": "EMA乖離大",
    "S": "週足抵抗/支持近い",
    "E": "重要イベント",
    "O": "既存ポジションあり",
    "C": "総リスク/相関超過",
}


def _reason_codes_to_text(codes_str: str) -> str:
    """reason_code 文字列 (e.g. "W;D") を日本語テキストに変換する。"""
    if not codes_str:
        return ""
    codes = [c.strip() for c in codes_str.split(";") if c.strip()]
    texts = [_REASON_TEXT.get(c, c) for c in codes]
    return "; ".join(texts)


def append_daily_signal_log(signals: list, output_dir: Path = None):
    """
    daily_signal_log.csv に全通貨・全判定を1行ずつ追記する。
    ENTRY / SKIP / NO_DATA / ERROR すべてを保存する。
    例外で全体停止しないよう fail-safe で動作する。
    """
    try:
        if output_dir is None:
            output_dir = DATA_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        filepath = output_dir / "daily_signal_log.csv"

        file_exists = filepath.exists() and filepath.stat().st_size > 0

        with open(filepath, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f, fieldnames=DAILY_SIGNAL_LOG_COLUMNS, extrasaction="ignore"
            )
            if not file_exists:
                writer.writeheader()

            for sig in signals:
                decision = sig.get("decision", "")
                reason_codes = sig.get("reason_codes", "")

                # status マッピング: ENTRY_OK → ENTRY, それ以外はそのまま
                status = "ENTRY" if decision == "ENTRY_OK" else decision

                row = {
                    "date_jst": sig.get("generated_date_jst", ""),
                    "run_id": sig.get("run_id", ""),
                    "version": sig.get("strategy_version", ""),
                    "pair": sig.get("pair", ""),
                    "status": status,
                    "reason_code": reason_codes,
                    "reason_text": _reason_codes_to_text(reason_codes),
                    "direction": sig.get("entry_side", "") or sig.get("alignment", ""),
                    "entry": sig.get("planned_entry_price", ""),
                    "sl": sig.get("planned_sl_price", ""),
                    "tp1": sig.get("planned_tp1_price", ""),
                    "tp2": sig.get("planned_tp2_price", ""),
                    "atr": sig.get("atr14", ""),
                    "ema20": sig.get("daily_ema20", ""),
                    "event_risk": sig.get("event_risk", ""),
                }
                writer.writerow(row)

        logger.info("daily_signal_log.csv updated (%d rows)", len(signals))
    except Exception:
        logger.exception("Failed to write daily_signal_log.csv (non-fatal)")


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
