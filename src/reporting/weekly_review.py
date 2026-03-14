"""
週次レビュー生成モジュール
data_spec.md セクション9 準拠
"""
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

from src.daily_strategy import STRATEGY_VERSION
from src.reporting.kpi import (
    load_signals,
    load_trades,
    filter_signals_by_period,
    filter_trades_by_period,
    compute_signal_kpi,
    compute_reason_code_breakdown,
    compute_trade_kpi,
    compute_per_pair_kpi,
)

JST = ZoneInfo("Asia/Tokyo")
REPORTS_DIR = Path(__file__).parent.parent.parent / "data" / "reports"

# 理由コードの説明
REASON_CODE_LABELS = {
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


def generate_weekly_review(
    week_end_date: str,
    signals: Optional[List[dict]] = None,
    trades: Optional[List[dict]] = None,
    output_dir: Optional[Path] = None,
) -> str:
    """週次レビューMarkdownを生成する。

    Args:
        week_end_date: 週末日 YYYY-MM-DD (この日を含む週)
        signals: シグナルリスト (省略時はCSV読み込み)
        trades: トレードリスト (省略時はCSV読み込み)
        output_dir: 出力先

    Returns:
        生成ファイルパス
    """
    if output_dir is None:
        output_dir = REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # 対象週の計算 (月曜〜日曜)
    end_dt = datetime.strptime(week_end_date, "%Y-%m-%d")
    weekday = end_dt.weekday()  # 0=Mon, 6=Sun
    week_start = end_dt - timedelta(days=weekday)
    week_end = week_start + timedelta(days=6)
    start_date = week_start.strftime("%Y-%m-%d")
    end_date = week_end.strftime("%Y-%m-%d")

    if signals is None:
        signals = load_signals()
    if trades is None:
        trades = load_trades()

    week_signals = filter_signals_by_period(signals, start_date, end_date)
    week_trades = filter_trades_by_period(trades, start_date, end_date)

    sig_kpi = compute_signal_kpi(week_signals)
    reason_codes = compute_reason_code_breakdown(week_signals)
    trade_kpi = compute_trade_kpi(week_trades)
    pair_kpi = compute_per_pair_kpi(week_trades)

    content = _render_weekly_markdown(
        start_date, end_date, sig_kpi, reason_codes, trade_kpi, pair_kpi
    )

    filename = f"weekly_review_{week_end.strftime('%Y%m%d')}.md"
    filepath = output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return str(filepath)


def _render_weekly_markdown(
    start_date: str,
    end_date: str,
    sig_kpi: dict,
    reason_codes: dict,
    trade_kpi: dict,
    pair_kpi: dict,
) -> str:
    lines = [
        "# Weekly Review",
        "",
        f"- Period: {start_date} ~ {end_date}",
        f"- Strategy Version: {STRATEGY_VERSION}",
        "",
        "## Signal Summary",
        f"- Signals: {sig_kpi['total_signals']}",
        f"- Entry OK: {sig_kpi['entry_ok']}",
        f"- Skip: {sig_kpi['skip']}",
        f"- No Data: {sig_kpi['no_data']}",
        f"- Error: {sig_kpi['error']}",
        "",
        "## KPI",
        f"- Executed Trades: {trade_kpi['closed_trades']}",
        f"- Open Trades: {trade_kpi['open_trades']}",
        f"- Win: {trade_kpi['win']}",
        f"- Loss: {trade_kpi['loss']}",
        f"- Breakeven: {trade_kpi['breakeven']}",
        f"- Win Rate: {trade_kpi['win_rate']}%",
        f"- Gross PnL: {trade_kpi['gross_pnl_jpy']:,.0f} JPY",
        f"- Net PnL: {trade_kpi['net_pnl_jpy']:,.0f} JPY",
        f"- Swap: {trade_kpi['swap_jpy']:,.0f} JPY",
        f"- Total R: {trade_kpi['total_r']}",
        f"- Average R: {trade_kpi['avg_r']}",
        "",
    ]

    # By Pair
    lines.append("## By Pair")
    if pair_kpi:
        for pair, kpi in pair_kpi.items():
            lines.append(
                f"- {pair}: {kpi['win']}W/{kpi['loss']}L "
                f"({kpi['win_rate']}%) "
                f"Net {kpi['net_pnl_jpy']:,.0f} JPY"
            )
    else:
        lines.append("- (no trades)")
    lines.append("")

    # Skip Reason Breakdown
    lines.append("## Skip Reason Breakdown")
    if reason_codes:
        for code, count in reason_codes.items():
            label = REASON_CODE_LABELS.get(code, "")
            lines.append(f"- {code} ({label}): {count}")
    else:
        lines.append("- (none)")
    lines.append("")

    # Rule Violations
    lines.append("## Rule Violations")
    lines.append(f"- Count: {trade_kpi['rule_violations']}")
    if trade_kpi["violation_details"]:
        for v in trade_kpi["violation_details"]:
            lines.append(f"  - {v['trade_id']}: {v['note']}")
    lines.append("")

    # Notes
    lines.append("## Notes")
    lines.append("- (manual entry)")
    lines.append("")

    return "\n".join(lines)
