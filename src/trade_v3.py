"""
V3 Trade and Fill モデル
監査可能な約定記録システム
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class Fill:
    """約定（Fill）記録 - 監査可能な最小単位"""
    trade_id: int
    symbol: str
    side: str  # "LONG" or "SHORT"
    fill_type: str  # "ENTRY", "TP1", "TP2", "SL", "BE"
    fill_time: datetime
    fill_price_mid: float
    fill_price_exec: float  # bid/ask + slippage適用後
    units: float  # 約定数量（通貨単位）
    spread_pips: float
    slippage_pips: float
    spread_cost_jpy: float
    slippage_cost_jpy: float
    swap_jpy: float = 0.0
    pnl_gross_jpy: float = 0.0  # コスト前損益
    pnl_net_jpy: float = 0.0    # コスト後損益


@dataclass
class Trade:
    """
    トレード記録（親）- 複数Fillを持つ

    CRITICAL: initial_sl は絶対に上書きしない（BEに移動してもinitial_slは保持）
    """
    trade_id: int
    symbol: str
    side: str  # "LONG" or "SHORT"
    pattern: str

    # エントリー
    entry_time: datetime
    entry_price_mid: float
    entry_price_exec: float
    units: float  # 初期数量

    # 初期リスク設定（上書き禁止）
    initial_sl_price_mid: float
    initial_sl_price_exec: float
    initial_r_per_unit_jpy: float  # 1通貨あたりの初期リスク
    initial_risk_jpy: float  # 想定最大損失

    # TP設定
    tp1_price_mid: float
    tp2_price_mid: float
    tp1_units: float  # TP1で決済する数量
    tp2_units: float  # TP2で決済する数量

    # ATR
    atr: float

    # 状態
    current_sl: float = None  # BEに移動後の現在SL（初期はinitial_sl_price_exec）
    tp1_hit: bool = False
    remaining_units: float = None  # 残存数量

    # 決済情報
    final_exit_time: Optional[datetime] = None
    final_exit_reason: Optional[str] = None  # "TP2", "SL", "BE"

    # 損益集計
    total_pnl_gross_jpy: float = 0.0
    total_pnl_net_jpy: float = 0.0
    total_cost_jpy: float = 0.0

    # 保有時間
    holding_hours: float = 0.0

    # 約定記録
    fills: List[Fill] = field(default_factory=list)

    def __post_init__(self):
        """初期化後の処理"""
        if self.current_sl is None:
            self.current_sl = self.initial_sl_price_exec
        if self.remaining_units is None:
            self.remaining_units = self.units

    def add_fill(self, fill: Fill):
        """約定を追加し、損益を集計"""
        self.fills.append(fill)
        self.total_pnl_gross_jpy += fill.pnl_gross_jpy
        self.total_pnl_net_jpy += fill.pnl_net_jpy
        self.total_cost_jpy += (fill.spread_cost_jpy + fill.slippage_cost_jpy + fill.swap_jpy)

        # 数量更新
        if fill.fill_type in ["TP1", "TP2", "SL", "BE"]:
            self.remaining_units -= fill.units

    def move_sl_to_be(self):
        """SLをBEに移動（initial_slは保持）"""
        self.current_sl = self.entry_price_exec

    def close(self, exit_time: datetime, exit_reason: str):
        """トレードをクローズ"""
        self.final_exit_time = exit_time
        self.final_exit_reason = exit_reason
        if exit_time and self.entry_time:
            self.holding_hours = (exit_time - self.entry_time).total_seconds() / 3600.0


def calculate_position_size(
    equity_jpy: float,
    entry_price: float,
    sl_price: float,
    risk_pct: float = 0.005,
    min_lot: float = 100.0,
    lot_step: float = 100.0
) -> tuple[float, float]:
    """
    0.5%リスクベースの動的ポジションサイジング

    Args:
        equity_jpy: 現在の資産（JPY）
        entry_price: エントリー価格
        sl_price: ストップロス価格
        risk_pct: リスク率（デフォルト0.005 = 0.5%）
        min_lot: 最小ロット（100 = 0.01 lot）
        lot_step: ロット刻み（100 = 0.01 lot）

    Returns:
        (units, risk_jpy): (取引数量, 想定最大損失JPY)
                          units=0の場合はスキップ
    """
    max_loss_jpy = equity_jpy * risk_pct
    risk_per_unit = abs(entry_price - sl_price)

    if risk_per_unit <= 0:
        return 0.0, 0.0

    # 理論数量
    units_raw = max_loss_jpy / risk_per_unit

    # 0.01lot刻みで切り捨て（超過しない）
    units = (units_raw // lot_step) * lot_step

    # 最小ロット未満はスキップ
    if units < min_lot:
        return 0.0, 0.0

    # 実際のリスク
    actual_risk_jpy = units * risk_per_unit

    return units, actual_risk_jpy
