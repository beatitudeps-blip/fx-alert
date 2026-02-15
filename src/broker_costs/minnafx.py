"""
みんなのFX コスト計算モジュール
スプレッド（固定/拡大帯）、スリッページ、スワップ、メンテナンス判定
"""
from datetime import datetime
from typing import Tuple
from ..config_loader import BrokerConfig


class MinnafxCostModel:
    """みんなのFX のコストモデル"""

    def __init__(self, config: BrokerConfig):
        self.config = config

    def get_spread_pips(self, symbol: str, dt: datetime) -> float:
        """
        スプレッド（pips）を取得

        Args:
            symbol: 通貨ペア
            dt: 判定時刻（JST）

        Returns:
            スプレッド（pips）
        """
        # 銭 → pips（1銭 = 0.01円 = 1 pip for JPY pairs）
        spread_sen = self.config.get_advertised_spread_sen(symbol, dt)
        return spread_sen  # 銭とpipsは同値（JPYペア）

    def calculate_execution_price(
        self,
        mid_price: float,
        side: str,
        symbol: str,
        dt: datetime
    ) -> float:
        """
        実行価格を計算（スプレッド + スリッページ考慮）

        Args:
            mid_price: 仲値
            side: "LONG" or "SHORT"
            symbol: 通貨ペア
            dt: 約定時刻（JST）

        Returns:
            実行価格
        """
        spread_pips = self.get_spread_pips(symbol, dt)
        slippage_pips = self.config.get_slippage_pips()

        # pips → 価格変動（JPYペアは0.01円/pip）
        half_spread = (spread_pips * 0.01) / 2
        slippage = slippage_pips * 0.01

        if side == "LONG":
            # LONG: ask + slippage
            ask = mid_price + half_spread
            return ask + slippage
        else:  # SHORT
            # SHORT: bid - slippage
            bid = mid_price - half_spread
            return bid - slippage

    def calculate_exit_price(
        self,
        mid_price: float,
        side: str,
        symbol: str,
        dt: datetime
    ) -> float:
        """
        決済価格を計算（スプレッド + スリッページ考慮）

        Args:
            mid_price: 仲値
            side: "LONG" or "SHORT"
            symbol: 通貨ペア
            dt: 約定時刻（JST）

        Returns:
            決済価格
        """
        spread_pips = self.get_spread_pips(symbol, dt)
        slippage_pips = self.config.get_slippage_pips()

        half_spread = (spread_pips * 0.01) / 2
        slippage = slippage_pips * 0.01

        if side == "LONG":
            # LONG exit: bid - slippage
            bid = mid_price - half_spread
            return bid - slippage
        else:  # SHORT
            # SHORT exit: ask + slippage
            ask = mid_price + half_spread
            return ask + slippage

    def calculate_fill_costs(
        self,
        units: float,
        side: str,
        symbol: str,
        dt: datetime
    ) -> Tuple[float, float]:
        """
        約定コストを計算（スプレッド + スリッページ）

        Args:
            units: 約定数量（通貨単位）
            side: "LONG" or "SHORT"
            symbol: 通貨ペア
            dt: 約定時刻（JST）

        Returns:
            (spread_cost_jpy, slippage_cost_jpy)
        """
        spread_pips = self.get_spread_pips(symbol, dt)
        slippage_pips = self.config.get_slippage_pips()

        # pips → 円（JPYペアは1pip = 0.01円）
        spread_cost_jpy = units * spread_pips * 0.01
        slippage_cost_jpy = units * slippage_pips * 0.01

        return spread_cost_jpy, slippage_cost_jpy

    def calculate_swap_jpy(
        self,
        units: float,
        side: str,
        symbol: str,
        holding_days: int
    ) -> float:
        """
        スワップ（円）を計算

        Args:
            units: 保有数量（通貨単位）
            side: "LONG" or "SHORT"
            symbol: 通貨ペア
            holding_days: 保有日数

        Returns:
            スワップ（円）
        """
        mode = self.config.get_swap_mode()
        if mode == 'ignore':
            return 0.0

        # 1ロット（10,000通貨）あたりのスワップを取得
        swap_per_lot = self.config.get_swap_jpy_per_lot(symbol, side)

        # 実際の数量に応じてスケール
        lot_size = self.config.get_lot_size_units(symbol)
        lots = units / lot_size

        return swap_per_lot * lots * holding_days

    def is_tradable(self, dt: datetime, use_daylight: bool = False) -> bool:
        """
        取引可能時間かどうか判定（メンテナンス時間を除く）

        Args:
            dt: 判定時刻（JST）
            use_daylight: 米国夏時間を適用するか

        Returns:
            True if 取引可能
        """
        return not self.config.is_maintenance_window(dt, use_daylight)

    def should_skip_entry(self, symbol: str, dt: datetime) -> Tuple[bool, str]:
        """
        エントリーを見送るべきか判定（スプレッドフィルター）

        Args:
            symbol: 通貨ペア
            dt: 判定時刻（JST）

        Returns:
            (should_skip, reason)
        """
        if not self.config.is_spread_filter_enabled():
            return False, ""

        # メンテナンス中
        if not self.is_tradable(dt):
            return True, "メンテナンス時間中"

        # スプレッド閾値チェック
        spread_pips = self.get_spread_pips(symbol, dt)
        multiplier = self.config.get_spread_filter_multiplier()

        # 固定帯スプレッドを基準とする
        fixed_dt = dt.replace(hour=10, minute=0)  # 固定帯の時刻
        fixed_spread = self.config.get_advertised_spread_sen(symbol, fixed_dt)

        if spread_pips > fixed_spread * multiplier:
            return True, f"スプレッド超過（{spread_pips:.1f} pips > {fixed_spread * multiplier:.1f} pips）"

        return False, ""


if __name__ == "__main__":
    from ..config_loader import load_broker_config
    from zoneinfo import ZoneInfo

    # テスト実行
    config = load_broker_config()
    cost_model = MinnafxCostModel(config)

    # 固定帯でのコスト
    dt_fixed = datetime(2026, 2, 15, 10, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    symbol = "USD/JPY"
    side = "LONG"
    units = 10000  # 1 lot

    print(f"=== {symbol} {side} @ {dt_fixed} ===")
    print(f"Spread: {cost_model.get_spread_pips(symbol, dt_fixed)} pips")

    entry_price = cost_model.calculate_execution_price(150.0, side, symbol, dt_fixed)
    exit_price = cost_model.calculate_exit_price(150.5, side, symbol, dt_fixed)
    print(f"Entry: 150.0 → {entry_price:.3f}")
    print(f"Exit: 150.5 → {exit_price:.3f}")

    spread_cost, slip_cost = cost_model.calculate_fill_costs(units, side, symbol, dt_fixed)
    print(f"Spread cost: {spread_cost:.2f} JPY")
    print(f"Slippage cost: {slip_cost:.2f} JPY")

    # 拡大帯でのコスト
    dt_widened = datetime(2026, 2, 15, 7, 30, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    print(f"\n=== {symbol} @ {dt_widened} (拡大帯) ===")
    print(f"Spread: {cost_model.get_spread_pips(symbol, dt_widened)} pips")

    should_skip, reason = cost_model.should_skip_entry(symbol, dt_widened)
    print(f"Should skip: {should_skip}, Reason: {reason}")

    # メンテナンステスト
    dt_maint = datetime(2026, 2, 15, 6, 55, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
    print(f"\n=== Maintenance check @ {dt_maint} ===")
    is_tradable = cost_model.is_tradable(dt_maint)
    print(f"Tradable: {is_tradable}")
