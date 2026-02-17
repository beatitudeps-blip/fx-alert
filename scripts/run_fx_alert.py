"""
FXアラート実行スクリプト（GitHub Actions用）

4H足シグナルをチェックしてLINE通知を送信
"""
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key, check_line_credentials
from src.config_loader import load_broker_config
from src.notify_line import LineNotifier
from src.signal_detector import detect_signals
from src.data import fetch_data


def check_exits(notifier, api_key, tz, dry_run):
    """オープントレードの決済チェック"""
    open_trades = notifier.state.setdefault("open_trades", {})
    if not open_trades:
        return

    closed = []
    for sym in list(open_trades.keys()):
        trade = open_trades[sym]
        h4 = fetch_data(sym, "4h", 100, api_key, use_cache=False)
        if h4["datetime"].dt.tz is None:
            h4["datetime"] = h4["datetime"].dt.tz_localize("UTC").dt.tz_convert(tz)

        now = datetime.now(tz)
        h4_end = h4["datetime"] + pd.Timedelta(hours=4)
        h4_past = h4[h4_end <= now]

        entry_t = pd.Timestamp(trade["entry_bar_dt"])
        h4_check = h4_past[h4_past["datetime"] >= entry_t]
        if trade.get("last_checked_bar_dt"):
            last_ck = pd.Timestamp(trade["last_checked_bar_dt"])
            h4_check = h4_check[h4_check["datetime"] > last_ck]

        if h4_check.empty:
            continue

        done = False
        for _, bar in h4_check.iterrows():
            if done:
                break
            t = bar["datetime"]
            hi, lo = bar["high"], bar["low"]
            side = trade["side"]
            sl = trade["current_sl"]
            entry_p = trade["entry_price"]

            sl_hit = (lo <= sl) if side == "LONG" else (hi >= sl)
            tp1_now = False
            if not trade["tp1_hit"]:
                tp1_now = (hi >= trade["tp1_price"]) if side == "LONG" else (lo <= trade["tp1_price"])
            tp2_hit = False
            if trade["tp1_hit"]:
                tp2_hit = (hi >= trade["tp2_price"]) if side == "LONG" else (lo <= trade["tp2_price"])

            # SL優先
            if sl_hit:
                exit_u = trade["remaining_units"]
                pnl = (sl - entry_p) * exit_u if side == "LONG" else (entry_p - sl) * exit_u
                total = trade["total_pnl"] + pnl
                ev = "SL(-0.5R)" if trade["tp1_hit"] else "SL"
                nt = f"TP1後SL=-0.5R（{sl:.3f}）で決済" if trade["tp1_hit"] else f"初期SL（{sl:.3f}）で決済"
                msg = notifier.create_exit_message(
                    symbol=sym, side=side, event=ev,
                    entry_time=trade["entry_time_str"], entry_price=entry_p,
                    event_time=t, event_price=sl,
                    realized_pnl=pnl, total_pnl=total, note=nt)
                _send_exit_notify(notifier, msg, dry_run)
                closed.append(sym)
                done = True

            elif tp1_now:
                tp1_u = trade["units"] * 0.5
                tp1_p = trade["tp1_price"]
                pnl = (tp1_p - entry_p) * tp1_u if side == "LONG" else (entry_p - tp1_p) * tp1_u
                trade["tp1_hit"] = True
                trade["total_pnl"] += pnl
                trade["remaining_units"] -= tp1_u
                ir = abs(entry_p - trade["sl_price"])
                trade["current_sl"] = entry_p - 0.5 * ir if side == "LONG" else entry_p + 0.5 * ir
                msg = notifier.create_exit_message(
                    symbol=sym, side=side, event="TP1",
                    entry_time=trade["entry_time_str"], entry_price=entry_p,
                    event_time=t, event_price=tp1_p,
                    realized_pnl=pnl, total_pnl=trade["total_pnl"],
                    note=f"50%利確→SLを-0.5R（{trade['current_sl']:.3f}）へ繰上げ")
                _send_exit_notify(notifier, msg, dry_run)
                # 同一バーでTP2もヒット？
                if (hi >= trade["tp2_price"]) if side == "LONG" else (lo <= trade["tp2_price"]):
                    rem = trade["remaining_units"]
                    tp2_p = trade["tp2_price"]
                    pnl2 = (tp2_p - entry_p) * rem if side == "LONG" else (entry_p - tp2_p) * rem
                    trade["total_pnl"] += pnl2
                    msg = notifier.create_exit_message(
                        symbol=sym, side=side, event="TP2",
                        entry_time=trade["entry_time_str"], entry_price=entry_p,
                        event_time=t, event_price=tp2_p,
                        realized_pnl=pnl2, total_pnl=trade["total_pnl"],
                        note="残り50%を3R利確→全決済")
                    _send_exit_notify(notifier, msg, dry_run)
                    closed.append(sym)
                    done = True

            elif tp2_hit:
                rem = trade["remaining_units"]
                tp2_p = trade["tp2_price"]
                pnl = (tp2_p - entry_p) * rem if side == "LONG" else (entry_p - tp2_p) * rem
                trade["total_pnl"] += pnl
                msg = notifier.create_exit_message(
                    symbol=sym, side=side, event="TP2",
                    entry_time=trade["entry_time_str"], entry_price=entry_p,
                    event_time=t, event_price=tp2_p,
                    realized_pnl=pnl, total_pnl=trade["total_pnl"],
                    note="残り50%を3R利確→全決済")
                _send_exit_notify(notifier, msg, dry_run)
                closed.append(sym)
                done = True

            if not done:
                trade["last_checked_bar_dt"] = t.isoformat() if hasattr(t, 'isoformat') else str(t)

    for sym in closed:
        del open_trades[sym]
    notifier._save_state()


def _send_exit_notify(notifier, msg, dry_run):
    """決済通知を送信"""
    print(f"\n{msg}")
    if not dry_run:
        notifier.send_line(msg)


def main():
    parser = argparse.ArgumentParser(description="FXアラートシステム")
    parser.add_argument("--symbols", type=str, required=True, help="通貨ペア（カンマ区切り）")
    parser.add_argument("--config", type=str, default="config/minnafx.yaml", help="設定ファイル")
    parser.add_argument("--equity", type=float, default=500000.0, help="口座残高")
    parser.add_argument("--risk-pct", type=float, default=0.005, help="リスク率")
    parser.add_argument("--atr-mult", type=float, default=1.0, help="ATR倍率")
    parser.add_argument("--tp1-r", type=float, default=1.5, help="TP1のR倍数")
    parser.add_argument("--tp2-r", type=float, default=3.0, help="TP2のR倍数")
    parser.add_argument("--tp2-mode", type=str, default="FIXED_R", choices=["FIXED_R", "STRUCTURE"], help="TP2モード")
    parser.add_argument("--dry-run", action="store_true", help="Dry run（LINE通知なし）")

    args = parser.parse_args()

    # .env ファイルを読み込み（存在すれば）
    load_dotenv_if_exists()

    # API Key
    api_key = check_api_key(required=True)

    # LINE認証情報（dry-runでは不要）
    if not args.dry_run:
        line_token, line_user_id = check_line_credentials(required=True)
    else:
        line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "dummy_token")
        line_user_id = os.getenv("LINE_USER_ID", "dummy_user_id")
        print("⚠️ DRY RUN モード: LINE通知は送信されません")

    # 設定読み込み
    config = load_broker_config(args.config)
    print(f"✅ 設定読み込み: {args.config}")

    # 通貨ペアリスト
    symbols = [s.strip() for s in args.symbols.split(",")]

    # LINE通知設定
    notifier = LineNotifier(
        line_token=line_token,
        line_user_id=line_user_id,
        config=config,
        state_file="data/notification_state.json"
    )

    # 実行時刻
    run_dt = datetime.now(ZoneInfo("Asia/Tokyo"))

    print(f"\n{'='*60}")
    print(f"FXアラートシステム")
    print(f"{'='*60}")
    print(f"実行時刻: {run_dt.strftime('%Y-%m-%d %H:%M:%S JST')}")
    print(f"通貨ペア: {', '.join(symbols)}")
    print(f"口座残高: {args.equity:,.0f}円")
    print(f"リスク設定: {args.risk_pct*100:.1f}%")
    print(f"={'='*60}\n")

    # 決済チェック（オープントレード）
    print("📊 決済チェック中...")
    check_exits(notifier, api_key, ZoneInfo("Asia/Tokyo"), args.dry_run)

    # シグナル検出
    print("📊 シグナル検出中...\n")
    signals = detect_signals(
        symbols=symbols,
        config=config,
        api_key=api_key,
        current_equity=args.equity,
        risk_pct=args.risk_pct,
        atr_multiplier=args.atr_mult,
        tp1_r=args.tp1_r,
        tp2_r=args.tp2_r,
        use_cache=False  # 本番では最新データを取得
    )

    # 結果を整形
    results = []
    bar_dt = None  # 確定4H足時刻（最初のシグナルから取得）

    for signal in signals:
        symbol = signal["symbol"]

        # bar_dt を保存（全通貨ペアで同じはず）
        if bar_dt is None and signal.get("bar_dt"):
            bar_dt = signal["bar_dt"]

        if signal.get("skip_reason"):
            # 見送り
            print(f"[{symbol}] ⏭️  見送り: {signal['skip_reason']}")
            results.append({
                "symbol": symbol,
                "status": "SKIP",
                "reason": signal["skip_reason"],
                "close": signal.get("close", 0.0),
                "ema20": signal.get("ema20", 0.0),
                "atr": signal.get("atr", 0.0),
                "ema_gap_pips": signal.get("ema_gap_pips", 0.0),
                "ema_gap_atr_ratio": signal.get("ema_gap_atr_ratio", 0.0),
                "market_state": signal.get("market_state", "不明")
            })
        else:
            # シグナル検出
            print(f"[{symbol}] 🔔 {signal['signal']}シグナル検出!")
            print(f"  パターン: {signal['pattern']}")
            print(f"  エントリー: {signal['entry_price']:.3f}")
            print(f"  SL: {signal['sl_price']:.3f} ({signal['sl_pips']:.1f}pips)")
            print(f"  TP1: {signal['tp1_price']:.3f}")
            print(f"  TP2: {signal['tp2_price']:.3f}")
            print(f"  ロット: {signal['lots']:.1f} ({signal['units']}通貨)")
            print(f"  リスク: {signal['risk_jpy']:,.0f}円")

            results.append({
                "symbol": symbol,
                "status": "SIGNAL",
                "side": signal["signal"],
                "pattern": signal["pattern"],
                "entry_price_mid": signal["entry_price"],
                "sl_price_mid": signal["sl_price"],
                "tp1_price_mid": signal["tp1_price"],
                "tp2_price_mid": signal["tp2_price"],
                "sl_pips": signal["sl_pips"],
                "lots": signal["lots"],
                "units": signal["units"],
                "risk_jpy": signal["risk_jpy"],
                "atr": signal.get("atr", 0.0),
                "ema20": signal.get("ema20", 0.0)
            })

    # 通知送信（シグナルがある場合、またはskipがある場合）
    if results and bar_dt:
        # バッチメッセージ作成
        msg = notifier.create_batch_message(
            run_dt=run_dt,
            bar_dt=bar_dt,
            results=results,
            equity_jpy=args.equity,
            risk_pct=args.risk_pct
        )

        if msg:
            if not args.dry_run:
                # 実際に送信
                success = notifier.send_line(msg)
                if success:
                    print("\n✅ LINE通知を送信しました")
                    notifier._mark_bar_sent(bar_dt)
                else:
                    print("\n❌ LINE通知の送信に失敗しました")
            else:
                # Dry run: メッセージだけ表示
                print("\n" + "="*60)
                print("📱 DRY RUN: 以下のメッセージが送信されます")
                print("="*60)
                print(msg)
                print("="*60)
        else:
            print("\n✅ 重複通知のためスキップしました")
    else:
        print("\n✅ 全通貨ペアでシグナルなし")

    # 新規トレード登録
    open_trades = notifier.state.setdefault("open_trades", {})
    for result in results:
        if result["status"] == "SIGNAL":
            sym = result["symbol"]
            if sym not in open_trades and bar_dt is not None:
                entry_bar_dt = bar_dt + timedelta(hours=4)
                open_trades[sym] = {
                    "symbol": sym,
                    "side": result["side"],
                    "entry_time_str": entry_bar_dt.strftime('%Y-%m-%d %H:%M JST'),
                    "entry_bar_dt": entry_bar_dt.isoformat(),
                    "entry_price": result["entry_price_mid"],
                    "sl_price": result["sl_price_mid"],
                    "current_sl": result["sl_price_mid"],
                    "tp1_price": result["tp1_price_mid"],
                    "tp2_price": result["tp2_price_mid"],
                    "tp1_hit": False,
                    "units": result["units"],
                    "remaining_units": result["units"],
                    "risk_jpy": result["risk_jpy"],
                    "total_pnl": 0.0,
                }
                print(f"  📝 {sym} オープントレード登録")
    notifier._save_state()

    print(f"\n{'='*60}")
    print(f"✅ FXアラート実行完了")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
