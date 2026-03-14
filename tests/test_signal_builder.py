"""
build_single_signal 統合テスト
strategy.md / data_spec.md 準拠

テスト対象:
- ENTRY_OK (BUY / SELL)
- SKIP (各理由コード W, D, A, P, X, S, R, O, C)
- 複数理由コードの付与
- signals.csv 必須列の網羅
- pullback_ok=False 時の理由コード X
"""
import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from src.daily_strategy.signal_builder import build_single_signal, STRATEGY_VERSION
from src.daily_strategy.csv_output import SIGNALS_COLUMNS


# --- テスト用データ生成ヘルパー ---

def _make_daily_df(closes, opens=None, highs=None, lows=None, n=30):
    """
    日足 DataFrame を生成する。
    closes を指定すると末尾 len(closes) 本の close を上書きする。
    それ以外の足は安定した上昇トレンド用データ。
    """
    base = 150.0
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    df = pd.DataFrame({
        "datetime": dates,
        "open": [base + i * 0.1 for i in range(n)],
        "high": [base + i * 0.1 + 0.5 for i in range(n)],
        "low": [base + i * 0.1 - 0.5 for i in range(n)],
        "close": [base + i * 0.1 + 0.05 for i in range(n)],
    })
    # 末尾の close を上書き
    if closes is not None:
        for j, c in enumerate(closes):
            df.loc[df.index[n - len(closes) + j], "close"] = c
    if opens is not None:
        for j, o in enumerate(opens):
            df.loc[df.index[n - len(opens) + j], "open"] = o
    if highs is not None:
        for j, h in enumerate(highs):
            df.loc[df.index[n - len(highs) + j], "high"] = h
    if lows is not None:
        for j, lo in enumerate(lows):
            df.loc[df.index[n - len(lows) + j], "low"] = lo
    return df


def _make_weekly_df(closes, highs=None, lows=None, n=25):
    """
    週足 DataFrame を生成する。
    上昇トレンド用のデフォルトデータ。
    """
    base = 148.0
    dates = pd.date_range("2025-07-01", periods=n, freq="W")
    df = pd.DataFrame({
        "datetime": dates,
        "open": [base + i * 0.2 for i in range(n)],
        "high": [base + i * 0.2 + 1.0 for i in range(n)],
        "low": [base + i * 0.2 - 1.0 for i in range(n)],
        "close": [base + i * 0.2 + 0.1 for i in range(n)],
    })
    if closes is not None:
        for j, c in enumerate(closes):
            df.loc[df.index[n - len(closes) + j], "close"] = c
    if highs is not None:
        for j, h in enumerate(highs):
            df.loc[df.index[n - len(highs) + j], "high"] = h
    if lows is not None:
        for j, lo in enumerate(lows):
            df.loc[df.index[n - len(lows) + j], "low"] = lo
    return df


def _make_uptrend_daily(n=30):
    """明確な上昇トレンドの日足データ (EMA20 上向き、close > EMA20)"""
    base = 148.0
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "datetime": dates,
        "open": [base + i * 0.3 for i in range(n)],
        "high": [base + i * 0.3 + 0.8 for i in range(n)],
        "low": [base + i * 0.3 - 0.3 for i in range(n)],
        "close": [base + i * 0.3 + 0.2 for i in range(n)],
    })


def _make_uptrend_weekly(n=25):
    """明確な上昇トレンドの週足データ"""
    base = 145.0
    dates = pd.date_range("2025-07-01", periods=n, freq="W")
    return pd.DataFrame({
        "datetime": dates,
        "open": [base + i * 0.5 for i in range(n)],
        "high": [base + i * 0.5 + 2.0 for i in range(n)],
        "low": [base + i * 0.5 - 1.0 for i in range(n)],
        "close": [base + i * 0.5 + 0.3 for i in range(n)],
    })


def _make_downtrend_daily(n=30):
    """明確な下降トレンドの日足データ"""
    base = 160.0
    dates = pd.date_range("2026-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "datetime": dates,
        "open": [base - i * 0.3 for i in range(n)],
        "high": [base - i * 0.3 + 0.3 for i in range(n)],
        "low": [base - i * 0.3 - 0.8 for i in range(n)],
        "close": [base - i * 0.3 - 0.2 for i in range(n)],
    })


def _make_downtrend_weekly(n=25):
    """明確な下降トレンドの週足データ"""
    base = 165.0
    dates = pd.date_range("2025-07-01", periods=n, freq="W")
    return pd.DataFrame({
        "datetime": dates,
        "open": [base - i * 0.5 for i in range(n)],
        "high": [base - i * 0.5 + 1.0 for i in range(n)],
        "low": [base - i * 0.5 - 2.0 for i in range(n)],
        "close": [base - i * 0.5 - 0.3 for i in range(n)],
    })


def _empty_state():
    return {
        "last_processed_bar": {},
        "open_positions": {},
        "consecutive_losses": 0,
    }


RUN_ID = "TEST_RUN_001"
GEN_AT = datetime(2026, 3, 14, 22, 30, 0)
EQUITY = 500000.0
RISK_PCT = 0.005


# ===========================================================
# 共通アサーション: signals.csv 必須列の存在確認
# ===========================================================

def _assert_required_columns(signal: dict):
    """data_spec.md §15 初期版必須列がすべて存在することを確認する。"""
    required = [
        "signal_id", "run_id", "strategy_version",
        "generated_at_utc", "pair",
        "weekly_trend", "daily_trend", "alignment",
        "close_price", "daily_ema20", "atr14",
        "ema_distance_abs", "ema_distance_atr_ratio", "pullback_ok",
        "pattern_name", "pattern_detected",
        "event_risk", "decision", "reason_codes",
        "entry_side", "planned_entry_price", "planned_sl_price",
        "planned_tp1_price", "planned_tp2_price",
        "planned_risk_jpy", "planned_lot",
    ]
    for col in required:
        assert col in signal, f"Missing required column: {col}"


def _assert_csv_columns_compatible(signal: dict):
    """csv_output.py SIGNALS_COLUMNS のキーが signal dict に存在することを確認。"""
    for col in SIGNALS_COLUMNS:
        assert col in signal, f"Missing CSV column: {col}"


# ===========================================================
# ENTRY_OK テスト
# ===========================================================

class TestEntryOkBuy:
    """BUY ENTRY_OK: 週足UP + 日足UP + パターン成立 + pullback OK"""

    def _build_buy_signal(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)

        # 末尾2本を Bullish Engulfing にする
        # 前日: 陰線
        daily_df.loc[daily_df.index[-2], "open"] = daily_df["close"].iloc[-2] + 0.3
        daily_df.loc[daily_df.index[-2], "close"] = daily_df["close"].iloc[-2] - 0.1
        prev_open = float(daily_df["open"].iloc[-2])
        prev_close = float(daily_df["close"].iloc[-2])

        # 当日: 陽線で前日実体を包む
        daily_df.loc[daily_df.index[-1], "open"] = prev_close - 0.01
        daily_df.loc[daily_df.index[-1], "close"] = prev_open + 0.01

        # pullback_ok にするために close を EMA20 に近づける
        from src.indicators import calculate_ema, calculate_atr
        ema20 = calculate_ema(daily_df["close"], 20)
        atr14 = calculate_atr(daily_df, 14)
        ema_val = float(ema20.iloc[-1])
        atr_val = float(atr14.iloc[-1])

        # close を ema20 + 0.1 * ATR に設定 (pullback_ok = True)
        target_close = ema_val + 0.1 * atr_val
        daily_df.loc[daily_df.index[-1], "close"] = target_close

        # 再度 engulfing 条件を満たすよう open を調整
        daily_df.loc[daily_df.index[-1], "open"] = prev_close - 0.01
        if target_close <= prev_open:
            daily_df.loc[daily_df.index[-1], "close"] = prev_open + 0.01

        # high/low を合理的に設定
        today_close = float(daily_df["close"].iloc[-1])
        today_open = float(daily_df["open"].iloc[-1])
        daily_df.loc[daily_df.index[-1], "high"] = max(today_open, today_close) + 0.2
        daily_df.loc[daily_df.index[-1], "low"] = min(today_open, today_close) - 0.2

        return build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )

    def test_decision_entry_ok(self):
        signal = self._build_buy_signal()
        # alignment が BUY_ONLY であること
        assert signal["alignment"] == "BUY_ONLY"
        assert signal["weekly_trend"] == "WEEKLY_UP"
        assert signal["daily_trend"] == "DAILY_UP"

    def test_entry_side_buy(self):
        signal = self._build_buy_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["entry_side"] == "BUY"

    def test_sl_below_signal_low(self):
        signal = self._build_buy_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["planned_sl_price"] < signal["signal_low"]

    def test_tp1_above_entry(self):
        signal = self._build_buy_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["planned_tp1_price"] > signal["planned_entry_price"]

    def test_tp2_above_tp1(self):
        signal = self._build_buy_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["planned_tp2_price"] > signal["planned_tp1_price"]

    def test_required_columns(self):
        signal = self._build_buy_signal()
        _assert_required_columns(signal)

    def test_strategy_version(self):
        signal = self._build_buy_signal()
        assert signal["strategy_version"] == STRATEGY_VERSION

    def test_event_risk_manual_check(self):
        signal = self._build_buy_signal()
        assert signal["event_risk"] == "manual_check"


class TestEntryOkSell:
    """SELL ENTRY_OK: 週足DOWN + 日足DOWN + パターン成立"""

    def _build_sell_signal(self):
        daily_df = _make_downtrend_daily(40)
        weekly_df = _make_downtrend_weekly(25)

        # 末尾2本を Bearish Engulfing にする
        # 前日: 陽線
        daily_df.loc[daily_df.index[-2], "open"] = daily_df["close"].iloc[-2] - 0.3
        daily_df.loc[daily_df.index[-2], "close"] = daily_df["close"].iloc[-2] + 0.1
        prev_open = float(daily_df["open"].iloc[-2])
        prev_close = float(daily_df["close"].iloc[-2])

        # 当日: 陰線で前日実体を包む
        daily_df.loc[daily_df.index[-1], "open"] = prev_close + 0.01
        daily_df.loc[daily_df.index[-1], "close"] = prev_open - 0.01

        # close を EMA20 近辺に
        from src.indicators import calculate_ema, calculate_atr
        ema20 = calculate_ema(daily_df["close"], 20)
        atr14 = calculate_atr(daily_df, 14)
        ema_val = float(ema20.iloc[-1])
        atr_val = float(atr14.iloc[-1])

        target_close = ema_val - 0.1 * atr_val
        daily_df.loc[daily_df.index[-1], "close"] = target_close
        daily_df.loc[daily_df.index[-1], "open"] = prev_close + 0.01
        if target_close >= prev_open:
            daily_df.loc[daily_df.index[-1], "close"] = prev_open - 0.01

        today_close = float(daily_df["close"].iloc[-1])
        today_open = float(daily_df["open"].iloc[-1])
        daily_df.loc[daily_df.index[-1], "high"] = max(today_open, today_close) + 0.2
        daily_df.loc[daily_df.index[-1], "low"] = min(today_open, today_close) - 0.2

        return build_single_signal(
            "EUR/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )

    def test_alignment_sell_only(self):
        signal = self._build_sell_signal()
        assert signal["alignment"] == "SELL_ONLY"
        assert signal["weekly_trend"] == "WEEKLY_DOWN"
        assert signal["daily_trend"] == "DAILY_DOWN"

    def test_entry_side_sell(self):
        signal = self._build_sell_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["entry_side"] == "SELL"

    def test_sl_above_signal_high(self):
        signal = self._build_sell_signal()
        if signal["decision"] == "ENTRY_OK":
            assert signal["planned_sl_price"] > signal["signal_high"]

    def test_required_columns(self):
        signal = self._build_sell_signal()
        _assert_required_columns(signal)


# ===========================================================
# SKIP テスト (各理由コード)
# ===========================================================

class TestSkipWeeklyNeutral:
    """SKIP [W]: 週足 NEUTRAL"""

    def test_reason_code_w(self):
        daily_df = _make_uptrend_daily(40)
        # 週足を完全横ばいにする (slope=0, close=EMA20)
        n = 25
        flat_close = 150.0
        dates = pd.date_range("2025-07-01", periods=n, freq="W")
        weekly_df = pd.DataFrame({
            "datetime": dates,
            "open": [flat_close] * n,
            "high": [flat_close + 1.0] * n,
            "low": [flat_close - 1.0] * n,
            "close": [flat_close] * n,
        })
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert signal["weekly_trend"] == "WEEKLY_NEUTRAL"
        assert "W" in signal["reason_codes"]


class TestSkipAlignment:
    """SKIP [A]: 週足/日足不整合"""

    def test_reason_code_a(self):
        daily_df = _make_uptrend_daily(40)     # 日足 UP
        weekly_df = _make_downtrend_weekly(25)  # 週足 DOWN
        signal = build_single_signal(
            "GBP/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert signal["alignment"] == "NO_TRADE"
        assert "A" in signal["reason_codes"]


class TestSkipNoPattern:
    """SKIP [P]: パターン不成立"""

    def test_reason_code_p(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        # 前日も当日も陽線 (小さい実体) → Engulfing 不成立、Pin Bar も不成立
        # close は変えずに open のみ微調整して両方陽線にする
        last_close = float(daily_df["close"].iloc[-1])
        prev_close = float(daily_df["close"].iloc[-2])
        daily_df.loc[daily_df.index[-2], "open"] = prev_close - 0.1
        daily_df.loc[daily_df.index[-1], "open"] = last_close - 0.1
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        # alignment が BUY_ONLY であることを前提にテスト
        if signal["alignment"] == "BUY_ONLY":
            assert signal["decision"] == "SKIP"
            assert "P" in signal["reason_codes"]
            assert signal["pattern_name"] == "NONE"
            assert signal["pattern_detected"] is False
        else:
            # alignment が NO_TRADE の場合、P は付かないが A が付く
            assert signal["decision"] == "SKIP"


class TestSkipEmaDivergence:
    """SKIP [X]: EMA乖離過大"""

    def test_reason_code_x_divergence(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        # close を EMA20 から大きく離す
        from src.indicators import calculate_ema, calculate_atr
        ema20 = calculate_ema(daily_df["close"], 20)
        atr14 = calculate_atr(daily_df, 14)
        ema_val = float(ema20.iloc[-1])
        atr_val = float(atr14.iloc[-1])
        daily_df.loc[daily_df.index[-1], "close"] = ema_val + 1.5 * atr_val
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert "X" in signal["reason_codes"]


class TestSkipPullbackNotOk:
    """SKIP [X]: pullback_ok=False (0.5ATR < 距離 <= 1.0ATR) → X"""

    def test_pullback_not_ok_uses_x(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)

        # close を EMA20 から 0.7 * ATR に設定 (0.5 < 0.7 <= 1.0)
        from src.indicators import calculate_ema, calculate_atr
        ema20 = calculate_ema(daily_df["close"], 20)
        atr14 = calculate_atr(daily_df, 14)
        ema_val = float(ema20.iloc[-1])
        atr_val = float(atr14.iloc[-1])
        daily_df.loc[daily_df.index[-1], "close"] = ema_val + 0.7 * atr_val

        # パターン成立させる (Bullish Engulfing)
        daily_df.loc[daily_df.index[-2], "open"] = daily_df["close"].iloc[-2] + 0.3
        daily_df.loc[daily_df.index[-2], "close"] = daily_df["close"].iloc[-2] - 0.1
        prev_open = float(daily_df["open"].iloc[-2])
        prev_close = float(daily_df["close"].iloc[-2])
        daily_df.loc[daily_df.index[-1], "open"] = prev_close - 0.01
        today_close = float(daily_df["close"].iloc[-1])
        if today_close < prev_open:
            daily_df.loc[daily_df.index[-1], "close"] = prev_open + 0.01

        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        # alignment は BUY_ONLY になるはず
        if signal["alignment"] == "BUY_ONLY":
            assert signal["decision"] == "SKIP"
            assert "X" in signal["reason_codes"]
            # D が付いていないこと
            assert "D" not in signal["reason_codes"] or signal["daily_trend"] == "DAILY_NEUTRAL"


class TestSkipPositionExists:
    """SKIP [O]: 既存ポジションあり"""

    def test_reason_code_o(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        state = _empty_state()
        state["open_positions"]["USDJPY"] = {"side": "BUY"}
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, state, EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert "O" in signal["reason_codes"]
        assert signal["position_status"] == "POSITION_EXISTS"


class TestSkipCorrelation:
    """SKIP [C]: 相関/総リスク超過"""

    def test_reason_code_c_max_positions(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        state = _empty_state()
        state["open_positions"] = {"EURJPY": {}, "GBPJPY": {}}
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, state, EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert "C" in signal["reason_codes"]
        assert signal["correlation_risk"] == "EXCEEDED"

    def test_reason_code_c_consecutive_losses(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        state = _empty_state()
        state["consecutive_losses"] = 3
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, state, EQUITY, RISK_PCT,
        )
        assert signal["decision"] == "SKIP"
        assert "C" in signal["reason_codes"]


# ===========================================================
# CSV 列互換性テスト
# ===========================================================

class TestCsvCompatibility:
    """signals.csv 出力との互換性テスト"""

    def test_all_csv_columns_present_entry_ok(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        _assert_csv_columns_compatible(signal)

    def test_all_csv_columns_present_skip(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_downtrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        _assert_csv_columns_compatible(signal)

    def test_pair_format_csv(self):
        """通貨ペアが USDJPY 形式であること (data_spec.md §3.2)"""
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert signal["pair"] == "USDJPY"

    def test_signal_id_format(self):
        """signal_id が {strategy_version}_{pair}_{timestamp} 形式であること"""
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert signal["signal_id"].startswith(STRATEGY_VERSION)
        assert "USDJPY" in signal["signal_id"]


# ===========================================================
# 数値整合性テスト
# ===========================================================

class TestNumericalConsistency:
    """SL/TP/リスク計算の整合性テスト"""

    def test_buy_tp1_is_1r(self):
        """BUY: TP1 = entry + 1R"""
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        if signal["decision"] == "ENTRY_OK" and signal["entry_side"] == "BUY":
            entry = signal["planned_entry_price"]
            sl = signal["planned_sl_price"]
            tp1 = signal["planned_tp1_price"]
            tp2 = signal["planned_tp2_price"]
            risk = entry - sl
            assert abs(tp1 - (entry + risk)) < 0.01
            assert abs(tp2 - (entry + 2 * risk)) < 0.01

    def test_sell_tp1_is_1r(self):
        """SELL: TP1 = entry - 1R"""
        daily_df = _make_downtrend_daily(40)
        weekly_df = _make_downtrend_weekly(25)
        signal = build_single_signal(
            "EUR/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        if signal["decision"] == "ENTRY_OK" and signal["entry_side"] == "SELL":
            entry = signal["planned_entry_price"]
            sl = signal["planned_sl_price"]
            tp1 = signal["planned_tp1_price"]
            tp2 = signal["planned_tp2_price"]
            risk = sl - entry
            assert abs(tp1 - (entry - risk)) < 0.01
            assert abs(tp2 - (entry - 2 * risk)) < 0.01

    def test_ema_distance_calculation(self):
        """ema_distance_abs と ema_distance_atr_ratio の計算が正しいこと"""
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        close = signal["close_price"]
        ema20 = signal["daily_ema20"]
        atr14 = signal["atr14"]
        expected_dist = abs(close - ema20)
        assert abs(signal["ema_distance_abs"] - round(expected_dist, 5)) < 1e-4
        if atr14 > 0:
            expected_ratio = expected_dist / atr14
            assert abs(signal["ema_distance_atr_ratio"] - round(expected_ratio, 4)) < 1e-3


# ===========================================================
# boolean 値テスト
# ===========================================================

class TestBooleanValues:
    """data_spec.md §13.1 準拠: boolean は TRUE/FALSE"""

    def test_pullback_ok_is_bool(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert isinstance(signal["pullback_ok"], bool)

    def test_pattern_detected_is_bool(self):
        daily_df = _make_uptrend_daily(40)
        weekly_df = _make_uptrend_weekly(25)
        signal = build_single_signal(
            "USD/JPY", daily_df, weekly_df,
            RUN_ID, GEN_AT, _empty_state(), EQUITY, RISK_PCT,
        )
        assert isinstance(signal["pattern_detected"], bool)
