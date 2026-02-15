"""
見送り通知の実際のLINE送信テスト

実行前に環境変数を設定してください：
  export LINE_CHANNEL_ACCESS_TOKEN="your_token"
  export LINE_USER_ID="your_user_id"
"""
import os
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists
from src.config_loader import load_broker_config
from src.notify_line import LineNotifier

# .envファイルを読み込む（存在すれば）
load_dotenv_if_exists()


def test_skip_notification():
    """見送り通知をLINEに実際に送信するテスト"""
    print("=" * 80)
    print("📱 見送り通知のLINE送信テスト")
    print("=" * 80)

    # 環境変数チェック
    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    line_user_id = os.environ.get("LINE_USER_ID")

    if not line_token or not line_user_id:
        print("\n❌ エラー: LINE認証情報が設定されていません")
        print("\n以下の環境変数を設定してください：")
        print("  export LINE_CHANNEL_ACCESS_TOKEN=\"your_token\"")
        print("  export LINE_USER_ID=\"your_user_id\"")
        print("\nまたは .env ファイルに設定してください。")
        return

    print(f"\n✅ LINE認証情報: OK")
    print(f"  Token: {line_token[:20]}...")
    print(f"  User ID: {line_user_id}")

    # 設定読み込み
    config = load_broker_config("config/minnafx.yaml")

    # LINE通知（実際の認証情報）
    notifier = LineNotifier(
        line_token=line_token,
        line_user_id=line_user_id,
        config=config,
        state_file="data/test_line_skip_state.json"
    )

    # テスト時刻
    run_dt = datetime.now(ZoneInfo("Asia/Tokyo"))
    bar_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    print(f"\n実行時刻: {run_dt.strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f"確定4H足: {bar_dt.strftime('%Y-%m-%d %H:%M JST')}")

    # テストケース: シグナル1、見送り2（各種理由コードを含む）
    print("\n" + "=" * 80)
    print("📊 テストケース: シグナル1通貨 + 見送り2通貨")
    print("=" * 80)

    # state_fileを削除してリセット
    state_file = Path("data/test_line_skip_state.json")
    if state_file.exists():
        state_file.unlink()
        print("  📝 state_fileリセット完了")

    results = [
        {
            "symbol": "EUR/JPY",
            "status": "SIGNAL",
            "side": "LONG",
            "pattern": "Bullish Engulfing",
            "entry_price_mid": 163.245,
            "sl_price_mid": 163.195,
            "tp1_price_mid": 163.295,
            "tp2_price_mid": 163.345,
            "atr": 0.050,
            "ema20": 163.150,
        },
        {
            "symbol": "USD/JPY",
            "status": "SKIP",
            "reason": "日足環境NG（レンジ）",
        },
        {
            "symbol": "GBP/JPY",
            "status": "SKIP",
            "reason": "スプレッド超過",
            "spread_pips": 14.9,
            "threshold_pips": 2.25
        },
    ]

    # メッセージ生成
    try:
        msg = notifier.create_batch_message(
            run_dt=run_dt,
            bar_dt=bar_dt,
            results=results,
            equity_jpy=100000.0,
            risk_pct=0.005
        )
    except Exception as e:
        print(f"❌ メッセージ生成エラー: {e}")
        import traceback
        traceback.print_exc()
        return

    if not msg:
        print("❌ メッセージ生成失敗（Noneが返された）")
        return

    print("\n✅ メッセージ生成成功")
    print("\n" + "=" * 80)
    print("送信するメッセージ:")
    print("=" * 80)
    print(msg)
    print("=" * 80)

    # 自動実行モード（コマンドライン引数で制御可能）
    auto_send = len(sys.argv) > 1 and sys.argv[1] == '--auto'

    if not auto_send:
        print("\n🚨 これからLINEに実際に送信します。")
        try:
            response = input("送信してよろしいですか？ [y/N]: ")
            if response.lower() != 'y':
                print("❌ キャンセルしました")
                return
        except (EOFError, KeyboardInterrupt):
            # 非対話的環境では自動実行
            print("\n⚠️ 非対話的環境を検出。自動送信します...")
            auto_send = True
    else:
        print("\n🚀 自動送信モード（--auto）")

    # 実際に送信
    print("\n📤 LINEに送信中...")
    success = notifier.send_line(msg)

    if success:
        print("✅ LINE送信成功！")
        print("\n📱 LINEアプリを確認してください。")
        print("   見送り理由コードが正しく表示されているか確認してください：")
        print("     ・USD/JPY: [E] 日足環境NG")
        print("     ・GBP/JPY: [S] 14.9pips > 2.2pips")
    else:
        print("❌ LINE送信失敗")
        print("   エラー内容を確認してください。")

    print("\n" + "=" * 80)
    print("✅ テスト完了")
    print("=" * 80)


if __name__ == "__main__":
    test_skip_notification()
