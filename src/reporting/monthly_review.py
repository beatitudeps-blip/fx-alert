"""
月次レビュー生成モジュール
data_spec.md セクション10 準拠
"""
from datetime import datetime
from calendar import monthrange
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


def generate_monthly_review(
    year_month: str,
    signals: Optional[List[dict]] = None,
    trades: Optional[List[dict]] = None,
    output_dir: Optional[Path] = None,
) -> str:
    """月次レビューMarkdownを生成する。

    Args:
        year_month: 対象月 YYYY-MM
        signals: シグナルリスト (省略時はCSV読み込み)
        trades: トレードリスト (省略時はCSV読み込み)
        output_dir: 出力先

    Returns:
        生成ファイルパス
    """
    if output_dir is None:
        output_dir = REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # 対象月の計算
    year, month = map(int, year_month.split("-"))
    _, last_day = monthrange(year, month)
    start_date = f"{year:04d}-{month:02d}-01"
    end_date = f"{year:04d}-{month:02d}-{last_day:02d}"

    if signals is None:
        signals = load_signals()
    if trades is None:
        trades = load_trades()

    month_signals = filter_signals_by_period(signals, start_date, end_date)
    month_trades = filter_trades_by_period(trades, start_date, end_date)

    sig_kpi = compute_signal_kpi(month_signals)
    reason_codes = compute_reason_code_breakdown(month_signals)
    trade_kpi = compute_trade_kpi(month_trades)
    pair_kpi = compute_per_pair_kpi(month_trades)

    suggestions = _suggest_improvements(
        sig_kpi, reason_codes, trade_kpi, pair_kpi, month_trades
    )

    content = _render_monthly_markdown(
        year_month, sig_kpi, reason_codes, trade_kpi, pair_kpi, suggestions
    )

    filename = f"monthly_review_{year:04d}{month:02d}.md"
    filepath = output_dir / filename
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    return str(filepath)


def _render_monthly_markdown(
    year_month: str,
    sig_kpi: dict,
    reason_codes: dict,
    trade_kpi: dict,
    pair_kpi: dict,
    suggestions: Optional[List[str]] = None,
) -> str:
    lines = [
        "# Monthly Review",
        "",
        f"- Month: {year_month}",
        f"- Strategy Version: {STRATEGY_VERSION}",
        "",
        "## KPI",
        f"- Signals: {sig_kpi['total_signals']}",
        f"- Entry OK: {sig_kpi['entry_ok']}",
        f"- Skip: {sig_kpi['skip']}",
        f"- Executed Trades: {trade_kpi['closed_trades']}",
        f"- Open Trades: {trade_kpi['open_trades']}",
        f"- Win: {trade_kpi['win']}",
        f"- Loss: {trade_kpi['loss']}",
        f"- Breakeven: {trade_kpi['breakeven']}",
        f"- Win Rate: {trade_kpi['win_rate']}%",
        f"- Profit Factor: {trade_kpi['profit_factor']}",
        f"- Gross PnL: {trade_kpi['gross_pnl_jpy']:,.0f} JPY",
        f"- Net PnL: {trade_kpi['net_pnl_jpy']:,.0f} JPY",
        f"- Swap: {trade_kpi['swap_jpy']:,.0f} JPY",
        f"- Total R: {trade_kpi['total_r']}",
        f"- Average R: {trade_kpi['avg_r']}",
        f"- Average Win: {trade_kpi['avg_win_jpy']:,.0f} JPY",
        f"- Average Loss: {trade_kpi['avg_loss_jpy']:,.0f} JPY",
        f"- Max Win: {trade_kpi['max_win_jpy']:,.0f} JPY",
        f"- Max Loss: {trade_kpi['max_loss_jpy']:,.0f} JPY",
        f"- Max Losing Streak: {trade_kpi['max_losing_streak']}",
        f"- Max Drawdown: {trade_kpi['max_drawdown_jpy']:,.0f} JPY",
        "",
    ]

    # By Pair
    lines.append("## By Pair")
    if pair_kpi:
        for pair, kpi in pair_kpi.items():
            lines.append(
                f"- {pair}: {kpi['win']}W/{kpi['loss']}L "
                f"({kpi['win_rate']}%) "
                f"Net {kpi['net_pnl_jpy']:,.0f} JPY "
                f"R={kpi['total_r']}"
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

    # Improvement Candidates
    lines.append("## Improvement Candidates")
    if suggestions:
        for i, s in enumerate(suggestions, 1):
            lines.append(f"{i}. {s}")
    else:
        lines.append("- (none detected)")
    lines.append("")

    return "\n".join(lines)


def _suggest_improvements(
    sig_kpi: dict,
    reason_codes: dict,
    trade_kpi: dict,
    pair_kpi: dict,
    trades: List[dict],
) -> List[str]:
    """KPI・トレードデータからルールベースの改善候補を自動生成する。"""
    suggestions = []  # type: List[str]

    # 1. 勝率が40%未満
    if trade_kpi["closed_trades"] >= 3 and trade_kpi["win_rate"] < 40:
        suggestions.append(
            f"Win rate {trade_kpi['win_rate']}% is below 40%. "
            "Review entry criteria or pattern filters."
        )

    # 2. Profit Factor < 1.0
    pf = trade_kpi["profit_factor"]
    if trade_kpi["closed_trades"] >= 3 and pf != "inf" and isinstance(pf, (int, float)) and pf < 1.0:
        suggestions.append(
            f"Profit Factor {pf} is below 1.0. "
            "Evaluate if losses are too large relative to wins."
        )

    # 3. 最大連敗 >= 3
    if trade_kpi["max_losing_streak"] >= 3:
        suggestions.append(
            f"Max losing streak reached {trade_kpi['max_losing_streak']}. "
            "Consider pausing new entries per strategy rule."
        )

    # 4. Average R が負
    if trade_kpi["closed_trades"] >= 3 and trade_kpi["avg_r"] < 0:
        suggestions.append(
            f"Average R is {trade_kpi['avg_r']}. "
            "Risk-reward balance needs review."
        )

    # 5. 特定通貨ペアの成績不良
    for pair, kpi in pair_kpi.items():
        if kpi["closed_trades"] >= 2 and kpi["win_rate"] == 0:
            suggestions.append(
                f"{pair}: 0% win rate ({kpi['loss']}L). "
                "Consider suspending or reviewing this pair."
            )

    # 6. SL到達率が高い (exit_reason ベース)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    if closed:
        sl_count = sum(1 for t in closed if t.get("exit_reason") == "SL")
        sl_pct = sl_count / len(closed) * 100
        if len(closed) >= 3 and sl_pct >= 60:
            suggestions.append(
                f"SL hit rate is {sl_pct:.0f}% ({sl_count}/{len(closed)}). "
                "Entry timing or SL placement may need adjustment."
            )

    # 7. MANUAL 決済が多い
    if closed:
        manual_count = sum(1 for t in closed if t.get("exit_reason") == "MANUAL")
        manual_pct = manual_count / len(closed) * 100
        if len(closed) >= 3 and manual_pct >= 50:
            suggestions.append(
                f"Manual exits account for {manual_pct:.0f}% ({manual_count}/{len(closed)}). "
                "Review adherence to TP1/TP2/SL plan."
            )

    # 8. ルール違反
    if trade_kpi["rule_violations"] > 0:
        suggestions.append(
            f"{trade_kpi['rule_violations']} rule violation(s) detected. "
            "Review discipline and process."
        )

    # 9. Skip理由の偏り (最頻出が全体の50%超)
    if reason_codes:
        total_skips = sum(reason_codes.values())
        if total_skips >= 5:
            max_code = max(reason_codes, key=reason_codes.get)
            max_count = reason_codes[max_code]
            max_pct = max_count / total_skips * 100
            if max_pct >= 50:
                label = REASON_CODE_LABELS.get(max_code, max_code)
                suggestions.append(
                    f"Skip reason '{max_code}' ({label}) dominates at "
                    f"{max_pct:.0f}% ({max_count}/{total_skips}). "
                    "Investigate if market regime has shifted."
                )

    return suggestions
