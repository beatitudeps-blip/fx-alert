"""データ取得モジュール"""
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
import requests
import pandas as pd


CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


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
                df = pd.DataFrame(data["values"])
                df["datetime"] = pd.to_datetime(df["datetime"])
                for col in ["open", "high", "low", "close"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
                return df

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

    # DataFrame変換
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return df
