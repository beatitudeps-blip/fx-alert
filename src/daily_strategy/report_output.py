"""
日次レポートMarkdown生成モジュール
data_spec.md セクション8 準拠
"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from src.daily_strategy import STRATEGY_VERSION

REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"


def write_daily_report(signals: list, run_id: str, output_dir: Path = None) -> str:
    """
    daily_signal_report_YYYYMMDD.md を生成する。

    Args:
        signals: シグナルレコードのリスト
        run_id: 実行ID
        output_dir: 出力ディレクトリ（デフォルトは data/reports/）

    Returns:
        生成されたファイルパス
    """
    if output_dir is None:
        output_dir = REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    now_utc = datetime.utcnow()
    jst = ZoneInfo("Asia/Tokyo")
    now_jst = now_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(jst)
    date_str = now_jst.strftime("%Y%m%d")
    filepath = output_dir / f"daily_signal_report_{date_str}.md"

    # サマリー集計
    entry_ok = sum(1 for s in signals if s.get("decision") == "ENTRY_OK")
    skip = sum(1 for s in signals if s.get("decision") == "SKIP")
    no_data = sum(1 for s in signals if s.get("decision") == "NO_DATA")
    error = sum(1 for s in signals if s.get("decision") == "ERROR")

    lines = [
        "# Daily Signal Report",
        "",
        f"- Run ID: {run_id}",
        f"- Run At (UTC): {now_utc.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Run Date (JST): {now_jst.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Strategy Version: {STRATEGY_VERSION}",
        "",
        "## Summary",
        f"- Total Pairs: {len(signals)}",
        f"- Entry OK: {entry_ok}",
        f"- Skip: {skip}",
        f"- No Data: {no_data}",
        f"- Error: {error}",
        "",
        "## Pair Details",
    ]

    for s in signals:
        pair = s.get("pair", "UNKNOWN")
        lines.append(f"### {pair}")
        lines.append("")

        decision = s.get("decision", "")
        lines.append(f"- **Decision: {decision}**")

        if s.get("weekly_trend"):
            lines.append(f"- Weekly Trend: {s['weekly_trend']}")
        if s.get("daily_trend"):
            lines.append(f"- Daily Trend: {s['daily_trend']}")
        if s.get("alignment"):
            lines.append(f"- Alignment: {s['alignment']}")

        if s.get("close_price") != "":
            lines.append(f"- Close: {s.get('close_price', '')}")
            lines.append(f"- Daily EMA20: {s.get('daily_ema20', '')}")
            lines.append(f"- Weekly EMA20: {s.get('weekly_ema20', '')}")
            lines.append(f"- ATR14: {s.get('atr14', '')}")

        if s.get("ema_distance_atr_ratio") != "":
            lines.append(f"- EMA Distance (ATR ratio): {s.get('ema_distance_atr_ratio', '')}")
            lines.append(f"- Pullback OK: {s.get('pullback_ok', '')}")

        if s.get("pattern_name"):
            lines.append(f"- Pattern: {s['pattern_name']}")

        if s.get("reason_codes"):
            lines.append(f"- Reason Codes: {s['reason_codes']}")

        if decision == "ENTRY_OK":
            lines.append(f"- Entry Side: {s.get('entry_side', '')}")
            lines.append(f"- Planned Entry: {s.get('planned_entry_price', '')}")
            lines.append(f"- Planned SL: {s.get('planned_sl_price', '')}")
            lines.append(f"- Planned TP1: {s.get('planned_tp1_price', '')}")
            lines.append(f"- Planned TP2: {s.get('planned_tp2_price', '')}")
            lines.append(f"- Risk (JPY): {s.get('planned_risk_jpy', '')}")
            lines.append(f"- Lot: {s.get('planned_lot', '')}")

        lines.append(f"- Event Risk: {s.get('event_risk', 'manual_check')}")

        if s.get("signal_note"):
            lines.append(f"- Note: {s['signal_note']}")

        lines.append("")

    content = "\n".join(lines)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return str(filepath)
