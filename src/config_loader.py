"""
設定ファイルローダー（みんなのFX対応）
config/minnafx.yaml を読み込み、バリデーションとアクセサを提供
"""
import yaml
from pathlib import Path
from datetime import datetime, time
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo


class BrokerConfig:
    """ブローカー設定を管理するクラス"""

    def __init__(self, config_path: str = "config/minnafx.yaml"):
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(self.config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)

        self._validate()
        self.tz = ZoneInfo(self.config['timezone'])

    def _validate(self):
        """設定ファイルの必須項目をバリデーション"""
        required_keys = ['broker', 'timezone', 'trade_unit', 'spread', 'maintenance', 'swap']
        for key in required_keys:
            if key not in self.config:
                raise ValueError(f"Missing required config key: {key}")

        # スプレッド設定の検証
        if 'advertised_sen' not in self.config['spread']:
            raise ValueError("Missing spread.advertised_sen")

        # 取引単位の検証
        tu = self.config['trade_unit']
        if tu['lot_size_units'] <= 0 or tu['min_lot'] <= 0 or tu['lot_step'] <= 0:
            raise ValueError("Invalid trade_unit values (must be > 0)")

    def get_lot_size_units(self, symbol: str = None) -> int:
        """1ロットの通貨単位数を取得（通貨ペア別の上書きにも対応）"""
        base = self.config['trade_unit']['lot_size_units']

        # 上書き設定があれば適用
        if symbol and symbol in self.config['trade_unit'].get('overrides', {}):
            return self.config['trade_unit']['overrides'][symbol]

        return base

    def get_min_lot(self) -> float:
        """最小ロット数"""
        return self.config['trade_unit']['min_lot']

    def get_lot_step(self) -> float:
        """ロット刻み"""
        return self.config['trade_unit']['lot_step']

    def get_slippage_pips(self) -> float:
        """片道スリッページ（pips）"""
        if not self.config['execution']['slippage']['enabled']:
            return 0.0
        return self.config['execution']['slippage']['one_way_pips']

    def is_spread_filter_enabled(self) -> bool:
        """スプレッドフィルターが有効か"""
        return self.config['execution']['spread_filter']['enabled']

    def get_spread_filter_multiplier(self) -> float:
        """スプレッド見送り閾値（広告スプレッドの何倍まで許容するか）"""
        return self.config['execution']['spread_filter']['max_multiplier_vs_advertised']

    def get_advertised_spread_sen(self, symbol: str, dt: datetime) -> float:
        """
        広告スプレッド（銭）を取得

        Args:
            symbol: 通貨ペア
            dt: 判定時刻（JST）

        Returns:
            広告スプレッド（銭）
        """
        if symbol not in self.config['spread']['advertised_sen']:
            raise ValueError(f"Unknown symbol: {symbol}")

        spreads = self.config['spread']['advertised_sen'][symbol]

        # 時刻に応じて固定帯/拡大帯を判定
        if self._is_widened_window(dt):
            return spreads['widened']
        else:
            return spreads['fixed']

    def _is_widened_window(self, dt: datetime) -> bool:
        """
        拡大帯時間帯かどうか判定

        Args:
            dt: 判定時刻（JST想定）

        Returns:
            True if 拡大帯
        """
        # datetimeのタイムゾーン確認
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)

        # JSTに変換
        dt_jst = dt.astimezone(self.tz)
        t = dt_jst.time()
        weekday = dt_jst.weekday()  # 0=Monday

        widened = self.config['spread']['widened_windows']

        # pre_open: 7:10-8:00（月曜は7:00-8:00）
        pre_start_str = widened['pre_open']['monday_start'] if weekday == 0 else widened['pre_open']['default_start']
        pre_start = time.fromisoformat(pre_start_str)
        pre_end = time.fromisoformat(widened['pre_open']['end'])

        if pre_start <= t < pre_end:
            return True

        # post_close: 5:00-6:50
        post_start = time.fromisoformat(widened['post_close']['start'])
        post_end = time.fromisoformat(widened['post_close']['end'])

        if post_start <= t < post_end:
            return True

        return False

    def is_maintenance_window(self, dt: datetime, use_daylight: bool = False) -> bool:
        """
        メンテナンス時間帯かどうか判定（約定不可）

        Args:
            dt: 判定時刻（JST想定）
            use_daylight: 米国夏時間を適用するか

        Returns:
            True if メンテナンス中
        """
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=self.tz)

        dt_jst = dt.astimezone(self.tz)
        t = dt_jst.time()
        weekday = dt_jst.weekday()  # 0=Monday

        maint = self.config['maintenance']

        # 日次メンテ
        daily_key = 'daylight_time' if use_daylight else 'standard_time'
        daily_config = maint['daily'][daily_key]

        # 月曜
        if weekday == 0:
            for window in daily_config['monday']:
                start = time.fromisoformat(window['start'])
                end = time.fromisoformat(window['end'])
                if start <= t < end:
                    return True
        # 火〜日
        else:
            for window in daily_config['tue_sun']:
                start = time.fromisoformat(window['start'])
                end = time.fromisoformat(window['end'])
                if start <= t < end:
                    return True

        # 週次メンテ（土曜12:00-18:00）
        for window in maint['weekly']:
            if window['dow'] == 'sat' and weekday == 5:  # Saturday
                start = time.fromisoformat(window['start'])
                end = time.fromisoformat(window['end'])
                if start <= t < end:
                    return True

        return False

    def get_swap_mode(self) -> str:
        """スワップモード（ignore / fixed_table / daily_csv）"""
        return self.config['swap']['mode']

    def get_swap_jpy_per_lot(self, symbol: str, side: str) -> float:
        """
        固定テーブルからスワップを取得（1ロットあたり/日）

        Args:
            symbol: 通貨ペア
            side: "LONG" or "SHORT"

        Returns:
            スワップ（円）
        """
        mode = self.get_swap_mode()
        if mode == 'ignore':
            return 0.0

        if mode == 'fixed_table':
            if symbol not in self.config['swap']['fixed_table']:
                return 0.0

            side_key = side.lower()
            return self.config['swap']['fixed_table'][symbol].get(side_key, 0.0)

        # daily_csvは別途CSVから読み込む想定（ここでは未実装）
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        """設定を辞書で返す"""
        return self.config


def load_broker_config(config_path: str = "config/minnafx.yaml") -> BrokerConfig:
    """ブローカー設定をロード"""
    return BrokerConfig(config_path)


if __name__ == "__main__":
    # テスト実行
    config = load_broker_config()
    print(f"Broker: {config.config['broker']}")
    print(f"Lot size: {config.get_lot_size_units()} units")
    print(f"Min lot: {config.get_min_lot()}")
    print(f"Lot step: {config.get_lot_step()}")

    # スプレッドテスト
    test_dt_fixed = datetime(2026, 2, 15, 10, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))  # JST 10:00 → 固定帯
    test_dt_widened = datetime(2026, 2, 15, 7, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))  # JST 7:30 → 拡大帯

    for symbol in ["USD/JPY", "EUR/JPY", "GBP/JPY"]:
        spread_fixed = config.get_advertised_spread_sen(symbol, test_dt_fixed)
        spread_widened = config.get_advertised_spread_sen(symbol, test_dt_widened)
        print(f"{symbol}: fixed={spread_fixed}銭, widened={spread_widened}銭")

    # メンテナンステスト
    test_dt_maint = datetime(2026, 2, 15, 6, 55, 0, tzinfo=ZoneInfo("Asia/Tokyo"))  # JST 6:55 → メンテ中
    is_maint = config.is_maintenance_window(test_dt_maint, use_daylight=False)
    print(f"JST 6:55 is maintenance: {is_maint}")
