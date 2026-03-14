"""
ブローカーCSV取込オーケストレーション
implementation_plan.md フェーズ2 タスク9, 10 準拠
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from src.broker_import.minnafx_parser import parse_minnafx_csv
from src.broker_import.signal_matcher import match_fills_to_signals, load_entry_ok_signals
from src.broker_import.trade_aggregator import aggregate_trades
from src.broker_import.csv_output import (
    append_raw_fills_csv,
    load_existing_fill_ids,
    write_trades_summary_csv,
)
from src.daily_strategy.csv_output import append_error_log

UTC = timezone.utc
DATA_DIR = Path(__file__).parent.parent.parent / "data"


def import_minnafx_csv(
    csv_path,
    output_dir: Path = None,
    signals_csv: Path = None,
    skip_duplicates: bool = True,
    strategy_pairs_only: bool = False,
) -> dict:
    """みんなのFX約定履歴CSVを取り込み、raw_fills / trades_summary を更新する。

    Args:
        csv_path: みんなのFX約定履歴CSVパス
        output_dir: 出力先ディレクトリ
        signals_csv: signals.csv パス (シグナル紐付け用)
        skip_duplicates: 既存fill_idとの重複をスキップするか
        strategy_pairs_only: trades_summary で戦略対象通貨のみ集約するか

    Returns:
        実行結果サマリー辞書
    """
    if output_dir is None:
        output_dir = DATA_DIR

    csv_path = Path(csv_path)
    imported_at_utc = datetime.now(UTC)

    result = {
        "csv_path": str(csv_path),
        "imported_at_utc": imported_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_rows": 0,
        "imported": 0,
        "duplicates": 0,
        "parse_errors": 0,
        "matched_signals": 0,
        "trades_generated": 0,
        "errors": [],
    }

    # 1. CSV パース
    fills, parse_errors = parse_minnafx_csv(csv_path, imported_at_utc)
    result["total_rows"] = len(fills) + len(parse_errors)
    result["parse_errors"] = len(parse_errors)

    if parse_errors:
        append_error_log(parse_errors, output_dir)
        result["errors"].extend(parse_errors)

    if not fills:
        return result

    # 2. 重複チェック
    if skip_duplicates:
        existing_ids = load_existing_fill_ids(output_dir)
        new_fills = []
        for fill in fills:
            if fill["fill_id"] in existing_ids:
                fill["import_status"] = "DUPLICATE"
                result["duplicates"] += 1
            else:
                new_fills.append(fill)
        fills_to_import = new_fills
    else:
        fills_to_import = fills

    result["imported"] = len(fills_to_import)

    # 3. シグナル紐付け
    signals = load_entry_ok_signals(signals_csv)
    if signals:
        match_fills_to_signals(fills_to_import, signals)
        matched_count = sum(
            1 for f in fills_to_import
            if f.get("matched_signal_id", "")
        )
        result["matched_signals"] = matched_count

    # 4. raw_fills.csv 追記
    if fills_to_import:
        append_raw_fills_csv(fills_to_import, output_dir)

    # 5. trades_summary 集約 (全 fills を使って再生成)
    # 既存 raw_fills + 新規を合わせて集約するため、全件読み込み
    all_fills = _load_all_raw_fills(output_dir)
    trades = aggregate_trades(
        all_fills,
        signals=signals,
        strategy_pairs_only=strategy_pairs_only,
    )
    write_trades_summary_csv(trades, output_dir)
    result["trades_generated"] = len(trades)

    return result


def _load_all_raw_fills(output_dir: Path) -> List[dict]:
    """raw_fills.csv の全レコードを読み込む。"""
    import csv

    filepath = output_dir / "raw_fills.csv"
    if not filepath.exists():
        return []

    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)
