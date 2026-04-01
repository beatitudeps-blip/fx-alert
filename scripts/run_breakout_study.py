"""
Breakout パラメータ探索: lookback / body_threshold / TP1後SL / TP比率
素のBreakoutが不採算だったため、改善の余地を調べる。
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
)
import pandas as pd

load_dotenv_if_exists()

START = "2015-01-01"
END = "2026-02-14"
EQUITY = 500000.0
RISK_PCT = 0.005
SPREAD_R = 0.05
SLIP_R = 0.05
SL_ATR_BUFFER = 0.1
TIME_STOP_DAYS = 7


def _is_jpy_cross(sym): return "JPY" in sym.replace("/", "")


def check_signal(d1, w1, lookback, body_atr):
    if len(d1) < lookback + 5 or len(w1) < 22:
        return None
    w_ema20 = calculate_ema(w1["close"], 20)
    atr14 = calculate_atr(d1, 14)
    wc, we = float(w1["close"].iloc[-1]), float(w_ema20.iloc[-1])
    atr = float(atr14.iloc[-1])
    if atr <= 0: return None
    ws = calculate_ema_slope(w_ema20)
    wt = determine_weekly_trend(wc, we, ws)
    if wt == "WEEKLY_NEUTRAL": return None

    close = float(d1["close"].iloc[-1])
    open_ = float(d1["open"].iloc[-1])
    hi = float(d1["high"].iloc[-1])
    lo = float(d1["low"].iloc[-1])
    highs = d1["high"].astype(float).iloc[:-1].tail(lookback)
    lows = d1["low"].astype(float).iloc[:-1].tail(lookback)
    highest, lowest = float(highs.max()), float(lows.min())
    body = abs(close - open_)
    if body < body_atr * atr: return None

    side = ""
    if wt == "WEEKLY_UP" and close > highest: side = "BUY"
    elif wt == "WEEKLY_DOWN" and close < lowest: side = "SELL"
    if not side: return None

    sl = (lo - SL_ATR_BUFFER * atr) if side == "BUY" else (hi + SL_ATR_BUFFER * atr)
    return {"side": side, "sl": sl, "hi": hi, "lo": lo, "close": close, "atr": atr}


def run_bt(sym, d1, w1, usdjpy_d1, lookback, body_atr, tp1_r, tp2_r, sl_after_tp1):
    trades, eq, active = [], EQUITY, None
    is_jpy = _is_jpy_cross(sym)
    pending = None

    for i in range(30, len(d1)):
        dt = d1["datetime"].iloc[i]
        co = float(d1["open"].iloc[i])

        if pending and not active:
            sig = pending; pending = None
            entry = co; side = sig["side"]
            risk = (entry - sig["sl"]) if side == "BUY" else (sig["sl"] - entry)
            if risk <= 0: continue
            tp1 = entry + tp1_r * risk if side == "BUY" else entry - tp1_r * risk
            tp2 = entry + tp2_r * risk if side == "BUY" else entry - tp2_r * risk

            if is_jpy: rjpu = risk
            else:
                rate = 110.0
                if usdjpy_d1 is not None:
                    m = usdjpy_d1["datetime"] <= dt
                    if m.any(): rate = float(usdjpy_d1.loc[m, "close"].iloc[-1])
                rjpu = risk * rate

            rj = eq * RISK_PCT
            u = rj / rjpu if rjpu > 0 else 0
            u = (u // 100) * 100
            if u < 100: continue
            arj = u * rjpu
            cost = arj * (SPREAD_R + SLIP_R)
            active = {"sym": sym, "side": side, "entry": entry, "sl": sig["sl"],
                      "tp1": tp1, "tp2": tp2, "csl": sig["sl"], "rp": risk,
                      "rj": arj, "cost": cost, "u": u, "ed": str(dt),
                      "tp1d": False, "tp1p": 0.0, "hd": 0}

        if active:
            h, l, c = float(d1["high"].iloc[i]), float(d1["low"].iloc[i]), float(d1["close"].iloc[i])
            s = active["side"]; sl = active["csl"]; active["hd"] += 1
            sl_hit = (l <= sl) if s == "BUY" else (h >= sl)
            tp1_hit = (h >= active["tp1"]) if s == "BUY" else (l <= active["tp1"])
            tp2_hit = (h >= active["tp2"]) if s == "BUY" else (l <= active["tp2"])
            if not active["tp1d"]: tp2_hit = False
            else: tp1_hit = False
            ts = TIME_STOP_DAYS and active["hd"] >= TIME_STOP_DAYS and not sl_hit and not tp1_hit and not tp2_hit

            if sl_hit and not active["tp1d"]:
                eq -= active["rj"]; trades.append({"pnl": -active["rj"], "pnl_r": -1.0, "cost": active["cost"], "hd": active["hd"], "er": "SL", "ed": active["ed"]})
                active = None
            elif sl_hit and active["tp1d"]:
                pr = ((active["csl"] - active["entry"]) if s == "BUY" else (active["entry"] - active["csl"])) / active["rp"] if active["rp"] > 0 else 0
                p = active["u"] * 0.5 * ((active["csl"] - active["entry"]) if s == "BUY" else (active["entry"] - active["csl"]))
                if not is_jpy and usdjpy_d1 is not None:
                    m = usdjpy_d1["datetime"] <= dt
                    if m.any(): p *= float(usdjpy_d1.loc[m, "close"].iloc[-1])
                eq += p; trades.append({"pnl": active["tp1p"]+p, "pnl_r": tp1_r*0.5+pr*0.5, "cost": active["cost"], "hd": active["hd"], "er": "BE", "ed": active["ed"]})
                active = None
            elif tp1_hit:
                p = active["rj"] * tp1_r * 0.5; eq += p
                if s == "BUY": active["csl"] = active["entry"] + sl_after_tp1 * active["rp"]
                else: active["csl"] = active["entry"] - sl_after_tp1 * active["rp"]
                active["tp1d"], active["tp1p"] = True, p
            elif tp2_hit:
                p = active["rj"] * tp2_r * 0.5; eq += p
                trades.append({"pnl": active["tp1p"]+p, "pnl_r": tp1_r*0.5+tp2_r*0.5, "cost": active["cost"], "hd": active["hd"], "er": "TP2", "ed": active["ed"]})
                active = None
            elif ts:
                epu = (c - active["entry"]) if s == "BUY" else (active["entry"] - c)
                pr = epu / active["rp"] if active["rp"] > 0 else 0
                if active["tp1d"]:
                    p = active["u"] * 0.5 * epu
                    if not is_jpy and usdjpy_d1 is not None:
                        m = usdjpy_d1["datetime"] <= dt
                        if m.any(): p *= float(usdjpy_d1.loc[m, "close"].iloc[-1])
                    eq += p; trades.append({"pnl": active["tp1p"]+p, "pnl_r": tp1_r*0.5+pr*0.5, "cost": active["cost"], "hd": active["hd"], "er": "TS", "ed": active["ed"]})
                else:
                    p = active["u"] * epu
                    if not is_jpy and usdjpy_d1 is not None:
                        m = usdjpy_d1["datetime"] <= dt
                        if m.any(): p *= float(usdjpy_d1.loc[m, "close"].iloc[-1])
                    eq += p; trades.append({"pnl": p, "pnl_r": pr, "cost": active["cost"], "hd": active["hd"], "er": "TS", "ed": active["ed"]})
                active = None
            continue

        monday = dt - pd.Timedelta(days=dt.weekday())
        w1s = w1[w1["datetime"] < monday]
        sig = check_signal(d1.iloc[:i+1], w1s, lookback, body_atr)
        if sig and i + 1 < len(d1):
            pending = sig

    return trades


def calc_metrics(trades, init_eq):
    if not trades: return {"n": 0, "wr": 0, "pfn": 0, "tr": 0, "dd": 0, "ah": 0}
    w = [t for t in trades if t["pnl"] > 0]
    lo = [t for t in trades if t["pnl"] < 0]
    gw = sum(t["pnl"] for t in w)
    gl = abs(sum(t["pnl"] for t in lo))
    tc = sum(t["cost"] for t in trades)
    pfn = (gw - tc*0.5) / (gl + tc*0.5) if (gl + tc*0.5) > 0 else 0
    tr = sum(t["pnl_r"] for t in trades)
    pk, md, eq = init_eq, 0, init_eq
    for t in trades:
        eq += t["pnl"] - t["cost"]
        if eq > pk: pk = eq
        dd = (pk - eq) / pk if pk > 0 else 0; md = max(md, dd)
    ah = sum(t["hd"] for t in trades) / len(trades)
    return {"n": len(trades), "wr": len(w)/len(trades)*100, "pfn": pfn, "tr": tr, "dd": md*100, "ah": ah}


if __name__ == "__main__":
    api_key = check_api_key(required=True)
    yrs = (pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25
    pairs = ["USD/JPY", "AUD/JPY"]  # まずJPYクロスのみ

    ws = (datetime.strptime(START, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    usdjpy_d1 = fetch_data_range("USD/JPY", "1day", ws, END, api_key)

    data = {}
    for pair in pairs:
        d1 = fetch_data_range(pair, "1day", ws, END, api_key)
        w1 = fetch_data_range(pair, "1week", ws, END, api_key)
        data[pair] = (d1, w1)

    # パラメータグリッド
    configs = [
        # (label, lookback, body_atr, tp1_r, tp2_r, sl_after_tp1)
        ("Base(20,0.5,1.5/3.0,BE)",  20, 0.5, 1.5, 3.0, 0.0),
        ("LB10",                      10, 0.5, 1.5, 3.0, 0.0),
        ("LB30",                      30, 0.5, 1.5, 3.0, 0.0),
        ("Body0.3",                   20, 0.3, 1.5, 3.0, 0.0),
        ("Body0.7",                   20, 0.7, 1.5, 3.0, 0.0),
        ("TP1=2R/TP2=4R",            20, 0.5, 2.0, 4.0, 0.0),
        ("TP1=1R/TP2=2R",            20, 0.5, 1.0, 2.0, 0.0),
        ("SL_after_TP1=-0.5R",       20, 0.5, 1.5, 3.0, -0.5),
        ("SL_after_TP1=+0.5R",       20, 0.5, 1.5, 3.0, 0.5),
        ("LB10+Body0.3",             10, 0.3, 1.5, 3.0, 0.0),
        ("LB10+TP1=1R/TP2=2R",       10, 0.5, 1.0, 2.0, 0.0),
        ("LB10+Body0.7+TP2=2R",      10, 0.7, 1.0, 2.0, 0.0),
    ]

    print(f"{'Config':<30} {'N':>5} {'WR%':>6} {'PFn':>6} {'TotalR':>8} {'DD%':>6} {'AvgH':>5}")
    print("-" * 72)

    for label, lb, ba, t1, t2, sltp1 in configs:
        all_tr = []
        for pair in pairs:
            d1, w1 = data[pair]
            tr = run_bt(pair, d1, w1, usdjpy_d1 if not _is_jpy_cross(pair) else None,
                        lb, ba, t1, t2, sltp1)
            all_tr.extend(tr)
        m = calc_metrics(all_tr, EQUITY * len(pairs))
        print(f"{label:<30} {m['n']:>5} {m['wr']:>5.1f}% {m['pfn']:>5.2f} {m['tr']:>+7.1f} {m['dd']:>5.2f} {m['ah']:>5.1f}")
