#!/usr/bin/env python3
"""
日次サマリーを Google Docs に出力するスクリプト。
NotebookLM向けに整形された「FX_Daily_Summary_Latest」ドキュメントを毎日上書き更新する。

使い方:
    python scripts/build_daily_summary.py
    python scripts/build_daily_summary.py --date 2026-03-20
    python scripts/build_daily_summary.py --dry-run
    python scripts/build_daily_summary.py --local-only  # ローカルファイル出力のみ

必要な環境変数:
    GOOGLE_SERVICE_ACCOUNT_JSON  (GitHub Secrets) or
    GOOGLE_SERVICE_ACCOUNT_FILE  (ローカル)
    GOOGLE_DAILY_SUMMARY_DOC_ID
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
    """ローカルにもテキストファイルとして保存する。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = REPORTS_DIR / f"daily_summary_{date_jst}.txt"
    filepath.write_text(text, encoding="utf-8")
    logger.info("ローカル保存: %s", filepath)
    return filepath


def update_google_doc(text: str, doc_id: str):
    """
    Google Docs の本文を全て置き換える。
    既存の本文を削除してから新しいテキストを挿入する。
    """
    from google_client import get_docs_service

    service = get_docs_service()

    # 現在のドキュメントを取得して本文の長さを確認
    doc = service.documents().get(documentId=doc_id).execute()
    body = doc.get("body", {})
    content = body.get("content", [])

    # 本文の末尾インデックスを取得（最低でも1）
    end_index = 1
    if content:
        last_element = content[-1]
        end_index = last_element.get("endIndex", 1)

    requests = []

    # 既存本文を削除（endIndex > 2 なら削除可能）
    if end_index > 2:
        requests.append({
            "deleteContentRange": {
                "range": {
                    "startIndex": 1,
                    "endIndex": end_index - 1,
                }
            }
        })

    # 新しいテキストを挿入
    requests.append({
        "insertText": {
            "location": {"index": 1},
            "text": text,
        }
    })

    service.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()

    logger.info("Google Docs 更新完了: doc_id=%s", doc_id)


def main():
    parser = argparse.ArgumentParser(description="Build daily summary for NotebookLM")
    parser.add_argument("--date", type=str, default=None, help="対象日 (YYYY-MM-DD JST)")
    parser.add_argument("--dry-run", action="store_true", help="テキスト生成のみ（Docs更新しない）")
    parser.add_argument("--local-only", action="store_true", help="ローカルファイル出力のみ")
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

    # run_id / version は最初の行から取得
    run_id = today_rows[0].get("run_id", "")
    version = today_rows[0].get("version", "")

    # テキスト生成
    text = render_daily_summary_text(
        date_jst=date_jst,
        today_rows=today_rows,
        recent_rows=recent_rows,
        run_id=run_id,
        version=version,
    )

    # ローカル保存（常に実行）
    save_local_summary(text, date_jst)

    if args.dry_run:
        logger.info("[DRY-RUN] 生成テキスト:")
        print(text)
        return

    if args.local_only:
        logger.info("[LOCAL-ONLY] Google Docs 更新はスキップ")
        print(text)
        return

    # Google Docs 更新
    try:
        from google_client import get_env
        doc_id = get_env("GOOGLE_DAILY_SUMMARY_DOC_ID")
        update_google_doc(text, doc_id)
        logger.info("完了: Google Docs 更新成功")
    except Exception as e:
        logger.error("Google Docs 更新失敗: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
