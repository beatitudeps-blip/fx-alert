#!/usr/bin/env python3
"""
みんなのFX 約定履歴CSV取込スクリプト

使い方:
    python scripts/import_broker_csv.py path/to/minnafx_export.csv

オプション:
    --output-dir DIR     出力先ディレクトリ (default: data/)
    --signals-csv PATH   signals.csv パス (default: data/signals.csv)
    --no-dedup           重複チェックをスキップ
    --strategy-only      戦略対象通貨のみ trades_summary に含める
"""
import argparse
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.broker_import.importer import import_minnafx_csv


def main():
    parser = argparse.ArgumentParser(
        description="みんなのFX 約定履歴CSV取込"
    )
    parser.add_argument(
        "csv_path",
        type=str,
        help="みんなのFX約定履歴CSVファイルパス",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="出力先ディレクトリ (default: data/)",
    )
    parser.add_argument(
        "--signals-csv",
        type=str,
        default=None,
        help="signals.csv パス (default: data/signals.csv)",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="重複チェックをスキップ",
    )
    parser.add_argument(
        "--strategy-only",
        action="store_true",
        help="戦略対象通貨のみ trades_summary に含める",
    )

    args = parser.parse_args()

    csv_path = Path(args.csv_path)
    if not csv_path.exists():
        print(f"ERROR: ファイルが見つかりません: {csv_path}")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else None
    signals_csv = Path(args.signals_csv) if args.signals_csv else None

    print(f"取込開始: {csv_path}")
    result = import_minnafx_csv(
        csv_path=csv_path,
        output_dir=output_dir,
        signals_csv=signals_csv,
        skip_duplicates=not args.no_dedup,
        strategy_pairs_only=args.strategy_only,
    )

    print(f"\n=== 取込結果 ===")
    print(f"  ファイル:        {result['csv_path']}")
    print(f"  取込日時(UTC):   {result['imported_at_utc']}")
    print(f"  総行数:          {result['total_rows']}")
    print(f"  取込済み:        {result['imported']}")
    print(f"  重複スキップ:    {result['duplicates']}")
    print(f"  パースエラー:    {result['parse_errors']}")
    print(f"  シグナル紐付け:  {result['matched_signals']}")
    print(f"  トレード集約:    {result['trades_generated']}")

    if result["parse_errors"] > 0:
        print(f"\n  [WARN] {result['parse_errors']}件のパースエラー → error_log.csv に記録")

    if result["errors"]:
        for err in result["errors"][:5]:
            print(f"    - {err.get('message', '')}")

    print("\n完了")


if __name__ == "__main__":
    main()
