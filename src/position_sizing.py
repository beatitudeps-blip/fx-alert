"""
厳格な0.5%リスク管理 + ロット丸め（みんなのFX対応）
違反ゼロを保証
"""
from typing import Tuple
from .config_loader import BrokerConfig


def calculate_position_size_strict(
    equity_jpy: float,
    entry_price: float,
    sl_price: float,
    risk_pct: float,
    config: BrokerConfig,
    symbol: str = None
) -> Tuple[float, float, bool]:
    """
    厳格な0.5%リスク管理 + ロット丸め（違反ゼロ保証）

    Args:
        equity_jpy: 現在の資産（JPY）
        entry_price: エントリー価格
        sl_price: ストップロス価格
        risk_pct: リスク率（デフォルト0.005 = 0.5%）
        config: ブローカー設定
        symbol: 通貨ペア（lot_size上書き用）

    Returns:
        (units, actual_risk_jpy, is_valid):
            units: 取引数量（通貨単位、0.0の場合は取引不可）
            actual_risk_jpy: 実際の最大損失（円）
            is_valid: Trueなら取引可能、Falseなら見送り
    """
    max_loss_jpy = equity_jpy * risk_pct
    risk_per_unit = abs(entry_price - sl_price)

    if risk_per_unit <= 0:
        return 0.0, 0.0, False

    # 理論数量
    units_raw = max_loss_jpy / risk_per_unit

    # ロット単位に丸める
    lot_size = config.get_lot_size_units(symbol)
    lot_step_size = config.get_lot_step() * lot_size  # 0.1Lot = 1,000通貨

    # 切り捨て（超過しない）
    units_rounded = (units_raw // lot_step_size) * lot_step_size

    # 最小ロット未満
    min_lot_size = config.get_min_lot() * lot_size
    if units_rounded < min_lot_size:
        return 0.0, 0.0, False

    # 丸め後の実際のリスク
    actual_risk_jpy = units_rounded * risk_per_unit

    # 【修正】SL約定時の追加コスト（スプレッド、スリッページ）を考慮
    # 保守的に10%の安全マージンを確保（浮動小数点誤差も考慮）
    safety_margin_pct = 0.10
    max_safe_risk = max_loss_jpy * (1.0 - safety_margin_pct)

    # 厳格チェック：安全マージンを考慮して超過チェック
    if actual_risk_jpy > max_safe_risk:
        # 1段階切り下げ
        units_rounded -= lot_step_size

        # 再度最小ロット未満チェック
        if units_rounded < min_lot_size:
            return 0.0, 0.0, False

        # 再計算
        actual_risk_jpy = units_rounded * risk_per_unit

        # 念のため再チェック（安全マージン考慮）
        if actual_risk_jpy > max_safe_risk:
            return 0.0, 0.0, False

    # 最終チェック：絶対に max_loss_jpy を超えないこと
    if actual_risk_jpy > max_loss_jpy:
        return 0.0, 0.0, False

    return units_rounded, actual_risk_jpy, True


def units_to_lots(units: float, config: BrokerConfig, symbol: str = None) -> float:
    """
    通貨単位 → ロット数変換

    Args:
        units: 通貨単位
        config: ブローカー設定
        symbol: 通貨ペア

    Returns:
        ロット数
    """
    lot_size = config.get_lot_size_units(symbol)
    return units / lot_size


def lots_to_units(lots: float, config: BrokerConfig, symbol: str = None) -> float:
    """
    ロット数 → 通貨単位変換

    Args:
        lots: ロット数
        config: ブローカー設定
        symbol: 通貨ペア

    Returns:
        通貨単位
    """
    lot_size = config.get_lot_size_units(symbol)
    return lots * lot_size


if __name__ == "__main__":
    from .config_loader import load_broker_config

    # テスト実行
    config = load_broker_config()

    equity = 100000.0
    entry = 150.0
    sl = 149.0
    risk_pct = 0.005

    units, risk, valid = calculate_position_size_strict(
        equity, entry, sl, risk_pct, config, symbol="USD/JPY"
    )

    lots = units_to_lots(units, config, "USD/JPY")

    print(f"=== Position Sizing Test ===")
    print(f"Equity: {equity:,.0f} JPY")
    print(f"Entry: {entry:.3f}, SL: {sl:.3f}")
    print(f"Risk per unit: {abs(entry - sl):.3f}")
    print(f"Max allowed risk: {equity * risk_pct:,.0f} JPY")
    print(f"\nResult:")
    print(f"  Units: {units:,.0f}")
    print(f"  Lots: {lots:.1f}")
    print(f"  Actual risk: {risk:,.2f} JPY")
    print(f"  Valid: {valid}")
    print(f"  Violation: {risk > equity * risk_pct}")

    # より小さいSL幅でテスト
    print(f"\n=== Small SL Test ===")
    entry2 = 150.0
    sl2 = 149.95
    units2, risk2, valid2 = calculate_position_size_strict(
        equity, entry2, sl2, risk_pct, config, symbol="USD/JPY"
    )
    lots2 = units_to_lots(units2, config, "USD/JPY")

    print(f"Entry: {entry2:.3f}, SL: {sl2:.3f}")
    print(f"Risk per unit: {abs(entry2 - sl2):.3f}")
    print(f"\nResult:")
    print(f"  Units: {units2:,.0f}")
    print(f"  Lots: {lots2:.1f}")
    print(f"  Actual risk: {risk2:,.2f} JPY")
    print(f"  Valid: {valid2}")
    print(f"  Violation: {risk2 > equity * risk_pct}")
