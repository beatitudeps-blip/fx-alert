#!/usr/bin/env python3
"""
日足/週足戦略 日次シグナル生成スクリプト
implementation_plan.md フェーズ1 メインエントリーポイント

usage:
    python scripts/run_daily_signal.py --equity 500000
    python scripts/run_daily_signal.py --equity 500000 --dry-run
"""
import os
import sys
import argparse
import traceback
from datetime import datetime
from pathlib import Path

# プロジェクトルートを sys.path に追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.daily_strategy import STRATEGY_VERSION
from src.daily_strategy.signal_builder import build_daily_signals
from src.daily_strategy.csv_output import append_signals_csv, append_error_log, append_daily_signal_log
from src.daily_strategy.report_output import write_daily_report
from src.daily_strategy.notifier import send_daily_notification
from src.daily_strategy.bar_checker import load_daily_state, save_daily_state

PAIRS = ["USD/JPY", "AUD/JPY"]


def parse_args():
    parser = argparse.ArgumentParser(description="Daily Signal Generator")
    parser.add_argument("--equity", type=float, default=500000.0, help="口座残高 (JPY)")
    parser.add_argument("--risk-pct", type=float, default=0.005, help="リスク率 (default: 0.005)")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml", help="ブローカー設定ファイル")
    parser.add_argument("--dry-run", action="store_true", help="LINE通知を送信しない")
    parser.add_argument("--force", action="store_true", help="日足未更新でも強制実行")
    return parser.parse_args()


def main():
    args = parse_args()
    run_id = f"RUN_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"

    print("=" * 50)
    print(f"Daily Signal Generator - {STRATEGY_VERSION}")
    print(f"Run ID: {run_id}")
    print(f"UTC: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Equity: {args.equity:,.0f} JPY")
    print(f"Risk: {args.risk_pct * 100:.1f}%")
    print(f"Pairs: {', '.join(PAIRS)}")
    print(f"Dry Run: {args.dry_run}")
    print("=" * 50)

    # 環境変数チェック
    api_key = os.environ.get("TWELVEDATA_API_KEY")
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.environ.get("LINE_USER_ID")

    if not api_key:
        print("ERROR: TWELVEDATA_API_KEY not set")
        sys.exit(1)
    if not args.dry_run and (not line_token or not line_user_id):
        print("ERROR: LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID not set")
        sys.exit(1)

    # ブローカー設定読み込み（任意）
    config = None
    try:
        from src.config_loader import load_broker_config
        config = load_broker_config(args.config)
        print(f"Config loaded: {args.config}")
    except Exception as e:
        print(f"WARN: Config load failed ({e}), using simple sizing")

    # 状態読み込み
    state = load_daily_state()
    print(f"State loaded: consecutive_losses={state.get('consecutive_losses', 0)}")
    print(f"Open positions: {list(state.get('open_positions', {}).keys())}")

    # シグナル生成
    print("\n--- Signal Generation ---")
    signals, errors = build_daily_signals(
        pairs=PAIRS,
        run_id=run_id,
        state=state,
        equity=args.equity,
        risk_pct=args.risk_pct,
        api_key=api_key,
        config=config,
    )

    # 結果表示
    for s in signals:
        decision = s.get("decision", "")
        pair = s.get("pair", "")
        reasons = s.get("reason_codes", "")
        print(f"  {pair}: {decision}" + (f" [{reasons}]" if reasons else ""))

    # CSV出力
    print("\n--- Output ---")
    append_signals_csv(signals)
    print("signals.csv updated")

    append_daily_signal_log(signals)
    print("daily_signal_log.csv updated")

    if errors:
        append_error_log(errors)
        print(f"error_log.csv updated ({len(errors)} errors)")

    # 日次レポート出力
    report_path = write_daily_report(signals, run_id)
    print(f"Report: {report_path}")

    # 状態保存
    save_daily_state(state)
    print("State saved")

    # LINE通知
    print("\n--- Notification ---")
    try:
        success = send_daily_notification(
            signals=signals,
            run_id=run_id,
            line_token=line_token or "",
            line_user_id=line_user_id or "",
            dry_run=args.dry_run,
        )
        if success:
            print("LINE notification sent" + (" (dry-run)" if args.dry_run else ""))
        else:
            print("LINE notification failed")
    except Exception as e:
        print(f"LINE notification error: {e}")
        errors.append({
            "error_id": f"ERR_NOTIFY_{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
            "run_id": run_id,
            "strategy_version": STRATEGY_VERSION,
            "occurred_at_utc": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stage": "NOTIFY",
            "severity": "ERROR",
            "error_type": type(e).__name__,
            "pair": "",
            "message": str(e),
        })
        append_error_log(errors[-1:])

    # 結果サマリー
    entry_ok = sum(1 for s in signals if s.get("decision") == "ENTRY_OK")
    skip = sum(1 for s in signals if s.get("decision") == "SKIP")
    no_data = sum(1 for s in signals if s.get("decision") == "NO_DATA")
    err_count = sum(1 for s in signals if s.get("decision") == "ERROR")

    print("\n--- Summary ---")
    print(f"ENTRY_OK: {entry_ok}")
    print(f"SKIP: {skip}")
    print(f"NO_DATA: {no_data}")
    print(f"ERROR: {err_count}")
    print(f"Total errors logged: {len(errors)}")
    print("=" * 50)

    if err_count > 0 or errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
