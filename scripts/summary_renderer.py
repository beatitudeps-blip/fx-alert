#!/usr/bin/env python3
"""
シグナルログの読み込み・要約・テキスト生成を行う共通モジュール。

build_daily_summary.py / build_weekly_review.py 等から利用する。
"""
import csv
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_DIR = Path(__file__).parent.parent / "data"

# reason_code → 日本語
REASON_TEXT_MAP = {
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


def load_daily_signal_log(data_dir: Path = None) -> list[dict]:
    """daily_signal_log.csv を全行読み込む。"""
    if data_dir is None:
        data_dir = DATA_DIR
    filepath = data_dir / "daily_signal_log.csv"
    if not filepath.exists():
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def filter_by_date(rows: list[dict], date_jst: str) -> list[dict]:
    """指定日付の行だけ返す。"""
    return [r for r in rows if r.get("date_jst") == date_jst]


def filter_recent_days(rows: list[dict], date_jst: str, days: int = 5) -> list[dict]:
    """指定日から過去N営業日分の行を返す（日付ベース、厳密な営業日ではない）。"""
    target = datetime.strptime(date_jst, "%Y-%m-%d").date()
    start = target - timedelta(days=days * 2)  # 余裕をもって取得
    filtered = []
    dates_seen = set()
    for r in reversed(rows):
        d = r.get("date_jst", "")
        if not d:
            continue
        row_date = datetime.strptime(d, "%Y-%m-%d").date()
        if row_date > target or row_date < start:
            continue
        dates_seen.add(row_date)
        filtered.append(r)
    # 日付が多すぎたら直近N日分に絞る
    unique_dates = sorted(dates_seen, reverse=True)[:days]
    date_set = set(unique_dates)
    return [r for r in filtered if datetime.strptime(r["date_jst"], "%Y-%m-%d").date() in date_set]


def summarize_signals(rows: list[dict]) -> dict:
    """行リストから status 別件数を集計する。"""
    counter = Counter(r.get("status", "UNKNOWN") for r in rows)
    return {
        "total": len(rows),
        "entry": counter.get("ENTRY", 0),
        "skip": counter.get("SKIP", 0),
        "error": counter.get("ERROR", 0),
        "no_data": counter.get("NO_DATA", 0),
    }


def summarize_reason_codes(rows: list[dict]) -> Counter:
    """reason_code の出現回数を集計する。"""
    counter = Counter()
    for r in rows:
        codes = r.get("reason_code", "")
        if not codes:
            continue
        for c in codes.split(";"):
            c = c.strip()
            if c:
                counter[c] += 1
    return counter


def _interpret_pair(row: dict) -> str:
    """1通貨の判定結果を日本語で1行にまとめる。"""
    pair = row.get("pair", "?")
    status = row.get("status", "?")
    reason = row.get("reason_text", "") or row.get("reason_code", "")

    if status == "ENTRY":
        direction = row.get("direction", "")
        entry = row.get("entry", "")
        return f"{pair}: エントリー条件成立 ({direction} @ {entry})"
    elif status == "SKIP":
        return f"{pair}: 見送り ({reason})"
    elif status == "NO_DATA":
        return f"{pair}: データ不足のため判定不可"
    elif status == "ERROR":
        return f"{pair}: エラー発生"
    return f"{pair}: {status}"


def render_daily_summary_text(
    date_jst: str,
    today_rows: list[dict],
    recent_rows: list[dict],
    run_id: str = "",
    version: str = "",
) -> str:
    """
    日次サマリーをテキストとして生成する。
    Google Docs 本文としてそのまま使える形式。
    """
    lines = []

    # --- タイトル ---
    lines.append(f"FX Daily Summary - {date_jst} JST")
    lines.append("")

    # --- 1. Run Metadata ---
    lines.append("■ Run Metadata")
    if run_id:
        lines.append(f"  run_id: {run_id}")
    if version:
        lines.append(f"  version: {version}")
    jst_now = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S JST")
    lines.append(f"  execution_time: {jst_now}")
    event_risks = set(r.get("event_risk", "") for r in today_rows if r.get("event_risk"))
    lines.append(f"  event_risk: {', '.join(event_risks) if event_risks else 'none'}")
    lines.append("")

    # --- 2. Summary ---
    summary = summarize_signals(today_rows)
    lines.append("■ Summary")
    lines.append(f"  ENTRY: {summary['entry']} 件")
    lines.append(f"  SKIP:  {summary['skip']} 件")
    lines.append(f"  ERROR: {summary['error']} 件")
    lines.append(f"  NO_DATA: {summary['no_data']} 件")
    lines.append("")

    # --- 3. Pair Details ---
    lines.append("■ Pair Details")
    for row in today_rows:
        pair = row.get("pair", "?")
        status = row.get("status", "?")
        lines.append(f"  [{pair}] status={status}")
        if row.get("reason_code"):
            lines.append(f"    reason: {row['reason_code']} ({row.get('reason_text', '')})")
        if row.get("direction"):
            lines.append(f"    direction: {row['direction']}")
        if status == "ENTRY":
            lines.append(f"    entry={row.get('entry', '')}  sl={row.get('sl', '')}  tp1={row.get('tp1', '')}  tp2={row.get('tp2', '')}")
        if row.get("atr"):
            lines.append(f"    atr={row.get('atr', '')}  ema20={row.get('ema20', '')}")
        lines.append("")

    # --- 4. Interpretation ---
    lines.append("■ Interpretation")
    for row in today_rows:
        lines.append(f"  - {_interpret_pair(row)}")
    # 全SKIP/NO_DATAなら待機日
    if summary["entry"] == 0:
        lines.append("  → 本日は待機優先日")
    lines.append("")

    # --- 5. Recent Context ---
    if recent_rows:
        lines.append("■ Recent Context (直近5営業日)")
        recent_summary = summarize_signals(recent_rows)
        lines.append(f"  ENTRY: {recent_summary['entry']} 件")
        lines.append(f"  SKIP:  {recent_summary['skip']} 件")
        reason_counts = summarize_reason_codes(recent_rows)
        if reason_counts:
            top_reasons = reason_counts.most_common(5)
            reason_str = ", ".join(
                f"{REASON_TEXT_MAP.get(c, c)}({n})" for c, n in top_reasons
            )
            lines.append(f"  主な見送り理由: {reason_str}")
        lines.append("")

    return "\n".join(lines)


def render_weekly_review_text(
    week_start: str,
    week_end: str,
    week_rows: list[dict],
) -> str:
    """
    週次レビューをテキストとして生成する（将来用の骨格）。
    """
    lines = []
    lines.append(f"FX Weekly Review - {week_start} ~ {week_end} JST")
    lines.append("")

    summary = summarize_signals(week_rows)
    lines.append("■ Weekly Summary")
    lines.append(f"  対象日数: {len(set(r.get('date_jst') for r in week_rows))} 日")
    lines.append(f"  ENTRY: {summary['entry']} 件")
    lines.append(f"  SKIP:  {summary['skip']} 件")
    lines.append(f"  ERROR: {summary['error']} 件")
    lines.append("")

    reason_counts = summarize_reason_codes(week_rows)
    if reason_counts:
        lines.append("■ Reason Code 内訳")
        for code, count in reason_counts.most_common():
            lines.append(f"  {code} ({REASON_TEXT_MAP.get(code, code)}): {count}")
        lines.append("")

    lines.append("■ Daily Breakdown")
    dates = sorted(set(r.get("date_jst", "") for r in week_rows))
    for d in dates:
        day_rows = [r for r in week_rows if r.get("date_jst") == d]
        day_summary = summarize_signals(day_rows)
        statuses = f"ENTRY={day_summary['entry']} SKIP={day_summary['skip']}"
        lines.append(f"  {d}: {statuses}")
    lines.append("")

    return "\n".join(lines)
