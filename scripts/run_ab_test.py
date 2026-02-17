"""
V5 パラメータABテスト + ポートフォリオ合算

バリアント:
  V4           : 1本待ち成行（固定）
  V5_10_06     : LIMIT_ATR_OFFSET=0.10, DISTANCE_ATR_RATIO=0.6
  V5_10_08     : LIMIT_ATR_OFFSET=0.10, DISTANCE_ATR_RATIO=0.8
  V5_05_06     : LIMIT_ATR_OFFSET=0.05, DISTANCE_ATR_RATIO=0.6
  V5_05_08     : LIMIT_ATR_OFFSET=0.05, DISTANCE_ATR_RATIO=0.8

ポートフォリオ: 1口座500k, max_open=2, max_risk=1%
"""
import sys
from pathlib import Path
from datetime import datetime
import json

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.backtest_fair import run_backtest_fair, run_portfolio_backtest
import pandas as pd
import numpy as np

load_dotenv_if_exists()

# ==================== 固定設定 ====================
INITIAL_EQUITY = 500_000
RISK_PCT = 0.005
SYMBOLS = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
START_DATE = "2023-01-01"
END_DATE = "2026-02-16"

VARIANTS = {
    "V4": {"mode": "V4", "limit_atr_offset": 0.10, "distance_atr_ratio": 0.6},
    "V5_10_06": {"mode": "V5", "limit_atr_offset": 0.10, "distance_atr_ratio": 0.6},
    "V5_10_08": {"mode": "V5", "limit_atr_offset": 0.10, "distance_atr_ratio": 0.8},
    "V5_05_06": {"mode": "V5", "limit_atr_offset": 0.05, "distance_atr_ratio": 0.6},
    "V5_05_08": {"mode": "V5", "limit_atr_offset": 0.05, "distance_atr_ratio": 0.8},
}


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
                "final_equity": initial_eq}
    pnls = [t.total_pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins) if wins else 0
    gl = abs(sum(losses)) if losses else 0
    pf = gp / gl if gl > 0 else (float('inf') if gp > 0 else 0)
    # MaxDD from equity curve
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
    output_base = Path(f"data/results_ab/{run_id}")
    output_base.mkdir(parents=True, exist_ok=True)

    print(f"{'='*80}")
    print("V5 パラメータABテスト")
    print(f"期間={START_DATE}~{END_DATE}, equity={INITIAL_EQUITY:,}, risk={RISK_PCT}")
    print(f"{'='*80}")

    # ==================== 1) 通貨別 × バリアント別 ====================
    all_rows = []
    for sym in SYMBOLS:
        for vname, vp in VARIANTS.items():
            trades, eq_df, stats = run_backtest_fair(
                symbol=sym, start_date=START_DATE, end_date=END_DATE,
                mode=vp["mode"], api_key=api_key,
                initial_equity=INITIAL_EQUITY, risk_pct=RISK_PCT,
                use_cache=True,
                limit_atr_offset=vp["limit_atr_offset"],
                distance_atr_ratio=vp["distance_atr_ratio"],
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
                "Skipped": stats.get("limit_expired", 0),
                "IntraBarSL": stats.get("intra_bar_sl", 0),
            }
            all_rows.append(row)
            print(f"  {sym} {vname}: Trades={m['trades']}, PF={m['pf']:.2f}, "
                  f"PnL={m['total_pnl']:,.0f}")

    df_compare = pd.DataFrame(all_rows)
    df_compare.to_csv(output_base / "comparison_table.csv", index=False)

    # ==================== 2) 30トレードチェック ====================
    print(f"\n{'─'*60}")
    print("30トレードチェック:")
    for _, r in df_compare.iterrows():
        if r["Trades"] < 30:
            print(f"  ⚠ {r['Symbol']} {r['Variant']}: {r['Trades']}件 < 30")
    if all(r["Trades"] >= 30 for _, r in df_compare.iterrows()):
        print("  全バリアント30件以上 ✓")

    # ==================== 3) ポートフォリオ合算 ====================
    print(f"\n{'─'*60}")
    print("ポートフォリオ合算 (max_open=2, max_risk=1%):")
    port_rows = []
    for vname, vp in VARIANTS.items():
        trades, eq_df, stats = run_portfolio_backtest(
            symbols=SYMBOLS, start_date=START_DATE, end_date=END_DATE,
            mode=vp["mode"], api_key=api_key,
            initial_equity=INITIAL_EQUITY, risk_pct=RISK_PCT,
            use_cache=True,
            limit_atr_offset=vp["limit_atr_offset"],
            distance_atr_ratio=vp["distance_atr_ratio"],
            max_open_positions=2, max_total_risk_pct=0.01,
        )
        pm = calc_portfolio_metrics(trades, eq_df, INITIAL_EQUITY, START_DATE, END_DATE)
        port_row = {
            "Variant": vname,
            "Trades": pm["trades"],
            "PF": round(pm["pf"], 2),
            "CAGR": round(pm["cagr"] * 100, 1),
            "MaxDD": round(pm["max_dd"] * 100, 2),
            "PnL": round(pm["pnl"]),
            "FinalEq": round(pm["final_equity"]),
            "Skipped_riskcap": stats["skipped_riskcap"],
        }
        port_rows.append(port_row)
        eq_df.to_csv(output_base / f"{vname}_portfolio_equity.csv", index=False)
        print(f"  {vname}: Trades={pm['trades']}, PF={pm['pf']:.2f}, "
              f"CAGR={pm['cagr']*100:.1f}%, MaxDD={pm['max_dd']*100:.1f}%, "
              f"PnL={pm['pnl']:,.0f}, RiskCapSkip={stats['skipped_riskcap']}")

    df_port = pd.DataFrame(port_rows)
    df_port.to_csv(output_base / "portfolio_summary.csv", index=False)

    # ==================== 出力 ====================
    print(f"\n{'='*100}")
    print("【通貨別 × バリアント別】")
    print(f"{'='*100}")
    hdr = (f"{'Symbol':<10}{'Variant':<12}{'Trades':>6}{'WinRate':>8}{'PF':>6}"
           f"{'AvgR':>7}{'MedR':>7}{'MaxDD':>8}{'CAGR':>7}{'PnL':>10}"
           f"{'Skip':>6}{'IBSL':>6}")
    print(hdr)
    print("─" * 100)
    for _, r in df_compare.iterrows():
        line = (f"{r['Symbol']:<10}{r['Variant']:<12}{r['Trades']:>6}"
                f"{r['WinRate']:>7.1f}%{r['PF']:>6.2f}"
                f"{r['AvgR']:>7.2f}{r['MedianR']:>7.2f}"
                f"{r['MaxDD']:>7.2f}%{r['CAGR']:>6.1f}%"
                f"{r['PnL']:>10,}{r['Skipped']:>6}{r['IntraBarSL']:>6}")
        print(line)
    print("─" * 100)

    print(f"\n{'='*100}")
    print("【ポートフォリオ合算】max_open=2, max_risk=1%")
    print(f"{'='*100}")
    phdr = (f"{'Variant':<12}{'Trades':>6}{'PF':>6}{'CAGR':>7}{'MaxDD':>8}"
            f"{'PnL':>10}{'FinalEq':>12}{'RiskSkip':>10}")
    print(phdr)
    print("─" * 80)
    for _, r in df_port.iterrows():
        line = (f"{r['Variant']:<12}{r['Trades']:>6}{r['PF']:>6.2f}"
                f"{r['CAGR']:>6.1f}%{r['MaxDD']:>7.2f}%"
                f"{r['PnL']:>10,}{r['FinalEq']:>12,}{r['Skipped_riskcap']:>10}")
        print(line)
    print("─" * 80)

    # ==================== 4) 最良V5バリアント選択 ====================
    print(f"\n{'='*100}")
    print("【最良V5バリアント】")
    print(f"{'='*100}")

    v5_rows = df_compare[df_compare["Variant"] != "V4"]
    v4_rows = df_compare[df_compare["Variant"] == "V4"]

    for sym in SYMBOLS:
        sym_v5 = v5_rows[v5_rows["Symbol"] == sym]
        if sym_v5.empty:
            continue
        best = sym_v5.loc[sym_v5["PF"].idxmax()]
        v4 = v4_rows[v4_rows["Symbol"] == sym].iloc[0]
        print(f"\n{sym}: {best['Variant']} (PF={best['PF']:.2f})")
        pf_diff = best["PF"] - v4["PF"]
        dd_diff = best["MaxDD"] - v4["MaxDD"]
        skip_rate = best["Skipped"] / (best["Trades"] + best["Skipped"]) * 100 if (best["Trades"] + best["Skipped"]) > 0 else 0
        print(f"  vs V4: PF {v4['PF']:.2f}→{best['PF']:.2f} ({pf_diff:+.2f}), "
              f"MaxDD {v4['MaxDD']:.1f}%→{best['MaxDD']:.1f}% ({dd_diff:+.1f}pp)")
        print(f"  失効率={skip_rate:.0f}%, AvgR={best['AvgR']:.2f}, IntraBarSL={best['IntraBarSL']}")

    # ポートフォリオ最良
    v5_port = df_port[df_port["Variant"] != "V4"]
    if not v5_port.empty:
        best_p = v5_port.loc[v5_port["PF"].idxmax()]
        v4_p = df_port[df_port["Variant"] == "V4"].iloc[0]
        print(f"\nPortfolio: {best_p['Variant']} (PF={best_p['PF']:.2f})")
        print(f"  vs V4: PF {v4_p['PF']:.2f}→{best_p['PF']:.2f}, "
              f"MaxDD {v4_p['MaxDD']:.1f}%→{best_p['MaxDD']:.1f}%, "
              f"CAGR {v4_p['CAGR']:.1f}%→{best_p['CAGR']:.1f}%")

    # バリアント定数表
    print(f"\n{'─'*50}")
    print("バリアント定数対応表:")
    print(f"{'Variant':<12}{'Mode':<6}{'LimitOffset':>12}{'DistRatio':>12}")
    print("─" * 50)
    for vn, vp in VARIANTS.items():
        print(f"{vn:<12}{vp['mode']:<6}{vp['limit_atr_offset']:>12.2f}{vp['distance_atr_ratio']:>12.1f}")

    print(f"\n出力: {output_base}/")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
