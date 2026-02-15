"""
LINE通知デモ（dry-run）
3通貨のサンプル通知を標準出力
"""
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

# パスを追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_broker_config
from src.notify_line import LineNotifier


def demo_notifications():
    """3通貨のLINE通知サンプルを出力"""

    try:
        # 設定読み込み
        config = load_broker_config("config/minnafx.yaml")
    except Exception as e:
        print(f"❌ 設定ファイル読み込みエラー: {e}")
        print("\nPyYAMLがインストールされていない可能性があります:")
        print("  pip3 install pyyaml")
        return

    # ダミーのnotifier（LINE送信はしない）
    notifier = LineNotifier(
        line_token="dummy_token",
        line_user_id="dummy_user",
        config=config,
        state_file="data/notification_state_demo.json"
    )

    # サンプルシグナル定義（JST固定帯時間）
    signal_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    samples = [
        {
            "symbol": "EUR/JPY",
            "side": "LONG",
            "pattern": "Bullish Engulfing",
            "entry_mid": 163.245,
            "sl_mid": 163.195,  # 0.05円（5pips）のSL幅
            "tp1_mid": 163.295,  # +5pips
            "tp2_mid": 163.345,  # +10pips
            "atr": 0.050,
            "ema20": 163.150,
        },
        {
            "symbol": "USD/JPY",
            "side": "LONG",
            "pattern": "Hammer",
            "entry_mid": 150.500,
            "sl_mid": 150.450,  # 0.05円（5pips）のSL幅
            "tp1_mid": 150.550,  # +5pips
            "tp2_mid": 150.600,  # +10pips
            "atr": 0.050,
            "ema20": 150.450,
        },
        {
            "symbol": "GBP/JPY",
            "side": "SHORT",
            "pattern": "Bearish Engulfing",
            "entry_mid": 190.500,
            "sl_mid": 190.550,  # 0.05円（5pips）のSL幅
            "tp1_mid": 190.450,  # -5pips（SHORTなのでマイナス）
            "tp2_mid": 190.400,  # -10pips
            "atr": 0.050,
            "ema20": 190.600,
        },
    ]

    print("=" * 80)
    print("📱 LINE通知サンプル（dry-run）")
    print("=" * 80)
    print(f"\nシグナル時刻: {signal_dt.strftime('%Y-%m-%d %H:%M JST')}")
    print(f"口座残高: 100,000円")
    print(f"リスク設定: 0.5% (最大500円/トレード)")
    print("\n" + "=" * 80 + "\n")

    for i, sample in enumerate(samples, 1):
        msg = notifier.create_signal_message(
            symbol=sample["symbol"],
            side=sample["side"],
            pattern=sample["pattern"],
            signal_dt=signal_dt,
            entry_price_mid=sample["entry_mid"],
            sl_price_mid=sample["sl_mid"],
            tp1_price_mid=sample["tp1_mid"],
            tp2_price_mid=sample["tp2_mid"],
            atr=sample["atr"],
            ema20=sample["ema20"],
            equity_jpy=100000.0,
            risk_pct=0.005,
            entry_mode="NEXT_OPEN_MARKET",
            exit_config={
                "tp1_close_pct": 0.5,
                "move_to_be": True,
                "be_buffer_pips": 0.0,
                "tp2_mode": "FIXED_R",
                "time_stop": None,
                "daily_flip_exit": False
            }
        )

        if msg:
            print(f"【サンプル {i}/{len(samples)}】")
            print(msg)
            print("\n" + "=" * 80 + "\n")
        else:
            print(f"【サンプル {i}/{len(samples)}】")
            print(f"❌ 通知なし（見送りまたは重複）\n")

    print("✅ デモ完了")
    print("\n📝 注意:")
    print("  - 本デモはLINE送信を行いません（dry-run）")
    print("  - 実際の通知は scripts/run_signal.py で実行します")
    print("  - 通知内容は config/minnafx.yaml の設定に基づきます")


if __name__ == "__main__":
    demo_notifications()
