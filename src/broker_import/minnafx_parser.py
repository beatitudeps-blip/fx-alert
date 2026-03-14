"""
みんなのFX 約定履歴CSV パーサー
data_spec.md セクション5 準拠

入力CSV列:
  通貨ペア, 区分, 売買, 数量, 約定価格, 建玉損益, 累計スワップ,
  手数料, 決済損益, 約定日時, 取引番号, 決済対象取引番号
"""
import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
UTC = timezone.utc

# 対象通貨ペア (戦略対象)
STRATEGY_PAIRS = {"USDJPY", "EURJPY", "GBPJPY"}

# --- 通貨ペア正規化 ---
_PAIR_CLEANUP_RE = re.compile(r"\s*(LIGHT|ライト|light)\s*", re.IGNORECASE)


def normalize_pair(raw_pair: str) -> str:
    """通貨ペアを正規化する。

    例: "EURJPY LIGHT" → "EURJPY"
        "USD/JPY" → "USDJPY"
    """
    s = raw_pair.strip()
    s = _PAIR_CLEANUP_RE.sub("", s)
    s = s.replace("/", "").replace(" ", "").upper()
    return s


# --- 数値正規化 ---

def normalize_numeric(value: str) -> Optional[float]:
    """数値列を正規化する。`-` や空欄は None を返す。"""
    s = value.strip()
    if s in ("", "-", "－"):
        return None
    s = s.replace(",", "")
    return float(s)


# --- 売買方向 ---

_SIDE_MAP = {"買": "BUY", "売": "SELL", "BUY": "BUY", "SELL": "SELL"}


def normalize_side(raw_side: str) -> str:
    s = raw_side.strip()
    mapped = _SIDE_MAP.get(s)
    if mapped is None:
        raise ValueError(f"不明な売買方向: {raw_side!r}")
    return mapped


# --- 区分 → fill_type ---

_TYPE_MAP = {"新規": "ENTRY", "決済": "EXIT"}


def normalize_fill_type(raw_kubun: str) -> str:
    s = raw_kubun.strip()
    mapped = _TYPE_MAP.get(s)
    if mapped is None:
        raise ValueError(f"不明な区分: {raw_kubun!r}")
    return mapped


# --- 約定日時パース ---

_DT_FORMATS = [
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%d %H:%M",
]


def parse_execution_time(raw_dt: str) -> Tuple[datetime, datetime]:
    """約定日時をパースし (utc, jst) のタプルで返す。

    入力はJSTとして解釈する。
    """
    s = raw_dt.strip()
    for fmt in _DT_FORMATS:
        try:
            dt_naive = datetime.strptime(s, fmt)
            dt_jst = dt_naive.replace(tzinfo=JST)
            dt_utc = dt_jst.astimezone(UTC)
            return dt_utc, dt_jst
        except ValueError:
            continue
    raise ValueError(f"約定日時のパースに失敗: {raw_dt!r}")


# --- fill_id 生成 ---

def build_fill_id(pair: str, exec_utc: datetime, side: str, quantity: float, price: float) -> str:
    """fill_id を生成する。data_spec.md 5.5 準拠。"""
    ts = exec_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    qty_str = f"{quantity:.0f}" if quantity == int(quantity) else f"{quantity}"
    price_str = f"{price:.3f}"
    return f"MINNA_NO_FX_{pair}_{ts}_{side}_{qty_str}_{price_str}"


# --- trade_group_id ---

def resolve_trade_group_id(fill_type: str, deal_id: str, settlement_ref: str) -> str:
    """trade_group_id を決定する。

    新規行: 取引番号を使用
    決済行: 決済対象取引番号を使用
    """
    if fill_type == "ENTRY":
        return deal_id.strip()
    else:
        ref = settlement_ref.strip()
        if ref in ("", "-"):
            return deal_id.strip()
        return ref


# --- CSV パーサー ---

# みんなのFX CSV の列名
MINNAFX_COLUMNS = [
    "通貨ペア", "区分", "売買", "数量", "約定価格",
    "建玉損益", "累計スワップ", "手数料", "決済損益",
    "約定日時", "取引番号", "決済対象取引番号",
]


def parse_minnafx_csv(
    filepath,
    imported_at_utc: Optional[datetime] = None,
    encoding: str = "utf-8",
) -> Tuple[List[dict], List[dict]]:
    """みんなのFX約定履歴CSVをパースし、raw_fills レコードのリストを返す。

    Returns:
        (fills: list[dict], errors: list[dict])
        fills: raw_fills.csv 形式の辞書リスト
        errors: パースエラーの辞書リスト (error_log.csv 形式)
    """
    filepath = Path(filepath)
    if imported_at_utc is None:
        imported_at_utc = datetime.now(UTC)

    fills = []
    errors = []
    seen_fill_ids = set()

    # エンコーディング候補
    encodings = [encoding, "shift_jis", "cp932", "utf-8-sig"]

    rows = None
    used_encoding = None
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                used_encoding = enc
                break
        except (UnicodeDecodeError, UnicodeError):
            continue

    if rows is None:
        errors.append(_make_parse_error(
            filepath.name, 0, "ENCODING_ERROR",
            f"CSVの読み込みに失敗。試行エンコーディング: {encodings}"
        ))
        return fills, errors

    for row_no, row in enumerate(rows, start=2):  # ヘッダー行=1, データ行=2~
        try:
            fill = _parse_single_row(row, row_no, filepath.name, imported_at_utc)

            # 重複チェック
            if fill["fill_id"] in seen_fill_ids:
                fill["import_status"] = "DUPLICATE"
                fill["import_note"] = "fill_id重複"
            else:
                seen_fill_ids.add(fill["fill_id"])

            fills.append(fill)

        except Exception as e:
            errors.append(_make_parse_error(
                filepath.name, row_no, type(e).__name__, str(e)
            ))

    return fills, errors


def _parse_single_row(
    row: dict,
    row_no: int,
    filename: str,
    imported_at_utc: datetime,
) -> dict:
    """CSV1行をraw_fillsレコードに変換する。"""
    raw_pair = row.get("通貨ペア", "")
    pair = normalize_pair(raw_pair)
    side = normalize_side(row.get("売買", ""))
    fill_type = normalize_fill_type(row.get("区分", ""))
    quantity = normalize_numeric(row.get("数量", "0"))
    price = normalize_numeric(row.get("約定価格", "0"))

    if quantity is None:
        quantity = 0.0
    if price is None:
        price = 0.0

    exec_utc, exec_jst = parse_execution_time(row.get("約定日時", ""))

    fill_id = build_fill_id(pair, exec_utc, side, quantity, price)

    deal_id = row.get("取引番号", "").strip()
    settlement_ref = row.get("決済対象取引番号", "").strip()
    trade_group_id = resolve_trade_group_id(fill_type, deal_id, settlement_ref)

    gross_pnl = normalize_numeric(row.get("建玉損益", "-"))
    net_pnl = normalize_numeric(row.get("決済損益", "-"))
    swap = normalize_numeric(row.get("累計スワップ", "-"))
    fee = normalize_numeric(row.get("手数料", "-"))

    return {
        "fill_id": fill_id,
        "broker": "MINNA_NO_FX",
        "broker_account_name": "",
        "broker_raw_file_name": filename,
        "broker_raw_row_no": row_no,
        "imported_at_utc": imported_at_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution_time_utc": exec_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "execution_time_jst": exec_jst.strftime("%Y-%m-%d %H:%M:%S"),
        "pair": pair,
        "side": side,
        "fill_type": fill_type,
        "quantity": quantity,
        "price": price,
        "gross_realized_pnl_jpy": gross_pnl if gross_pnl is not None else "",
        "net_realized_pnl_jpy": net_pnl if net_pnl is not None else "",
        "swap_jpy": swap if swap is not None else 0.0,
        "fee_jpy": fee if fee is not None else 0.0,
        "commission_jpy": "",
        "order_type": "UNKNOWN",
        "broker_position_id": "",
        "broker_order_id": "",
        "broker_deal_id": deal_id,
        "trade_group_id": trade_group_id,
        "matched_signal_id": "",
        "strategy_version": "",
        "import_status": "IMPORTED",
        "import_note": "",
        "created_by": "broker_import",
        "updated_at_utc": "",
    }


def _make_parse_error(filename: str, row_no: int, error_type: str, message: str) -> dict:
    """パースエラーを error_log.csv 形式で返す。"""
    now = datetime.now(UTC)
    return {
        "error_id": f"IMPORT_ERR_{filename}_{row_no}_{now.strftime('%Y%m%dT%H%M%SZ')}",
        "run_id": "",
        "strategy_version": "",
        "occurred_at_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage": "IMPORT",
        "severity": "ERROR",
        "error_type": error_type,
        "pair": "",
        "message": message,
        "detail": f"file={filename}, row={row_no}",
        "retry_count": 0,
        "resolved": "FALSE",
        "created_by": "broker_import",
    }
