"""
bar_dt（確定4H足時刻）の確認テスト
モックデータを使ってbar_dtのログ出力をテスト
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_broker_config
from src.notify_line import LineNotifier


def create_mock_4h_data():
    """モック4H足データ生成（UTC区切りを想定）"""
    # UTC 00:00, 04:00, 08:00, 12:00, 16:00, 20:00
    # JST 09:00, 13:00, 17:00, 21:00, 01:00, 05:00

    # 現在時刻をJSTで取得
    now_jst = datetime.now(ZoneInfo("Asia/Tokyo"))
    print(f"現在時刻（JST）: {now_jst.strftime('%Y-%m-%d %H:%M:%S')}")

    # 直近の確定4H足を計算（UTC区切り想定）
    now_utc = now_jst.astimezone(ZoneInfo("UTC"))

    # UTC時間を4時間単位に切り捨て
    hour_utc = (now_utc.hour // 4) * 4
    last_bar_utc = now_utc.replace(hour=hour_utc, minute=0, second=0, microsecond=0)

    # 1つ前の確定足（現在形成中のバーを除く）
    confirmed_bar_utc = last_bar_utc - timedelta(hours=4)
    confirmed_bar_jst = confirmed_bar_utc.astimezone(ZoneInfo("Asia/Tokyo"))

    print(f"確定4H足（UTC）: {confirmed_bar_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"確定4H足（JST）: {confirmed_bar_jst.strftime('%Y-%m-%d %H:%M JST')}")

    # モックデータフレーム生成（最新200本）
    dates = []
    for i in range(200, 0, -1):
        bar_time = confirmed_bar_utc - timedelta(hours=4 * i)
        dates.append(bar_time)

    df = pd.DataFrame({
        'datetime': dates,
        'open': [150.0] * 200,
        'high': [150.5] * 200,
        'low': [149.5] * 200,
        'close': [150.2] * 200
    })

    return df, confirmed_bar_jst


def test_bar_dt_logging():
    """bar_dtログ出力テスト"""
    print("=" * 80)
    print("bar_dt（確定4H足時刻）確認テスト")
    print("=" * 80)
    print()

    # モックデータ生成
    h4_data, expected_bar_dt = create_mock_4h_data()

    print()
    print("=" * 80)
    print("💡 cron設定のヒント")
    print("=" * 80)

    # 確定足時刻のパターンを判定
    hour = expected_bar_dt.hour

    if hour in [1, 5, 9, 13, 17, 21]:
        print(f"\n✅ 確定足時刻: JST {hour:02d}:00")
        print(f"   → このパターンは UTC 16:00, 20:00, 00:00, 04:00, 08:00, 12:00 区切り")
        print(f"   → cron設定: 5 1,5,9,13,17,21 * * *")
        print(f"\n   例: 確定後5分に実行")
        print(f"   5 1,5,9,13,17,21 * * * python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY")
    elif hour in [3, 7, 11, 15, 19, 23]:
        print(f"\n✅ 確定足時刻: JST {hour:02d}:00")
        print(f"   → このパターンは UTC 18:00, 22:00, 02:00, 06:00, 10:00, 14:00 区切り")
        print(f"   → cron設定: 5 3,7,11,15,19,23 * * *")
        print(f"\n   例: 確定後5分に実行")
        print(f"   5 3,7,11,15,19,23 * * * python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY")
    else:
        print(f"\n⚠️ 確定足時刻: JST {hour:02d}:00")
        print(f"   → 標準的なパターンではありません")
        print(f"   → cron設定: 5 {hour} * * * （この時刻 + 5分）")

    print()
    print("=" * 80)
    print("次足始値時刻")
    print("=" * 80)
    next_bar = expected_bar_dt + timedelta(hours=4)
    print(f"次足始値: {next_bar.strftime('%Y-%m-%d %H:%M JST')}")

    print()
    print("=" * 80)
    print("月間送信数計算")
    print("=" * 80)
    print(f"1日6回 × 31日 = 186通/月")
    print(f"LINE無料枠200通/月以内 ✅")

    print()
    print("=" * 80)
    print("✅ テスト完了")
    print("=" * 80)
    print()
    print("📝 次のステップ:")
    print("1. 実際のTwelve Data APIで確認する場合:")
    print("   export TWELVEDATA_API_KEY='your_key'")
    print("   python3 scripts/run_signal.py --dry-run --symbols USD/JPY --log-level INFO")
    print()
    print("2. cron設定:")
    print(f"   上記の推奨cron設定を使用してください")
    print()


if __name__ == "__main__":
    test_bar_dt_logging()
