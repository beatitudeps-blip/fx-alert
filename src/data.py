"""データ取得モジュール"""
import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import requests
import pandas as pd


CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

MAX_OUTPUT_SIZE = 5000


def _parse_response(data: dict) -> pd.DataFrame:
    """API レスポンスを DataFrame に変換"""
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return df


def fetch_data(
    symbol: str,
    interval: str,
    outputsize: int,
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> pd.DataFrame:
    """
    Twelve Data APIからOHLCデータ取得（キャッシュ対応）

    Args:
        symbol: 通貨ペア（例: "USD/JPY"）
        interval: 時間足（例: "4h", "1day"）
        outputsize: 取得本数
        api_key: APIキー（Noneの場合は環境変数から取得）
        use_cache: キャッシュを使用するか

    Returns:
        OHLC DataFrame（datetime, open, high, low, close列）
    """
    if api_key is None:
        api_key = os.environ.get("TWELVEDATA_API_KEY")
        if not api_key:
            raise ValueError("TWELVEDATA_API_KEY not found in environment")

    # キャッシュキー生成
    cache_key = hashlib.md5(
        f"{symbol}_{interval}_{outputsize}".encode()
    ).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"

    # キャッシュチェック（24時間以内）
    if use_cache and cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime < timedelta(hours=24):
            with open(cache_file, "r") as f:
                data = json.load(f)
                return _parse_response(data)

    # API呼び出し
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": api_key,
    }
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()

    if "values" not in data:
        raise ValueError(f"API error: {data}")

    # キャッシュ保存
    if use_cache:
        with open(cache_file, "w") as f:
            json.dump(data, f)

    return _parse_response(data)


def fetch_data_range(
    symbol: str,
    interval: str,
    start_date: str,
    end_date: str,
    api_key: Optional[str] = None,
    use_cache: bool = True
) -> pd.DataFrame:
    """
    日付範囲指定でデータ取得（5000本超はチャンク分割）

    Args:
        symbol: 通貨ペア
        interval: 時間足（"4h", "1day" 等）
        start_date: 開始日 (YYYY-MM-DD)
        end_date: 終了日 (YYYY-MM-DD)
        api_key: APIキー
        use_cache: キャッシュ使用

    Returns:
        OHLC DataFrame
    """
    if api_key is None:
        api_key = os.environ.get("TWELVEDATA_API_KEY")
        if not api_key:
            raise ValueError("TWELVEDATA_API_KEY not found in environment")

    # キャッシュキー生成
    cache_key = hashlib.md5(
        f"{symbol}_{interval}_{start_date}_{end_date}".encode()
    ).hexdigest()
    cache_file = CACHE_DIR / f"{cache_key}.json"

    # キャッシュチェック（24時間以内）
    if use_cache and cache_file.exists():
        mtime = datetime.fromtimestamp(cache_file.stat().st_mtime)
        if datetime.now() - mtime < timedelta(hours=24):
            with open(cache_file, "r") as f:
                data = json.load(f)
                return _parse_response(data)

    # チャンク分割取得
    url = "https://api.twelvedata.com/time_series"
    all_values = []
    current_end = end_date
    chunk_count = 0

    while True:
        params = {
            "symbol": symbol,
            "interval": interval,
            "start_date": start_date,
            "end_date": current_end,
            "outputsize": MAX_OUTPUT_SIZE,
            "apikey": api_key,
        }

        # レートリミット対策（2回目以降）
        if chunk_count > 0:
            time.sleep(8)

        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        if "values" not in data:
            if chunk_count == 0:
                raise ValueError(f"API error: {data}")
            break

        values = data["values"]
        if not values:
            break

        all_values.extend(values)
        chunk_count += 1
        print(f"    chunk {chunk_count}: {len(values)} bars "
              f"({values[-1]['datetime']} ~ {values[0]['datetime']})")

        # 5000本未満 = 全データ取得済み
        if len(values) < MAX_OUTPUT_SIZE:
            break

        # 次チャンクの end_date = 今回の最古バーの1秒前
        oldest = values[-1]["datetime"]
        oldest_dt = pd.to_datetime(oldest) - timedelta(seconds=1)
        current_end = oldest_dt.strftime("%Y-%m-%d %H:%M:%S")

        # start_date を超えたら終了
        if oldest_dt < pd.to_datetime(start_date):
            break

    if not all_values:
        raise ValueError(f"No data returned for {symbol} {interval} {start_date}~{end_date}")

    # 重複排除してキャッシュ保存
    combined_data = {"values": all_values}

    # DataFrame変換 → 重複排除
    df = _parse_response(combined_data)
    df = df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)

    # キャッシュ保存（重複排除済み）
    if use_cache:
        deduped_values = df.to_dict(orient="records")
        for v in deduped_values:
            v["datetime"] = str(v["datetime"])
        with open(cache_file, "w") as f:
            json.dump({"values": deduped_values}, f)

    print(f"    total: {len(df)} bars ({df.iloc[0]['datetime']} ~ {df.iloc[-1]['datetime']})")
    return df
