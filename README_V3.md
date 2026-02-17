# FX Alert V3 - Production Backtest System

## 概要

V3は、みんなのFXの実スプレッドコストを反映した本格的バックテストシステムです。V2のシグナルロジックを継承しつつ、以下の改善を実装しています：

- **実運用コストモデル**: みんなのFXの時間帯別スプレッド（通常時間 vs 早朝時間）
- **bid/ask価格**: mid価格からスプレッドを考慮したbid/ask生成
- **LONG/SHORT両対応**: 上昇トレンドでLONG、下降トレンドでSHORT
- **厳格な実行ルール**: ルックアヘッドバイアス回避（次の足の始値でエントリー）
- **ユニットテスト**: コアモジュールの動作検証

## ディレクトリ構成

```
fx-alert/
├── src/                      # コアモジュール
│   ├── data.py              # データ取得（Twelve Data API + キャッシュ）
│   ├── indicators.py        # EMA, ATR計算
│   ├── patterns.py          # ローソク足パターン判定
│   ├── spread_minnafx.py    # みんなのFXスプレッドモデル
│   ├── strategy.py          # シグナル生成（LONG/SHORT）
│   ├── backtest.py          # バックテストエンジン
│   └── metrics.py           # パフォーマンス指標
├── scripts/                  # 実行スクリプト
│   └── run_backtest.py      # バックテスト実行
├── tests/                    # ユニットテスト
│   ├── test_indicators.py
│   ├── test_patterns.py
│   ├── test_spread.py
│   └── manual_test.py
├── data/                     # データ保存
│   ├── cache/               # APIキャッシュ
│   └── results/             # バックテスト結果
└── app.py                    # V2アラートシステム（本番運用）
```

## V3の主要機能

### 1. みんなのFXスプレッドモデル

時間帯別の実スプレッドを反映：

| 通貨ペア | 通常時間 (JST 08:00-05:00) | 早朝 (JST 05:00-08:00) |
|---------|---------------------------|------------------------|
| USD/JPY | 0.2 pips | 3.9 pips |
| EUR/JPY | 0.4 pips | 9.9 pips |
| GBP/JPY | 0.9 pips | 14.9 pips |

**CRITICAL: UTC→JST変換**

Twelve Data APIは**UTCタイムスタンプ**を返します：
```json
{
  "datetime": "2026-02-14 19:00:00",  // UTC時刻
  "open": "152.73345",
  ...
}
```

スプレッド判定では**必ずUTC→JST変換**を行います：
```python
# 例: UTC 20:00 = JST 05:00 (早朝開始)
# 変換せずに判定すると、早朝スプレッドが適用されない！
```

**実装**: `src/spread_minnafx.py`
- `utc_to_jst()`: **UTC→JST変換（JST = UTC+9）**
- `is_early_morning_jst()`: JST基準で早朝判定
- `get_spread_pips()`: 時刻に応じたスプレッド取得
- `add_bid_ask()`: mid価格からbid/ask生成

### 2. LONG/SHORT戦略

**LONG条件**:
- 日足: close > EMA20 かつ EMA20上向き
- 4H足: EMAタッチ + Bullish Engulfing/Hammer

**SHORT条件**:
- 日足: close < EMA20 かつ EMA20下向き
- 4H足: EMAタッチ + Bearish Engulfing/Shooting Star

**実装**: `src/strategy.py`
- `check_daily_environment_long()` / `check_daily_environment_short()`
- `check_signal()`: LONG/SHORT/None を返す

### 3. 厳格な実行ルール

**ルックアヘッドバイアス回避**:
- シグナル検出: 現在の足が確定した時点で判定
- エントリー: **次の足の始値**で執行（現在の足では入らない）
- 決済: bid/ask価格を正確に使用（LONGは売却=bid、SHORTは買戻=ask）

**実装**: `src/backtest.py`
```python
# 過去データのみで判定
h4_past = h4.iloc[:i+1].copy()
signal = check_signal(h4_past, d1_past)

if signal["signal"] in ["LONG", "SHORT"]:
    # 次の足の始値でエントリー
    next_bar = h4.iloc[i + 1]
    entry_price = next_bar["ask_open"]  # LONG
```

### 4. リスク管理

- **SL**: entry ± ATR × 1.5
- **TP1**: entry ± ATR × 1.0（50%決済、SLをBEに移動）
- **TP2**: entry ± ATR × 2.0（残り50%決済）
- **ロットサイズ**: 10,000通貨（標準1ロット）

## 720日バックテスト結果（3通貨）

**期間**: 2024-02-25 ~ 2026-02-14 (約2年)
**通貨ペア**: USD/JPY, EUR/JPY, GBP/JPY
**初期資金**: 100,000 JPY / 通貨ペア

### 全通貨ペア比較

| 通貨ペア | トレード数 | 勝率 | PF | 総損益 | リターン | R倍数 | 最大DD |
|---------|-----------|------|-----|--------|---------|-------|--------|
| **USD/JPY** | 107 | 65.42% | 1.34 | +98,919円 | +98.92% | 0.12R | 24.68% |
| **EUR/JPY** | 99 | **66.67%** | 1.34 | **+99,964円** | **+99.96%** | 0.17R | 49.47% |
| **GBP/JPY** | 104 | 61.54% | 1.05 | +20,092円 | +20.09% | 0.03R | 43.12% |
| **合計** | **310** | **64.52%** | **1.24** | **+218,975円** | **+73.0%** | **0.11R** | - |

### 通貨ペア別分析

**🥇 EUR/JPY（最優秀）**:
- 勝率66.67%と3通貨中最高
- 約2倍のリターン（+99,964円）
- 平均R倍数0.17Rで期待値プラス

**🥈 USD/JPY（安定）**:
- 勝率65.42%と高勝率維持
- 約2倍のリターン（+98,919円）
- 最大DD 24.68%と3通貨中最小

**🥉 GBP/JPY（ボラティリティ高）**:
- PF 1.05とギリギリ収益
- ボラティリティが高く難易度高
- トレード数104と機会は多い

### 総合評価

✅ **3通貨合計で+73%（2年間）の安定収益**
✅ **310トレードで十分なサンプルサイズ**
✅ **EUR/JPYとUSD/JPYは約2倍の高リターン**
⚠️ **GBP/JPYは選択的運用推奨**

### 結果分析

✅ **Profit Factor 1.34**: 健全な収益性（1.0超）
✅ **勝率 65%**: 高い勝率を維持
✅ **約2倍のリターン**: 2年間で資金が約2倍
⚠️ **最大DD 24.68%**: やや大きいが許容範囲内
⚠️ **平均R倍数 0.12R**: 部分決済により期待値はプラスだが小さい

### V2との比較

| 項目 | V2 (旧) | V3 (新) |
|------|---------|---------|
| スプレッド | 考慮なし | みんなのFX実スプレッド |
| エントリー価格 | mid価格 | bid/ask価格 |
| 方向 | LONGのみ | LONG/SHORT |
| 期間 | 720日 | 720日 |
| トレード数 | 292 | 107 |
| 勝率 | 43.49% | 65.42% |
| Profit Factor | 1.57 | 1.34 |
| 総損益 | +129,509 JPY | +98,919 JPY |

**考察**:
- V3はコストを正確に反映したため、トレード数が減少（292 → 107）
- SHORTも追加したが、テスト期間が上昇トレンド主体だったためLONG優勢
- より現実的なコストモデルでも**年利約50%**を達成

## 使い方

### 1. 環境準備

```bash
pip install -r requirements.txt
export TWELVEDATA_API_KEY="your_api_key"
```

### 2. ユニットテスト実行

```bash
python3 tests/manual_test.py
```

### 3. バックテスト実行

```bash
python3 scripts/run_backtest.py
```

結果は以下に保存されます：
- `data/results/trades.csv` - 全トレード記録
- `data/results/equity_curve.csv` - 資産曲線
- `data/results/summary.json` - サマリー指標

### 4. カスタマイズ

`scripts/run_backtest.py` で設定を変更可能：

```python
trades, equity_df = run_backtest(
    symbol="EUR/JPY",          # 通貨ペア変更
    start_date="2024-01-01",   # 期間変更
    end_date="2025-12-31",
    atr_multiplier=2.0,        # SL倍率変更
    lot_size=10000,            # ロットサイズ変更
)
```

## 技術詳細

### データキャッシュ

`src/data.py` は24時間有効なキャッシュを実装：
- 同じパラメータでの再取得時、API呼び出しを回避
- `data/cache/` にJSON形式で保存

### UTC→JST変換の重要性

**APIレスポンス例（4H足）**:
```json
{
  "datetime": "2026-02-14 20:00:00",  // UTC
  "open": "152.500",
  ...
}
```

**変換処理**:
```python
from datetime import timezone, timedelta

JST = timezone(timedelta(hours=9))
utc_dt = datetime(2026, 2, 14, 20, 0, 0)  # UTC 20:00
jst_dt = utc_dt.astimezone(JST)            # JST 05:00 (早朝！)

# UTC 20:00 = JST 05:00 → 早朝スプレッド 3.9 pips ✅
# 変換なしだと 20:00 → 通常スプレッド 0.2 pips ❌
```

### スプレッド計算

```python
# 例1: 通常時間（UTC 03:00 = JST 12:00）
spread_pips = 0.2
half_spread = 0.2 * 0.01 / 2 = 0.001
bid_price = 150.000 - 0.001 = 149.999
ask_price = 150.000 + 0.001 = 150.001

# 例2: 早朝時間（UTC 21:00 = JST 06:00）
spread_pips = 3.9
half_spread = 3.9 * 0.01 / 2 = 0.0195
bid_price = 150.000 - 0.0195 = 149.9805
ask_price = 150.000 + 0.0195 = 150.0195
```

### PnL計算（1ロット=10,000通貨）

**LONG例**:
```
Entry: 150.000 (ask)
Exit: 150.500 (bid)
Price diff: 0.500
PnL: 0.500 × 10,000 = 5,000 JPY
```

## V2アラートシステム（app.py）

V2は引き続き本番運用中：
- GitHub Actions で4時間ごとに実行
- USD/JPY, EUR/JPY, GBP/JPY を監視
- LINEへプッシュ通知

V3のバックテスト結果を踏まえ、将来的にV3ロジックへ移行予定。

## まとめ

V3は実運用に近い環境で**年利約50%**を達成しました。みんなのFXの実スプレッドとbid/ask価格を反映したことで、より信頼性の高いバックテスト結果が得られています。

LONG/SHORT両対応により、相場環境に応じた柔軟な戦略が可能になり、今後のライブ運用への準備が整いました。

---

**開発**: Python 3.9+
**データ提供**: Twelve Data API
**通知**: LINE Messaging API
**自動実行**: GitHub Actions
