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

    # シグナル検出
    print("📊 シグナル検出中...\n")
    signals = detect_signals(
        symbols=symbols,
        config=config,
        api_key=api_key,
        current_equity=args.equity,
        risk_pct=args.risk_pct,
        atr_multiplier=args.atr_mult,
        tp1_r=args.tp1_r,
        tp2_r=args.tp2_r,
        use_cache=False  # 本番では最新データを取得
    )

    # 結果を整形
    results = []
    bar_dt = None  # 確定4H足時刻（最初のシグナルから取得）

    for signal in signals:
        symbol = signal["symbol"]

        # bar_dt を保存（全通貨ペアで同じはず）
        if bar_dt is None and signal.get("bar_dt"):
            bar_dt = signal["bar_dt"]

        if signal.get("skip_reason"):
            # 見送り
            print(f"[{symbol}] ⏭️  見送り: {signal['skip_reason']}")
            results.append({
                "symbol": symbol,
                "status": "SKIP",
                "reason": signal["skip_reason"]
            })
        else:
            # シグナル検出
            print(f"[{symbol}] 🔔 {signal['signal']}シグナル検出!")
            print(f"  パターン: {signal['pattern']}")
            print(f"  エントリー: {signal['entry_price']:.3f}")
            print(f"  SL: {signal['sl_price']:.3f} ({signal['sl_pips']:.1f}pips)")
            print(f"  TP1: {signal['tp1_price']:.3f}")
            print(f"  TP2: {signal['tp2_price']:.3f}")
            print(f"  ロット: {signal['lots']:.1f} ({signal['units']}通貨)")
            print(f"  リスク: {signal['risk_jpy']:,.0f}円")

            results.append({
                "symbol": symbol,
                "status": "SIGNAL",
                "side": signal["signal"],
                "pattern": signal["pattern"],
                "entry_price": signal["entry_price"],
                "sl_price": signal["sl_price"],
                "tp1_price": signal["tp1_price"],
                "tp2_price": signal["tp2_price"],
                "sl_pips": signal["sl_pips"],
                "lots": signal["lots"],
                "units": signal["units"],
                "risk_jpy": signal["risk_jpy"],
                "atr": signal["atr"]
            })

    # 通知送信（シグナルがある場合、またはskipがある場合）
    if results and bar_dt:
        # バッチメッセージ作成
        msg = notifier.create_batch_message(
            run_dt=run_dt,
            bar_dt=bar_dt,
            results=results,
            equity_jpy=args.equity,
            risk_pct=args.risk_pct
        )

        if msg:
            if not args.dry_run:
                # 実際に送信
                success = notifier.send_line(msg)
                if success:
                    print("\n✅ LINE通知を送信しました")
                    notifier._mark_bar_sent(bar_dt)
                else:
                    print("\n❌ LINE通知の送信に失敗しました")
            else:
                # Dry run: メッセージだけ表示
                print("\n" + "="*60)
                print("📱 DRY RUN: 以下のメッセージが送信されます")
                print("="*60)
                print(msg)
                print("="*60)
        else:
            print("\n✅ 重複通知のためスキップしました")
    else:
        print("\n✅ 全通貨ペアでシグナルなし")

    print(f"\n{'='*60}")
    print(f"✅ FXアラート実行完了")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
