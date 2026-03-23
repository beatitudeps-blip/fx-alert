#!/usr/bin/env python3
"""
日次サマリーを data/reports/ にローカル保存する。

役割:
  1. NotebookLM 向け整形テキストの生成
  2. GAS Webhook 失敗時のバックアップ資料
  3. git commit で履歴として蓄積（GitHub上で閲覧可能）

Google API には一切依存しない。
Sheets/Docs 更新は GAS Webhook 側で行う。

使い方:
    python scripts/build_daily_summary.py
    python scripts/build_daily_summary.py --date 2026-03-20
    python scripts/build_daily_summary.py --dry-run
"""
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from summary_renderer import (
    load_daily_signal_log,
    filter_by_date,
    filter_recent_days,
    render_daily_summary_text,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

REPORTS_DIR = Path(__file__).parent.parent / "data" / "reports"


def get_today_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def save_local_summary(text: str, date_jst: str) -> Path:
    """data/reports/ にテキストファイルとして保存する。
    GAS 失敗時のバックアップとして git commit 対象にもなる。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = REPORTS_DIR / f"daily_summary_{date_jst}.txt"
    filepath.write_text(text, encoding="utf-8")
    logger.info("ローカル保存: %s", filepath)
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description="Build daily summary (local backup + GAS fallback)"
    )
    parser.add_argument("--date", type=str, default=None, help="対象日 (YYYY-MM-DD JST)")
    parser.add_argument("--dry-run", action="store_true", help="標準出力のみ（ファイル保存しない）")
    args = parser.parse_args()

    date_jst = args.date or get_today_jst()
    logger.info("=== Build Daily Summary ===")
    logger.info("Date: %s", date_jst)

    # データ読み込み
    all_rows = load_daily_signal_log()
    today_rows = filter_by_date(all_rows, date_jst)

    if not today_rows:
        logger.warning("対象日 %s のデータがありません", date_jst)
        sys.exit(0)

    recent_rows = filter_recent_days(all_rows, date_jst, days=5)

    run_id = today_rows[0].get("run_id", "")
    version = today_rows[0].get("version", "")

    text = render_daily_summary_text(
        date_jst=date_jst,
        today_rows=today_rows,
        recent_rows=recent_rows,
        run_id=run_id,
        version=version,
    )

    if args.dry_run:
        print(text)
        return

    # ローカル保存（常に実行 — GAS失敗時のバックアップ）
    save_local_summary(text, date_jst)
    print(text)
    logger.info("完了")


if __name__ == "__main__":
    main()
