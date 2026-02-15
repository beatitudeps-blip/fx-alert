"""
日足スイング高値/安値検出モジュール

ロング：High[i] > High[i-1] AND High[i] > High[i+1]
ショート：Low[i] < Low[i-1] AND Low[i] < Low[i+1]
"""
import pandas as pd
from typing import Optional, Tuple
from datetime import datetime, timedelta


def detect_swing_highs(df: pd.DataFrame, lookback_days: int = 20) -> pd.DataFrame:
    """
    日足データからスイング高値を検出

    Args:
        df: 日足DataFrame（columns: datetime, high, low, close, ...）
        lookback_days: 検出期間（日数）

    Returns:
        スイング高値のDataFrame（datetime, swing_high列追加）
    """
    df = df.copy()
    df['swing_high'] = None

    # High[i] > High[i-1] AND High[i] > High[i+1]
    for i in range(1, len(df) - 1):
        if df.iloc[i]['high'] > df.iloc[i-1]['high'] and \
           df.iloc[i]['high'] > df.iloc[i+1]['high']:
            df.loc[df.index[i], 'swing_high'] = df.iloc[i]['high']

    return df


def detect_swing_lows(df: pd.DataFrame, lookback_days: int = 20) -> pd.DataFrame:
    """
    日足データからスイング安値を検出

    Args:
        df: 日足DataFrame（columns: datetime, high, low, close, ...）
        lookback_days: 検出期間（日数）

    Returns:
        スイング安値のDataFrame（datetime, swing_low列追加）
    """
    df = df.copy()
    df['swing_low'] = None

    # Low[i] < Low[i-1] AND Low[i] < Low[i+1]
    for i in range(1, len(df) - 1):
        if df.iloc[i]['low'] < df.iloc[i-1]['low'] and \
           df.iloc[i]['low'] < df.iloc[i+1]['low']:
            df.loc[df.index[i], 'swing_low'] = df.iloc[i]['low']

    return df


def find_nearest_swing_high(
    df: pd.DataFrame,
    current_time: datetime,
    lookback_days: int = 20
) -> Optional[float]:
    """
    直近N日以内の最も近いスイング高値を取得

    Args:
        df: スイング高値検出済みの日足DataFrame
        current_time: 現在時刻
        lookback_days: 検索期間（日数）

    Returns:
        スイング高値（見つからない場合はNone）
    """
    # lookback_days日前の日付
    start_date = current_time - timedelta(days=lookback_days)

    # 期間内のデータを抽出
    mask = (df['datetime'] >= start_date) & (df['datetime'] < current_time)
    recent_df = df[mask]

    # スイング高値が存在する行のみ抽出
    swing_highs = recent_df[recent_df['swing_high'].notna()]

    if len(swing_highs) == 0:
        return None

    # 最も近い（最新の）スイング高値を返す
    nearest_swing = swing_highs.iloc[-1]
    return nearest_swing['swing_high']


def find_nearest_swing_low(
    df: pd.DataFrame,
    current_time: datetime,
    lookback_days: int = 20
) -> Optional[float]:
    """
    直近N日以内の最も近いスイング安値を取得

    Args:
        df: スイング安値検出済みの日足DataFrame
        current_time: 現在時刻
        lookback_days: 検索期間（日数）

    Returns:
        スイング安値（見つからない場合はNone）
    """
    # lookback_days日前の日付
    start_date = current_time - timedelta(days=lookback_days)

    # 期間内のデータを抽出
    mask = (df['datetime'] >= start_date) & (df['datetime'] < current_time)
    recent_df = df[mask]

    # スイング安値が存在する行のみ抽出
    swing_lows = recent_df[recent_df['swing_low'].notna()]

    if len(swing_lows) == 0:
        return None

    # 最も近い（最新の）スイング安値を返す
    nearest_swing = swing_lows.iloc[-1]
    return nearest_swing['swing_low']


def calculate_structure_tp2(
    df_daily: pd.DataFrame,
    current_time: datetime,
    entry_price: float,
    sl_price: float,
    side: str,
    max_r: float = 3.0,
    lookback_days: int = 20
) -> Tuple[float, str]:
    """
    日足構造型TP2を計算

    Args:
        df_daily: 日足DataFrame
        current_time: 現在時刻
        entry_price: エントリー価格
        sl_price: SL価格
        side: "LONG" or "SHORT"
        max_r: 最大R倍数（デフォルト3.0）
        lookback_days: 検索期間（日数）

    Returns:
        (tp2_price, tp2_source): TP2価格と設定根拠
    """
    sl_distance = abs(entry_price - sl_price)
    max_tp2_r = max_r * sl_distance

    if side == "LONG":
        # ロング：スイング高値を検出
        df_with_swings = detect_swing_highs(df_daily, lookback_days)
        structure_high = find_nearest_swing_high(df_with_swings, current_time, lookback_days)

        max_tp2_price = entry_price + max_tp2_r

        if structure_high is not None and structure_high < max_tp2_price:
            # 構造高値が3R以内
            return structure_high, "STRUCTURE"
        else:
            # 構造高値がない、または3Rを超える → 3Rキャップ
            return max_tp2_price, "MAX_R"

    else:  # SHORT
        # ショート：スイング安値を検出
        df_with_swings = detect_swing_lows(df_daily, lookback_days)
        structure_low = find_nearest_swing_low(df_with_swings, current_time, lookback_days)

        max_tp2_price = entry_price - max_tp2_r

        if structure_low is not None and structure_low > max_tp2_price:
            # 構造安値が3R以内
            return structure_low, "STRUCTURE"
        else:
            # 構造安値がない、または3Rを超える → 3Rキャップ
            return max_tp2_price, "MAX_R"


if __name__ == "__main__":
    # 簡易テスト
    import numpy as np

    # テストデータ作成
    dates = pd.date_range('2024-01-01', periods=30, freq='D')
    highs = [150 + i + np.random.rand() * 2 for i in range(30)]
    lows = [148 + i + np.random.rand() * 2 for i in range(30)]

    # 明示的なスイング高値を作成（15日目）
    highs[15] = 170.0
    highs[14] = 168.0
    highs[16] = 168.5

    df = pd.DataFrame({
        'datetime': dates,
        'high': highs,
        'low': lows,
        'close': [(h + l) / 2 for h, l in zip(highs, lows)]
    })

    print("=== スイング検出テスト ===")
    df_with_swings = detect_swing_highs(df)
    swing_points = df_with_swings[df_with_swings['swing_high'].notna()]

    print(f"\n検出されたスイング高値: {len(swing_points)}件")
    for idx, row in swing_points.iterrows():
        print(f"  {row['datetime'].date()}: {row['swing_high']:.3f}")

    # 最も近いスイング高値を検索
    current_time = pd.Timestamp('2024-01-25')
    nearest = find_nearest_swing_high(df_with_swings, current_time, lookback_days=20)

    if nearest is not None:
        print(f"\n{current_time.date()}時点の最も近いスイング高値: {nearest:.3f}")
    else:
        print(f"\n{current_time.date()}時点の最も近いスイング高値: None")

    # 構造型TP2計算
    tp2_price, source = calculate_structure_tp2(
        df, current_time, entry_price=165.0, sl_price=164.0, side="LONG", max_r=3.0
    )

    print(f"\n構造型TP2: {tp2_price:.3f} (根拠: {source})")
