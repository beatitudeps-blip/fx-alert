"""
シグナル紐付けモジュール
data_spec.md セクション7 準拠

signals.csv の ENTRY_OK レコードと raw_fills の ENTRY レコードを
通貨ペア・約定日時の近さで紐付ける。
"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

UTC = timezone.utc
DATA_DIR = Path(__file__).parent.parent.parent / "data"

# エントリー約定から前後この時間以内のシグナルを候補とする
MATCH_WINDOW_HOURS = 48


def load_entry_ok_signals(signals_csv: Path = None) -> List[dict]:
    """signals.csv から ENTRY_OK レコードを読み込む。"""
    if signals_csv is None:
        signals_csv = DATA_DIR / "signals.csv"

    if not signals_csv.exists():
        return []

    signals = []
    with open(signals_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("decision") == "ENTRY_OK":
                signals.append(row)
    return signals


def _parse_utc(s: str) -> Optional[datetime]:
    """UTC 文字列をパースする。"""
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def match_fills_to_signals(
    fills: List[dict],
    signals: Optional[List[dict]] = None,
    signals_csv: Path = None,
) -> List[dict]:
    """raw_fills の ENTRY レコードに matched_signal_id を付与する。

    マッチング条件:
    1. pair が一致
    2. entry_side が一致
    3. 約定時刻がシグナル生成時刻から MATCH_WINDOW_HOURS 以内
    4. 複数候補がある場合は時間的に最も近いものを選択

    Returns:
        fills (破壊的に更新して返す)
    """
    if signals is None:
        signals = load_entry_ok_signals(signals_csv)

    if not signals:
        return fills

    # シグナルを pair → list でインデックス
    sig_by_pair = {}  # type: Dict[str, List[dict]]
    for sig in signals:
        pair = sig.get("pair", "")
        if pair not in sig_by_pair:
            sig_by_pair[pair] = []
        sig_by_pair[pair].append(sig)

    window = timedelta(hours=MATCH_WINDOW_HOURS)

    for fill in fills:
        if fill.get("fill_type") != "ENTRY":
            continue
        if fill.get("matched_signal_id", ""):
            continue

        pair = fill.get("pair", "")
        fill_utc = _parse_utc(fill.get("execution_time_utc", ""))
        if fill_utc is None:
            continue

        candidates = sig_by_pair.get(pair, [])
        best_sig = None
        best_delta = None

        for sig in candidates:
            sig_side = sig.get("entry_side", "")
            if sig_side != fill.get("side", ""):
                continue

            sig_utc = _parse_utc(sig.get("generated_at_utc", ""))
            if sig_utc is None:
                continue

            delta = abs(fill_utc - sig_utc)
            if delta > window:
                continue

            if best_delta is None or delta < best_delta:
                best_sig = sig
                best_delta = delta

        if best_sig is not None:
            fill["matched_signal_id"] = best_sig.get("signal_id", "")
            fill["import_status"] = "MATCHED"

    return fills
