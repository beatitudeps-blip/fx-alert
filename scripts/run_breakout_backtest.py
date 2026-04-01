"""
Breakout 単体バックテスト: USD/JPY + AUD/JPY + AUD/USD + EUR/USD
週足トレンド方向 + 日足20日高値/安値ブレイク + 翌日始値エントリー
TP1=1.5R / TP2=3.0R / spread=0.05R / slippage=0.05R / time stop=7d
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
TP1_R = 1.5
TP2_R = 3.0
SPREAD_R = 0.05
SLIP_R = 0.05
SL_ATR_BUFFER = 0.1
BREAKOUT_LOOKBACK = 20
BODY_ATR_THRESHOLD = 0.5
TIME_STOP_DAYS = 7


def _is_jpy_cross(sym: str) -> bool:
    return "JPY" in sym.replace("/", "")


def check_breakout_signal(d1, w1):
    """Breakout シグナル判定。look-ahead bias なし。"""
    if len(d1) < BREAKOUT_LOOKBACK + 5 or len(w1) < 22:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    w_ema20 = calculate_ema(w1["close"], 20)
    atr14 = calculate_atr(d1, 14)

    wc = float(w1["close"].iloc[-1])
    we = float(w_ema20.iloc[-1])
    atr = float(atr14.iloc[-1])
    if atr <= 0:
        return {"decision": "SKIP", "reason_codes": ["DATA"]}

    ws = calculate_ema_slope(w_ema20)
    wt = determine_weekly_trend(wc, we, ws)

    if wt == "WEEKLY_NEUTRAL":
        return {"decision": "SKIP", "reason_codes": ["W"]}

    close = float(d1["close"].iloc[-1])
    open_ = float(d1["open"].iloc[-1])
    today_high = float(d1["high"].iloc[-1])
    today_low = float(d1["low"].iloc[-1])

    # 当日を除く過去20本の高値/安値
    highs = d1["high"].astype(float).iloc[:-1].tail(BREAKOUT_LOOKBACK)
    lows = d1["low"].astype(float).iloc[:-1].tail(BREAKOUT_LOOKBACK)
    highest = float(highs.max())
    lowest = float(lows.min())

    body = abs(close - open_)
    body_ok = body >= BODY_ATR_THRESHOLD * atr

    side = ""
    if wt == "WEEKLY_UP" and close > highest:
        side = "BUY"
    elif wt == "WEEKLY_DOWN" and close < lowest:
        side = "SELL"

    if not side:
        return {"decision": "SKIP", "reason_codes": ["B"],
                "skip_reason": "no_breakout"}

    if not body_ok:
        return {"decision": "SKIP", "reason_codes": ["B"],
                "skip_reason": "body_too_small"}

    # SL
    if side == "BUY":
        sl = today_low - SL_ATR_BUFFER * atr
    else:
        sl = today_high + SL_ATR_BUFFER * atr

    return {
        "decision": "ENTRY_OK", "reason_codes": [], "side": side,
        "sl": sl, "risk_price": 0,  # risk calculated after entry price known
        "signal_high": today_high, "signal_low": today_low,
        "close": close, "atr": atr,
        "signal_date": str(d1["datetime"].iloc[-1]),
    }


def run(sym, d1, w1, usdjpy_d1=None):
    """Breakout バックテスト。翌日始値エントリー。"""
    trades, eq, active = [], EQUITY, None
    skips = {}
    is_jpy = _is_jpy_cross(sym)
    pending_signal = None  # シグナル日の判定結果を翌日まで保持

    for i in range(30, len(d1)):
        dt = d1["datetime"].iloc[i]
        current_open = float(d1["open"].iloc[i])

        # --- 前日のシグナルがあれば翌日始値でエントリー ---
        if pending_signal is not None and active is None:
            sig = pending_signal
            pending_signal = None

            entry = current_open
            side = sig["side"]

            if side == "BUY":
                sl = sig["sl"]
                risk = entry - sl
            else:
                sl = sig["sl"]
                risk = sl - entry

            if risk <= 0:
                skips["R"] = skips.get("R", 0) + 1
            else:
                tp1 = entry + TP1_R * risk if side == "BUY" else entry - TP1_R * risk
                tp2 = entry + TP2_R * risk if side == "BUY" else entry - TP2_R * risk

                # ポジションサイジング
                if is_jpy:
                    risk_jpy_per_unit = risk
                else:
                    usdjpy_rate = 110.0
                    if usdjpy_d1 is not None:
                        mask = usdjpy_d1["datetime"] <= dt
                        if mask.any():
                            usdjpy_rate = float(usdjpy_d1.loc[mask, "close"].iloc[-1])
                    risk_jpy_per_unit = risk * usdjpy_rate

                rj = eq * RISK_PCT
                u = rj / risk_jpy_per_unit if risk_jpy_per_unit > 0 else 0
                u = (u // 100) * 100
                if u < 100:
                    skips["SIZE"] = skips.get("SIZE", 0) + 1
                else:
                    arj = u * risk_jpy_per_unit
                    cost = arj * (SPREAD_R + SLIP_R)
                    active = {
                        "symbol": sym, "side": side, "entry": entry,
                        "sl": sl, "tp1": tp1, "tp2": tp2,
                        "csl": sl, "risk_price": risk,
                        "rj": arj, "cost": cost, "units": u,
                        "risk_jpy_per_unit": risk_jpy_per_unit,
                        "entry_date": str(dt),
                        "tp1d": False, "tp1p": 0.0, "holding_days": 0,
                    }

        # --- アクティブポジション管理 ---
        if active:
            h = float(d1["high"].iloc[i])
            l = float(d1["low"].iloc[i])
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

            time_stopped = (TIME_STOP_DAYS and active["holding_days"] >= TIME_STOP_DAYS
                            and not sl_hit and not tp1_hit and not tp2_hit)

            if sl_hit and not active["tp1d"]:
                pnl = -active["rj"]
                eq += pnl
                active.update(exit_date=str(dt), exit_reason="SL", pnl=pnl, pnl_r=-1.0)
                trades.append(active); active = None
            elif sl_hit and active["tp1d"]:
                # TP1後SLヒット: SL = entry ∓ 0.5R
                if s == "BUY":
                    exit_pnl_per_unit = active["csl"] - active["entry"]
                else:
                    exit_pnl_per_unit = active["entry"] - active["csl"]
                pnl_r_remaining = exit_pnl_per_unit / active["risk_price"] if active["risk_price"] > 0 else 0
                pnl = active["units"] * 0.5 * exit_pnl_per_unit
                if not is_jpy and usdjpy_d1 is not None:
                    mask = usdjpy_d1["datetime"] <= dt
                    if mask.any():
                        pnl *= float(usdjpy_d1.loc[mask, "close"].iloc[-1])
                total_pnl = active["tp1p"] + pnl
                total_r = TP1_R * 0.5 + pnl_r_remaining * 0.5
                eq += pnl
                active.update(exit_date=str(dt), exit_reason="BE", pnl=total_pnl, pnl_r=total_r)
                trades.append(active); active = None
            elif tp1_hit:
                p = active["rj"] * TP1_R * 0.5
                eq += p
                # TP1後、SLを -0.5R に移動
                if s == "BUY":
                    active["csl"] = active["entry"] - 0.5 * active["risk_price"]
                else:
                    active["csl"] = active["entry"] + 0.5 * active["risk_price"]
                active["tp1d"], active["tp1p"] = True, p
            elif tp2_hit:
                p = active["rj"] * TP2_R * 0.5
                eq += p
                total = active["tp1p"] + p
                active.update(exit_date=str(dt), exit_reason="TP2",
                              pnl=total, pnl_r=TP1_R*0.5 + TP2_R*0.5)
                trades.append(active); active = None
            elif time_stopped:
                if s == "BUY":
                    exit_pnl_per_unit = c - active["entry"]
                else:
                    exit_pnl_per_unit = active["entry"] - c
                pnl_r = exit_pnl_per_unit / active["risk_price"] if active["risk_price"] > 0 else 0
                if active["tp1d"]:
                    pnl = active["units"] * 0.5 * exit_pnl_per_unit
                    if not is_jpy and usdjpy_d1 is not None:
                        mask = usdjpy_d1["datetime"] <= dt
                        if mask.any():
                            pnl *= float(usdjpy_d1.loc[mask, "close"].iloc[-1])
                    total_pnl = active["tp1p"] + pnl
                    total_r = TP1_R * 0.5 + pnl_r * 0.5
                else:
                    total_pnl = active["units"] * exit_pnl_per_unit
                    if not is_jpy and usdjpy_d1 is not None:
                        mask = usdjpy_d1["datetime"] <= dt
                        if mask.any():
                            total_pnl *= float(usdjpy_d1.loc[mask, "close"].iloc[-1])
                    total_r = pnl_r
                eq += (total_pnl - active["tp1p"] if active["tp1d"] else total_pnl)
                active.update(exit_date=str(dt), exit_reason="TIME_STOP",
                              pnl=total_pnl, pnl_r=total_r)
                trades.append(active); active = None
            continue

        # --- シグナル判定（翌日エントリーのため保持のみ） ---
        monday = dt - pd.Timedelta(days=dt.weekday())
        w1s = w1[w1["datetime"] < monday]

        sig = check_breakout_signal(d1.iloc[:i+1], w1s)
        if sig["decision"] == "ENTRY_OK":
            # 翌日始値でエントリーするため、i+1 が存在するか確認
            if i + 1 < len(d1):
                pending_signal = sig
            else:
                skips["LAST_BAR"] = skips.get("LAST_BAR", 0) + 1
        elif sig["decision"] == "SKIP":
            for r in sig["reason_codes"]:
                skips[r] = skips.get(r, 0) + 1

    if active:
        active.update(exit_date=str(d1["datetime"].iloc[-1]),
                      exit_reason="OPEN", pnl=0, pnl_r=0)
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

    avg_hd = sum(t.get("holding_days", 0) for t in cl) / len(cl) if cl else 0

    return {"trades": len(cl), "tpy": len(cl)/yrs if yrs > 0 else 0,
            "wr": len(w)/len(cl)*100 if cl else 0,
            "pf": pf, "pfn": pfn, "tr": tr, "ar": tr/len(cl) if cl else 0,
            "pnl": tp, "cost": tc, "net": tp-tc, "dd": md*100, "ms": ms,
            "ret": tp/init_eq*100, "ann": tp/init_eq*100/yrs if yrs > 0 else 0,
            "avg_hold": avg_hd}


if __name__ == "__main__":
    api_key = check_api_key(required=True)
    yrs = (pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25
    pairs = ["USD/JPY", "AUD/JPY", "EUR/USD", "AUD/USD"]

    print(f"\n{'='*80}")
    print(f"BREAKOUT BACKTEST - D1_W1_BREAKOUT_V1")
    print(f"{'='*80}")
    print(f"Period:    {START} ~ {END} ({yrs:.1f} years)")
    print(f"Pairs:     {', '.join(pairs)}")
    print(f"Lookback:  {BREAKOUT_LOOKBACK} days")
    print(f"Body:      >= {BODY_ATR_THRESHOLD} ATR")
    print(f"Entry:     next day open")
    print(f"TP:        TP1={TP1_R}R / TP2={TP2_R}R")
    print(f"SL:        signal high/low ± {SL_ATR_BUFFER} ATR")
    print(f"TimeStop:  {TIME_STOP_DAYS} days")
    print(f"Cost:      spread={SPREAD_R}R + slippage={SLIP_R}R")
    print(f"Risk:      {RISK_PCT*100:.1f}%")
    print(f"Equity:    {EQUITY:,.0f} JPY")
    print(f"{'='*80}\n")

    ws = (datetime.strptime(START, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
    usdjpy_d1 = fetch_data_range("USD/JPY", "1day", ws, END, api_key)
    print(f"USDJPY reference data: {len(usdjpy_d1)} bars\n")

    all_trades = []
    for pair in pairs:
        d1 = fetch_data_range(pair, "1day", ws, END, api_key)
        w1 = fetch_data_range(pair, "1week", ws, END, api_key)

        tr, eq, sk = run(pair, d1, w1,
                         usdjpy_d1=usdjpy_d1 if not _is_jpy_cross(pair) else None)
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
        print(f"  Avg Hold:   {m['avg_hold']:.1f} days")
        print(f"  Exits:      {er}")
        print(f"  Skips:      {sk}")
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
    print(f"  Avg Hold:   {m['avg_hold']:.1f} days")
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
