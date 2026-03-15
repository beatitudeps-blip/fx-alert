"""
最終バックテスト: USD/JPY + AUD/JPY
ATR指値エントリー(0.25*ATR) + EMA距離フィルター(0.2-1.2*ATR)
TP1=1.5R / TP2=3.0R / spread=0.05R / slippage=0.05R
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.data import fetch_data_range
from src.indicators import calculate_ema, calculate_atr
from src.daily_strategy.trend import (
    calculate_ema_slope, determine_weekly_trend,
    determine_daily_trend, determine_alignment,
)
from src.daily_strategy.patterns import detect_pattern
from src.daily_strategy.filters import (
    check_ema_distance, check_ema_divergence,
    check_chasing, check_weekly_room,
)
import pandas as pd
import json

load_dotenv_if_exists()

START = "2015-01-01"
END = "2026-02-14"
EQUITY = 500000.0
RISK_PCT = 0.005
TP1_R = 1.5
TP2_R = 3.0
SPREAD_R = 0.05
SLIP_R = 0.05
ENTRY_OFFSET_ATR = 0.25   # 指値エントリー: close ∓ 0.25*ATR
EMA_DIST_MIN = 0.2        # EMA距離下限: 0.2*ATR
EMA_DIST_MAX = 1.2        # EMA距離上限: 1.2*ATR


def check_signal(d1, w1):
    if len(d1) < 22 or len(w1) < 22:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    d_ema20 = calculate_ema(d1["close"], 20)
    w_ema20 = calculate_ema(w1["close"], 20)
    atr14 = calculate_atr(d1, 14)

    close = float(d1["close"].iloc[-1])
    de = float(d_ema20.iloc[-1])
    we = float(w_ema20.iloc[-1])
    wc = float(w1["close"].iloc[-1])
    atr = float(atr14.iloc[-1])
    if atr <= 0:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    ds = calculate_ema_slope(d_ema20)
    ws = calculate_ema_slope(w_ema20)
    wt = determine_weekly_trend(wc, we, ws)
    dt = determine_daily_trend(close, de, ds)
    al = determine_alignment(wt, dt)

    rc = []
    if wt == "WEEKLY_NEUTRAL": rc.append("W")
    if dt == "DAILY_NEUTRAL": rc.append("D")
    if al == "NO_TRADE" and "W" not in rc and "D" not in rc: rc.append("A")

    # EMA距離フィルター: 0.2*ATR <= |price - EMA20| <= 1.2*ATR
    ema_dist_ratio = abs(close - de) / atr
    pullback_ok = EMA_DIST_MIN <= ema_dist_ratio <= EMA_DIST_MAX
    if ema_dist_ratio > EMA_DIST_MAX:
        rc.append("X")

    today = {k: float(d1[k].iloc[-1]) for k in ["open","close","high","low"]}
    prev = {k: float(d1[k].iloc[-2]) for k in ["open","close","high","low"]}
    pn, pd_ = detect_pattern(today, prev, al)
    if not pd_ and al != "NO_TRADE": rc.append("P")

    if check_chasing(today["high"], today["low"], atr) and al != "NO_TRADE" and "X" not in rc:
        rc.append("X")

    side = ""
    entry = sl = risk = 0.0
    if al == "BUY_ONLY":
        side = "BUY"
        entry = close - ENTRY_OFFSET_ATR * atr  # 指値エントリー
        sl = today["low"] - 0.1 * atr
        risk = entry - sl
    elif al == "SELL_ONLY":
        side = "SELL"
        entry = close + ENTRY_OFFSET_ATR * atr  # 指値エントリー
        sl = today["high"] + 0.1 * atr
        risk = sl - entry

    if al in ("BUY_ONLY","SELL_ONLY") and risk > 0:
        _, _, rs = check_weekly_room(w1, entry, al, risk)
        if rs: rc.append("S")
    if al in ("BUY_ONLY","SELL_ONLY") and risk <= 0: rc.append("R")
    if not pullback_ok and al != "NO_TRADE" and "X" not in rc: rc.append("X")

    if al == "NO_TRADE" or rc:
        return {"decision": "SKIP", "reason_codes": rc}

    if side == "BUY":
        tp1, tp2 = entry + TP1_R * risk, entry + TP2_R * risk
    else:
        tp1, tp2 = entry - TP1_R * risk, entry - TP2_R * risk

    return {"decision": "ENTRY_OK", "reason_codes": [], "side": side,
            "entry": entry, "sl": sl, "tp1": tp1, "tp2": tp2,
            "risk_price": risk, "pattern": pn,
            "signal_date": str(d1["datetime"].iloc[-1])}


def run(sym, d1, w1):
    trades, eq, active = [], EQUITY, None
    skips = {}

    for i in range(30, len(d1)):
        dt = d1["datetime"].iloc[i]
        # 確定済み週足のみ（当週の未完成バーを除外し look-ahead bias を防ぐ）
        monday = dt - pd.Timedelta(days=dt.weekday())
        w1s = w1[w1["datetime"] < monday]

        if active:
            h, l = float(d1["high"].iloc[i]), float(d1["low"].iloc[i])
            s = active["side"]
            sl = active["csl"]

            sl_hit = (l <= sl) if s == "BUY" else (h >= sl)
            tp1_hit = (h >= active["tp1"]) if s == "BUY" else (l <= active["tp1"])
            tp2_hit = (h >= active["tp2"]) if s == "BUY" else (l <= active["tp2"])

            if not active["tp1d"]:
                tp2_hit = False
            else:
                tp1_hit = False

            if sl_hit and not active["tp1d"]:
                pnl = -active["rj"]
                eq += pnl
                active.update(exit_date=str(dt), exit_reason="SL", pnl=pnl, pnl_r=-1.0)
                trades.append(active); active = None
            elif sl_hit and active["tp1d"]:
                active.update(exit_date=str(dt), exit_reason="BE", pnl=active["tp1p"], pnl_r=TP1_R*0.5)
                trades.append(active); active = None
            elif tp1_hit:
                p = active["rj"] * TP1_R * 0.5
                eq += p
                active["tp1d"], active["tp1p"], active["csl"] = True, p, active["entry"]
            elif tp2_hit:
                p = active["rj"] * TP2_R * 0.5
                eq += p
                total = active["tp1p"] + p
                active.update(exit_date=str(dt), exit_reason="TP2", pnl=total, pnl_r=TP1_R*0.5+TP2_R*0.5)
                trades.append(active); active = None
            continue

        sig = check_signal(d1.iloc[:i+1], w1s)
        if sig["decision"] == "ENTRY_OK":
            # 指値エントリー約定判定: 当日 high/low の範囲内か
            bar_h = float(d1["high"].iloc[i])
            bar_l = float(d1["low"].iloc[i])
            if sig["side"] == "BUY" and sig["entry"] < bar_l:
                sig = {"decision": "SKIP", "reason_codes": ["LIMIT_NOT_FILLED"]}
            elif sig["side"] == "SELL" and sig["entry"] > bar_h:
                sig = {"decision": "SKIP", "reason_codes": ["LIMIT_NOT_FILLED"]}
        if sig["decision"] == "SKIP":
            for r in sig["reason_codes"]: skips[r] = skips.get(r, 0) + 1
        elif sig["decision"] == "ENTRY_OK":
            rj = eq * RISK_PCT
            u = rj / sig["risk_price"] if sig["risk_price"] > 0 else 0
            u = (u // 100) * 100
            if u < 100:
                skips["SIZE"] = skips.get("SIZE", 0) + 1; continue
            arj = u * sig["risk_price"]
            cost = arj * (SPREAD_R + SLIP_R)
            active = {"symbol": sym, "side": sig["side"], "entry": sig["entry"],
                      "sl": sig["sl"], "tp1": sig["tp1"], "tp2": sig["tp2"],
                      "csl": sig["sl"], "risk_price": sig["risk_price"],
                      "rj": arj, "cost": cost, "units": u,
                      "entry_date": str(dt), "pattern": sig["pattern"],
                      "tp1d": False, "tp1p": 0.0}

    if active:
        active.update(exit_date=str(d1["datetime"].iloc[-1]), exit_reason="OPEN", pnl=0, pnl_r=0)
        trades.append(active)

    return trades, eq, skips


def metrics(trades, init_eq, yrs):
    cl = [t for t in trades if t.get("exit_reason") != "OPEN"]
    w = [t for t in cl if t["pnl"] > 0]
    lo = [t for t in cl if t["pnl"] < 0]
    gw = sum(t["pnl"] for t in w) if w else 0
    gl = abs(sum(t["pnl"] for t in lo)) if lo else 0
    tc = sum(t.get("cost", 0) for t in cl)
    pf = gw / gl if gl > 0 else float("inf")
    pfn = (gw - tc*0.5) / (gl + tc*0.5) if (gl + tc*0.5) > 0 else float("inf")
    tr = sum(t["pnl_r"] for t in cl)
    tp = sum(t["pnl"] for t in cl)

    pk, md, eq = init_eq, 0, init_eq
    for t in cl:
        eq += t["pnl"] - t.get("cost", 0)
        if eq > pk: pk = eq
        dd = (pk - eq) / pk if pk > 0 else 0
        md = max(md, dd)

    st, ms = 0, 0
    for t in cl:
        if t["pnl"] < 0: st += 1; ms = max(ms, st)
        else: st = 0

    return {"trades": len(cl), "tpy": len(cl)/yrs, "wr": len(w)/len(cl)*100 if cl else 0,
            "pf": pf, "pfn": pfn, "tr": tr, "ar": tr/len(cl) if cl else 0,
            "pnl": tp, "cost": tc, "net": tp-tc, "dd": md*100, "ms": ms,
            "ret": tp/init_eq*100, "ann": tp/init_eq*100/yrs}


if __name__ == "__main__":
    api_key = check_api_key(required=True)
    yrs = (pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25
    pairs = ["USD/JPY", "AUD/JPY"]

    print(f"\n{'='*80}")
    print(f"FINAL BACKTEST")
    print(f"{'='*80}")
    print(f"Period:   {START} ~ {END} ({yrs:.1f} years)")
    print(f"Pairs:    {', '.join(pairs)}")
    print(f"TP:       TP1={TP1_R}R / TP2={TP2_R}R")
    print(f"SL:       0.1 * ATR14")
    print(f"Risk:     {RISK_PCT*100:.1f}%")
    print(f"Entry:    limit offset={ENTRY_OFFSET_ATR}*ATR")
    print(f"EMA:      [{EMA_DIST_MIN}, {EMA_DIST_MAX}]*ATR")
    print(f"Cost:     spread=0.05R + slippage=0.05R")
    print(f"Equity:   {EQUITY:,.0f} JPY")
    print(f"{'='*80}\n")

    all_trades = []
    for pair in pairs:
        ws = (datetime.strptime(START, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        d1 = fetch_data_range(pair, "1day", ws, END, api_key)
        w1 = fetch_data_range(pair, "1week", ws, END, api_key)

        tr, eq, sk = run(pair, d1, w1)
        m = metrics(tr, EQUITY, yrs)
        cl = [t for t in tr if t.get("exit_reason") != "OPEN"]
        er = {}
        for t in cl: er[t["exit_reason"]] = er.get(t["exit_reason"], 0) + 1

        print(f"[{pair}]")
        print(f"  Trades:     {m['trades']}  ({m['tpy']:.1f}/yr)")
        print(f"  Win Rate:   {m['wr']:.1f}%")
        print(f"  PF gross:   {m['pf']:.2f}")
        print(f"  PF net:     {m['pfn']:.2f}")
        print(f"  Total R:    {m['tr']:+.1f}  (Avg {m['ar']:+.3f})")
        print(f"  PnL gross:  {m['pnl']:+,.0f} JPY")
        print(f"  Cost:       {m['cost']:,.0f} JPY")
        print(f"  PnL net:    {m['net']:+,.0f} JPY")
        print(f"  Max DD:     {m['dd']:.2f}%")
        print(f"  Max Streak: {m['ms']}")
        print(f"  Return:     {m['ret']:+.2f}% ({m['ann']:+.2f}%/yr)")
        print(f"  Exits:      {er}")
        print()
        all_trades.extend(tr)

    # Combined
    m = metrics(all_trades, EQUITY * len(pairs), yrs)
    cl = [t for t in all_trades if t.get("exit_reason") != "OPEN"]
    er = {}
    for t in cl: er[t["exit_reason"]] = er.get(t["exit_reason"], 0) + 1

    print(f"{'='*80}")
    print(f"COMBINED ({len(pairs)} pairs)")
    print(f"{'='*80}")
    print(f"  Trades:     {m['trades']}  ({m['tpy']:.1f}/yr)")
    print(f"  Win Rate:   {m['wr']:.1f}%")
    print(f"  PF gross:   {m['pf']:.2f}")
    print(f"  PF net:     {m['pfn']:.2f}")
    print(f"  Total R:    {m['tr']:+.1f}  (Avg {m['ar']:+.3f})")
    print(f"  PnL gross:  {m['pnl']:+,.0f} JPY")
    print(f"  Cost:       {m['cost']:,.0f} JPY")
    print(f"  PnL net:    {m['net']:+,.0f} JPY")
    print(f"  Max DD:     {m['dd']:.2f}%")
    print(f"  Max Streak: {m['ms']}")
    print(f"  Exits:      {er}")

    # Annual
    yearly = {}
    for t in cl:
        yr = t["entry_date"][:4]
        if yr not in yearly:
            yearly[yr] = {"n": 0, "pnl": 0, "w": 0, "r": 0}
        yearly[yr]["n"] += 1
        yearly[yr]["pnl"] += t["pnl"] - t.get("cost", 0)
        yearly[yr]["r"] += t["pnl_r"]
        if t["pnl"] > 0: yearly[yr]["w"] += 1

    print(f"\n{'Year':<6} {'Trades':>7} {'WR%':>6} {'R':>7} {'NetPnL':>12}")
    print("-" * 42)
    for yr in sorted(yearly):
        y = yearly[yr]
        wr = y["w"] / y["n"] * 100 if y["n"] > 0 else 0
        print(f"{yr:<6} {y['n']:>7} {wr:>5.0f}% {y['r']:>+6.1f} {y['pnl']:>+12,.0f}")
