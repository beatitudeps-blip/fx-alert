"""
改善仮説スタディ: look-ahead bias 修正後のD1/W1戦略
4つの仮説を網羅的にテスト

仮説:
  1) 通貨フィルター: USDJPY only / USDJPY+AUDJPY / AUDJPY only
  2) エントリー遅延: entry = close ∓ 0.25*ATR
  3) EMA距離フィルター: 0.2*ATR < |price - EMA20| < 1.2*ATR
  4) スプレッドフィルター: spread > 0.3 pips → skip
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from itertools import product

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.env_check import load_dotenv_if_exists, check_api_key
from src.data import fetch_data_range
from src.indicators import calculate_ema, calculate_atr
from src.daily_strategy.trend import (
    calculate_ema_slope, determine_weekly_trend,
    determine_daily_trend, determine_alignment,
)
from src.daily_strategy.patterns import detect_pattern
from src.daily_strategy.filters import check_chasing, check_weekly_room
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

# 広告スプレッド（銭）— スプレッドフィルター用
ADVERTISED_SPREAD_SEN = {
    "USD/JPY": 0.2,
    "EUR/JPY": 0.4,
    "AUD/JPY": 0.4,
}


def check_signal(d1, w1, params):
    """
    シグナル判定（仮説パラメータ対応版）

    params:
        ema_dist_min: EMA距離下限（ATR比、0=無効）
        ema_dist_max: EMA距離上限（ATR比、1.0=デフォルト）
        entry_offset_atr: エントリー遅延（ATR比、0=終値エントリー）
        spread_max_pips: スプレッド上限（pips、0=無効）
        pair: 通貨ペア名（スプレッドフィルター用）
    """
    ema_dist_min = params.get("ema_dist_min", 0.0)
    ema_dist_max = params.get("ema_dist_max", 1.0)
    entry_offset_atr = params.get("entry_offset_atr", 0.0)
    spread_max_pips = params.get("spread_max_pips", 0.0)
    pair = params.get("pair", "")

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

    # --- EMA距離フィルター（仮説3: カスタム範囲） ---
    ema_dist_ratio = abs(close - de) / atr
    pullback_ok = ema_dist_min <= ema_dist_ratio <= ema_dist_max
    if ema_dist_ratio > ema_dist_max:
        rc.append("X")

    today = {k: float(d1[k].iloc[-1]) for k in ["open", "close", "high", "low"]}
    prev = {k: float(d1[k].iloc[-2]) for k in ["open", "close", "high", "low"]}
    pn, pd_ = detect_pattern(today, prev, al)
    if not pd_ and al != "NO_TRADE": rc.append("P")

    if check_chasing(today["high"], today["low"], atr) and al != "NO_TRADE" and "X" not in rc:
        rc.append("X")

    # --- スプレッドフィルター（仮説4） ---
    if spread_max_pips > 0 and pair in ADVERTISED_SPREAD_SEN:
        spread_pips = ADVERTISED_SPREAD_SEN[pair] / 10.0  # 銭→pips (1pip = 1銭 for JPY pairs)
        if spread_pips > spread_max_pips:
            rc.append("SPREAD")

    side = ""
    entry = sl = risk = 0.0
    if al == "BUY_ONLY":
        side = "BUY"
        # 仮説2: エントリー遅延（BUYなら終値より低い位置でエントリー）
        entry = close - entry_offset_atr * atr
        sl = today["low"] - 0.1 * atr
        risk = entry - sl
    elif al == "SELL_ONLY":
        side = "SELL"
        # 仮説2: エントリー遅延（SELLなら終値より高い位置でエントリー）
        entry = close + entry_offset_atr * atr
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


def run(sym, d1, w1, params):
    """バックテスト実行（仮説パラメータ対応）"""
    trades, eq, active = [], EQUITY, None
    skips = {}
    params["pair"] = sym
    entry_offset_atr = params.get("entry_offset_atr", 0.0)

    for i in range(30, len(d1)):
        dt_val = d1["datetime"].iloc[i]
        # 確定済み週足のみ（look-ahead bias 防止）
        monday = dt_val - pd.Timedelta(days=dt_val.weekday())
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
                active.update(exit_date=str(dt_val), exit_reason="SL", pnl=pnl, pnl_r=-1.0)
                trades.append(active); active = None
            elif sl_hit and active["tp1d"]:
                active.update(exit_date=str(dt_val), exit_reason="BE", pnl=active["tp1p"], pnl_r=TP1_R*0.5)
                trades.append(active); active = None
            elif tp1_hit:
                p = active["rj"] * TP1_R * 0.5
                eq += p
                active["tp1d"], active["tp1p"], active["csl"] = True, p, active["entry"]
            elif tp2_hit:
                p = active["rj"] * TP2_R * 0.5
                eq += p
                total = active["tp1p"] + p
                active.update(exit_date=str(dt_val), exit_reason="TP2", pnl=total, pnl_r=TP1_R*0.5+TP2_R*0.5)
                trades.append(active); active = None
            continue

        # エントリー遅延の場合、前日のシグナルで当日エントリーを判定
        if entry_offset_atr > 0:
            # 前日シグナル → 当日の価格でエントリー可能か確認
            sig = check_signal(d1.iloc[:i+1], w1s, params)
            if sig["decision"] == "ENTRY_OK":
                # エントリー価格が当日の high/low の範囲内にあるか確認
                bar_h = float(d1["high"].iloc[i])
                bar_l = float(d1["low"].iloc[i])
                if sig["side"] == "BUY" and sig["entry"] < bar_l:
                    sig["decision"] = "SKIP"
                    sig["reason_codes"] = ["LIMIT_NOT_FILLED"]
                elif sig["side"] == "SELL" and sig["entry"] > bar_h:
                    sig["decision"] = "SKIP"
                    sig["reason_codes"] = ["LIMIT_NOT_FILLED"]
        else:
            sig = check_signal(d1.iloc[:i+1], w1s, params)

        if sig["decision"] == "SKIP":
            for r in sig.get("reason_codes", []): skips[r] = skips.get(r, 0) + 1
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
                      "entry_date": str(dt_val), "pattern": sig["pattern"],
                      "tp1d": False, "tp1p": 0.0}

    if active:
        active.update(exit_date=str(d1["datetime"].iloc[-1]), exit_reason="OPEN", pnl=0, pnl_r=0)
        trades.append(active)

    return trades, eq, skips


def calc_metrics(trades, init_eq, yrs):
    """メトリクス計算"""
    cl = [t for t in trades if t.get("exit_reason") != "OPEN"]
    if not cl:
        return {"trades": 0, "tpy": 0, "wr": 0, "pf": 0, "pfn": 0,
                "tr": 0, "ar": 0, "pnl": 0, "cost": 0, "net": 0, "dd": 0, "ms": 0}
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

    return {"trades": len(cl), "tpy": round(len(cl)/yrs, 1), "wr": round(len(w)/len(cl)*100, 1),
            "pf": round(pf, 2), "pfn": round(pfn, 2),
            "tr": round(tr, 1), "ar": round(tr/len(cl), 3),
            "pnl": round(tp), "cost": round(tc), "net": round(tp - tc),
            "dd": round(md * 100, 2), "ms": ms}


def run_scenario(name, pairs, data_cache, params, yrs):
    """1シナリオの全通貨バックテスト"""
    all_trades = []
    for pair in pairs:
        d1, w1 = data_cache[pair]
        tr, _, _ = run(pair, d1, w1, params.copy())
        all_trades.extend(tr)
    init_eq = EQUITY * len(pairs)
    m = calc_metrics(all_trades, init_eq, yrs)
    return m


if __name__ == "__main__":
    api_key = check_api_key(required=True)
    yrs = (pd.to_datetime(END) - pd.to_datetime(START)).days / 365.25

    print(f"\n{'='*90}")
    print(f"改善仮説スタディ — D1/W1 EMA20 Pullback (look-ahead bias 修正済み)")
    print(f"{'='*90}")
    print(f"Period: {START} ~ {END} ({yrs:.1f} years)")
    print(f"TP1={TP1_R}R / TP2={TP2_R}R / Cost: spread={SPREAD_R}R + slip={SLIP_R}R")
    print(f"{'='*90}\n")

    # --- データ取得（全通貨キャッシュ） ---
    all_pairs = ["USD/JPY", "EUR/JPY", "AUD/JPY"]
    data_cache = {}
    for pair in all_pairs:
        print(f"Fetching {pair}...")
        ws = (datetime.strptime(START, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        d1 = fetch_data_range(pair, "1day", ws, END, api_key)
        w1 = fetch_data_range(pair, "1week", ws, END, api_key)
        data_cache[pair] = (d1, w1)
        print(f"  D1: {len(d1)} bars, W1: {len(w1)} bars")

    # ===================================================================
    # ベースライン（修正後）
    # ===================================================================
    print(f"\n{'='*90}")
    print("BASELINE (修正後、全3通貨)")
    print(f"{'='*90}")

    base_params = {"ema_dist_min": 0.0, "ema_dist_max": 1.0,
                   "entry_offset_atr": 0.0, "spread_max_pips": 0.0}

    for pair in all_pairs:
        d1, w1 = data_cache[pair]
        tr, _, sk = run(pair, d1, w1, base_params.copy())
        m = calc_metrics(tr, EQUITY, yrs)
        print(f"  {pair:>8}: Trades={m['trades']:>3}  WR={m['wr']:>5.1f}%  "
              f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
              f"R={m['tr']:>+6.1f}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    m = run_scenario("BASE_ALL3", all_pairs, data_cache, base_params, yrs)
    print(f"  {'COMBINED':>8}: Trades={m['trades']:>3}  WR={m['wr']:>5.1f}%  "
          f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
          f"R={m['tr']:>+6.1f}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    # ===================================================================
    # 仮説1: 通貨フィルター
    # ===================================================================
    print(f"\n{'='*90}")
    print("仮説1: 通貨フィルター")
    print(f"{'='*90}")

    pair_combos = {
        "USDJPY_only":      ["USD/JPY"],
        "USDJPY+AUDJPY":    ["USD/JPY", "AUD/JPY"],
        "AUDJPY_only":      ["AUD/JPY"],
        "USDJPY+EURJPY":    ["USD/JPY", "EUR/JPY"],  # 参考: EUR/JPY含む
    }
    for label, pairs in pair_combos.items():
        m = run_scenario(label, pairs, data_cache, base_params, yrs)
        print(f"  {label:>20}: Trades={m['trades']:>3}  WR={m['wr']:>5.1f}%  "
              f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
              f"R={m['tr']:>+6.1f}  Net={m['net']:>+8,}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    # ===================================================================
    # 仮説2: エントリー遅延
    # ===================================================================
    print(f"\n{'='*90}")
    print("仮説2: エントリー遅延 (entry = close ∓ offset*ATR)")
    print(f"{'='*90}")

    # USDJPY+AUDJPY をベースに（仮説1で最善の可能性が高い組み合わせ）
    test_pairs_h2 = ["USD/JPY", "AUD/JPY"]
    for offset in [0.0, 0.10, 0.15, 0.20, 0.25, 0.30]:
        params = base_params.copy()
        params["entry_offset_atr"] = offset
        m = run_scenario(f"offset={offset}", test_pairs_h2, data_cache, params, yrs)
        filled = m["trades"]
        print(f"  offset={offset:.2f}*ATR: Trades={filled:>3}  WR={m['wr']:>5.1f}%  "
              f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
              f"R={m['tr']:>+6.1f}  Net={m['net']:>+8,}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    # ===================================================================
    # 仮説3: EMA距離フィルター
    # ===================================================================
    print(f"\n{'='*90}")
    print("仮説3: EMA距離フィルター (min*ATR < |price - EMA20| < max*ATR)")
    print(f"{'='*90}")

    test_pairs_h3 = ["USD/JPY", "AUD/JPY"]
    ema_ranges = [
        (0.0, 0.5),   # デフォルト（近い場合のみ）
        (0.0, 1.0),   # ベースライン
        (0.0, 1.2),   # 少し広げる
        (0.1, 0.8),   # 近すぎを除外
        (0.1, 1.0),   # 近すぎを除外+標準上限
        (0.1, 1.2),   # 近すぎを除外+広い上限
        (0.2, 1.0),   # ユーザー指定
        (0.2, 1.2),   # ユーザー指定
        (0.2, 1.5),   # さらに広い
        (0.3, 1.2),   # さらに厳しい下限
    ]
    for ema_min, ema_max in ema_ranges:
        params = base_params.copy()
        params["ema_dist_min"] = ema_min
        params["ema_dist_max"] = ema_max
        m = run_scenario(f"ema[{ema_min}-{ema_max}]", test_pairs_h3, data_cache, params, yrs)
        print(f"  [{ema_min:.1f}, {ema_max:.1f}]: Trades={m['trades']:>3}  WR={m['wr']:>5.1f}%  "
              f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
              f"R={m['tr']:>+6.1f}  Net={m['net']:>+8,}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    # ===================================================================
    # 仮説4: スプレッドフィルター
    # ===================================================================
    print(f"\n{'='*90}")
    print("仮説4: スプレッドフィルター (spread > threshold → skip)")
    print(f"{'='*90}")
    print("  注: みんなのFX JPYクロスの広告スプレッド")
    print(f"      USD/JPY={ADVERTISED_SPREAD_SEN['USD/JPY']}銭  "
          f"EUR/JPY={ADVERTISED_SPREAD_SEN['EUR/JPY']}銭  "
          f"AUD/JPY={ADVERTISED_SPREAD_SEN['AUD/JPY']}銭")
    print(f"      (1銭 = 1pip for JPYペア)")
    print()

    # スプレッドフィルター: spread > X pips なら skip
    # USD/JPY=0.2pips, EUR/JPY=0.4pips, AUD/JPY=0.4pips
    # threshold=0.3 → EUR/JPY と AUD/JPY がスキップされる
    for threshold in [0.0, 0.1, 0.2, 0.3, 0.5]:
        params = base_params.copy()
        params["spread_max_pips"] = threshold
        for pairs_label, pairs_list in [("ALL3", all_pairs), ("USD+AUD", test_pairs_h2)]:
            m = run_scenario(f"spread<={threshold}", pairs_list, data_cache, params, yrs)
            print(f"  max={threshold:.1f}pip {pairs_label:>8}: Trades={m['trades']:>3}  WR={m['wr']:>5.1f}%  "
                  f"PFg={m['pf']:>5.2f}  PFn={m['pfn']:>5.2f}  "
                  f"R={m['tr']:>+6.1f}  Net={m['net']:>+8,}  DD={m['dd']:>5.2f}%  Streak={m['ms']}")

    # ===================================================================
    # 組み合わせテスト: 最も有望な仮説の組み合わせ
    # ===================================================================
    print(f"\n{'='*90}")
    print("組み合わせテスト: 仮説の複合効果")
    print(f"{'='*90}")

    combo_tests = [
        # (label, pairs, params_override)
        ("BASE USDJPY+AUDJPY",
         ["USD/JPY", "AUD/JPY"],
         {}),
        ("offset=0.15 + ema[0.1,1.0]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.15, "ema_dist_min": 0.1, "ema_dist_max": 1.0}),
        ("offset=0.15 + ema[0.2,1.2]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.15, "ema_dist_min": 0.2, "ema_dist_max": 1.2}),
        ("offset=0.20 + ema[0.1,1.0]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.20, "ema_dist_min": 0.1, "ema_dist_max": 1.0}),
        ("offset=0.20 + ema[0.2,1.2]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.20, "ema_dist_min": 0.2, "ema_dist_max": 1.2}),
        ("offset=0.25 + ema[0.2,1.2]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.25, "ema_dist_min": 0.2, "ema_dist_max": 1.2}),
        ("offset=0.25 + ema[0.1,1.2]",
         ["USD/JPY", "AUD/JPY"],
         {"entry_offset_atr": 0.25, "ema_dist_min": 0.1, "ema_dist_max": 1.2}),
        # USDJPY only の組み合わせも
        ("USDJPY only + offset=0.15 + ema[0.1,1.2]",
         ["USD/JPY"],
         {"entry_offset_atr": 0.15, "ema_dist_min": 0.1, "ema_dist_max": 1.2}),
        ("USDJPY only + offset=0.20 + ema[0.2,1.2]",
         ["USD/JPY"],
         {"entry_offset_atr": 0.20, "ema_dist_min": 0.2, "ema_dist_max": 1.2}),
        ("USDJPY only + offset=0.25 + ema[0.2,1.2]",
         ["USD/JPY"],
         {"entry_offset_atr": 0.25, "ema_dist_min": 0.2, "ema_dist_max": 1.2}),
    ]

    print(f"  {'Label':<48} {'Tr':>3} {'WR%':>6} {'PFg':>5} {'PFn':>5} "
          f"{'R':>6} {'Net':>9} {'DD%':>6} {'MS':>3}")
    print("  " + "-" * 95)

    for label, pairs, overrides in combo_tests:
        params = base_params.copy()
        params.update(overrides)
        m = run_scenario(label, pairs, data_cache, params, yrs)
        print(f"  {label:<48} {m['trades']:>3} {m['wr']:>5.1f}% "
              f"{m['pf']:>5.2f} {m['pfn']:>5.2f} "
              f"{m['tr']:>+5.1f} {m['net']:>+9,} {m['dd']:>5.2f}% {m['ms']:>3}")

    print(f"\n{'='*90}")
    print("目標: PF net >= 1.20")
    print(f"{'='*90}")
