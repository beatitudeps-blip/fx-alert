# ⚠️ タイムゾーン変換の重要性（CRITICAL）

## 問題

Twelve Data APIは**UTCタイムスタンプ**を返しますが、みんなのFXのスプレッドは**JSTの時刻**で決まります。

UTC→JST変換を行わないと、**9時間のズレ**が発生し、スプレッドコストが全く異なる結果になります。

## 具体例

### ❌ 変換なしの場合（間違い）

```python
# APIレスポンス
datetime_str = "2026-02-14 20:00:00"  # UTC 20:00

# 変換なしで時刻判定
t = datetime.fromisoformat(datetime_str).time()  # 20:00
is_early = (time(5, 0) <= t < time(8, 0))  # False
spread = 0.2 pips  # 通常スプレッド ❌ 間違い！
```

### ✅ 変換ありの場合（正しい）

```python
# APIレスポンス
datetime_str = "2026-02-14 20:00:00"  # UTC 20:00

# UTC → JST変換
from datetime import timezone, timedelta
JST = timezone(timedelta(hours=9))

dt_utc = datetime.fromisoformat(datetime_str).replace(tzinfo=timezone.utc)
dt_jst = dt_utc.astimezone(JST)  # JST 2026-02-15 05:00

# JST時刻で判定
t = dt_jst.time()  # 05:00
is_early = (time(5, 0) <= t < time(8, 0))  # True
spread = 3.9 pips  # 早朝スプレッド ✅ 正しい！
```

## スプレッドコストの差

| UTC時刻 | JST時刻 | 変換なし | 変換あり（正しい） | コスト差 |
|---------|---------|----------|-------------------|----------|
| 20:00 | 05:00 | 0.2 pips | 3.9 pips | **19.5倍** |
| 21:00 | 06:00 | 0.2 pips | 3.9 pips | **19.5倍** |
| 22:00 | 07:00 | 0.2 pips | 3.9 pips | **19.5倍** |
| 23:00 | 08:00 | 0.2 pips | 0.2 pips | 1倍 |
| 00:00 | 09:00 | 0.2 pips | 0.2 pips | 1倍 |
| 03:00 | 12:00 | 0.2 pips | 0.2 pips | 1倍 |

**4H足の確定時刻（UTC）**: 00:00, 04:00, 08:00, 12:00, 16:00, **20:00**

UTC 20:00の足は**JST 05:00（早朝開始）**に該当するため、正確な変換が必須です。

## 実装

### src/spread_minnafx.py

```python
from datetime import timezone, timedelta

JST = timezone(timedelta(hours=9))

def utc_to_jst(dt: datetime) -> datetime:
    """UTC datetime → JST変換"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(JST)

def is_early_morning_jst(dt: datetime) -> bool:
    """早朝判定（必ずUTC→JST変換してから判定）"""
    dt_jst = utc_to_jst(dt)
    t = dt_jst.time()
    return time(5, 0) <= t < time(8, 0)
```

## テスト

### tests/test_spread.py

```python
def test_utc_to_jst_conversion():
    # UTC 20:00 = JST 05:00 (早朝)
    utc_dt = datetime(2024, 1, 1, 20, 0, 0)
    jst_dt = utc_to_jst(utc_dt)
    assert jst_dt.hour == 5
    assert jst_dt.day == 2  # 日付またぎ

def test_early_morning_spread():
    # UTC 21:00 = JST 06:00 → 早朝スプレッド
    dt = datetime(2024, 1, 1, 21, 0, 0)
    spread = get_spread_pips("USD/JPY", dt)
    assert spread == 3.9  # 早朝 ✅
```

## バックテストへの影響

UTC→JST変換を行わない場合：
- 早朝時間帯のトレードが**通常スプレッド**で計算される
- 実際より**コストが低く見積もられる**
- バックテスト結果が**過度に楽観的**になる
- 実運用で**予想外の損失**が発生する

## まとめ

✅ **必ずUTC→JST変換を行う**
✅ **スプレッドモデル内で変換を実装**（呼び出し側に依存しない）
✅ **ユニットテストで検証**
✅ **ドキュメントに明記**

UTC→JST変換は、**実運用コストを正確に反映するための最重要項目**です。
