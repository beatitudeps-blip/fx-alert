"""
運用リスク管理バックテスト比較:
  A) ベースライン（現行: 1-bar expiry あり, time stop なし）
  B) + Time Stop 7営業日
出力: trades, fill rate, win rate, PF gross/net, total R, max DD, avg holding days
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

load_dotenv_if_exists()

START = "2015-01-01"
END = "2026-02-14"
EQUITY = 500000.0
RISK_PCT = 0.005
TP1_R = 1.5
TP2_R = 3.0
SPREAD_R = 0.05
SLIP_R = 0.05
ENTRY_OFFSET_ATR = 0.25
EMA_DIST_MIN = 0.2
EMA_DIST_MAX = 1.2


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

    ema_dist_ratio = abs(close - de) / atr
    pullback_ok = EMA_DIST_MIN <= ema_dist_ratio <= EMA_DIST_MAX
    if ema_dist_ratio > EMA_DIST_MAX:
        rc.append("X")

    today = {k: float(d1[k].iloc[-1]) for k in ["open", "close", "high", "low"]}
    prev = {k: float(d1[k].iloc[-2]) for k in ["open", "close", "high", "low"]}
    pn, pd_ = detect_pattern(today, prev, al)
    if not pd_ and al != "NO_TRADE": rc.append("P")

    if check_chasing(today["high"], today["low"], atr) and al != "NO_TRADE" and "X" not in rc:
        rc.append("X")

    side = ""
    entry = sl = risk = 0.0
    if al == "BUY_ONLY":
        side = "BUY"
        entry = close - ENTRY_OFFSET_ATR * atr
        sl = today["low"] - 0.1 * atr
        risk = entry - sl
    elif al == "SELL_ONLY":
        side = "SELL"
        entry = close + ENTRY_OFFSET_ATR * atr
        sl = today["high"] + 0.1 * atr
        risk = sl - entry

    if al in ("BUY_ONLY", "SELL_ONLY") and risk > 0:
        _, _, rs = check_weekly_room(w1, entry, al, risk)
        if rs: rc.append("S")
    if al in ("BUY_ONLY", "SELL_ONLY") and risk <= 0: rc.append("R")
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


def run(sym, d1, w1, time_stop_days=None):
    """
    time_stop_days: None=無効, int=N営業日後にTIME_STOPで強制決済
    """
    trades, eq, active = [], EQUITY, None
    skips = {}
    signals_total = 0
    fills_total = 0

    for i in range(30, len(d1)):
        dt = d1["datetime"].iloc[i]
        monday = dt - pd.Timedelta(days=dt.weekday())
        w1s = w1[w1["datetime"] < monday]

        if active:
            h, l = float(d1["high"].iloc[i]), float(d1["low"].iloc[i])
            c = float(d1["close"].iloc[i])
            s = active["side"]
            sl = active["csl"]
            active["holding_days"] += 1

            sl_hit = (l <= sl) if s == "BUY" else (h >= sl)
            tp1_hit = (h >= active["tp1"]) if s == "BUY" else (l <= active["tp1"])
            tp2_hit = (h >= active["tp2"]) if s == "BUY" else (l <= active["tp2"])

            if not active["tp1d"]:
                tp2_hit = False
            else:
                tp1_hit = False

            # Time stop check (before SL/TP to give SL/TP priority on same bar)
            time_stopped = False
            if time_stop_days and active["holding_days"] >= time_stop_days:
                if not sl_hit and not tp1_hit and not tp2_hit:
                    time_stopped = True

            if sl_hit and not active["tp1d"]:
                pnl = -active["rj"]
                eq += pnl
                active.update(exit_date=str(dt), exit_reason="SL", pnl=pnl, pnl_r=-1.0)
                trades.append(active); active = None
            elif sl_hit and active["tp1d"]:
                active.update(exit_date=str(dt), exit_reason="BE", pnl=active["tp1p"], pnl_r=TP1_R * 0.5)
                trades.append(active); active = None
            elif tp1_hit:
                p = active["rj"] * TP1_R * 0.5
                eq += p
                active["tp1d"], active["tp1p"], active["csl"] = True, p, active["entry"]
            elif tp2_hit:
                p = active["rj"] * TP2_R * 0.5
                eq += p
                total = active["tp1p"] + p
                active.update(exit_date=str(dt), exit_reason="TP2", pnl=total, pnl_r=TP1_R * 0.5 + TP2_R * 0.5)
                trades.append(active); active = None
            elif time_stopped:
                # Time stop: close at current close price
                if s == "BUY":
                    exit_pnl_per_unit = c - active["entry"]
                else:
                    exit_pnl_per_unit = active["entry"] - c
                pnl_r = exit_pnl_per_unit / active["risk_price"] if active["risk_price"] > 0 else 0
                # Half position if TP1 already done
                if active["tp1d"]:
                    pnl = active["units"] * 0.5 * exit_pnl_per_unit
                    total_pnl = active["tp1p"] + pnl
                    total_r = TP1_R * 0.5 + pnl_r * 0.5
                else:
                    pnl = active["units"] * exit_pnl_per_unit
                    total_pnl = pnl
                    total_r = pnl_r
                eq += (total_pnl - (active.get("tp1p", 0) if active["tp1d"] else 0))
                active.update(exit_date=str(dt), exit_reason="TIME_STOP",
                              pnl=total_pnl, pnl_r=total_r)
                trades.append(active); active = None
            continue

        sig = check_signal(d1.iloc[:i + 1], w1s)
        if sig["decision"] == "ENTRY_OK":
            signals_total += 1
            # 1-bar limit order fill check
            bar_h = float(d1["high"].iloc[i])
            bar_l = float(d1["low"].iloc[i])
            if sig["side"] == "BUY" and sig["entry"] < bar_l:
                sig = {"decision": "SKIP", "reason_codes": ["LIMIT_NOT_FILLED"]}
            elif sig["side"] == "SELL" and sig["entry"] > bar_h:
                sig = {"decision": "SKIP", "reason_codes": ["LIMIT_NOT_FILLED"]}

        if sig["decision"] == "SKIP":
            for r in sig["reason_codes"]: skips[r] = skips.get(r, 0) + 1
        elif sig["decision"] == "ENTRY_OK":
            fills_total += 1
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
                      "tp1d": False, "tp1p": 0.0, "holding_days": 0}

    if active:
        active.update(exit_date=str(d1["datetime"].iloc[-1]), exit_reason="OPEN", pnl=0, pnl_r=0)
        trades.append(active)

    return trades, eq, skips, signals_total, fills_total


def metrics(trades, init_eq, yrs):
    cl = [t for t in trades if t.get("exit_reason") != "OPEN"]
    w = [t for t in cl if t["pnl"] > 0]
    lo = [t for t in cl if t["pnl"] < 0]
    gw = sum(t["pnl"] for t in w) if w else 0
    gl = abs(sum(t["pnl"] for t in lo)) if lo else 0
    tc = sum(t.get("cost", 0) for t in cl)
    pf = gw / gl if gl > 0 else float("inf")
    pfn = (gw - tc * 0.5) / (gl + tc * 0.5) if (gl + tc * 0.5) > 0 else float("inf")
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

    avg_hd = sum(t.get("holding_days", 0) for t in cl) / len(cl) if cl else 0

    er = {}
    for t in cl: er[t["exit_reason"]] = er.get(t["exit_reason"], 0) + 1

    return {"trades": len(cl), "tpy": len(cl) / yrs, "wr": len(w) / len(cl) * 100 if cl else 0,
            "pf": pf, "pfn": pfn, "tr": tr, "ar": tr / len(cl) if cl else 0,
            "pnl": tp, "cost": tc, "net": tp - tc, "dd": md * 100, "ms": ms,
            "ret": tp / init_eq * 100, "ann": tp / init_eq * 100 / yrs,
            "avg_hold": avg_hd, "exits": er}


if __name__ == "__main__":
    api_key = check_api_key(required=True)
    yrs = (pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25
    pairs = ["USD/JPY", "AUD/JPY"]

    scenarios = [
        {"name": "A) Baseline (1-bar expiry, no time stop)", "time_stop": None},
        {"name": "B) + Time Stop 7 days", "time_stop": 7},
        {"name": "C) + Time Stop 10 days", "time_stop": 10},
        {"name": "D) + Time Stop 5 days", "time_stop": 5},
    ]

    print(f"\n{'=' * 80}")
    print(f"OPERATIONAL RISK BACKTEST COMPARISON")
    print(f"{'=' * 80}")
    print(f"Period:   {START} ~ {END} ({yrs:.1f} years)")
    print(f"Pairs:    {', '.join(pairs)}")
    print(f"Entry:    limit offset={ENTRY_OFFSET_ATR}*ATR, 1-bar expiry")
    print(f"EMA:      [{EMA_DIST_MIN}, {EMA_DIST_MAX}]*ATR")
    print(f"TP:       TP1={TP1_R}R / TP2={TP2_R}R")
    print(f"Cost:     spread={SPREAD_R}R + slippage={SLIP_R}R")
    print(f"{'=' * 80}\n")

    # Fetch data once
    data = {}
    for pair in pairs:
        ws = (datetime.strptime(START, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        d1 = fetch_data_range(pair, "1day", ws, END, api_key)
        w1 = fetch_data_range(pair, "1week", ws, END, api_key)
        data[pair] = (d1, w1)

    # Run scenarios
    results = []
    for sc in scenarios:
        print(f"\n--- {sc['name']} ---")
        all_trades = []
        total_signals = 0
        total_fills = 0

        for pair in pairs:
            d1, w1 = data[pair]
            tr, eq, sk, sigs, fills = run(pair, d1, w1, time_stop_days=sc["time_stop"])
            total_signals += sigs
            total_fills += fills

            m = metrics(tr, EQUITY, yrs)
            print(f"  [{pair}] Trades={m['trades']}  WR={m['wr']:.1f}%  "
                  f"PFg={m['pf']:.2f}  PFn={m['pfn']:.2f}  "
                  f"R={m['tr']:+.1f}  DD={m['dd']:.2f}%  "
                  f"AvgHold={m['avg_hold']:.1f}d  Exits={m['exits']}")
            all_trades.extend(tr)

        m = metrics(all_trades, EQUITY * len(pairs), yrs)
        fill_rate = total_fills / total_signals * 100 if total_signals > 0 else 0
        results.append({
            "name": sc["name"],
            "time_stop": sc["time_stop"],
            "m": m,
            "signals": total_signals,
            "fills": total_fills,
            "fill_rate": fill_rate,
        })

    # Summary comparison table
    print(f"\n\n{'=' * 80}")
    print(f"COMPARISON SUMMARY (Combined {len(pairs)} pairs)")
    print(f"{'=' * 80}")
    print(f"{'Scenario':<42} {'Trades':>6} {'Fill%':>6} {'WR%':>5} "
          f"{'PFg':>5} {'PFn':>5} {'TotR':>6} {'DD%':>6} {'AvgHD':>6} {'MaxL':>5}")
    print("-" * 100)
    for r in results:
        m = r["m"]
        print(f"{r['name']:<42} {m['trades']:>6} {r['fill_rate']:>5.1f}% {m['wr']:>4.1f}% "
              f"{m['pf']:>5.2f} {m['pfn']:>5.2f} {m['tr']:>+5.1f} {m['dd']:>5.2f}% "
              f"{m['avg_hold']:>5.1f}d {m['ms']:>5}")
    print()

    # Exit reason breakdown
    print(f"\nExit Reason Breakdown:")
    print(f"{'Scenario':<42} {'SL':>5} {'BE':>5} {'TP2':>5} {'TIME':>5}")
    print("-" * 65)
    for r in results:
        ex = r["m"]["exits"]
        print(f"{r['name']:<42} {ex.get('SL', 0):>5} {ex.get('BE', 0):>5} "
              f"{ex.get('TP2', 0):>5} {ex.get('TIME_STOP', 0):>5}")
