#!/usr/bin/env python3
"""
週次 / 月次レビュー生成スクリプト

使い方:
    # 週次レビュー (指定日を含む週)
    python scripts/generate_review.py weekly 2026-03-09

    # 月次レビュー (指定月)
    python scripts/generate_review.py monthly 2026-03

    # 出力先指定
    python scripts/generate_review.py weekly 2026-03-09 --output-dir reports/
"""
import argparse
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.reporting.weekly_review import generate_weekly_review
from src.reporting.monthly_review import generate_monthly_review


def main():
    parser = argparse.ArgumentParser(
        description="週次 / 月次レビュー生成"
    )
    parser.add_argument(
        "type",
        choices=["weekly", "monthly"],
        help="レビュー種別",
    )
    parser.add_argument(
        "date",
        type=str,
        help="対象期間 (weekly: YYYY-MM-DD, monthly: YYYY-MM)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="出力先ディレクトリ (default: data/reports/)",
    )

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None

    if args.type == "weekly":
        filepath = generate_weekly_review(
            week_end_date=args.date,
            output_dir=output_dir,
        )
    else:
        filepath = generate_monthly_review(
            year_month=args.date,
            output_dir=output_dir,
        )

    print(f"レビュー生成完了: {filepath}")


if __name__ == "__main__":
    main()
