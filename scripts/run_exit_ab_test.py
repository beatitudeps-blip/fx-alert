"""退出方式ABテスト

エントリーは全てV4（1本待ち成行）で固定。退出ロジックのみ変更。

Variant 0: V4_BASE          TP2=3R + TP1後BE
Variant 1: V4_EMA_EXIT      EMA退出 + TP1後BE
Variant 2: V4_PARTIAL_STOP  TP2=3R + TP1後SL=-0.5R
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.backtest_fair import run_backtest_exit_variant, run_portfolio_exit_variant
import pandas as pd
import numpy as np

load_dotenv_if_exists()

# ==================== 固定設定 ====================
INITIAL_EQUITY = 500_000
RISK_PCT = 0.005
SYMBOLS = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
START_DATE = "2023-01-01"
END_DATE = "2026-02-16"

VARIANTS = ["V4_BASE", "V4_EMA_EXIT", "V4_PARTIAL_STOP"]


def calc_metrics(trades, initial_eq, start_date, end_date):
    closed = [t for t in trades if t.exit_time is not None]
    if not closed:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0, "pf": 0,
                "total_pnl": 0, "max_dd": 0, "avg_r": 0, "median_r": 0,
                "cagr": 0, "final_equity": initial_eq}
    pnls = [t.total_pnl for t in closed]
    risks = [t.risk_jpy for t in closed]
    r_multiples = [p / r if r > 0 else 0 for p, r in zip(pnls, risks)]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 0
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
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
    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    years = (d2 - d1).days / 365.25
    cagr = ((final_eq / initial_eq) ** (1 / years) - 1) if years > 0 and final_eq > 0 else 0
    return {
        "trades": len(closed), "wins": len(wins), "losses": len(losses),
        "win_rate": len(wins) / len(closed), "pf": pf,
        "total_pnl": sum(pnls), "max_dd": max_dd,
        "avg_r": np.mean(r_multiples), "median_r": np.median(r_multiples),
        "cagr": cagr, "final_equity": final_eq,
    }


def calc_portfolio_metrics(trades, eq_curve, initial_eq, start_date, end_date):
    closed = [t for t in trades if t.exit_time is not None]
    if not closed:
        return {"trades": 0, "pf": 0, "cagr": 0, "max_dd": 0, "pnl": 0,
                "final_equity": initial_eq, "win_rate": 0}
    pnls = [t.total_pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 0
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
    max_dd = 0.0
    peak = initial_eq
    for _, row in eq_curve.iterrows():
        e = row["equity"]
        if e > peak:
            peak = e
        dd = (peak - e) / peak if peak > 0 else 0
        max_dd = max(max_dd, dd)
    final_eq = eq_curve.iloc[-1]["equity"] if len(eq_curve) > 0 else initial_eq
    d1 = datetime.strptime(start_date, "%Y-%m-%d")
    d2 = datetime.strptime(end_date, "%Y-%m-%d")
    years = (d2 - d1).days / 365.25
    cagr = ((final_eq / initial_eq) ** (1 / years) - 1) if years > 0 and final_eq > 0 else 0
    return {
        "trades": len(closed), "pf": pf, "cagr": cagr, "max_dd": max_dd,
        "pnl": sum(pnls), "final_equity": final_eq,
        "win_rate": len(wins) / len(closed) if closed else 0,
    }


def main():
    api_key = check_api_key(required=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(f"data/results_exit_ab/{run_id}")
    output_base.mkdir(parents=True, exist_ok=True)

    print(f"{'='*80}")
    print("退出方式ABテスト（エントリー=V4成行で固定）")
    print(f"期間={START_DATE}~{END_DATE}, equity={INITIAL_EQUITY:,}, risk={RISK_PCT}")
    print(f"{'='*80}")

    # ==================== 1) 通貨別 × バリアント別 ====================
    all_rows = []
    exit_detail_rows = []

    for sym in SYMBOLS:
        for vname in VARIANTS:
            trades, eq_df, stats = run_backtest_exit_variant(
                symbol=sym, start_date=START_DATE, end_date=END_DATE,
                exit_variant=vname, api_key=api_key,
                initial_equity=INITIAL_EQUITY, risk_pct=RISK_PCT,
                use_cache=True,
            )
            m = calc_metrics(trades, INITIAL_EQUITY, START_DATE, END_DATE)
            row = {
                "Symbol": sym, "Variant": vname,
                "Trades": m["trades"],
                "WinRate": round(m["win_rate"] * 100, 1),
                "PF": round(m["pf"], 2),
                "AvgR": round(m["avg_r"], 2),
                "MedianR": round(m["median_r"], 2),
                "MaxDD": round(m["max_dd"] * 100, 2),
                "CAGR": round(m["cagr"] * 100, 1),
                "PnL": round(m["total_pnl"]),
            }
            all_rows.append(row)
            exit_detail_rows.append({
                "Symbol": sym, "Variant": vname,
                "SL": stats["sl_count"],
                "BE": stats["be_count"],
                "PartialSL": stats["partial_sl_count"],
                "TP2": stats["tp2_count"],
                "EMA_EXIT": stats["ema_exit_count"],
            })
            print(f"  {sym} {vname}: Trades={m['trades']}, PF={m['pf']:.2f}, "
                  f"PnL={m['total_pnl']:,.0f}")

    df_compare = pd.DataFrame(all_rows)
    df_compare.to_csv(output_base / "comparison_table.csv", index=False)

    # ==================== 2) ポートフォリオ合算 ====================
    print(f"\n{'─'*60}")
    print("ポートフォリオ合算 (max_open=2, max_risk=1%):")
    port_rows = []
    port_exit_rows = []

    for vname in VARIANTS:
        trades, eq_df, stats = run_portfolio_exit_variant(
            symbols=SYMBOLS, start_date=START_DATE, end_date=END_DATE,
            exit_variant=vname, api_key=api_key,
            initial_equity=INITIAL_EQUITY, risk_pct=RISK_PCT,
            use_cache=True,
            max_open_positions=2, max_total_risk_pct=0.01,
        )
        pm = calc_portfolio_metrics(trades, eq_df, INITIAL_EQUITY, START_DATE, END_DATE)
        port_row = {
            "Variant": vname,
            "Trades": pm["trades"],
            "WR": round(pm["win_rate"] * 100, 1),
            "PF": round(pm["pf"], 2),
            "CAGR": round(pm["cagr"] * 100, 1),
            "MaxDD": round(pm["max_dd"] * 100, 2),
            "PnL": round(pm["pnl"]),
            "FinalEq": round(pm["final_equity"]),
            "RiskSkip": stats["skipped_riskcap"],
        }
        port_rows.append(port_row)
        port_exit_rows.append({
            "Variant": vname,
            "SL": stats["sl_count"],
            "BE": stats["be_count"],
            "PartialSL": stats["partial_sl_count"],
            "TP2": stats["tp2_count"],
            "EMA_EXIT": stats["ema_exit_count"],
        })
        eq_df.to_csv(output_base / f"{vname}_portfolio_equity.csv", index=False)
        print(f"  {vname}: Trades={pm['trades']}, PF={pm['pf']:.2f}, "
              f"CAGR={pm['cagr']*100:.1f}%, MaxDD={pm['max_dd']*100:.1f}%, "
              f"PnL={pm['pnl']:,.0f}, RiskSkip={stats['skipped_riskcap']}")

    df_port = pd.DataFrame(port_rows)
    df_port.to_csv(output_base / "portfolio_summary.csv", index=False)

    # ==================== 出力 ====================
    print(f"\n{'='*100}")
    print("【通貨別 × バリアント別】")
    print(f"{'='*100}")
    hdr = (f"{'Symbol':<10}{'Variant':<20}{'Trades':>6}{'WR':>6}{'PF':>6}"
           f"{'AvgR':>7}{'MedR':>7}{'MaxDD':>8}{'CAGR':>7}{'PnL':>10}")
    print(hdr)
    print("─" * 100)
    for _, r in df_compare.iterrows():
        line = (f"{r['Symbol']:<10}{r['Variant']:<20}{r['Trades']:>6}"
                f"{r['WinRate']:>5.1f}%{r['PF']:>6.2f}"
                f"{r['AvgR']:>7.2f}{r['MedianR']:>7.2f}"
                f"{r['MaxDD']:>7.2f}%{r['CAGR']:>6.1f}%"
                f"{r['PnL']:>10,}")
        print(line)
    print("─" * 100)

    print(f"\n{'='*100}")
    print("【ポートフォリオ合算】max_open=2, max_risk=1%")
    print(f"{'='*100}")
    phdr = (f"{'Variant':<20}{'Trades':>6}{'WR':>6}{'PF':>6}{'CAGR':>7}{'MaxDD':>8}"
            f"{'PnL':>10}{'FinalEq':>12}{'RiskSkip':>10}")
    print(phdr)
    print("─" * 90)
    for _, r in df_port.iterrows():
        line = (f"{r['Variant']:<20}{r['Trades']:>6}{r['WR']:>5.1f}%{r['PF']:>6.2f}"
                f"{r['CAGR']:>6.1f}%{r['MaxDD']:>7.2f}%"
                f"{r['PnL']:>10,}{r['FinalEq']:>12,}{r['RiskSkip']:>10}")
        print(line)
    print("─" * 90)

    # ==================== 3) 退出分類カウント ====================
    print(f"\n{'='*100}")
    print("【退出分類カウント（通貨別）】")
    print(f"{'='*100}")
    df_exit = pd.DataFrame(exit_detail_rows)
    ehdr = f"{'Symbol':<10}{'Variant':<20}{'SL':>6}{'BE':>6}{'P.SL':>6}{'TP2':>6}{'EMA':>6}"
    print(ehdr)
    print("─" * 65)
    for _, r in df_exit.iterrows():
        line = (f"{r['Symbol']:<10}{r['Variant']:<20}{r['SL']:>6}{r['BE']:>6}"
                f"{r['PartialSL']:>6}{r['TP2']:>6}{r['EMA_EXIT']:>6}")
        print(line)
    print("─" * 65)

    print(f"\n【退出分類カウント（ポートフォリオ）】")
    df_pexit = pd.DataFrame(port_exit_rows)
    print(ehdr.replace("Symbol    ", "          "))
    print("─" * 65)
    for _, r in df_pexit.iterrows():
        line = (f"{'':>10}{r['Variant']:<20}{r['SL']:>6}{r['BE']:>6}"
                f"{r['PartialSL']:>6}{r['TP2']:>6}{r['EMA_EXIT']:>6}")
        print(line)
    print("─" * 65)

    # ==================== 4) バリアント定義 ====================
    print(f"\n{'─'*60}")
    print("バリアント定義:")
    print(f"{'Variant':<20}{'Entry':<12}{'TP2':<10}{'TP1後SL':<15}{'残50%退出':<12}")
    print("─" * 60)
    print(f"{'V4_BASE':<20}{'成行':<12}{'3.0R':<10}{'BE(entry)':<15}{'TP2固定':<12}")
    print(f"{'V4_EMA_EXIT':<20}{'成行':<12}{'なし':<10}{'BE(entry)':<15}{'EMAクロス':<12}")
    print(f"{'V4_PARTIAL_STOP':<20}{'成行':<12}{'3.0R':<10}{'-0.5R':<15}{'TP2固定':<12}")

    print(f"\n出力: {output_base}/")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
