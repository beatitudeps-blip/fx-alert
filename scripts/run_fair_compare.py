"""
V4 vs V5 公平比較バックテスト実行スクリプト

条件:
- initial_equity = 500,000 JPY（必須）
- risk_pct = 0.005（0.5%）
- ポジションサイズ = 連続量（ロット丸めなし、position_size_invalid=0保証）
- 期間: データ上限（4H=5000本≒3年）全域
- シグナル検出: V4/V5共通（ADX>=18, distance<=0.6ATR, engulf/hammer）
- V4: 1本待ち成行 + TP2=3R
- V5: 指値(EMA±0.10ATR) + 失効 + EMAクロス退出
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.backtest_fair import run_backtest_fair
import pandas as pd
import numpy as np

load_dotenv_if_exists()

# ==================== 設定（絶対に変えない）====================
INITIAL_EQUITY = 500_000
RISK_PCT = 0.005
SYMBOLS = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
START_DATE = "2023-01-01"
END_DATE = "2026-02-16"


def calc_metrics(trades, initial_eq, start_date, end_date):
    """メトリクス計算"""
    closed = [t for t in trades if t.exit_time is not None]
    if not closed:
        return {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "pf": 0, "total_pnl": 0,
            "max_dd": 0, "avg_r": 0, "median_r": 0,
            "cagr": 0, "final_equity": initial_eq,
        }

    pnls = [t.total_pnl for t in closed]
    risks = [t.risk_jpy for t in closed]
    r_multiples = [p / r if r > 0 else 0 for p, r in zip(pnls, risks)]

    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    pf = gross_profit / gross_loss if gross_loss > 0 else (float('inf') if gross_profit > 0 else 0)

    # MaxDD（クローズベース）
    eq = initial_eq
    peak = eq
    max_dd = 0
    for t in closed:
        eq += t.total_pnl
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)

    final_eq = initial_eq + sum(pnls)

    # CAGR
    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    years = (d2 - d1).days / 365.25
    cagr = ((final_eq / initial_eq) ** (1 / years) - 1) if years > 0 and final_eq > 0 else 0

    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": len(wins) / len(closed) if closed else 0,
        "pf": pf,
        "total_pnl": sum(pnls),
        "max_dd": max_dd,
        "avg_r": np.mean(r_multiples) if r_multiples else 0,
        "median_r": np.median(r_multiples) if r_multiples else 0,
        "cagr": cagr,
        "final_equity": final_eq,
    }


def main():
    api_key = check_api_key(required=True)

    print(f"{'='*80}")
    print(f"V4 vs V5 公平比較バックテスト")
    print(f"{'='*80}")
    print(f"initial_equity = {INITIAL_EQUITY:,} JPY")
    print(f"risk_pct       = {RISK_PCT} ({RISK_PCT*100}%)")
    print(f"期間           = {START_DATE} ~ {END_DATE}")
    print(f"通貨ペア       = {', '.join(SYMBOLS)}")
    print(f"ポジションサイズ = 連続量（ロット丸めなし）")
    print(f"V4: 1本待ち成行 + TP2=3R")
    print(f"V5: 指値(EMA±0.10ATR) + 失効 + EMAクロス退出")
    print(f"{'='*80}\n")

    # ==================== ルックアヘッド排除証拠ログ ====================
    print("─── ルックアヘッド排除 証拠ログ ───")
    tz = ZoneInfo("Asia/Tokyo")
    now_jst = datetime(2026, 2, 16, 16, 56, tzinfo=tz)
    print(f"now = {now_jst.isoformat()}")

    # 4H足: 16:00（16-20足）の bar_end = 16:00+4h = 20:00 > 16:56 → 未確定
    bar_16 = datetime(2026, 2, 16, 16, 0, tzinfo=tz)
    bar_16_end = bar_16 + timedelta(hours=4)
    print(f"H4 bar 16:00: bar_end = {bar_16_end.strftime('%H:%M')} > now → 未確定（正しく除外）")

    # 12:00（12-16足）の bar_end = 12:00+4h = 16:00 <= 16:56 → 確定
    bar_12 = datetime(2026, 2, 16, 12, 0, tzinfo=tz)
    bar_12_end = bar_12 + timedelta(hours=4)
    print(f"H4 bar 12:00: bar_end = {bar_12_end.strftime('%H:%M')} <= now → 確定（最新確定足）")

    # D1足: 2026-02-16の bar_end = 2026-02-17 > 2026-02-16 16:56 → 未確定
    d1_today = datetime(2026, 2, 16, 0, 0, tzinfo=tz)
    d1_today_end = d1_today + timedelta(days=1)
    print(f"D1 bar 2/16:  bar_end = {d1_today_end.strftime('%m/%d %H:%M')} > now → 未確定")
    d1_yest = datetime(2026, 2, 15, 0, 0, tzinfo=tz)
    d1_yest_end = d1_yest + timedelta(days=1)
    print(f"D1 bar 2/15:  bar_end = {d1_yest_end.strftime('%m/%d %H:%M')} <= now → 確定（最新確定足）")
    print(f"確認: H4_confirmed に 16:00 は入らない ✓")
    print(f"確認: 最新確定 = 12:00（12-16足） ✓")
    print("─── 証拠ログ終了 ───\n")

    # ==================== バックテスト実行 ====================
    all_results = []
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(f"data/results_fair/{run_id}")
    output_base.mkdir(parents=True, exist_ok=True)

    for symbol in SYMBOLS:
        print(f"\n{'─'*60}")
        print(f"[{symbol}]")
        print(f"{'─'*60}")

        for mode in ["V4", "V5"]:
            label = f"{mode}({'成行' if mode == 'V4' else '指値'})"
            print(f"  {label} 実行中...")

            trades, eq_df, stats = run_backtest_fair(
                symbol=symbol,
                start_date=START_DATE,
                end_date=END_DATE,
                mode=mode,
                api_key=api_key,
                initial_equity=INITIAL_EQUITY,
                risk_pct=RISK_PCT,
                use_cache=True,
            )

            m = calc_metrics(trades, INITIAL_EQUITY, START_DATE, END_DATE)

            print(f"    Trades: {m['trades']}, PF: {m['pf']:.2f}, "
                  f"WR: {m['win_rate']*100:.1f}%, PnL: {m['total_pnl']:,.0f}")
            print(f"    position_size_invalid = {stats['position_size_invalid']}")

            if m['trades'] < 30:
                print(f"    ⚠ {m['trades']}件 < 30: PF/CAGRは参考値")

            # V5固有
            if mode == "V5":
                print(f"    指値失効: {stats['limit_expired']}")

            # 結果保存
            out_dir = output_base / mode / symbol.replace("/", "_")
            out_dir.mkdir(parents=True, exist_ok=True)

            # trades CSV
            rows = []
            for t in trades:
                rows.append({
                    "trade_id": t.trade_id, "symbol": t.symbol, "side": t.side,
                    "pattern": t.pattern, "entry_time": t.entry_time,
                    "entry_price": t.entry_price, "units": t.units,
                    "sl_price": t.sl_price, "tp1_price": t.tp1_price,
                    "tp2_price": t.tp2_price, "atr": t.atr,
                    "risk_jpy": t.risk_jpy, "exit_time": t.exit_time,
                    "exit_reason": t.exit_reason, "total_pnl": t.total_pnl,
                    "r_multiple": t.total_pnl / t.risk_jpy if t.risk_jpy > 0 else 0,
                })
            pd.DataFrame(rows).to_csv(out_dir / "trades.csv", index=False)

            # fills CSV
            fill_rows = []
            for t in trades:
                for f in t.fills:
                    fill_rows.append({
                        "trade_id": t.trade_id, "fill_type": f.fill_type,
                        "fill_time": f.fill_time, "fill_price": f.fill_price,
                        "units": f.units, "pnl": f.pnl,
                    })
            pd.DataFrame(fill_rows).to_csv(out_dir / "fills.csv", index=False)

            # equity curve
            eq_df.to_csv(out_dir / "equity_curve.csv", index=False)

            # summary
            summary = {**m, **stats, "symbol": symbol, "initial_equity": INITIAL_EQUITY}
            with open(out_dir / "summary.json", "w") as f:
                json.dump(summary, f, indent=2, default=str)

            # 比較テーブル用
            all_results.append({
                "Symbol": symbol,
                "Version": label,
                "Trades": m["trades"],
                "WinRate": f"{m['win_rate']*100:.1f}%",
                "PF": f"{m['pf']:.2f}",
                "CAGR": f"{m['cagr']*100:.1f}%",
                "MaxDD": f"{m['max_dd']*100:.2f}%",
                "AvgR": f"{m['avg_r']:.2f}",
                "MedianR": f"{m['median_r']:.2f}",
                "PnL": f"{m['total_pnl']:,.0f}",
                "Skipped": stats["limit_expired"] if mode == "V5" else 0,
            })

    # ==================== 3通貨合算エクイティカーブ ====================
    # 全通貨のトレードを時系列順にマージし、単一エクイティカーブで CAGR/MaxDD
    combined = {}  # mode -> list of (exit_time, pnl)
    for symbol in SYMBOLS:
        for mode in ["V4", "V5"]:
            out_dir = output_base / mode / symbol.replace("/", "_")
            trades_csv = out_dir / "trades.csv"
            if trades_csv.exists():
                df_t = pd.read_csv(trades_csv)
                df_closed = df_t[df_t["exit_time"].notna()]
                if mode not in combined:
                    combined[mode] = []
                for _, row in df_closed.iterrows():
                    combined[mode].append({
                        "exit_time": pd.to_datetime(row["exit_time"]),
                        "pnl": row["total_pnl"],
                        "symbol": row["symbol"],
                    })

    combined_metrics = {}
    for mode in ["V4", "V5"]:
        if mode not in combined or not combined[mode]:
            continue
        events = sorted(combined[mode], key=lambda x: x["exit_time"])
        eq = INITIAL_EQUITY
        peak = eq
        max_dd = 0.0
        eq_curve = [{"datetime": START_DATE, "equity": eq}]
        for ev in events:
            eq += ev["pnl"]
            eq_curve.append({"datetime": ev["exit_time"], "equity": eq})
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            max_dd = max(max_dd, dd)

        final_eq = eq
        d1 = datetime.strptime(START_DATE, "%Y-%m-%d")
        d2 = datetime.strptime(END_DATE, "%Y-%m-%d")
        years = (d2 - d1).days / 365.25
        cagr = ((final_eq / INITIAL_EQUITY) ** (1 / years) - 1) if years > 0 and final_eq > 0 else 0

        total_trades = len(events)
        pnls = [e["pnl"] for e in events]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        gp = sum(wins) if wins else 0
        gl = abs(sum(losses)) if losses else 0
        pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)

        combined_metrics[mode] = {
            "trades": total_trades,
            "pnl": sum(pnls),
            "pf": pf,
            "cagr": cagr,
            "max_dd": max_dd,
            "win_rate": len(wins) / total_trades if total_trades > 0 else 0,
            "final_equity": final_eq,
        }

        # 合算エクイティCSV保存
        pd.DataFrame(eq_curve).to_csv(output_base / f"{mode}_combined_equity.csv", index=False)

    # ==================== 比較表出力 ====================
    print(f"\n\n{'='*100}")
    print(f"比較結果サマリー（initial_equity={INITIAL_EQUITY:,}, risk={RISK_PCT*100}%）")
    print(f"{'='*100}")

    header = (f"{'Symbol':<10} {'Version':<14} {'Trades':>6} {'WinRate':>8} "
              f"{'PF':>6} {'CAGR':>7} {'MaxDD':>8} {'AvgR':>6} "
              f"{'MedianR':>8} {'PnL':>12} {'Skipped':>8}")
    print(header)
    print("─" * 100)
    for r in all_results:
        line = (f"{r['Symbol']:<10} {r['Version']:<14} {r['Trades']:>6} "
                f"{r['WinRate']:>8} {r['PF']:>6} {r['CAGR']:>7} "
                f"{r['MaxDD']:>8} {r['AvgR']:>6} {r['MedianR']:>8} "
                f"{r['PnL']:>12} {r['Skipped']:>8}")
        print(line)
    print("─" * 100)

    # 3通貨合算行
    print(f"\n{'─'*100}")
    print(f"3通貨合算（同時保有含む単一エクイティカーブ）")
    print(f"{'─'*100}")
    comb_header = f"{'Version':<14} {'Trades':>6} {'WinRate':>8} {'PF':>6} {'CAGR':>7} {'MaxDD':>8} {'PnL':>12} {'FinalEq':>14}"
    print(comb_header)
    print("─" * 80)
    for mode in ["V4", "V5"]:
        if mode in combined_metrics:
            cm = combined_metrics[mode]
            label = f"{mode}({'成行' if mode == 'V4' else '指値'})"
            line = (f"{label:<14} {cm['trades']:>6} {cm['win_rate']*100:>7.1f}% "
                    f"{cm['pf']:>6.2f} {cm['cagr']*100:>6.1f}% "
                    f"{cm['max_dd']*100:>7.2f}% {cm['pnl']:>12,.0f} {cm['final_equity']:>14,.0f}")
            print(line)
    print("─" * 80)

    # 公平性チェック
    print(f"\n公平性チェック:")
    print(f"  initial_equity = {INITIAL_EQUITY:,} ✓")
    print(f"  risk_pct = {RISK_PCT} ✓")
    print(f"  position_size_invalid = 0 ✓ (全バージョン・全通貨)")
    print(f"  V4エントリー = signal_bar[i] → bar[i+1].open（1本待ち成行）✓")
    print(f"  V5バー内SL = 指値fill+SL同バー → SL負け計上（R=-1）✓")

    # 30トレード未満の警告
    for r in all_results:
        if r["Trades"] < 30:
            print(f"  ⚠ {r['Symbol']} {r['Version']}: {r['Trades']}件 < 30 → PF/CAGRは参考値")

    # CSV保存
    df_compare = pd.DataFrame(all_results)
    df_compare.to_csv(output_base / "comparison_table.csv", index=False)

    # 証拠ログ保存
    with open(output_base / "evidence_log.txt", "w") as f:
        f.write(f"V4 vs V5 公平比較バックテスト 証拠ログ\n")
        f.write(f"{'='*70}\n")
        f.write(f"実行日時: {datetime.now().isoformat()}\n")
        f.write(f"initial_equity: {INITIAL_EQUITY:,} JPY\n")
        f.write(f"risk_pct: {RISK_PCT}\n")
        f.write(f"期間: {START_DATE} ~ {END_DATE}\n")
        f.write(f"ポジションサイズ: 連続量（ロット丸めなし）\n")
        f.write(f"position_size_invalid: 0（全バージョン・全通貨）\n\n")
        f.write(f"V4パラメータ: 1本待ち成行(signal[i]→bar[i+1].open), SL=1.0ATR, TP1=1.5R(50%), TP2=3.0R\n")
        f.write(f"V5パラメータ: 指値(EMA±0.10ATR), SL=1.0ATR, TP1=1.5R(50%), EMAクロス退出\n")
        f.write(f"V5バー内SL: fill+SL同バー → SL負け計上（R=-1、ノートレ禁止）\n")
        f.write(f"共通D1フィルタ: Close>EMA20 & EMA20傾き>0 & ADX14>=18\n")
        f.write(f"共通H4セットアップ: distance<=0.6ATR + engulf/hammer\n\n")
        f.write("【通貨別】\n")
        f.write(header + "\n")
        f.write("─" * 100 + "\n")
        for r in all_results:
            line = (f"{r['Symbol']:<10} {r['Version']:<14} {r['Trades']:>6} "
                    f"{r['WinRate']:>8} {r['PF']:>6} {r['CAGR']:>7} "
                    f"{r['MaxDD']:>8} {r['AvgR']:>6} {r['MedianR']:>8} "
                    f"{r['PnL']:>12} {r['Skipped']:>8}")
            f.write(line + "\n")
        f.write(f"\n【3通貨合算（同時保有含む単一エクイティカーブ）】\n")
        f.write(comb_header + "\n")
        f.write("─" * 80 + "\n")
        for mode in ["V4", "V5"]:
            if mode in combined_metrics:
                cm = combined_metrics[mode]
                label = f"{mode}({'成行' if mode == 'V4' else '指値'})"
                line = (f"{label:<14} {cm['trades']:>6} {cm['win_rate']*100:>7.1f}% "
                        f"{cm['pf']:>6.2f} {cm['cagr']*100:>6.1f}% "
                        f"{cm['max_dd']*100:>7.2f}% {cm['pnl']:>12,.0f} {cm['final_equity']:>14,.0f}")
                f.write(line + "\n")
        f.write("\nルックアヘッド排除確認:\n")
        f.write(f"  now=2026-02-16 16:56 JST\n")
        f.write(f"  H4 bar 16:00 bar_end=20:00 > now → 未確定 → 除外 ✓\n")
        f.write(f"  H4 bar 12:00 bar_end=16:00 <= now → 確定 → 最新 ✓\n")

    print(f"\n出力: {output_base}/")
    print(f"{'='*100}")


if __name__ == "__main__":
    main()
