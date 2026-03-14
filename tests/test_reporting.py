"""
reporting モジュールのテスト
"""
import os
import tempfile
from pathlib import Path

import pytest

from src.reporting.kpi import (
    _parse_date,
    _to_float,
    _calc_max_losing_streak,
    _calc_max_drawdown,
    filter_signals_by_period,
    filter_trades_by_period,
    compute_signal_kpi,
    compute_reason_code_breakdown,
    compute_trade_kpi,
    compute_per_pair_kpi,
)
from src.reporting.weekly_review import generate_weekly_review
from src.reporting.monthly_review import generate_monthly_review, _suggest_improvements


# --- テストデータ ---

def _make_signals():
    """テスト用シグナルデータ"""
    return [
        {"generated_date_jst": "2026-03-02", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""},
        {"generated_date_jst": "2026-03-02", "pair": "EURJPY", "decision": "SKIP", "reason_codes": "W;D"},
        {"generated_date_jst": "2026-03-03", "pair": "GBPJPY", "decision": "SKIP", "reason_codes": "P"},
        {"generated_date_jst": "2026-03-03", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""},
        {"generated_date_jst": "2026-03-04", "pair": "EURJPY", "decision": "NO_DATA", "reason_codes": ""},
        {"generated_date_jst": "2026-03-05", "pair": "GBPJPY", "decision": "SKIP", "reason_codes": "X"},
        {"generated_date_jst": "2026-03-06", "pair": "USDJPY", "decision": "ERROR", "reason_codes": ""},
        # 範囲外
        {"generated_date_jst": "2026-02-28", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""},
        {"generated_date_jst": "2026-03-10", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""},
    ]


def _make_trades():
    """テスト用トレードデータ"""
    return [
        {
            "pair_trade_date_jst": "2026-03-02",
            "trade_id": "T001",
            "pair": "USDJPY",
            "side": "BUY",
            "status": "CLOSED",
            "result": "WIN",
            "gross_pnl_jpy": "15000",
            "net_pnl_jpy": "14800",
            "swap_jpy": "-200",
            "fee_jpy": "0",
            "pnl_r": "1.5",
            "rule_violation": "",
            "violation_note": "",
        },
        {
            "pair_trade_date_jst": "2026-03-03",
            "trade_id": "T002",
            "pair": "EURJPY",
            "side": "SELL",
            "status": "CLOSED",
            "result": "LOSS",
            "gross_pnl_jpy": "-8000",
            "net_pnl_jpy": "-8100",
            "swap_jpy": "-100",
            "fee_jpy": "0",
            "pnl_r": "-1.0",
            "rule_violation": "",
            "violation_note": "",
        },
        {
            "pair_trade_date_jst": "2026-03-04",
            "trade_id": "T003",
            "pair": "GBPJPY",
            "side": "BUY",
            "status": "CLOSED",
            "result": "WIN",
            "gross_pnl_jpy": "20000",
            "net_pnl_jpy": "19700",
            "swap_jpy": "-300",
            "fee_jpy": "0",
            "pnl_r": "2.0",
            "rule_violation": "",
            "violation_note": "",
        },
        {
            "pair_trade_date_jst": "2026-03-05",
            "trade_id": "T004",
            "pair": "USDJPY",
            "side": "BUY",
            "status": "CLOSED",
            "result": "LOSS",
            "gross_pnl_jpy": "-10000",
            "net_pnl_jpy": "-10050",
            "swap_jpy": "-50",
            "fee_jpy": "0",
            "pnl_r": "-1.0",
            "rule_violation": "TRUE",
            "violation_note": "TP1前にSL手動移動",
        },
        {
            "pair_trade_date_jst": "2026-03-06",
            "trade_id": "T005",
            "pair": "USDJPY",
            "side": "BUY",
            "status": "OPEN",
            "result": "",
            "gross_pnl_jpy": "",
            "net_pnl_jpy": "",
            "swap_jpy": "",
            "fee_jpy": "",
            "pnl_r": "",
            "rule_violation": "",
            "violation_note": "",
        },
        # 範囲外
        {
            "pair_trade_date_jst": "2026-02-28",
            "trade_id": "T000",
            "pair": "USDJPY",
            "side": "BUY",
            "status": "CLOSED",
            "result": "WIN",
            "gross_pnl_jpy": "5000",
            "net_pnl_jpy": "5000",
            "swap_jpy": "0",
            "fee_jpy": "0",
            "pnl_r": "0.5",
            "rule_violation": "",
            "violation_note": "",
        },
    ]


# ==================== kpi.py ====================


class TestParseDate:
    def test_iso_datetime(self):
        assert _parse_date("2026-03-02T12:00:00Z") == "2026-03-02"

    def test_date_only(self):
        assert _parse_date("2026-03-02") == "2026-03-02"

    def test_empty(self):
        assert _parse_date("") is None

    def test_whitespace(self):
        assert _parse_date("  ") is None


class TestToFloat:
    def test_normal(self):
        assert _to_float("123.45") == 123.45

    def test_none(self):
        assert _to_float(None) == 0.0

    def test_empty(self):
        assert _to_float("") == 0.0

    def test_invalid(self):
        assert _to_float("abc") == 0.0

    def test_int(self):
        assert _to_float(42) == 42.0


class TestFilterSignalsByPeriod:
    def test_basic_filter(self):
        signals = _make_signals()
        result = filter_signals_by_period(signals, "2026-03-02", "2026-03-06")
        assert len(result) == 7

    def test_excludes_out_of_range(self):
        signals = _make_signals()
        result = filter_signals_by_period(signals, "2026-03-02", "2026-03-03")
        assert len(result) == 4

    def test_strategy_pairs_filter(self):
        signals = _make_signals() + [
            {"generated_date_jst": "2026-03-02", "pair": "AUDUSD", "decision": "ENTRY_OK", "reason_codes": ""}
        ]
        result = filter_signals_by_period(signals, "2026-03-02", "2026-03-06", strategy_pairs_only=True)
        assert len(result) == 7  # AUDUSD excluded

    def test_no_strategy_filter(self):
        signals = _make_signals() + [
            {"generated_date_jst": "2026-03-02", "pair": "AUDUSD", "decision": "ENTRY_OK", "reason_codes": ""}
        ]
        result = filter_signals_by_period(signals, "2026-03-02", "2026-03-06", strategy_pairs_only=False)
        assert len(result) == 8  # AUDUSD included

    def test_fallback_to_generated_at_utc(self):
        signals = [
            {"generated_at_utc": "2026-03-02T01:00:00Z", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""}
        ]
        result = filter_signals_by_period(signals, "2026-03-02", "2026-03-02")
        assert len(result) == 1


class TestFilterTradesByPeriod:
    def test_basic_filter(self):
        trades = _make_trades()
        result = filter_trades_by_period(trades, "2026-03-02", "2026-03-06")
        assert len(result) == 5

    def test_excludes_out_of_range(self):
        trades = _make_trades()
        result = filter_trades_by_period(trades, "2026-03-02", "2026-03-03")
        assert len(result) == 2


class TestComputeSignalKpi:
    def test_basic(self):
        signals = _make_signals()[:7]  # in-range only
        kpi = compute_signal_kpi(signals)
        assert kpi["total_signals"] == 7
        assert kpi["entry_ok"] == 2
        assert kpi["skip"] == 3
        assert kpi["no_data"] == 1
        assert kpi["error"] == 1

    def test_empty(self):
        kpi = compute_signal_kpi([])
        assert kpi["total_signals"] == 0


class TestComputeReasonCodeBreakdown:
    def test_basic(self):
        signals = _make_signals()[:7]
        codes = compute_reason_code_breakdown(signals)
        assert codes["W"] == 1
        assert codes["D"] == 1
        assert codes["P"] == 1
        assert codes["X"] == 1

    def test_empty(self):
        codes = compute_reason_code_breakdown([])
        assert codes == {}


class TestComputeTradeKpi:
    def test_basic(self):
        trades = _make_trades()[:5]  # T001-T005
        kpi = compute_trade_kpi(trades)
        assert kpi["total_trades"] == 5
        assert kpi["closed_trades"] == 4
        assert kpi["open_trades"] == 1
        assert kpi["win"] == 2
        assert kpi["loss"] == 2
        assert kpi["breakeven"] == 0
        assert kpi["win_rate"] == 50.0
        assert kpi["net_pnl_jpy"] == 14800 + (-8100) + 19700 + (-10050)
        assert kpi["total_r"] == round(1.5 + (-1.0) + 2.0 + (-1.0), 3)
        assert kpi["rule_violations"] == 1

    def test_empty(self):
        kpi = compute_trade_kpi([])
        assert kpi["total_trades"] == 0
        assert kpi["win_rate"] == 0.0
        assert kpi["profit_factor"] == 0.0

    def test_profit_factor(self):
        trades = _make_trades()[:4]  # T001-T004
        kpi = compute_trade_kpi(trades)
        gross_profit = 14800 + 19700  # wins
        gross_loss = abs(-8100 + -10050)  # losses
        expected_pf = round(gross_profit / gross_loss, 2)
        assert kpi["profit_factor"] == expected_pf

    def test_violation_details(self):
        trades = _make_trades()[:5]
        kpi = compute_trade_kpi(trades)
        assert len(kpi["violation_details"]) == 1
        assert kpi["violation_details"][0]["trade_id"] == "T004"


class TestComputePerPairKpi:
    def test_basic(self):
        trades = _make_trades()[:4]
        pair_kpi = compute_per_pair_kpi(trades)
        assert "USDJPY" in pair_kpi
        assert "EURJPY" in pair_kpi
        assert "GBPJPY" in pair_kpi
        assert pair_kpi["USDJPY"]["win"] == 1
        assert pair_kpi["USDJPY"]["loss"] == 1
        assert pair_kpi["EURJPY"]["loss"] == 1
        assert pair_kpi["GBPJPY"]["win"] == 1

    def test_empty(self):
        pair_kpi = compute_per_pair_kpi([])
        assert pair_kpi == {}


class TestCalcMaxLosingStreak:
    def test_basic(self):
        trades = [
            {"result": "WIN"},
            {"result": "LOSS"},
            {"result": "LOSS"},
            {"result": "LOSS"},
            {"result": "WIN"},
            {"result": "LOSS"},
        ]
        assert _calc_max_losing_streak(trades) == 3

    def test_no_losses(self):
        trades = [{"result": "WIN"}, {"result": "WIN"}]
        assert _calc_max_losing_streak(trades) == 0

    def test_empty(self):
        assert _calc_max_losing_streak([]) == 0


class TestCalcMaxDrawdown:
    def test_basic(self):
        # cumulative: 100, 50, 150, 50, 200
        pnl = [100, -50, 100, -100, 150]
        dd = _calc_max_drawdown(pnl)
        # peak=150 at index2, then drop to 50 → dd=100
        assert dd == 100.0

    def test_no_drawdown(self):
        pnl = [100, 100, 100]
        assert _calc_max_drawdown(pnl) == 0.0

    def test_empty(self):
        assert _calc_max_drawdown([]) == 0.0


# ==================== weekly_review.py ====================


class TestGenerateWeeklyReview:
    def test_basic(self, tmp_path):
        signals = _make_signals()
        trades = _make_trades()

        filepath = generate_weekly_review(
            week_end_date="2026-03-05",
            signals=signals,
            trades=trades,
            output_dir=tmp_path,
        )

        assert os.path.exists(filepath)
        content = Path(filepath).read_text(encoding="utf-8")

        # ヘッダ
        assert "# Weekly Review" in content
        assert "Strategy Version:" in content

        # Signal Summary
        assert "## Signal Summary" in content

        # KPI
        assert "## KPI" in content
        assert "Win Rate:" in content
        assert "Net PnL:" in content
        assert "Total R:" in content

        # By Pair
        assert "## By Pair" in content

        # Skip Reason
        assert "## Skip Reason Breakdown" in content

        # Rule Violations
        assert "## Rule Violations" in content

    def test_filename_format(self, tmp_path):
        filepath = generate_weekly_review(
            week_end_date="2026-03-04",
            signals=[],
            trades=[],
            output_dir=tmp_path,
        )
        # 2026-03-04 is Wednesday → week = Mon 03-02 ~ Sun 03-08
        assert "weekly_review_20260308.md" in filepath

    def test_empty_data(self, tmp_path):
        filepath = generate_weekly_review(
            week_end_date="2026-03-05",
            signals=[],
            trades=[],
            output_dir=tmp_path,
        )
        content = Path(filepath).read_text(encoding="utf-8")
        assert "(no trades)" in content
        assert "(none)" in content  # reason codes


# ==================== monthly_review.py ====================


class TestGenerateMonthlyReview:
    def test_basic(self, tmp_path):
        signals = _make_signals()
        trades = _make_trades()

        filepath = generate_monthly_review(
            year_month="2026-03",
            signals=signals,
            trades=trades,
            output_dir=tmp_path,
        )

        assert os.path.exists(filepath)
        content = Path(filepath).read_text(encoding="utf-8")

        # ヘッダ
        assert "# Monthly Review" in content
        assert "Month: 2026-03" in content
        assert "Strategy Version:" in content

        # KPI (月次は PF, Avg Win/Loss, Max Win/Loss, Max Losing Streak, Max DD を含む)
        assert "## KPI" in content
        assert "Profit Factor:" in content
        assert "Average Win:" in content
        assert "Average Loss:" in content
        assert "Max Win:" in content
        assert "Max Loss:" in content
        assert "Max Losing Streak:" in content
        assert "Max Drawdown:" in content

        # By Pair
        assert "## By Pair" in content

        # Skip Reason
        assert "## Skip Reason Breakdown" in content

        # Rule Violations
        assert "## Rule Violations" in content

        # Improvement Candidates (月次のみ)
        assert "## Improvement Candidates" in content

    def test_filename_format(self, tmp_path):
        filepath = generate_monthly_review(
            year_month="2026-03",
            signals=[],
            trades=[],
            output_dir=tmp_path,
        )
        assert "monthly_review_202603.md" in filepath

    def test_empty_data(self, tmp_path):
        filepath = generate_monthly_review(
            year_month="2026-03",
            signals=[],
            trades=[],
            output_dir=tmp_path,
        )
        content = Path(filepath).read_text(encoding="utf-8")
        assert "(no trades)" in content

    def test_february(self, tmp_path):
        """2月(28日 or 29日)の期間計算"""
        filepath = generate_monthly_review(
            year_month="2026-02",
            signals=[
                {"generated_date_jst": "2026-02-28", "pair": "USDJPY", "decision": "ENTRY_OK", "reason_codes": ""},
            ],
            trades=[],
            output_dir=tmp_path,
        )
        content = Path(filepath).read_text(encoding="utf-8")
        assert "Month: 2026-02" in content
        assert "Signals: 1" in content


# ==================== _suggest_improvements ====================


class TestSuggestImprovements:
    def _base_trade_kpi(self, **overrides):
        kpi = {
            "total_trades": 5, "closed_trades": 5, "open_trades": 0,
            "win": 2, "loss": 3, "breakeven": 0,
            "win_rate": 40.0, "profit_factor": 1.1,
            "gross_pnl_jpy": 5000, "net_pnl_jpy": 4000, "swap_jpy": -100,
            "total_r": 0.5, "avg_r": 0.1,
            "avg_win_jpy": 5000, "avg_loss_jpy": -3000,
            "max_win_jpy": 8000, "max_loss_jpy": -5000,
            "max_losing_streak": 2, "max_drawdown_jpy": 6000,
            "rule_violations": 0, "violation_details": [],
        }
        kpi.update(overrides)
        return kpi

    def _base_sig_kpi(self):
        return {"total_signals": 10, "entry_ok": 5, "skip": 5, "no_data": 0, "error": 0}

    def test_low_win_rate(self):
        kpi = self._base_trade_kpi(win_rate=30.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("below 40%" in s for s in result)

    def test_low_pf(self):
        kpi = self._base_trade_kpi(profit_factor=0.8)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("below 1.0" in s for s in result)

    def test_max_losing_streak(self):
        kpi = self._base_trade_kpi(max_losing_streak=3)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("losing streak" in s.lower() for s in result)

    def test_negative_avg_r(self):
        kpi = self._base_trade_kpi(avg_r=-0.3)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("Average R" in s for s in result)

    def test_pair_zero_win_rate(self):
        kpi = self._base_trade_kpi()
        pair_kpi = {"GBPJPY": {"closed_trades": 3, "win": 0, "loss": 3, "win_rate": 0}}
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, pair_kpi, [])
        assert any("GBPJPY" in s for s in result)

    def test_high_sl_rate(self):
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "SL"}] * 4 + [{"status": "CLOSED", "exit_reason": "TP1_TP2"}]
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert any("SL hit rate" in s for s in result)

    def test_high_manual_rate(self):
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "MANUAL"}] * 3 + [{"status": "CLOSED", "exit_reason": "SL"}]
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert any("Manual exits" in s for s in result)

    def test_rule_violations(self):
        kpi = self._base_trade_kpi(rule_violations=2)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("violation" in s.lower() for s in result)

    def test_skip_reason_dominance(self):
        kpi = self._base_trade_kpi()
        reason_codes = {"W": 6, "P": 2, "D": 2}
        result = _suggest_improvements(self._base_sig_kpi(), reason_codes, kpi, {}, [])
        assert any("Skip reason 'W'" in s for s in result)

    def test_no_suggestions_when_healthy(self):
        kpi = self._base_trade_kpi(win_rate=55.0, profit_factor=1.8, avg_r=0.5, max_losing_streak=1)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert len(result) == 0

    # --- 境界値テスト ---

    def test_win_rate_exactly_40_no_suggestion(self):
        """勝率ちょうど40%はトリガーしない (< 40 のみ)"""
        kpi = self._base_trade_kpi(win_rate=40.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("below 40%" in s for s in result)

    def test_win_rate_below_threshold_trades(self):
        """closed_trades < 3 の場合、低勝率でもトリガーしない"""
        kpi = self._base_trade_kpi(closed_trades=2, win_rate=0.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("below 40%" in s for s in result)

    def test_pf_exactly_1_no_suggestion(self):
        """PF ちょうど 1.0 はトリガーしない (< 1.0 のみ)"""
        kpi = self._base_trade_kpi(profit_factor=1.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("below 1.0" in s for s in result)

    def test_pf_inf_no_suggestion(self):
        """PF が "inf" (損失なし) はトリガーしない"""
        kpi = self._base_trade_kpi(profit_factor="inf")
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("below 1.0" in s for s in result)

    def test_pf_below_threshold_trades(self):
        """closed_trades < 3 の場合、低PFでもトリガーしない"""
        kpi = self._base_trade_kpi(closed_trades=2, profit_factor=0.5)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("below 1.0" in s for s in result)

    def test_losing_streak_exactly_3(self):
        """連敗ちょうど3はトリガーする (>= 3)"""
        kpi = self._base_trade_kpi(max_losing_streak=3)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert any("losing streak" in s.lower() for s in result)

    def test_losing_streak_2_no_suggestion(self):
        """連敗2はトリガーしない"""
        kpi = self._base_trade_kpi(max_losing_streak=2)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("losing streak" in s.lower() for s in result)

    def test_avg_r_zero_no_suggestion(self):
        """avg_r = 0 はトリガーしない (< 0 のみ)"""
        kpi = self._base_trade_kpi(avg_r=0.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("Average R" in s for s in result)

    def test_avg_r_below_threshold_trades(self):
        """closed_trades < 3 の場合、負のavg_rでもトリガーしない"""
        kpi = self._base_trade_kpi(closed_trades=2, avg_r=-1.0)
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, [])
        assert not any("Average R" in s for s in result)

    def test_pair_one_trade_no_suggestion(self):
        """1トレードのみの通貨ペアはトリガーしない (closed_trades >= 2)"""
        kpi = self._base_trade_kpi()
        pair_kpi = {"GBPJPY": {"closed_trades": 1, "win": 0, "loss": 1, "win_rate": 0}}
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, pair_kpi, [])
        assert not any("GBPJPY" in s for s in result)

    def test_pair_nonzero_win_rate_no_suggestion(self):
        """勝率 > 0% の通貨ペアはトリガーしない"""
        kpi = self._base_trade_kpi()
        pair_kpi = {"GBPJPY": {"closed_trades": 3, "win": 1, "loss": 2, "win_rate": 33.3}}
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, pair_kpi, [])
        assert not any("GBPJPY" in s for s in result)

    def test_sl_rate_exactly_60(self):
        """SL到達率ちょうど60%はトリガーする (>= 60)"""
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "SL"}] * 3 + [{"status": "CLOSED", "exit_reason": "TP1_TP2"}] * 2
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert any("SL hit rate" in s for s in result)

    def test_sl_rate_below_60_no_suggestion(self):
        """SL到達率59%以下はトリガーしない"""
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "SL"}] * 2 + [{"status": "CLOSED", "exit_reason": "TP1_TP2"}] * 2
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert not any("SL hit rate" in s for s in result)

    def test_sl_rate_below_threshold_trades(self):
        """CLOSED < 3 の場合、高SL率でもトリガーしない"""
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "SL"}] * 2
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert not any("SL hit rate" in s for s in result)

    def test_manual_rate_exactly_50(self):
        """MANUAL決済率ちょうど50%はトリガーする (>= 50)"""
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "MANUAL"}] * 2 + [{"status": "CLOSED", "exit_reason": "SL"}] * 2
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert any("Manual exits" in s for s in result)

    def test_manual_rate_below_50_no_suggestion(self):
        """MANUAL決済率49%以下はトリガーしない"""
        kpi = self._base_trade_kpi()
        trades = [{"status": "CLOSED", "exit_reason": "MANUAL"}] * 1 + [{"status": "CLOSED", "exit_reason": "SL"}] * 3
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert not any("Manual exits" in s for s in result)

    def test_skip_reason_exactly_50_pct(self):
        """理由コード占有率ちょうど50%はトリガーする (>= 50)"""
        kpi = self._base_trade_kpi()
        reason_codes = {"W": 5, "P": 3, "D": 2}  # W = 50%
        result = _suggest_improvements(self._base_sig_kpi(), reason_codes, kpi, {}, [])
        assert any("Skip reason 'W'" in s for s in result)

    def test_skip_reason_below_50_no_suggestion(self):
        """理由コード占有率49%以下はトリガーしない"""
        kpi = self._base_trade_kpi()
        reason_codes = {"W": 4, "P": 3, "D": 3}  # W = 40%
        result = _suggest_improvements(self._base_sig_kpi(), reason_codes, kpi, {}, [])
        assert not any("dominates" in s for s in result)

    def test_skip_reason_below_5_total_no_suggestion(self):
        """合計Skip < 5 の場合、偏りがあってもトリガーしない"""
        kpi = self._base_trade_kpi()
        reason_codes = {"W": 3, "P": 1}  # W = 75% but total = 4
        result = _suggest_improvements(self._base_sig_kpi(), reason_codes, kpi, {}, [])
        assert not any("dominates" in s for s in result)

    def test_open_trades_excluded_from_sl_check(self):
        """OPEN トレードは SL/MANUAL カウントに含まれない"""
        kpi = self._base_trade_kpi()
        trades = [
            {"status": "CLOSED", "exit_reason": "TP1_TP2"},
            {"status": "CLOSED", "exit_reason": "TP1_TP2"},
            {"status": "CLOSED", "exit_reason": "TP1_TP2"},
            {"status": "OPEN", "exit_reason": ""},
            {"status": "OPEN", "exit_reason": ""},
        ]
        result = _suggest_improvements(self._base_sig_kpi(), {}, kpi, {}, trades)
        assert not any("SL hit rate" in s for s in result)
        assert not any("Manual exits" in s for s in result)

    def test_multiple_suggestions_simultaneously(self):
        """複数条件が同時にトリガーされるケース"""
        kpi = self._base_trade_kpi(
            win_rate=20.0, profit_factor=0.5, avg_r=-0.8,
            max_losing_streak=4, rule_violations=1,
        )
        pair_kpi = {"EURJPY": {"closed_trades": 2, "win": 0, "loss": 2, "win_rate": 0}}
        reason_codes = {"W": 8, "P": 1, "D": 1}
        trades = [{"status": "CLOSED", "exit_reason": "SL"}] * 4 + [{"status": "CLOSED", "exit_reason": "TP1_TP2"}]
        result = _suggest_improvements(self._base_sig_kpi(), reason_codes, kpi, pair_kpi, trades)
        # 少なくとも5つ以上: win_rate, PF, losing streak, avg_r, pair, SL rate, violations, skip dominance
        assert len(result) >= 5

    def test_suggestions_in_monthly_review(self, tmp_path):
        """自動提案が monthly_review.md に反映される"""
        trades = _make_trades()
        # 全LOSS にして低勝率を再現
        for t in trades:
            if t.get("status") == "CLOSED":
                t["result"] = "LOSS"
                t["net_pnl_jpy"] = "-5000"
                t["pnl_r"] = "-1.0"
                t["exit_reason"] = "SL"

        filepath = generate_monthly_review(
            year_month="2026-03",
            signals=_make_signals(),
            trades=trades,
            output_dir=tmp_path,
        )
        content = Path(filepath).read_text(encoding="utf-8")
        assert "## Improvement Candidates" in content
        assert "(none detected)" not in content
