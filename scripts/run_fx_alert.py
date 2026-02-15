"""
FXアラート実行スクリプト（GitHub Actions用）

4H足シグナルをチェックしてLINE通知を送信
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key, check_line_credentials
from src.config_loader import load_broker_config
from src.notify_line import LineNotifier
from src.signal_detector import detect_signals  # 実装が必要


def main():
    parser = argparse.ArgumentParser(description="FXアラートシステム")
    parser.add_argument("--symbols", type=str, required=True, help="通貨ペア（カンマ区切り）")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml", help="設定ファイル")
    parser.add_argument("--equity", type=float, default=500000.0, help="口座残高")
    parser.add_argument("--risk-pct", type=float, default=0.005, help="リスク率")
    parser.add_argument("--atr-mult", type=float, default=1.0, help="ATR倍率")
    parser.add_argument("--tp1-r", type=float, default=1.5, help="TP1のR倍数")
    parser.add_argument("--tp2-r", type=float, default=3.0, help="TP2のR倍数")
    parser.add_argument("--tp2-mode", type=str, default="FIXED_R", choices=["FIXED_R", "STRUCTURE"], help="TP2モード")
    parser.add_argument("--dry-run", action="store_true", help="Dry run（LINE通知なし）")

    args = parser.parse_args()

    # .env ファイルを読み込み（存在すれば）
    load_dotenv_if_exists()

    # API Key
    api_key = check_api_key(required=True)

    # LINE認証情報（dry-runでは不要）
    if not args.dry_run:
        line_token, line_user_id = check_line_credentials(required=True)
    else:
        line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy_token")
        line_user_id = os.getenv("LINE_USER_ID", "dummy_user_id")
        print("⚠️ DRY RUN モード: LINE通知は送信されません")

    # 設定読み込み
    config = load_broker_config(args.config)
    print(f"✅ 設定読み込み: {args.config}")

    # 通貨ペアリスト
    symbols = [s.strip() for s in args.symbols.split(",")]

    # LINE通知設定
    notifier = LineNotifier(
        line_token=line_token,
        line_user_id=line_user_id,
        config=config,
        state_file="data/notification_state.json"
    )

    # 実行時刻
    run_dt = datetime.now(ZoneInfo("Asia/Tokyo"))

    print(f"\n{'='*60}")
    print(f"FXアラートシステム")
    print(f"{'='*60}")
    print(f"実行時刻: {run_dt.strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print(f"口座残高: {args.equity:,.0f}円")
    print(f"リスク設定: {args.risk_pct*100:.1f}%")
    print(f"={'='*60}\n")

    # TODO: シグナル検出ロジックを実装
    # 現在は仮実装
    print("⚠️ 注意: シグナル検出ロジックは未実装です")
    print("   本番運用前に src/signal_detector.py を実装してください")
    
    # 仮の結果
    results = []
    for symbol in symbols:
        print(f"[{symbol}] シグナルチェック中...")
        # TODO: 実際のシグナル検出を実装
        # results.append({
        #     "symbol": symbol,
        #     "status": "NO_SIGNAL",
        #     "reason": "条件不一致"
        # })
        print(f"  ✅ チェック完了 (シグナルなし)")

    # 通知送信（シグナルがある場合）
    if results and not args.dry_run:
        # TODO: バッチメッセージ作成・送信
        # msg = notifier.create_batch_message(...)
        # notifier.send_line(msg)
        pass

    print(f"\n{'='*60}")
    print(f"✅ FXアラート実行完了")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
