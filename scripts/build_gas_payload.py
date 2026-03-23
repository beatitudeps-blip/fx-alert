#!/usr/bin/env python3
"""
daily_signal_log.csv から当日分を抽出し、GAS Webhook 用 JSON を生成する。
送信は GitHub Actions の curl ステップで行う。このスクリプトは生成専用。

使い方:
    python scripts/build_gas_payload.py
    python scripts/build_gas_payload.py --date 2026-03-20
    python scripts/build_gas_payload.py --dry-run

出力:
    data/gas_payload.json

必要な環境変数:
    GAS_SECRET  (token として JSON に埋め込む)
"""
import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from summary_renderer import load_daily_signal_log, filter_by_date

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def get_today_jst() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def _to_float_or_none(val):
    """数値文字列を float に変換。空文字列は None を返す。"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def build_payload(date_jst: str, token: str = "") -> dict:
    """
    当日の daily_signal_log.csv から GAS 送信用 JSON を組み立てる。
    """
    all_rows = load_daily_signal_log()
    today_rows = filter_by_date(all_rows, date_jst)

    if not today_rows:
        logger.warning("対象日 %s のデータがありません", date_jst)
        return {}

    # summary 集計
    summary = {"entry": 0, "skip": 0, "error": 0, "no_data": 0}
    for r in today_rows:
        status = r.get("status", "").upper()
        if status == "ENTRY":
            summary["entry"] += 1
        elif status == "SKIP":
            summary["skip"] += 1
        elif status == "ERROR":
            summary["error"] += 1
        elif status == "NO_DATA":
            summary["no_data"] += 1

    # rows 構築
    rows = []
    for r in today_rows:
        rows.append({
            "date_jst": r.get("date_jst", ""),
            "pair": r.get("pair", ""),
            "status": r.get("status", ""),
            "reason_code": r.get("reason_code", ""),
            "reason_text": r.get("reason_text", ""),
            "direction": r.get("direction", ""),
            "entry": _to_float_or_none(r.get("entry")),
            "sl": _to_float_or_none(r.get("sl")),
            "tp1": _to_float_or_none(r.get("tp1")),
            "tp2": _to_float_or_none(r.get("tp2")),
            "atr": _to_float_or_none(r.get("atr")),
            "ema20": _to_float_or_none(r.get("ema20")),
            "event_risk": r.get("event_risk", ""),
        })

    # run_id / version は最初の行から
    run_id = today_rows[0].get("run_id", "")
    version = today_rows[0].get("version", "")
    event_risk = today_rows[0].get("event_risk", "manual_check")

    return {
        "token": token,
        "date": date_jst,
        "run_id": run_id,
        "version": version,
        "event_risk": event_risk,
        "summary": summary,
        "rows": rows,
    }


def save_payload(payload: dict, output_dir: Path = None) -> Path:
    """JSON ファイルに保存する。"""
    if output_dir is None:
        output_dir = DATA_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    filepath = output_dir / "gas_payload.json"
    filepath.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Payload saved: %s", filepath)
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Build GAS webhook payload (JSON generation only)")
    parser.add_argument("--date", type=str, default=None, help="対象日 (YYYY-MM-DD JST)")
    parser.add_argument("--dry-run", action="store_true", help="標準出力に表示のみ（ファイル保存しない）")
    args = parser.parse_args()

    date_jst = args.date or get_today_jst()
    logger.info("=== Build GAS Payload ===")
    logger.info("Date: %s", date_jst)

    token = os.environ.get("GAS_SECRET", "")
    payload = build_payload(date_jst, token=token)

    if not payload:
        logger.warning("Payload is empty — no data for %s", date_jst)
        sys.exit(0)

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    save_payload(payload)
    logger.info("完了")


if __name__ == "__main__":
    main()
