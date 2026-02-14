import os
import csv
import argparse
from dataclasses import dataclass, asdict
from datetime import timedelta

import requests
import pandas as pd

# ====== CONFIG DEFAULTS ======
PIP = 0.01  # JPY crosses: 1 pip = 0.01
JPY_PER_PIP_PER_1000U = 10.0  # 1000通貨あたり 1pip ≒ 10円（USDJPY/EURJPY/GBPJPY）

SYMBOLS_DEFAULT = ["USD/JPY", "EUR/JPY", "GBP/JPY"]


@dataclass
class Trade:
    symbol: str
    entry_time: str
    exit_time: str
    entry_price: float
    exit_price: float
    units: int
    sl: float
    tp1: float
    tp2: float
    outcome: str  # win / loss / mix / timeout
    pnl_yen: float
    r_mult: float
    bars_held: int


def fetch_ohlc_twelvedata(symbol: str, interval: str, outputsize: int, apikey: str) -> pd.DataFrame:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,  # "4h" or "1day"
        "outputsize": outputsize,
        "apikey": apikey,
        "format": "JSON",
    }
    r = requests.get(url, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    if "values" not in data:
        raise RuntimeError(f"Twelve Data error for {symbol} {interval}: {data}")

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    for c in ["open", "high", "low", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("datetime").reset_index(drop=True)
    return df


def add_ema(df: pd.DataFrame, period: int, src: str = "close", out: str = "ema") -> pd.DataFrame:
    df = df.copy()
    df[out] = df[src].ewm(span=period, adjust=False).mean()
    return df


def add_atr(df: pd.DataFrame, period: int = 14, out: str = "atr") -> pd.DataFrame:
    df = df.copy()
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    df["tr"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # Welles Wilder smoothing (EMA alpha=1/period)
    df[out] = df["tr"].ewm(alpha=1 / period, adjust=False).mean()
    return df


def make_daily_env(d1: pd.DataFrame) -> pd.DataFrame:
    d1 = add_ema(d1, 20, out="ema20_d1")
    d1["env_ok"] = (d1["close"] > d1["ema20_d1"]) & (d1["ema20_d1"] > d1["ema20_d1"].shift(1))
    return d1[["datetime", "env_ok", "ema20_d1"]]


def attach_env_to_h4(h4: pd.DataFrame, d1_env: pd.DataFrame) -> pd.DataFrame:
    h4 = h4.copy().sort_values("datetime")
    d1_env = d1_env.copy().sort_values("datetime")
    out = pd.merge_asof(h4, d1_env, on="datetime", direction="backward")
    out["env_ok"] = out["env_ok"].fillna(False)
    return out


def bullish_engulfing(prev_open, prev_close, open_, close_) -> bool:
    # 前足が陰線、当足が陽線、実体で包む（厳しめ）
    return (prev_close < prev_open) and (close_ > open_) and (close_ >= prev_open) and (open_ <= prev_close)


def bullish_hammer(open_, high, low, close_) -> bool:
    # 陽線＋下ヒゲが長い（数式で固定）
    body = abs(close_ - open_)
    if body <= 0:
        return False
    lower = min(open_, close_) - low
    upper = high - max(open_, close_)
    return (close_ > open_) and (lower >= body * 1.5) and (lower >= upper * 2.0)


def add_trigger_and_signal(h4: pd.DataFrame) -> pd.DataFrame:
    h4 = add_ema(h4, 20, out="ema20_h4")
    h4 = add_atr(h4, 14, out="atr14")

    # EMAタッチ（レンジ誤発火を減らすため「触れる」定義）
    h4["touch_ema"] = (h4["low"] <= h4["ema20_h4"]) & (h4["high"] >= h4["ema20_h4"])

    # トリガー（確定足）
    prev_o = h4["open"].shift(1)
    prev_c = h4["close"].shift(1)

    h4["engulf"] = (
        (prev_c < prev_o) &
        (h4["close"] > h4["open"]) &
        (h4["close"] >= prev_o) &
        (h4["open"] <= prev_c)
    )

    # hammerはベクトル化しにくいのでapply（本数は最大でも数千）
    h4["hammer"] = h4.apply(lambda r: bullish_hammer(r["open"], r["high"], r["low"], r["close"]), axis=1)

    h4["trigger"] = h4["engulf"] | h4["hammer"]

    # シグナル：日足環境OK＋EMAタッチ＋トリガー＋ATR有効
    h4["signal"] = h4["env_ok"] & h4["touch_ema"] & h4["trigger"] & h4["atr14"].notna()
    return h4


def filter_last_days(df: pd.DataFrame, days: int) -> pd.DataFrame:
    end = df["datetime"].max()
    start = end - timedelta(days=days)
    return df[df["datetime"] >= start].reset_index(drop=True)


def calc_units_jpy(risk_yen: float, sl_pips: float) -> int:
    # units = risk / (sl_pips * (yen per pip per unit))
    # yen per pip per 1000 units ≒ 10円
    if sl_pips <= 0:
        return 0
    units = risk_yen / (sl_pips * (JPY_PER_PIP_PER_1000U / 1000.0))  # yen per pip per 1 unit
    # 1000通貨単位で切り下げ（保守的）
    units_rounded = int(units // 1000 * 1000)
    return max(units_rounded, 0)


def yen_pnl_from_pips(pips: float, units: int) -> float:
    return pips * (units / 1000.0) * JPY_PER_PIP_PER_1000U


def backtest_symbol(
    h4: pd.DataFrame,
    symbol: str,
    initial_yen: float,
    risk_pct: float,
    spread_pips: float,
    atr_mult_sl: float,
    entry_mode: str = "next_open",
) -> tuple[list[Trade], pd.DataFrame]:
    """
    戦略：
    - Entry: signal発生足の次足open（既定）
    - SL: entry - atr_mult_sl * ATR
    - TP1: +1R 半分決済
    - TP2: +2R 残り決済
    - 同一足でSL/TP同時到達はSL優先（保守）
    - スプレッド：ロングでentryを不利に（open + spread）
    """
    trades: list[Trade] = []
    equity = initial_yen
    equity_curve = []

    i = 0
    while i < len(h4) - 2:
        row = h4.iloc[i]
        if not bool(row["signal"]):
            equity_curve.append({"datetime": row["datetime"], "equity_yen": equity, "symbol": symbol})
            i += 1
            continue

        # --- Entry ---
        entry_idx = i if entry_mode == "close" else i + 1
        entry_bar = h4.iloc[entry_idx]
        entry_time = str(entry_bar["datetime"])

        atr = float(h4.iloc[i]["atr14"])
        if not (atr > 0):
            equity_curve.append({"datetime": row["datetime"], "equity_yen": equity, "symbol": symbol})
            i += 1
            continue

        entry_price = float(entry_bar["open"] if entry_mode != "close" else row["close"])
        entry_price = entry_price + (spread_pips * PIP)  # askで買う想定（保守）

        sl_price = entry_price - (atr_mult_sl * atr)
        r_dist = entry_price - sl_price
        sl_pips = r_dist / PIP
        if sl_pips <= 0:
            equity_curve.append({"datetime": row["datetime"], "equity_yen": equity, "symbol": symbol})
            i += 1
            continue

        risk_yen = equity * risk_pct
        units = calc_units_jpy(risk_yen, sl_pips)
        if units < 1000:
            # リスクが小さすぎて最小単位で建てられない
            equity_curve.append({"datetime": row["datetime"], "equity_yen": equity, "symbol": symbol})
            i += 1
            continue

        tp1 = entry_price + 1.0 * r_dist
        tp2 = entry_price + 2.0 * r_dist

        # --- Walk forward ---
        half_units = units // 2  # 端数切り下げ（保守）。残りは units - half_units
        rest_units = units - half_units

        tp1_done = False
        realized_yen = 0.0
        exit_time = None
        exit_price = None
        outcome = None
        bars_held = 0

        # 開始バーはentry_idxから
        k = entry_idx
        while k < len(h4):
            bar = h4.iloc[k]
            hi = float(bar["high"])
            lo = float(bar["low"])
            bars_held = k - entry_idx + 1

            hit_sl = lo <= sl_price
            hit_tp1 = hi >= tp1
            hit_tp2 = hi >= tp2

            # --- Before TP1 ---
            if not tp1_done:
                if hit_sl and hit_tp1:
                    # 保守：SL優先 → 全量SL
                    pips = (sl_price - entry_price) / PIP
                    pnl = yen_pnl_from_pips(pips, units)
                    equity += pnl
                    exit_time = str(bar["datetime"])
                    exit_price = sl_price
                    outcome = "loss"
                    realized_yen = pnl
                    break
                if hit_sl:
                    pips = (sl_price - entry_price) / PIP
                    pnl = yen_pnl_from_pips(pips, units)
                    equity += pnl
                    exit_time = str(bar["datetime"])
                    exit_price = sl_price
                    outcome = "loss"
                    realized_yen = pnl
                    break
                if hit_tp1:
                    # 半分利確
                    pips_half = (tp1 - entry_price) / PIP  # = +1R pips
                    pnl_half = yen_pnl_from_pips(pips_half, half_units)
                    equity += pnl_half
                    realized_yen += pnl_half
                    tp1_done = True

                    # TP1当たったバーの時刻は覚えておく（ただしtradeのexitは最終決済時刻）
                    # 以降は残り半分をTP2/SLで追う

                    # ただし同一足でTP2も同時に到達していたら、残りもTP2で即決済（保守的にTP2優先でもOKだが、ここはTP2優先＝自然）
                    if hit_tp2:
                        pips_rest = (tp2 - entry_price) / PIP
                        pnl_rest = yen_pnl_from_pips(pips_rest, rest_units)
                        equity += pnl_rest
                        realized_yen += pnl_rest
                        exit_time = str(bar["datetime"])
                        exit_price = tp2
                        outcome = "win"
                        break

                    k += 1
                    continue

            # --- After TP1 ---
            else:
                if hit_sl and hit_tp2:
                    # 同一足で両方：保守 SL 優先（残り半分）
                    pips_rest = (sl_price - entry_price) / PIP
                    pnl_rest = yen_pnl_from_pips(pips_rest, rest_units)
                    equity += pnl_rest
                    realized_yen += pnl_rest
                    exit_time = str(bar["datetime"])
                    exit_price = sl_price
                    outcome = "mix"
                    break
                if hit_sl:
                    pips_rest = (sl_price - entry_price) / PIP
                    pnl_rest = yen_pnl_from_pips(pips_rest, rest_units)
                    equity += pnl_rest
                    realized_yen += pnl_rest
                    exit_time = str(bar["datetime"])
                    exit_price = sl_price
                    outcome = "mix"
                    break
                if hit_tp2:
                    pips_rest = (tp2 - entry_price) / PIP
                    pnl_rest = yen_pnl_from_pips(pips_rest, rest_units)
                    equity += pnl_rest
                    realized_yen += pnl_rest
                    exit_time = str(bar["datetime"])
                    exit_price = tp2
                    outcome = "win"
                    break

            k += 1

        # 終端まで未決済なら最終クローズで全決済（便宜）
        if exit_time is None:
            last = h4.iloc[-1]
            close = float(last["close"])
            # exitはbid想定だが、ここでは保守でスプレッド控除なし（entryで既に不利にしている）
            pips_total = (close - entry_price) / PIP
            pnl_total = yen_pnl_from_pips(pips_total, units)
            equity += pnl_total
            realized_yen = pnl_total
            exit_time = str(last["datetime"])
            exit_price = close
            outcome = "timeout"
            bars_held = len(h4) - entry_idx

        # R倍率（建玉時の想定リスク円で割る）
        r_mult = realized_yen / risk_yen if risk_yen > 0 else 0.0

        trades.append(
            Trade(
                symbol=symbol,
                entry_time=entry_time,
                exit_time=exit_time,
                entry_price=entry_price,
                exit_price=float(exit_price),
                units=int(units),
                sl=float(sl_price),
                tp1=float(tp1),
                tp2=float(tp2),
                outcome=str(outcome),
                pnl_yen=float(realized_yen),
                r_mult=float(r_mult),
                bars_held=int(bars_held),
            )
        )

        # エントリーの次バーから探索続行（重複を抑える）
        # （ポジション同時保有はしない設計）
        i = entry_idx + 1

    # equity curve：最後まで埋める
    if len(equity_curve) == 0 or equity_curve[-1]["datetime"] != h4.iloc[-1]["datetime"]:
        for j in range(max(0, i), len(h4)):
            equity_curve.append({"datetime": h4.iloc[j]["datetime"], "equity_yen": equity, "symbol": symbol})

    return trades, pd.DataFrame(equity_curve)


def stats_from_trades(trades: list[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {
            "trades": 0,
            "win_rate_%": 0.0,
            "profit_factor": 0.0,
            "net_yen": 0.0,
            "gross_profit_yen": 0.0,
            "gross_loss_yen": 0.0,
            "max_drawdown_yen": 0.0,
            "avg_r": 0.0,
            "avg_pnl_yen": 0.0,
        }

    pnls = [t.pnl_yen for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [-p for p in pnls if p < 0]  # positive numbers

    win_rate = (len(wins) / n) * 100.0
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net = sum(pnls)
    pf = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    # drawdown from trade-by-trade equity (yen)
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = peak - eq
        max_dd = max(max_dd, dd)

    avg_r = sum(t.r_mult for t in trades) / n
    avg_pnl = net / n

    return {
        "trades": n,
        "win_rate_%": round(win_rate, 2),
        "profit_factor": ("inf" if pf == float("inf") else round(pf, 2)),
        "net_yen": round(net, 0),
        "gross_profit_yen": round(gross_profit, 0),
        "gross_loss_yen": round(gross_loss, 0),
        "max_drawdown_yen": round(max_dd, 0),
        "avg_r": round(avg_r, 3),
        "avg_pnl_yen": round(avg_pnl, 0),
    }


def write_trades_csv(trades: list[Trade], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(trades[0]).keys()) if trades else [])
        if trades:
            w.writeheader()
            for t in trades:
                w.writerow(asdict(t))


def write_equity_csv(eq: pd.DataFrame, path: str) -> None:
    eq = eq.copy()
    eq["datetime"] = eq["datetime"].astype(str)
    eq.to_csv(path, index=False, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=720)
    ap.add_argument("--symbols", type=str, default=",".join(SYMBOLS_DEFAULT))
    ap.add_argument("--initial-yen", type=float, default=436000.0)
    ap.add_argument("--risk-pct", type=float, default=0.005)  # 0.5%
    ap.add_argument("--spread-pips", type=float, default=0.3)  # 0.3pips（保守）
    ap.add_argument("--atr-mult-sl", type=float, default=1.5)
    ap.add_argument("--entry-mode", choices=["next_open", "close"], default="next_open")
    ap.add_argument("--trades-csv", type=str, default="trades_v2.csv")
    ap.add_argument("--equity-csv", type=str, default="equity_v2.csv")
    ap.add_argument("--outputsize-h4", type=int, default=5000)
    ap.add_argument("--outputsize-d1", type=int, default=1500)
    args = ap.parse_args()

    apikey = os.environ.get("TWELVEDATA_API_KEY", "8c92b81341dd4e3794deaa30fcea7bc9")

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    all_trades: list[Trade] = []
    equity_frames = []

    print("=== BACKTEST V2 (ATR-adaptive Trend Follow, partial exits) ===")
    print(f"days={args.days} initial_yen={args.initial_yen:.0f} risk_pct={args.risk_pct} "
          f"spread_pips={args.spread_pips} atr_mult_sl={args.atr_mult_sl} entry_mode={args.entry_mode}")
    print(f"symbols={symbols}")

    for sym in symbols:
        # fetch
        h4 = fetch_ohlc_twelvedata(sym, "4h", args.outputsize_h4, apikey)
        d1 = fetch_ohlc_twelvedata(sym, "1day", args.outputsize_d1, apikey)

        # env + signal
        d1_env = make_daily_env(d1)
        h4 = attach_env_to_h4(h4, d1_env)
        h4 = add_trigger_and_signal(h4)

        # window
        h4 = filter_last_days(h4, args.days)

        # backtest (symbol equity reset is NOT desired; for simplicity each symbol is evaluated independently here)
        trades, eq = backtest_symbol(
            h4=h4,
            symbol=sym,
            initial_yen=args.initial_yen,
            risk_pct=args.risk_pct,
            spread_pips=args.spread_pips,
            atr_mult_sl=args.atr_mult_sl,
            entry_mode=args.entry_mode,
        )

        s = stats_from_trades(trades)
        print(f"\n--- {sym} ---")
        for k, v in s.items():
            print(f"{k}: {v}")

        all_trades.extend(trades)
        equity_frames.append(eq)

    # combined stats (円損益の合算のみ＝シンボル別独立運用の"参考合算")
    print("\n=== COMBINED (reference) ===")
    s_all = stats_from_trades(all_trades)
    for k, v in s_all.items():
        print(f"{k}: {v}")

    # write outputs
    if all_trades:
        write_trades_csv(all_trades, args.trades_csv)
        print(f"\ntrades csv: {args.trades_csv}")
    else:
        print("\nNo trades -> trades csv not written.")

    if equity_frames:
        eq_all = pd.concat(equity_frames, ignore_index=True)
        write_equity_csv(eq_all, args.equity_csv)
        print(f"equity csv: {args.equity_csv}")


if __name__ == "__main__":
    main()
