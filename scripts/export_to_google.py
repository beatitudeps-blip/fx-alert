#!/usr/bin/env python3
"""
daily_signal_log.csv → Google Sheets 追記スクリプト

使い方:
    python scripts/export_to_google.py
    python scripts/export_to_google.py --date 2026-03-20
    python scripts/export_to_google.py --dry-run

必要な環境変数:
    GOOGLE_SERVICE_ACCOUNT_JSON  (GitHub Secrets) or
    GOOGLE_SERVICE_ACCOUNT_FILE  (ローカル)
    GOOGLE_SHEETS_SPREADSHEET_ID
"""
import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from google_client import get_gspread_client, get_env
from summary_renderer import load_daily_signal_log, filter_by_date, _extract_date

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

SHEET_NAME = "signals_log"
HEADER = [
    "date_jst", "run_id", "version", "pair",
    "status", "reason_code", "reason_text",
    "direction", "entry", "sl", "tp1", "tp2",
    "atr", "ema20", "event_risk",
]

MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds


def get_today_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def _retry(func, *args, **kwargs):
    """Google API 呼び出しを最大 MAX_RETRIES 回リトライする。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt == MAX_RETRIES:
                raise
            logger.warning("リトライ %d/%d: %s", attempt, MAX_RETRIES, e)
            time.sleep(RETRY_DELAY * attempt)


def export_to_sheets(date_jst: str, dry_run: bool = False) -> int:
    """
    指定日の daily_signal_log 行を Google Sheets に追記する。
    重複判定: date_jst(日付部分) + pair + run_id の組み合わせ。
    Returns: 追記した行数。
    """
    # ローカルCSVから対象日のデータを取得
    all_rows = load_daily_signal_log()
    target_rows = filter_by_date(all_rows, date_jst)

    if not target_rows:
        logger.warning("対象日 %s のデータが daily_signal_log.csv にありません", date_jst)
        return 0

    logger.info("対象日 %s: %d 行を検出", date_jst, len(target_rows))

    if dry_run:
        logger.info("[DRY-RUN] 以下の行を追記予定:")
        for r in target_rows:
            logger.info("  %s / %s / %s", r.get("date_jst"), r.get("pair"), r.get("status"))
        return len(target_rows)

    # Google Sheets に接続
    spreadsheet_id = get_env("GOOGLE_SHEETS_SPREADSHEET_ID")
    client = _retry(get_gspread_client)
    spreadsheet = _retry(client.open_by_key, spreadsheet_id)

    # シートを取得または作成
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except Exception:
        logger.info("シート '%s' が存在しないため作成します", SHEET_NAME)
        worksheet = _retry(
            spreadsheet.add_worksheet, title=SHEET_NAME, rows=1000, cols=len(HEADER)
        )
        _retry(worksheet.append_row, HEADER, value_input_option="RAW")

    # 既存データから重複チェック用キーを取得
    existing = _retry(worksheet.get_all_records)
    existing_keys = set()
    for row in existing:
        key = (
            _extract_date(str(row.get("date_jst", ""))),
            str(row.get("pair", "")),
            str(row.get("run_id", "")),
        )
        existing_keys.add(key)

    # 重複を除外して追記
    new_rows = []
    for r in target_rows:
        key = (
            _extract_date(r.get("date_jst", "")),
            r.get("pair", ""),
            r.get("run_id", ""),
        )
        if key in existing_keys:
            logger.info("重複スキップ: %s", key)
            continue
        row_values = [r.get(col, "") for col in HEADER]
        new_rows.append(row_values)

    if not new_rows:
        logger.info("追記する新規行はありません（全て重複）")
        return 0

    _retry(worksheet.append_rows, new_rows, value_input_option="RAW")
    logger.info("Google Sheets に %d 行追記しました", len(new_rows))
    return len(new_rows)


def main():
    parser = argparse.ArgumentParser(description="Export daily signal log to Google Sheets")
    parser.add_argument("--date", type=str, default=None, help="対象日 (YYYY-MM-DD JST)")
    parser.add_argument("--dry-run", action="store_true", help="実際にはSheets更新しない")
    args = parser.parse_args()

    date_jst = args.date or get_today_jst()
    logger.info("=== Export to Google Sheets ===")
    logger.info("Date: %s", date_jst)

    try:
        count = export_to_sheets(date_jst, dry_run=args.dry_run)
        logger.info("完了: %d 行追記", count)
    except Exception as e:
        logger.error("Google Sheets エクスポート失敗: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
