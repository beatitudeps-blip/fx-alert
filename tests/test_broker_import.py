"""
ブローカーCSV取込モジュール テスト
implementation_plan.md フェーズ2 / data_spec.md セクション5, 6, 7 準拠
"""
import sys
import csv
import tempfile
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from src.broker_import.minnafx_parser import (
    normalize_pair,
    normalize_numeric,
    normalize_side,
    normalize_fill_type,
    parse_execution_time,
    build_fill_id,
    resolve_trade_group_id,
    parse_minnafx_csv,
)
from src.broker_import.signal_matcher import match_fills_to_signals
from src.broker_import.trade_aggregator import aggregate_trades, _estimate_exit_reason
from src.broker_import.csv_output import (
    write_raw_fills_csv,
    append_raw_fills_csv,
    load_existing_fill_ids,
    write_trades_summary_csv,
    RAW_FILLS_COLUMNS,
    TRADES_SUMMARY_COLUMNS,
)
from src.broker_import.importer import import_minnafx_csv

UTC = timezone.utc


# ===========================================================
# normalize_pair テスト
# ===========================================================

class TestNormalizePair:
    def test_basic(self):
        assert normalize_pair("USDJPY") == "USDJPY"

    def test_light_suffix(self):
        assert normalize_pair("EURJPY LIGHT") == "EURJPY"

    def test_light_case_insensitive(self):
        assert normalize_pair("GBPJPY light") == "GBPJPY"
        assert normalize_pair("EURJPY Light") == "EURJPY"

    def test_slash_format(self):
        assert normalize_pair("USD/JPY") == "USDJPY"

    def test_whitespace(self):
        assert normalize_pair("  EURJPY  ") == "EURJPY"

    def test_light_with_slash(self):
        assert normalize_pair("EUR/JPY LIGHT") == "EURJPY"


# ===========================================================
# normalize_numeric テスト
# ===========================================================

class TestNormalizeNumeric:
    def test_normal_number(self):
        assert normalize_numeric("150.123") == 150.123

    def test_comma_separated(self):
        assert normalize_numeric("1,000") == 1000.0

    def test_dash_returns_none(self):
        assert normalize_numeric("-") is None

    def test_empty_returns_none(self):
        assert normalize_numeric("") is None

    def test_negative_number(self):
        assert normalize_numeric("-500") == -500.0

    def test_comma_in_large_number(self):
        assert normalize_numeric("10,000") == 10000.0


# ===========================================================
# normalize_side テスト
# ===========================================================

class TestNormalizeSide:
    def test_buy_japanese(self):
        assert normalize_side("買") == "BUY"

    def test_sell_japanese(self):
        assert normalize_side("売") == "SELL"

    def test_buy_english(self):
        assert normalize_side("BUY") == "BUY"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_side("不明")


# ===========================================================
# normalize_fill_type テスト
# ===========================================================

class TestNormalizeFillType:
    def test_entry(self):
        assert normalize_fill_type("新規") == "ENTRY"

    def test_exit(self):
        assert normalize_fill_type("決済") == "EXIT"

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            normalize_fill_type("不明")


# ===========================================================
# parse_execution_time テスト
# ===========================================================

class TestParseExecutionTime:
    def test_slash_format(self):
        utc, jst = parse_execution_time("2026/03/14 10:30:00")
        assert jst.hour == 10
        assert jst.minute == 30
        # JST → UTC は -9時間
        assert utc.hour == 1
        assert utc.minute == 30

    def test_dash_format(self):
        utc, jst = parse_execution_time("2026-03-14 10:30:00")
        assert jst.hour == 10

    def test_no_seconds(self):
        utc, jst = parse_execution_time("2026/03/14 10:30")
        assert jst.hour == 10

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            parse_execution_time("invalid")


# ===========================================================
# build_fill_id テスト
# ===========================================================

class TestBuildFillId:
    def test_format(self):
        dt = datetime(2026, 3, 15, 0, 5, 10, tzinfo=UTC)
        fid = build_fill_id("USDJPY", dt, "BUY", 10000, 156.235)
        assert fid == "MINNA_NO_FX_USDJPY_2026-03-15T00:05:10Z_BUY_10000_156.235"

    def test_fractional_quantity(self):
        dt = datetime(2026, 3, 15, 0, 5, 10, tzinfo=UTC)
        fid = build_fill_id("EURJPY", dt, "SELL", 5000, 160.100)
        assert "5000" in fid
        assert "SELL" in fid


# ===========================================================
# resolve_trade_group_id テスト
# ===========================================================

class TestResolveTradeGroupId:
    def test_entry_uses_deal_id(self):
        assert resolve_trade_group_id("ENTRY", "12345", "") == "12345"

    def test_exit_uses_settlement_ref(self):
        assert resolve_trade_group_id("EXIT", "99999", "12345") == "12345"

    def test_exit_falls_back_to_deal_id(self):
        assert resolve_trade_group_id("EXIT", "99999", "-") == "99999"
        assert resolve_trade_group_id("EXIT", "99999", "") == "99999"


# ===========================================================
# parse_minnafx_csv テスト
# ===========================================================

def _make_test_csv(tmp_dir, rows, encoding="utf-8"):
    """テスト用CSVを作成する。"""
    filepath = tmp_dir / "test_minnafx.csv"
    headers = [
        "通貨ペア", "区分", "売買", "数量", "約定価格",
        "建玉損益", "累計スワップ", "手数料", "決済損益",
        "約定日時", "取引番号", "決済対象取引番号",
    ]
    with open(filepath, "w", newline="", encoding=encoding) as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
    return filepath


class TestParseMinnafxCsv:
    def test_basic_entry_and_exit(self, tmp_path):
        csv_path = _make_test_csv(tmp_path, [
            ["USDJPY", "新規", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
            ["USDJPY", "決済", "売", "10,000", "156.000",
             "5,000", "100", "0", "5,100",
             "2026/03/15 14:00:00", "100002", "100001"],
        ])
        fills, errors = parse_minnafx_csv(csv_path)

        assert len(errors) == 0
        assert len(fills) == 2

        entry = fills[0]
        assert entry["pair"] == "USDJPY"
        assert entry["side"] == "BUY"
        assert entry["fill_type"] == "ENTRY"
        assert entry["quantity"] == 10000.0
        assert entry["price"] == 155.5
        assert entry["trade_group_id"] == "100001"
        assert entry["import_status"] == "IMPORTED"

        exit_fill = fills[1]
        assert exit_fill["fill_type"] == "EXIT"
        assert exit_fill["side"] == "SELL"
        assert exit_fill["trade_group_id"] == "100001"
        assert exit_fill["net_realized_pnl_jpy"] == 5100.0

    def test_light_pair_normalization(self, tmp_path):
        csv_path = _make_test_csv(tmp_path, [
            ["EURJPY LIGHT", "新規", "買", "5,000", "160.000",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "200001", ""],
        ])
        fills, errors = parse_minnafx_csv(csv_path)
        assert fills[0]["pair"] == "EURJPY"

    def test_dash_values(self, tmp_path):
        csv_path = _make_test_csv(tmp_path, [
            ["GBPJPY", "新規", "売", "10,000", "190.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "300001", ""],
        ])
        fills, errors = parse_minnafx_csv(csv_path)
        entry = fills[0]
        assert entry["gross_realized_pnl_jpy"] == ""
        assert entry["net_realized_pnl_jpy"] == ""
        assert entry["swap_jpy"] == 0.0
        assert entry["fee_jpy"] == 0.0

    def test_duplicate_detection(self, tmp_path):
        # 同一約定を2回記録
        csv_path = _make_test_csv(tmp_path, [
            ["USDJPY", "新規", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
            ["USDJPY", "新規", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
        ])
        fills, errors = parse_minnafx_csv(csv_path)
        assert fills[0]["import_status"] == "IMPORTED"
        assert fills[1]["import_status"] == "DUPLICATE"

    def test_parse_error_handling(self, tmp_path):
        csv_path = _make_test_csv(tmp_path, [
            ["USDJPY", "不明な区分", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
        ])
        fills, errors = parse_minnafx_csv(csv_path)
        assert len(errors) == 1
        assert errors[0]["stage"] == "IMPORT"

    def test_non_strategy_pair_imported(self, tmp_path):
        """戦略対象外通貨もraw_fillsには保存される"""
        csv_path = _make_test_csv(tmp_path, [
            ["AUDJPY", "新規", "買", "10,000", "95.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "400001", ""],
        ])
        fills, errors = parse_minnafx_csv(csv_path)
        assert len(fills) == 1
        assert fills[0]["pair"] == "AUDJPY"


# ===========================================================
# signal_matcher テスト
# ===========================================================

class TestSignalMatcher:
    def test_match_by_pair_side_time(self):
        fills = [
            {
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "D1_W1_EMA20_PULLBACK_V1_USDJPY_2026-03-13T22:00:00Z",
                "pair": "USDJPY",
                "entry_side": "BUY",
                "generated_at_utc": "2026-03-13T22:00:00Z",
                "decision": "ENTRY_OK",
            },
        ]
        result = match_fills_to_signals(fills, signals)
        assert result[0]["matched_signal_id"] == signals[0]["signal_id"]
        assert result[0]["import_status"] == "MATCHED"

    def test_no_match_wrong_pair(self):
        fills = [
            {
                "fill_type": "ENTRY",
                "pair": "EURJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "sig1",
                "pair": "USDJPY",
                "entry_side": "BUY",
                "generated_at_utc": "2026-03-13T22:00:00Z",
                "decision": "ENTRY_OK",
            },
        ]
        result = match_fills_to_signals(fills, signals)
        assert result[0]["matched_signal_id"] == ""

    def test_no_match_outside_window(self):
        fills = [
            {
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-20T01:00:00Z",  # 6日後
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "sig1",
                "pair": "USDJPY",
                "entry_side": "BUY",
                "generated_at_utc": "2026-03-13T22:00:00Z",
                "decision": "ENTRY_OK",
            },
        ]
        result = match_fills_to_signals(fills, signals)
        assert result[0]["matched_signal_id"] == ""

    def test_exit_fills_not_matched(self):
        fills = [
            {
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "sig1",
                "pair": "USDJPY",
                "entry_side": "SELL",
                "generated_at_utc": "2026-03-13T22:00:00Z",
                "decision": "ENTRY_OK",
            },
        ]
        result = match_fills_to_signals(fills, signals)
        assert result[0]["matched_signal_id"] == ""


# ===========================================================
# trade_aggregator テスト
# ===========================================================

class TestTradeAggregator:
    def _make_fills(self):
        return [
            {
                "trade_group_id": "100001",
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
            {
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-15T05:00:00Z",
                "quantity": "10000",
                "price": "156.000",
                "gross_realized_pnl_jpy": "5000",
                "net_realized_pnl_jpy": "5100",
                "swap_jpy": "100",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]

    def test_basic_aggregation(self):
        fills = self._make_fills()
        trades = aggregate_trades(fills)
        assert len(trades) == 1
        trade = trades[0]
        assert trade["pair"] == "USDJPY"
        assert trade["side"] == "BUY"
        assert trade["status"] == "CLOSED"
        assert trade["result"] == "WIN"
        assert trade["net_pnl_jpy"] == 5100.0
        assert trade["swap_jpy"] == 100.0
        assert trade["entry_price_actual"] == 155.5
        assert trade["total_entry_quantity"] == 10000.0
        assert trade["total_exit_quantity"] == 10000.0

    def test_open_trade(self):
        fills = [self._make_fills()[0]]  # entry only
        trades = aggregate_trades(fills)
        assert len(trades) == 1
        assert trades[0]["status"] == "OPEN"
        assert trades[0]["result"] == "OPEN"

    def test_loss_trade(self):
        fills = self._make_fills()
        fills[1]["net_realized_pnl_jpy"] = "-3000"
        fills[1]["gross_realized_pnl_jpy"] = "-3000"
        trades = aggregate_trades(fills)
        assert trades[0]["result"] == "LOSS"

    def test_strategy_pairs_only(self):
        fills = [
            {
                "trade_group_id": "500001",
                "fill_type": "ENTRY",
                "pair": "AUDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "95.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        trades_all = aggregate_trades(fills, strategy_pairs_only=False)
        assert len(trades_all) == 1

        trades_filtered = aggregate_trades(fills, strategy_pairs_only=True)
        assert len(trades_filtered) == 0

    def test_partial_exit(self):
        fills = [
            {
                "trade_group_id": "100001",
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
            {
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-15T05:00:00Z",
                "quantity": "5000",
                "price": "156.000",
                "gross_realized_pnl_jpy": "2500",
                "net_realized_pnl_jpy": "2500",
                "swap_jpy": "50",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        trades = aggregate_trades(fills)
        assert len(trades) == 1
        trade = trades[0]
        assert trade["status"] == "OPEN"
        assert trade["total_exit_quantity"] == 5000.0
        assert trade["remaining_quantity"] == 5000.0

    def test_pnl_r_from_signal_planned_risk_jpy(self):
        """シグナルの planned_risk_jpy から pnl_r を算出"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG001"
        signals = [
            {
                "signal_id": "SIG001",
                "planned_risk_jpy": "5000",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        # pnl_r = net_pnl(5100) / risk_jpy_planned(5000) = 1.02
        assert trade["risk_jpy_planned"] == 5000.0
        assert trade["pnl_r"] == 1.02

    def test_pnl_r_fallback_from_sl_and_qty(self):
        """planned_risk_jpy が空の場合、SL価格と数量からフォールバック"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG002"
        signals = [
            {
                "signal_id": "SIG002",
                "planned_risk_jpy": "",  # 空
                "planned_entry_price": "",
                "planned_sl_price": "155.000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        # fallback: |155.500 - 155.000| * 10000 = 5000
        assert trade["risk_jpy_planned"] == 5000.0
        # pnl_r = 5100 / 5000 = 1.02
        assert trade["pnl_r"] == 1.02

    def test_pnl_r_empty_without_signal(self):
        """シグナル紐付けなし → pnl_r は空"""
        fills = self._make_fills()
        trades = aggregate_trades(fills)
        trade = trades[0]
        assert trade["pnl_r"] == ""
        assert trade["risk_jpy_planned"] == ""

    def test_pnl_r_not_computed_for_open(self):
        """OPEN トレードでは pnl_r を算出しない"""
        fills = [self._make_fills()[0]]  # entry only
        fills[0]["matched_signal_id"] = "SIG003"
        signals = [
            {
                "signal_id": "SIG003",
                "planned_risk_jpy": "5000",
                "planned_sl_price": "155.000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        assert trade["status"] == "OPEN"
        assert trade["pnl_r"] == ""
        # risk_jpy_planned は計算されるべき
        assert trade["risk_jpy_planned"] == 5000.0

    def test_risk_price_from_actual_entry(self):
        """planned_entry_price がない場合、actual から risk_price 算出"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG004"
        signals = [
            {
                "signal_id": "SIG004",
                "planned_risk_jpy": "5000",
                "planned_entry_price": "",  # 空
                "planned_sl_price": "155.000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        # risk_price = |155.500 - 155.000| = 0.5
        assert trade["risk_price"] == 0.5

    def test_exit_reason_tp1_tp2(self):
        """TP2到達 → TP1_TP2"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG_TP2"
        fills[1]["price"] = "156.500"  # TP2 到達
        fills[1]["net_realized_pnl_jpy"] = "10000"
        signals = [
            {
                "signal_id": "SIG_TP2",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
                "planned_tp1_price": "156.000",
                "planned_tp2_price": "156.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        assert trade["exit_reason"] == "TP1_TP2"
        assert trade["tp1_hit"] is True
        assert trade["tp2_hit"] is True
        assert trade["sl_hit"] is False
        assert trade["exit_price_actual"] == 156.5

    def test_exit_reason_sl(self):
        """SL到達 → SL"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG_SL"
        fills[1]["price"] = "155.000"  # SL 到達
        fills[1]["net_realized_pnl_jpy"] = "-5000"
        signals = [
            {
                "signal_id": "SIG_SL",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
                "planned_tp1_price": "156.000",
                "planned_tp2_price": "156.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        assert trades[0]["exit_reason"] == "SL"
        assert trades[0]["sl_hit"] is True

    def test_exit_reason_tp1_be_split_exit(self):
        """分割決済: TP1で50%利確 + 建値SLで残り決済 → TP1_BE"""
        fills = [
            {
                "trade_group_id": "100001",
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "SIG_BE",
                "import_status": "IMPORTED",
            },
            {   # TP1 で50%利確
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-15T03:00:00Z",
                "quantity": "5000",
                "price": "156.000",
                "gross_realized_pnl_jpy": "2500",
                "net_realized_pnl_jpy": "2500",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
            {   # 建値SLで残り決済
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-16T05:00:00Z",
                "quantity": "5000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "0",
                "net_realized_pnl_jpy": "0",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "SIG_BE",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
                "planned_tp1_price": "156.000",
                "planned_tp2_price": "156.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        assert trade["exit_reason"] == "TP1_BE"
        assert trade["tp1_hit"] is True
        assert trade["tp2_hit"] is False

    def test_exit_reason_tp1_tp2_split_exit(self):
        """分割決済: TP1で50%利確 + TP2で残り利確 → TP1_TP2"""
        fills = [
            {
                "trade_group_id": "100001",
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "SIG_TP12",
                "import_status": "IMPORTED",
            },
            {   # TP1 で50%利確
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-15T03:00:00Z",
                "quantity": "5000",
                "price": "156.000",
                "gross_realized_pnl_jpy": "2500",
                "net_realized_pnl_jpy": "2500",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
            {   # TP2 で残り利確
                "trade_group_id": "100001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-17T05:00:00Z",
                "quantity": "5000",
                "price": "156.500",
                "gross_realized_pnl_jpy": "5000",
                "net_realized_pnl_jpy": "5000",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "SIG_TP12",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
                "planned_tp1_price": "156.000",
                "planned_tp2_price": "156.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        trade = trades[0]
        assert trade["exit_reason"] == "TP1_TP2"
        assert trade["tp1_hit"] is True
        assert trade["tp2_hit"] is True

    def test_exit_reason_manual(self):
        """SL/TP いずれにも該当しない → MANUAL"""
        fills = self._make_fills()
        fills[0]["matched_signal_id"] = "SIG_MAN"
        fills[1]["price"] = "155.800"  # SL でも TP でもない
        fills[1]["net_realized_pnl_jpy"] = "3000"
        signals = [
            {
                "signal_id": "SIG_MAN",
                "planned_entry_price": "155.500",
                "planned_sl_price": "155.000",
                "planned_tp1_price": "156.000",
                "planned_tp2_price": "156.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        assert trades[0]["exit_reason"] == "MANUAL"

    def test_exit_reason_unknown_no_signal(self):
        """シグナル紐付けなし → UNKNOWN"""
        fills = self._make_fills()
        trades = aggregate_trades(fills)
        assert trades[0]["exit_reason"] == "UNKNOWN"

    def test_exit_reason_sell_sl(self):
        """SELL側のSL到達"""
        fills = [
            {
                "trade_group_id": "200001",
                "fill_type": "ENTRY",
                "pair": "USDJPY",
                "side": "SELL",
                "execution_time_utc": "2026-03-14T01:00:00Z",
                "quantity": "10000",
                "price": "155.500",
                "gross_realized_pnl_jpy": "",
                "net_realized_pnl_jpy": "",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "SIG_SELL_SL",
                "import_status": "IMPORTED",
            },
            {
                "trade_group_id": "200001",
                "fill_type": "EXIT",
                "pair": "USDJPY",
                "side": "BUY",
                "execution_time_utc": "2026-03-15T05:00:00Z",
                "quantity": "10000",
                "price": "156.000",  # SL到達 (SELL なので上方向)
                "gross_realized_pnl_jpy": "-5000",
                "net_realized_pnl_jpy": "-5000",
                "swap_jpy": "0",
                "fee_jpy": "0",
                "matched_signal_id": "",
                "import_status": "IMPORTED",
            },
        ]
        signals = [
            {
                "signal_id": "SIG_SELL_SL",
                "planned_entry_price": "155.500",
                "planned_sl_price": "156.000",
                "planned_tp1_price": "155.000",
                "planned_tp2_price": "154.500",
                "planned_risk_jpy": "5000",
            }
        ]
        trades = aggregate_trades(fills, signals=signals)
        assert trades[0]["exit_reason"] == "SL"
        assert trades[0]["sl_hit"] is True


# ===========================================================
# csv_output テスト
# ===========================================================

class TestCsvOutput:
    def test_write_and_load_raw_fills(self, tmp_path):
        fills = [
            {"fill_id": "test_001", "broker": "MINNA_NO_FX", "pair": "USDJPY"},
            {"fill_id": "test_002", "broker": "MINNA_NO_FX", "pair": "EURJPY"},
        ]
        write_raw_fills_csv(fills, tmp_path)

        ids = load_existing_fill_ids(tmp_path)
        assert "test_001" in ids
        assert "test_002" in ids

    def test_append_raw_fills(self, tmp_path):
        fills1 = [{"fill_id": "test_001", "broker": "MINNA_NO_FX"}]
        fills2 = [{"fill_id": "test_002", "broker": "MINNA_NO_FX"}]

        append_raw_fills_csv(fills1, tmp_path)
        append_raw_fills_csv(fills2, tmp_path)

        ids = load_existing_fill_ids(tmp_path)
        assert len(ids) == 2

    def test_write_trades_summary(self, tmp_path):
        trades = [
            {
                "trade_id": "test_trade_001",
                "pair": "USDJPY",
                "side": "BUY",
                "status": "CLOSED",
                "result": "WIN",
                "rule_violation": False,
            },
        ]
        write_trades_summary_csv(trades, tmp_path)

        filepath = tmp_path / "trades_summary.csv"
        assert filepath.exists()

        with open(filepath, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["trade_id"] == "test_trade_001"
        assert rows[0]["rule_violation"] == "FALSE"


# ===========================================================
# importer 統合テスト
# ===========================================================

class TestImporter:
    def test_full_import_flow(self, tmp_path):
        # テスト用CSV作成
        csv_path = _make_test_csv(tmp_path, [
            ["USDJPY", "新規", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
            ["USDJPY", "決済", "売", "10,000", "156.000",
             "5,000", "100", "0", "5,100",
             "2026/03/15 14:00:00", "100002", "100001"],
        ])

        result = import_minnafx_csv(
            csv_path=csv_path,
            output_dir=tmp_path,
        )

        assert result["imported"] == 2
        assert result["parse_errors"] == 0
        assert result["duplicates"] == 0
        assert result["trades_generated"] == 1

        # raw_fills.csv が生成された
        assert (tmp_path / "raw_fills.csv").exists()
        # trades_summary.csv が生成された
        assert (tmp_path / "trades_summary.csv").exists()

    def test_duplicate_skip_on_reimport(self, tmp_path):
        csv_path = _make_test_csv(tmp_path, [
            ["USDJPY", "新規", "買", "10,000", "155.500",
             "-", "-", "-", "-",
             "2026/03/14 10:00:00", "100001", ""],
        ])

        # 1回目
        result1 = import_minnafx_csv(csv_path=csv_path, output_dir=tmp_path)
        assert result1["imported"] == 1
        assert result1["duplicates"] == 0

        # 2回目 (同じCSV)
        result2 = import_minnafx_csv(csv_path=csv_path, output_dir=tmp_path)
        assert result2["imported"] == 0
        assert result2["duplicates"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
