"""
FXシグナル検出→LINE通知（みんなのFX実運用対応）

実データから確定足のみでシグナル判定し、
config/minnafx.yamlに基づいたコスト/リスク管理で通知を生成

Usage:
    python3 scripts/run_signal.py --dry-run --symbols USD/JPY,EUR/JPY,GBP/JPY
    python3 scripts/run_signal.py --send --symbols EUR/JPY --equity 100000
"""
import os
import sys
import argparse
import logging
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import pandas as pd
import requests

# パス追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key, check_line_credentials
from src.config_loader import load_broker_config
from src.broker_costs.minnafx import MinnafxCostModel
from src.position_sizing import calculate_position_size_strict, units_to_lots
from src.notify_line import LineNotifier

# .env ファイルを読み込み（存在すれば）
load_dotenv_if_exists()


# ==================== データ取得 ====================

def fetch_data(symbol: str, interval: str, outputsize: int, api_key: str) -> pd.DataFrame:
    """Twelve Data APIからOHLCデータ取得"""
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

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return df


# ==================== インジケーター計算 ====================

def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """EMA計算"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR計算"""
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ==================== パターン判定 ====================

def is_bullish_engulfing(prev_row: pd.Series, curr_row: pd.Series) -> bool:
    """Bullish Engulfingパターン判定"""
    prev_bearish = prev_row["close"] < prev_row["open"]
    curr_bullish = curr_row["close"] > curr_row["open"]
    engulfing = (
        curr_row["close"] >= prev_row["open"] and
        curr_row["open"] <= prev_row["close"]
    )
    return prev_bearish and curr_bullish and engulfing


def is_bullish_hammer(row: pd.Series) -> bool:
    """Hammerパターン判定（長い下ヒゲ）"""
    body = abs(row["close"] - row["open"])
    if body <= 0:
        return False

    lower_wick = min(row["open"], row["close"]) - row["low"]
    upper_wick = row["high"] - max(row["open"], row["close"])

    return (
        row["close"] > row["open"] and
        lower_wick >= body * 1.5 and
        lower_wick >= upper_wick * 2.0
    )


def is_bearish_engulfing(prev_row: pd.Series, curr_row: pd.Series) -> bool:
    """Bearish Engulfingパターン判定"""
    prev_bullish = prev_row["close"] > prev_row["open"]
    curr_bearish = curr_row["close"] < curr_row["open"]
    engulfing = (
        curr_row["close"] <= prev_row["open"] and
        curr_row["open"] >= prev_row["close"]
    )
    return prev_bullish and curr_bearish and engulfing


def is_bearish_shooting_star(row: pd.Series) -> bool:
    """Shooting Starパターン判定（長い上ヒゲ）"""
    body = abs(row["close"] - row["open"])
    if body <= 0:
        return False

    upper_wick = row["high"] - max(row["open"], row["close"])
    lower_wick = min(row["open"], row["close"]) - row["low"]

    return (
        row["close"] < row["open"] and
        upper_wick >= body * 1.5 and
        upper_wick >= lower_wick * 2.0
    )


# ==================== 環境チェック ====================

def check_daily_environment(d1: pd.DataFrame) -> dict:
    """日足環境チェック（EMA20上昇トレンド）"""
    d1 = d1.copy()
    d1["ema20"] = calculate_ema(d1["close"], 20)

    # 確定足のみ（最新足は形成中なので除外）
    if len(d1) < 3:
        return {"ok": False, "reason": "日足データ不足"}

    latest = d1.iloc[-2]  # 1つ前の確定足
    prev = d1.iloc[-3]

    # close > EMA20 かつ EMA20上向き
    is_uptrend = latest["close"] > latest["ema20"] and latest["ema20"] > prev["ema20"]
    is_downtrend = latest["close"] < latest["ema20"] and latest["ema20"] < prev["ema20"]

    if is_uptrend:
        return {"ok": True, "direction": "LONG", "ema20": latest["ema20"]}
    elif is_downtrend:
        return {"ok": True, "direction": "SHORT", "ema20": latest["ema20"]}
    else:
        return {"ok": False, "reason": "日足環境NG（レンジ）"}


# ==================== シグナル判定 ====================

def check_signal(h4: pd.DataFrame, d1: pd.DataFrame, atr_mult: float = 1.2) -> dict:
    """シグナル判定（確定足のみ）"""
    # 日足環境チェック
    env = check_daily_environment(d1)
    if not env["ok"]:
        return {"signal": False, "reason": env["reason"]}

    # 4H足の計算
    h4 = h4.copy()
    h4["ema20"] = calculate_ema(h4["close"], 20)
    h4["atr14"] = calculate_atr(h4, 14)

    # 確定足のみ（最新足は形成中なので除外）
    if len(h4) < 3:
        return {"signal": False, "reason": "4H足データ不足"}

    latest = h4.iloc[-2]  # 1つ前の確定足（シグナル足）
    prev = h4.iloc[-3]

    # EMAタッチチェック
    touch_ema = latest["low"] <= latest["ema20"] <= latest["high"]
    if not touch_ema:
        return {"signal": False, "reason": "EMAタッチなし"}

    # 方向別のパターンチェック
    if env["direction"] == "LONG":
        is_engulfing = is_bullish_engulfing(prev, latest)
        is_hammer = is_bullish_hammer(latest)

        if not (is_engulfing or is_hammer):
            return {"signal": False, "reason": "LONGトリガーパターンなし"}

        pattern = "Bullish Engulfing" if is_engulfing else "Bullish Hammer"
        side = "LONG"

    else:  # SHORT
        is_engulfing = is_bearish_engulfing(prev, latest)
        is_shooting = is_bearish_shooting_star(latest)

        if not (is_engulfing or is_shooting):
            return {"signal": False, "reason": "SHORTトリガーパターンなし"}

        pattern = "Bearish Engulfing" if is_engulfing else "Shooting Star"
        side = "SHORT"

    atr = latest["atr14"]

    # SL/TP計算（仲値ベース）
    entry_mid = latest["close"]

    if side == "LONG":
        sl_mid = entry_mid - (atr * atr_mult)
        tp1_mid = entry_mid + (abs(entry_mid - sl_mid) * 1.2)  # 1.2R
        tp2_mid = entry_mid + (abs(entry_mid - sl_mid) * 2.4)  # 2.4R
    else:  # SHORT
        sl_mid = entry_mid + (atr * atr_mult)
        tp1_mid = entry_mid - (abs(entry_mid - sl_mid) * 1.2)
        tp2_mid = entry_mid - (abs(entry_mid - sl_mid) * 2.4)

    return {
        "signal": True,
        "side": side,
        "pattern": pattern,
        "signal_dt": latest["datetime"],
        "entry_mid": entry_mid,
        "sl_mid": sl_mid,
        "tp1_mid": tp1_mid,
        "tp2_mid": tp2_mid,
        "atr": atr,
        "ema20": latest["ema20"],
        "daily_ema20": env["ema20"]
    }


# ==================== メイン処理 ====================

def main():
    parser = argparse.ArgumentParser(description="FXシグナル検出→LINE通知")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml", help="設定ファイル")
    parser.add_argument("--symbols", type=str, default="USD/JPY,EUR/JPY,GBP/JPY", help="通貨ペア（カンマ区切り）")
    parser.add_argument("--equity", type=float, default=100000.0, help="口座残高（JPY）")
    parser.add_argument("--risk-pct", type=float, default=0.005, help="リスク率（デフォルト0.005=0.5%）")
    parser.add_argument("--atr-mult", type=float, default=1.2, help="SL距離（ATR × atr_mult）")
    parser.add_argument("--dry-run", action="store_true", help="標準出力のみ（LINE送信しない）")
    parser.add_argument("--send", action="store_true", help="LINE送信する")
    parser.add_argument("--entry-mode", type=str, default="NEXT_OPEN_MARKET", choices=["NEXT_OPEN_MARKET", "BREAKOUT_STOP"])
    parser.add_argument("--log-level", type=str, default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()

    # ログ設定
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger(__name__)

    # 設定読み込み
    try:
        config = load_broker_config(args.config)
        logger.info(f"✅ 設定ファイル読み込み: {args.config}")
    except Exception as e:
        logger.error(f"❌ 設定ファイル読み込みエラー: {e}")
        return

    # Twelve Data API Key（必須）
    api_key = check_api_key(required=True)

    # LINE認証情報（--sendの場合のみ必須）
    if args.send:
        line_token, line_user_id = check_line_credentials(required=True)
    else:
        line_token = "dummy_token"
        line_user_id = "dummy_user"

    # コストモデル
    cost_model = MinnafxCostModel(config)

    # LINE通知
    notifier = LineNotifier(
        line_token=line_token,
        line_user_id=line_user_id,
        config=config,
        state_file="data/notification_state.json"
    )

    # 通貨ペアリスト
    symbols = [s.strip() for s in args.symbols.split(",")]

    logger.info(f"=== FXシグナル検出開始 ===")
    logger.info(f"対象通貨: {', '.join(symbols)}")
    logger.info(f"口座残高: {args.equity:,.0f}円")
    logger.info(f"リスク設定: {args.risk_pct*100:.1f}%")
    logger.info(f"モード: {'dry-run（標準出力のみ）' if args.dry_run else 'LINE送信（1通にまとめる）'}")

    # 結果収集用（3通貨分をまとめる）
    results = []
    bar_dt = None  # 確定4H足時刻（全通貨で共通）

    for symbol in symbols:
        logger.info(f"\n{'='*60}")
        logger.info(f"[{symbol}] チェック中...")

        try:
            # データ取得
            h4 = fetch_data(symbol, "4h", 200, api_key)
            d1 = fetch_data(symbol, "1day", 120, api_key)
            logger.info(f"  データ取得: 4H {len(h4)}本, 日足 {len(d1)}本")

            # シグナル判定
            result = check_signal(h4, d1, args.atr_mult)

            # 確定4H足時刻を取得（全通貨で共通）
            if len(h4) >= 2:
                latest_bar = h4.iloc[-2]  # 確定足
                bar_dt_tmp = latest_bar["datetime"]
                if bar_dt_tmp.tzinfo is None:
                    bar_dt_tmp = bar_dt_tmp.tz_localize("UTC").tz_convert(ZoneInfo("Asia/Tokyo"))
                else:
                    bar_dt_tmp = bar_dt_tmp.astimezone(ZoneInfo("Asia/Tokyo"))

                if bar_dt is None:
                    bar_dt = bar_dt_tmp

            if not result["signal"]:
                logger.info(f"  ❌ シグナルなし: {result['reason']}")
                # 見送り結果を追加
                results.append({
                    "symbol": symbol,
                    "status": "SKIP",
                    "reason": result["reason"]
                })
                continue

            logger.info(f"  ✅ シグナル検出: {result['side']} {result['pattern']}")

            # 次足時刻（4H足なら+4時間）
            next_dt = result["signal_dt"] + pd.Timedelta(hours=4)

            # JSTに変換
            if next_dt.tzinfo is None:
                next_dt = next_dt.tz_localize("UTC").tz_convert(ZoneInfo("Asia/Tokyo"))
            else:
                next_dt = next_dt.astimezone(ZoneInfo("Asia/Tokyo"))

            # メンテナンス時間チェック
            if not cost_model.is_tradable(next_dt):
                logger.warning(f"  ⚠️ 見送り: メンテナンス時間中（{next_dt.strftime('%Y-%m-%d %H:%M JST')}）")
                results.append({
                    "symbol": symbol,
                    "status": "SKIP",
                    "reason": f"メンテナンス時間中（{next_dt.strftime('%H:%M JST')}）"
                })
                continue

            # スプレッドフィルター
            should_skip, skip_reason = cost_model.should_skip_entry(symbol, next_dt)
            if should_skip:
                logger.warning(f"  ⚠️ 見送り: {skip_reason}")
                results.append({
                    "symbol": symbol,
                    "status": "SKIP",
                    "reason": skip_reason
                })
                continue

            # 実行価格計算
            entry_exec = cost_model.calculate_execution_price(
                result["entry_mid"], result["side"], symbol, next_dt
            )
            sl_exec = cost_model.calculate_exit_price(
                result["sl_mid"], result["side"], symbol, next_dt
            )

            # ポジションサイジング（厳格0.5%）
            units, actual_risk, is_valid = calculate_position_size_strict(
                args.equity, entry_exec, sl_exec, args.risk_pct, config, symbol
            )

            if not is_valid:
                logger.warning(f"  ⚠️ 見送り: ポジションサイズ計算不可（最小ロット未満）")
                results.append({
                    "symbol": symbol,
                    "status": "SKIP",
                    "reason": "ポジションサイズ計算不可（最小ロット未満）"
                })
                continue

            lots = units_to_lots(units, config, symbol)

            # Violations=0 確認
            max_allowed_risk = args.equity * args.risk_pct
            if actual_risk > max_allowed_risk:
                logger.error(f"  ❌ CRITICAL: リスク超過検出（{actual_risk:.0f}円 > {max_allowed_risk:.0f}円）")
                results.append({
                    "symbol": symbol,
                    "status": "SKIP",
                    "reason": f"リスク超過（{actual_risk:.0f}円 > {max_allowed_risk:.0f}円）"
                })
                continue

            logger.info(f"  推奨数量: {lots:.1f}Lot ({units:,.0f}通貨), リスク: {actual_risk:.0f}円")

            # シグナル結果を追加
            results.append({
                "symbol": symbol,
                "status": "SIGNAL",
                "side": result["side"],
                "pattern": result["pattern"],
                "entry_price_mid": result["entry_mid"],
                "sl_price_mid": result["sl_mid"],
                "tp1_price_mid": result["tp1_mid"],
                "tp2_price_mid": result["tp2_mid"],
                "atr": result["atr"],
                "ema20": result["ema20"],
                "entry_mode": args.entry_mode,
                "exit_config": {
                    "tp1_close_pct": 0.5,
                    "move_to_be": True,
                    "be_buffer_pips": 0.0,
                    "tp2_mode": "FIXED_R",
                    "time_stop": None,
                    "daily_flip_exit": False
                }
            })

        except Exception as e:
            logger.error(f"  ❌ エラー: {e}", exc_info=True)
            results.append({
                "symbol": symbol,
                "status": "SKIP",
                "reason": f"エラー: {str(e)}"
            })

    # バッチ通知メッセージ生成（3通貨を1通にまとめる）
    logger.info(f"\n{'='*60}")

    if bar_dt is None:
        logger.error("❌ 確定4H足時刻を取得できませんでした")
        return

    run_dt = datetime.now(ZoneInfo("Asia/Tokyo"))

    # ⚠️ 重要: bar_dtをログ出力（cron設定の参考にする）
    logger.info(f"確定4H足時刻（bar_dt）: {bar_dt.strftime('%Y-%m-%d %H:%M JST')}")
    logger.info(f"次足始値: {(bar_dt + pd.Timedelta(hours=4)).strftime('%Y-%m-%d %H:%M JST')}")
    logger.info(f"💡 cron設定のヒント: Twelve Data APIは通常 JST 00:00, 04:00, 08:00... → cron「5 0,4,8,12,16,20 * * *」")

    batch_msg = notifier.create_batch_message(
        run_dt=run_dt,
        bar_dt=bar_dt,
        results=results,
        equity_jpy=args.equity,
        risk_pct=args.risk_pct
    )

    if batch_msg is None:
        logger.info("⚠️ 同一4Hバーで既に送信済み（bar_dtデデュープ）")
        return

    # サマリー表示
    signal_count = sum(1 for r in results if r["status"] == "SIGNAL")
    skip_count = sum(1 for r in results if r["status"] == "SKIP")
    logger.info(f"結果: シグナル {signal_count}通貨、見送り {skip_count}通貨")

    # 通知出力/送信
    print(f"\n{'='*80}")
    print("📊 バッチ通知（3通貨まとめ）")
    print(f"{'='*80}")
    print(batch_msg)

    if args.send:
        success = notifier.send_line(batch_msg)
        if success:
            logger.info("✅ LINE送信完了（1通）")
        else:
            logger.error("❌ LINE送信失敗")
    elif args.dry_run:
        logger.info("\n📝 dry-runモード: LINE送信は行いませんでした")

    logger.info(f"\n次回通知: 次の4H足確定後（bar_dt: {bar_dt.strftime('%Y-%m-%d %H:%M JST')}）")


if __name__ == "__main__":
    main()
