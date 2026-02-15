"""
バッチ通知テスト（3通貨を1通にまとめる）

検証項目:
1. 3通貨の結果を1つのメッセージにまとめる
2. textメッセージ1件のみ
3. 同一bar_dtでは再送しない（bar_dtデデュープ）
4. 見送りも短く含まれる
"""
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config_loader import load_broker_config
from src.notify_line import LineNotifier


def test_batch_message():
    """バッチメッセージ生成テスト"""
    print("=" * 80)
    print("テスト1: バッチメッセージ生成（3通貨まとめ）")
    print("=" * 80)

    config = load_broker_config("config/minnafx.yaml")
    notifier = LineNotifier(
        line_token="test_token",
        line_user_id="test_user",
        config=config,
        state_file="data/test_batch_state.json"
    )

    # テスト時刻
    run_dt = datetime(2026, 2, 15, 13, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    bar_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    # 3通貨の結果（シグナル1、見送り2）
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
            "reason": "日足環境NG（レンジ）"
        },
        {
            "symbol": "GBP/JPY",
            "status": "SKIP",
            "reason": "スプレッド超過（14.9 pips > 2.25 pips）"
        },
    ]

    msg = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg:
        print("\n✅ バッチメッセージ生成成功")
        print("\n" + "=" * 80)
        print(msg)
        print("=" * 80)

        # 検証
        assert "EUR/JPY" in msg, "EUR/JPYが含まれていない"
        assert "USD/JPY" in msg, "USD/JPYが含まれていない"
        assert "GBP/JPY" in msg, "GBP/JPYが含まれていない"
        assert "シグナル: 1通貨" in msg, "シグナルカウントが正しくない"
        assert "見送り: 2通貨" in msg, "見送りカウントが正しくない"
        assert "日足環境NG" in msg, "見送り理由が含まれていない"
        print("\n✅ 必須項目チェック完了")
    else:
        print("❌ メッセージ生成失敗")
        return False

    return True


def test_bar_dt_dedup():
    """bar_dtデデュープテスト"""
    print("\n" + "=" * 80)
    print("テスト2: bar_dtデデュープ（同一4Hバーでは再送しない）")
    print("=" * 80)

    # state_fileを削除してリセット
    state_file = Path("data/test_batch_state.json")
    if state_file.exists():
        state_file.unlink()

    config = load_broker_config("config/minnafx.yaml")
    notifier = LineNotifier(
        line_token="test_token",
        line_user_id="test_user",
        config=config,
        state_file="data/test_batch_state.json"
    )

    run_dt = datetime(2026, 2, 15, 13, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    bar_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

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
    ]

    # 1回目の送信
    msg1 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg1 is None:
        print("❌ 1回目の生成失敗")
        return False

    print("✅ 1回目: メッセージ生成成功")

    # 2回目の送信（同じbar_dt）
    msg2 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg2 is None:
        print("✅ 2回目: 同一bar_dtで正しくブロック（デデュープ成功）")
    else:
        print("❌ 2回目: デデュープ失敗（重複送信されてしまう）")
        return False

    # 3回目の送信（異なるbar_dt）
    bar_dt2 = datetime(2026, 2, 15, 16, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    msg3 = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt2,
        results=results,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg3:
        print("✅ 3回目: 異なるbar_dtで正しく生成")
    else:
        print("❌ 3回目: 異なるbar_dtなのに生成されない")
        return False

    return True


def test_all_skips():
    """全通貨見送りでも通知するテスト"""
    print("\n" + "=" * 80)
    print("テスト3: 全通貨見送りでも短文通知")
    print("=" * 80)

    # state_fileを削除してリセット
    state_file = Path("data/test_batch_state.json")
    if state_file.exists():
        state_file.unlink()

    config = load_broker_config("config/minnafx.yaml")
    notifier = LineNotifier(
        line_token="test_token",
        line_user_id="test_user",
        config=config,
        state_file="data/test_batch_state.json"
    )

    run_dt = datetime(2026, 2, 15, 13, 5, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    bar_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    # 全通貨見送り
    results = [
        {"symbol": "EUR/JPY", "status": "SKIP", "reason": "日足環境NG"},
        {"symbol": "USD/JPY", "status": "SKIP", "reason": "EMAタッチなし"},
        {"symbol": "GBP/JPY", "status": "SKIP", "reason": "パターン不成立"},
    ]

    msg = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results,
        equity_jpy=100000.0,
        risk_pct=0.005
    )

    if msg:
        print("\n✅ 全通貨見送りでも通知生成成功")
        print("\n" + "=" * 80)
        print(msg)
        print("=" * 80)

        assert "シグナル: 0通貨" in msg, "シグナルカウントが正しくない"
        assert "見送り: 3通貨" in msg, "見送りカウントが正しくない"
        print("\n✅ 全通貨見送り通知確認完了")
    else:
        print("❌ 全通貨見送りでメッセージ生成されない")
        return False

    return True


def main():
    """全テスト実行"""
    print("\n" + "=" * 80)
    print("バッチ通知テスト（LINE無料枠節約設計）")
    print("=" * 80 + "\n")

    results = []

    # テスト1: バッチメッセージ生成
    results.append(("バッチメッセージ生成", test_batch_message()))

    # テスト2: bar_dtデデュープ
    results.append(("bar_dtデデュープ", test_bar_dt_dedup()))

    # テスト3: 全通貨見送り
    results.append(("全通貨見送り通知", test_all_skips()))

    # 結果サマリー
    print("\n" + "=" * 80)
    print("テスト結果サマリー")
    print("=" * 80)

    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 80)
    if all_passed:
        print("✅ 全テスト合格")
        print("🎯 バッチ通知は実運用可能です（LINE無料枠200通/月を守る設計）")
    else:
        print("❌ 一部テスト失敗")
        print("修正が必要です")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
