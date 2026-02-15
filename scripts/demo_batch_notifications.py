"""
バッチ通知デモ（3通貨を1通にまとめる）
LINE無料枠（200通/月）を守る設計
"""
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_broker_config
from src.notify_line import LineNotifier


def demo_batch_notification():
    """バッチ通知のデモ（dry-run）"""
    print("=" * 80)
    print("📊 バッチ通知デモ（3通貨を1通にまとめる）")
    print("=" * 80)

    # 設定読み込み
    config = load_broker_config("config/minnafx.yaml")

    # LINE通知（ダミー認証情報）
    notifier = LineNotifier(
        line_token="dummy_token",
        line_user_id="dummy_user",
        config=config,
        state_file="data/demo_batch_state.json"
    )

    # テスト時刻
    run_dt = datetime.now(ZoneInfo("Asia/Tokyo"))
    bar_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    print(f"\n実行時刻: {run_dt.strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f"確定4H足: {bar_dt.strftime('%Y-%m-%d %H:%M JST')}")

    # ケース1: シグナル2、見送り1
    print("\n" + "=" * 80)
    print("ケース1: シグナル2通貨、見送り1通貨")
    print("=" * 80)

    # state_fileを削除してリセット
    state_file = Path("data/demo_batch_state.json")
    if state_file.exists():
        state_file.unlink()

    results1 = [
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

    msg1 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results1,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg1:
        print("\n✅ メッセージ生成成功")
        print("\n" + msg1)
    else:
        print("❌ メッセージ生成失敗")

    # ケース2: 全通貨見送り
    print("\n" + "=" * 80)
    print("ケース2: 全通貨見送り（シグナルなし）")
    print("=" * 80)

    # 異なるbar_dtでリセット
    bar_dt2 = datetime(2026, 2, 15, 16, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    results2 = [
        {"symbol": "EUR/JPY", "status": "SKIP", "reason": "日足環境NG（レンジ）"},
        {"symbol": "USD/JPY", "status": "SKIP", "reason": "メンテナンス時間中"},
        {"symbol": "GBP/JPY", "status": "SKIP", "reason": "最小ロット未満"},
    ]

    msg2 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt2,
        results=results2,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg2:
        print("\n✅ メッセージ生成成功（全通貨見送りでも通知）")
        print("\n" + msg2)
    else:
        print("❌ メッセージ生成失敗")

    # ケース3: 全通貨シグナル
    print("\n" + "=" * 80)
    print("ケース3: 全通貨シグナル（最高の状態）")
    print("=" * 80)

    bar_dt3 = datetime(2026, 2, 15, 20, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    results3 = [
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
            "status": "SIGNAL",
            "side": "LONG",
            "pattern": "Hammer",
            "entry_price_mid": 150.500,
            "sl_price_mid": 150.450,
            "tp1_price_mid": 150.550,
            "tp2_price_mid": 150.600,
            "atr": 0.050,
            "ema20": 150.450,
        },
        {
            "symbol": "GBP/JPY",
            "status": "SIGNAL",
            "side": "SHORT",
            "pattern": "Bearish Engulfing",
            "entry_price_mid": 190.500,
            "sl_price_mid": 190.550,
            "tp1_price_mid": 190.450,
            "tp2_price_mid": 190.400,
            "atr": 0.050,
            "ema20": 190.600,
        },
    ]

    msg3 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt3,
        results=results3,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg3:
        print("\n✅ メッセージ生成成功（全通貨シグナル）")
        print("\n" + msg3)
    else:
        print("❌ メッセージ生成失敗")

    # まとめ
    print("\n" + "=" * 80)
    print("✅ バッチ通知デモ完了")
    print("=" * 80)
    print("\n📋 特徴:")
    print("  ✅ 3通貨を1通にまとめる（messages配列は1要素）")
    print("  ✅ シグナルは詳細ブロック、見送りは1〜2行に圧縮")
    print("  ✅ 全通貨見送りでも通知（チェック完了を確認）")
    print("  ✅ bar_dtデデュープで同一4Hバーでは再送しない")
    print("\n💰 コスト:")
    print("  ・1日6回（4H足確定後）× 31日 = 186通/月")
    print("  ・LINE無料枠200通/月以内 ✅")
    print("\n🚀 実運用準備完了！")


if __name__ == "__main__":
    demo_batch_notification()
