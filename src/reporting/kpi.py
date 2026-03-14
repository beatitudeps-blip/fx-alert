"""
KPI集計モジュール
data_spec.md セクション9, 10 準拠

signals.csv と trades_summary.csv から週次・月次KPIを算出する。
"""
import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

from src.daily_strategy import STRATEGY_VERSION

UTC = timezone.utc
JST = ZoneInfo("Asia/Tokyo")
DATA_DIR = Path(__file__).parent.parent.parent / "data"

# 戦略対象通貨ペア
STRATEGY_PAIRS = {"USDJPY", "EURJPY", "GBPJPY"}


# --- CSV ローダー ---

def load_signals(csv_path: Optional[Path] = None) -> List[dict]:
    if csv_path is None:
        csv_path = DATA_DIR / "signals.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_trades(csv_path: Optional[Path] = None) -> List[dict]:
    if csv_path is None:
        csv_path = DATA_DIR / "trades_summary.csv"
    if not csv_path.exists():
        return []
    with open(csv_path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# --- 期間フィルター ---

def _parse_date(s: str) -> Optional[str]:
    """日付文字列をYYYY-MM-DD形式に正規化する。"""
    s = s.strip()
    if not s:
        return None
    # YYYY-MM-DDTHH:MM:SSZ → YYYY-MM-DD
    if "T" in s:
        return s[:10]
    return s[:10]


def filter_signals_by_period(
    signals: List[dict],
    start_date: str,
    end_date: str,
    strategy_pairs_only: bool = True,
) -> List[dict]:
    """シグナルを期間でフィルターする。日付はJSTベース(generated_date_jst)。"""
    filtered = []
    for s in signals:
        date = s.get("generated_date_jst", "")
        if not date:
            date = _parse_date(s.get("generated_at_utc", ""))
        if date and start_date <= date <= end_date:
            if strategy_pairs_only and s.get("pair", "") not in STRATEGY_PAIRS:
                continue
            filtered.append(s)
    return filtered


def filter_trades_by_period(
    trades: List[dict],
    start_date: str,
    end_date: str,
    strategy_pairs_only: bool = True,
) -> List[dict]:
    """トレードを期間でフィルターする。pair_trade_date_jstまたはentry_time_utcを使う。"""
    filtered = []
    for t in trades:
        date = t.get("pair_trade_date_jst", "")
        if not date:
            date = _parse_date(t.get("entry_time_utc", ""))
        if date and start_date <= date <= end_date:
            if strategy_pairs_only and t.get("pair", "") not in STRATEGY_PAIRS:
                continue
            filtered.append(t)
    return filtered


# --- KPI 算出 ---

def _to_float(val) -> float:
    if val is None or val == "":
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def compute_signal_kpi(signals: List[dict]) -> dict:
    """シグナル系KPIを算出する。"""
    total = len(signals)
    entry_ok = sum(1 for s in signals if s.get("decision") == "ENTRY_OK")
    skip = sum(1 for s in signals if s.get("decision") == "SKIP")
    no_data = sum(1 for s in signals if s.get("decision") == "NO_DATA")
    error = sum(1 for s in signals if s.get("decision") == "ERROR")

    return {
        "total_signals": total,
        "entry_ok": entry_ok,
        "skip": skip,
        "no_data": no_data,
        "error": error,
    }


def compute_reason_code_breakdown(signals: List[dict]) -> Dict[str, int]:
    """理由コード別件数を集計する。"""
    counter = Counter()  # type: Counter
    for s in signals:
        codes = s.get("reason_codes", "").strip()
        if not codes:
            continue
        for code in codes.split(";"):
            code = code.strip()
            if code:
                counter[code] += 1
    return dict(sorted(counter.items()))


def compute_trade_kpi(trades: List[dict]) -> dict:
    """トレード系KPIを算出する。"""
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    open_trades = [t for t in trades if t.get("status") == "OPEN"]

    wins = [t for t in closed if t.get("result") == "WIN"]
    losses = [t for t in closed if t.get("result") == "LOSS"]
    breakeven = [t for t in closed if t.get("result") == "BREAKEVEN"]

    total_closed = len(closed)
    win_count = len(wins)
    loss_count = len(losses)

    win_rate = (win_count / total_closed * 100) if total_closed > 0 else 0.0

    # PnL
    pnl_list = [_to_float(t.get("net_pnl_jpy", 0)) for t in closed]
    gross_pnl = sum(_to_float(t.get("gross_pnl_jpy", 0)) for t in closed)
    net_pnl = sum(pnl_list)
    swap_total = sum(_to_float(t.get("swap_jpy", 0)) for t in closed)
    fee_total = sum(_to_float(t.get("fee_jpy", 0)) for t in closed)

    # R値
    r_list = [_to_float(t.get("pnl_r", 0)) for t in closed if t.get("pnl_r", "") != ""]
    total_r = sum(r_list)
    avg_r = (total_r / len(r_list)) if r_list else 0.0

    # 平均利益/損失
    win_pnls = [_to_float(t.get("net_pnl_jpy", 0)) for t in wins]
    loss_pnls = [_to_float(t.get("net_pnl_jpy", 0)) for t in losses]
    avg_win = (sum(win_pnls) / len(win_pnls)) if win_pnls else 0.0
    avg_loss = (sum(loss_pnls) / len(loss_pnls)) if loss_pnls else 0.0
    max_win = max(win_pnls) if win_pnls else 0.0
    max_loss = min(loss_pnls) if loss_pnls else 0.0

    # Profit Factor
    gross_profit = sum(p for p in pnl_list if p > 0)
    gross_loss_abs = abs(sum(p for p in pnl_list if p < 0))
    pf = (gross_profit / gross_loss_abs) if gross_loss_abs > 0 else float("inf") if gross_profit > 0 else 0.0

    # 最大連敗
    max_losing_streak = _calc_max_losing_streak(closed)

    # 最大DD (簡易: 累積PnLベース)
    max_dd = _calc_max_drawdown(pnl_list)

    # ルール違反
    violations = [t for t in trades if t.get("rule_violation", "").upper() in ("TRUE", "1")]

    return {
        "total_trades": len(trades),
        "closed_trades": total_closed,
        "open_trades": len(open_trades),
        "win": win_count,
        "loss": loss_count,
        "breakeven": len(breakeven),
        "win_rate": round(win_rate, 1),
        "gross_pnl_jpy": round(gross_pnl, 2),
        "net_pnl_jpy": round(net_pnl, 2),
        "swap_jpy": round(swap_total, 2),
        "fee_jpy": round(fee_total, 2),
        "total_r": round(total_r, 3),
        "avg_r": round(avg_r, 3),
        "avg_win_jpy": round(avg_win, 2),
        "avg_loss_jpy": round(avg_loss, 2),
        "max_win_jpy": round(max_win, 2),
        "max_loss_jpy": round(max_loss, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
        "max_losing_streak": max_losing_streak,
        "max_drawdown_jpy": round(max_dd, 2),
        "rule_violations": len(violations),
        "violation_details": [
            {"trade_id": t.get("trade_id", ""), "note": t.get("violation_note", "")}
            for t in violations
        ],
    }


def compute_per_pair_kpi(trades: List[dict]) -> Dict[str, dict]:
    """通貨ペア別KPIを算出する。"""
    by_pair = defaultdict(list)  # type: Dict[str, List[dict]]
    for t in trades:
        pair = t.get("pair", "UNKNOWN")
        by_pair[pair].append(t)

    result = {}
    for pair in sorted(by_pair.keys()):
        result[pair] = compute_trade_kpi(by_pair[pair])
    return result


def _calc_max_losing_streak(closed_trades: List[dict]) -> int:
    """最大連敗数を計算する。"""
    max_streak = 0
    current = 0
    for t in closed_trades:
        if t.get("result") == "LOSS":
            current += 1
            max_streak = max(max_streak, current)
        else:
            current = 0
    return max_streak


def _calc_max_drawdown(pnl_list: List[float]) -> float:
    """累積PnLベースの最大ドローダウンを計算する。"""
    if not pnl_list:
        return 0.0
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_list:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd
