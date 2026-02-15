"""バックテストエンジン"""
import pandas as pd
from typing import List, Dict, Optional, Tuple
from .data import fetch_data
from .strategy import check_signal
from .spread_minnafx import add_bid_ask
from .indicators import calculate_atr


class Trade:
    """トレード記録"""
    def __init__(
        self,
        entry_time,
        direction: str,
        entry_price: float,
        sl: float,
        tp1: float,
        tp2: float,
        atr: float,
        pattern: str
    ):
        self.entry_time = entry_time
        self.direction = direction  # "LONG" or "SHORT"
        self.entry_price = entry_price
        self.sl = sl
        self.tp1 = tp1
        self.tp2 = tp2
        self.atr = atr
        self.pattern = pattern
        self.exit_time = None
        self.exit_price = None
        self.exit_reason = None
        self.pnl = 0.0
        self.position_size = 1.0  # 初期50%残り
        self.tp1_hit = False


def run_backtest(
    symbol: str,
    start_date: str,
    end_date: str,
    api_key: Optional[str] = None,
    atr_multiplier: float = 1.5,
    risk_pct: float = 0.005,
    lot_size: int = 10000,
    use_cache: bool = True
) -> Tuple[List[Trade], pd.DataFrame]:
    """
    バックテスト実行

    Args:
        symbol: 通貨ペア
        start_date: 開始日（例: "2024-01-01"）
        end_date: 終了日（例: "2024-12-31"）
        api_key: APIキー
        atr_multiplier: ATR倍率（SL計算用）
        risk_pct: リスク率（0.005 = 0.5%）
        lot_size: 1ロットの単位数（デフォルト10,000）
        use_cache: キャッシュ使用

    Returns:
        (trades, equity_df)
    """
    # データ取得
    h4 = fetch_data(symbol, "4h", 5000, api_key, use_cache)
    d1 = fetch_data(symbol, "1day", 1000, api_key, use_cache)

    # 日付フィルタリング
    h4 = h4[(h4["datetime"] >= start_date) & (h4["datetime"] <= end_date)].reset_index(drop=True)
    d1 = d1[(d1["datetime"] >= start_date) & (d1["datetime"] <= end_date)].reset_index(drop=True)

    # bid/ask追加
    h4 = add_bid_ask(h4, symbol)

    trades: List[Trade] = []
    active_trade: Optional[Trade] = None
    initial_balance = 100000.0
    balance = initial_balance
    equity_curve = []

    for i in range(len(h4)):
        current_bar = h4.iloc[i]
        current_time = current_bar["datetime"]

        # アクティブトレードの決済チェック
        if active_trade is not None:
            direction = active_trade.direction
            sl = active_trade.sl
            tp1 = active_trade.tp1
            tp2 = active_trade.tp2

            if direction == "LONG":
                # SL判定（bid価格で）
                if current_bar["bid_low"] <= sl:
                    active_trade.exit_time = current_time
                    active_trade.exit_price = sl
                    active_trade.exit_reason = "SL" if not active_trade.tp1_hit else "BE"
                    pnl_remaining = (sl - active_trade.entry_price) * active_trade.position_size * lot_size
                    balance += pnl_remaining
                    active_trade.pnl += pnl_remaining  # 累積PnL
                    active_trade = None
                    equity_curve.append({"datetime": current_time, "balance": balance})
                    continue

                # TP1判定（bid価格で）
                if not active_trade.tp1_hit and current_bar["bid_high"] >= tp1:
                    active_trade.tp1_hit = True
                    active_trade.position_size = 0.5  # 50%決済、残り50%
                    pnl_partial = (tp1 - active_trade.entry_price) * 0.5 * lot_size
                    active_trade.pnl += pnl_partial  # 累積PnLに加算
                    balance += pnl_partial
                    # SLをBEに移動
                    active_trade.sl = active_trade.entry_price

                # TP2判定（bid価格で）
                if active_trade.tp1_hit and current_bar["bid_high"] >= tp2:
                    active_trade.exit_time = current_time
                    active_trade.exit_price = tp2
                    active_trade.exit_reason = "TP2"
                    pnl_partial = (tp2 - active_trade.entry_price) * 0.5 * lot_size
                    active_trade.pnl += pnl_partial  # 累積PnLに加算
                    balance += pnl_partial
                    active_trade = None
                    equity_curve.append({"datetime": current_time, "balance": balance})
                    continue

            elif direction == "SHORT":
                # SL判定（ask価格で）
                if current_bar["ask_high"] >= sl:
                    active_trade.exit_time = current_time
                    active_trade.exit_price = sl
                    active_trade.exit_reason = "SL" if not active_trade.tp1_hit else "BE"
                    pnl_remaining = (active_trade.entry_price - sl) * active_trade.position_size * lot_size
                    balance += pnl_remaining
                    active_trade.pnl += pnl_remaining  # 累積PnL
                    active_trade = None
                    equity_curve.append({"datetime": current_time, "balance": balance})
                    continue

                # TP1判定（ask価格で）
                if not active_trade.tp1_hit and current_bar["ask_low"] <= tp1:
                    active_trade.tp1_hit = True
                    active_trade.position_size = 0.5
                    pnl_partial = (active_trade.entry_price - tp1) * 0.5 * lot_size
                    active_trade.pnl += pnl_partial  # 累積PnLに加算
                    balance += pnl_partial
                    active_trade.sl = active_trade.entry_price

                # TP2判定（ask価格で）
                if active_trade.tp1_hit and current_bar["ask_low"] <= tp2:
                    active_trade.exit_time = current_time
                    active_trade.exit_price = tp2
                    active_trade.exit_reason = "TP2"
                    pnl_partial = (active_trade.entry_price - tp2) * 0.5 * lot_size
                    active_trade.pnl += pnl_partial  # 累積PnLに加算
                    balance += pnl_partial
                    active_trade = None
                    equity_curve.append({"datetime": current_time, "balance": balance})
                    continue

        # 新規シグナルチェック（アクティブトレードがない場合のみ）
        if active_trade is None and i >= 20:  # 十分なデータがある場合
            # 過去データで判定（ルックアヘッドバイアス回避）
            h4_past = h4.iloc[:i+1].copy()
            d1_past = d1[d1["datetime"] <= current_time].copy()

            if len(d1_past) >= 20:
                signal = check_signal(h4_past, d1_past)

                if signal["signal"] in ["LONG", "SHORT"]:
                    # 次の足の始値でエントリー（lookahead回避）
                    if i + 1 < len(h4):
                        next_bar = h4.iloc[i + 1]
                        direction = signal["signal"]
                        atr = signal["atr"]

                        if direction == "LONG":
                            entry_price = next_bar["ask_open"]  # LONGはask価格
                            sl = entry_price - atr * atr_multiplier
                            tp1 = entry_price + atr * 1.0
                            tp2 = entry_price + atr * 2.0
                        else:  # SHORT
                            entry_price = next_bar["bid_open"]  # SHORTはbid価格
                            sl = entry_price + atr * atr_multiplier
                            tp1 = entry_price - atr * 1.0
                            tp2 = entry_price - atr * 2.0

                        trade = Trade(
                            entry_time=next_bar["datetime"],
                            direction=direction,
                            entry_price=entry_price,
                            sl=sl,
                            tp1=tp1,
                            tp2=tp2,
                            atr=atr,
                            pattern=signal["pattern"]
                        )
                        trades.append(trade)
                        active_trade = trade

    equity_df = pd.DataFrame(equity_curve)
    return trades, equity_df
