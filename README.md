# FX Alert - V2戦略

自動FXシグナル検出・LINE通知システム（ATR適応型・部分決済戦略）

## 📊 概要

USD/JPY、EUR/JPY、GBP/JPYの3通貨ペアを4時間ごとに自動監視し、V2戦略の条件を満たしたときにLINE通知を送信します。

### バックテスト結果（720日間）

- **総トレード数:** 292回
- **勝率:** 43.49%
- **プロフィットファクター:** 1.57
- **総利益:** +129,509円（+29.7%）
- **初期資金:** 436,000円 → **最終資金:** 565,509円

## 🎯 V2戦略の仕組み

### 1. 日足環境フィルター（最重要）

**「日足環境NG」とは？**

日足（1日足）のチャートで**上昇トレンドが確認できない**状態を指します。

#### 判定条件：
```
✅ 日足環境OK = 以下の2つを両方満たす
  1. 最新の終値 > EMA20（日足）
  2. 最新のEMA20 > 前日のEMA20（EMA20が上向き）

❌ 日足環境NG = 上記のいずれかを満たさない
```

#### なぜ重要なのか？

- **大きなトレンドに逆らわない**ため
- 日足で下落トレンド中に4時間足で押し目買いしても、大きな下落に巻き込まれるリスクが高い
- 日足で上昇トレンドの時だけエントリーすることで、勝率とリスクリワードレシオが改善

#### 例：

```
日足で下落トレンド中（環境NG）:
  ↓↓↓ 大きな流れは下向き
  └─ 4時間足で一時的に反発しても、すぐに下落する可能性が高い

日足で上昇トレンド中（環境OK）:
  ↑↑↑ 大きな流れは上向き
  └─ 4時間足の押し目（一時的な下落）は買いチャンス
```

### 2. 4時間足でのエントリー条件

日足環境OKの場合のみ、以下をチェック：

#### A. EMAタッチ
- 4時間足の**安値〜高値の範囲内にEMA20が含まれる**
- つまり、価格がEMA20に「触れている」または「近い」

#### B. トリガーパターン（どちらか）

**Bullish Engulfing（強気の包み足）:**
```
前の足: 陰線（終値 < 始値）
現在の足: 陽線（終値 > 始値）で前の足を包む
```

**Hammer（ハンマー）:**
```
陽線で下ヒゲが長い
- 下ヒゲ ≥ 実体の1.5倍
- 下ヒゲ ≥ 上ヒゲの2倍
```

### 3. ATR（Average True Range）

**ボラティリティ（価格変動の大きさ）を測定**

- 市場の動きが激しいとき → ATRが大きい → SLを広く設定
- 市場の動きが穏やかなとき → ATRが小さい → SLを狭く設定

固定pipsではなく、**市場の状況に適応**するのがV2の特徴です。

## 📈 エントリー〜決済の流れ

### 1. シグナル発生
```
日足環境OK
  ↓
4時間足でEMAタッチ
  ↓
Engulfing または Hammer
  ↓
✅ LINE通知送信
```

### 2. エントリー（バックテストの場合）
- 次の足の始値でロング
- スプレッド考慮（0.3pips不利に設定）

### 3. ストップロス（SL）
```
SL = エントリー価格 - (ATR × 1.5)
```
例：ATRが0.3円の場合、SLは約45pips

### 4. テイクプロフィット（TP）
```
TP1 = エントリー価格 + (SL幅 × 1.0)  ← 50%決済
TP2 = エントリー価格 + (SL幅 × 2.0)  ← 残り50%決済
```

### 5. 決済ルール
- TP1到達 → 半分利確
- TP2到達 → 残り全決済
- SL到達 → 全決済
- 同一足で両方到達 → 保守的にSL優先

## 🔧 セットアップ

### 1. 必要なもの

- Twelve Data APIキー（無料プラン可）
- LINE Messaging API
  - Channel Access Token
  - User ID

### 2. GitHub Secrets設定

リポジトリの Settings > Secrets and variables > Actions で以下を設定：

```
TWELVEDATA_API_KEY=（あなたのAPIキー）
LINE_CHANNEL_ACCESS_TOKEN=（LINEのトークン）
LINE_USER_ID=（あなたのLINE User ID）
```

### 3. 自動実行スケジュール

GitHub Actionsで以下の時刻に自動実行：
```
JST: 01:05, 05:05, 09:05, 13:05, 17:05, 21:05
（4時間ごと、4時間足の確定後）
```

## 🚀 使い方

### ローカルでテスト実行

```bash
cd /Users/mitsuru/fx-alert

# 環境変数設定
export TWELVEDATA_API_KEY="your_api_key"
export LINE_CHANNEL_ACCESS_TOKEN="your_line_token"
export LINE_USER_ID="your_line_user_id"

# 実行
python3 app.py
```

### 出力例

```
=== V2シグナルチェック開始 ===

[USD/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ 日足環境NG

[EUR/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ✅ シグナル検出

[GBP/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ EMAタッチなし

=== 1件のシグナルを通知 ===
✅ EUR/JPY 通知送信完了
```

### LINE通知内容

```
🚨 EUR/JPY V2シグナル検出
パターン: Engulfing
価格: 163.450
EMA20: 163.280
ATR: 0.285
時刻: 2026-02-14 13:00:00
```

## 📁 ファイル構成

```
fx-alert/
├── app.py                      # メイン実行ファイル（3通貨対応）
├── backtest_v2.py              # V2戦略バックテスト
├── backtest_multi.py           # 複数通貨バックテスト（V1）
├── requirements.txt            # バックテスト用依存関係
├── requirements-app.txt        # 本番用依存関係（軽量）
├── .github/workflows/
│   └── fx-alert.yml            # GitHub Actions設定
└── README.md                   # このファイル
```

## 🔍 プログラムの内部構造

### app.py の処理フロー

```
main()
  │
  ├─ for 各通貨 (USD/JPY, EUR/JPY, GBP/JPY):
  │   │
  │   ├─ fetch_data() ──────────┐
  │   │  ├─ 4時間足 200本取得  │  API呼び出し
  │   │  └─ 日足 100本取得     │
  │   │                         │
  │   ├─ check_signal() ────────┤
  │   │  │                      │
  │   │  ├─ check_daily_environment()  ← 日足環境チェック
  │   │  │  ├─ calculate_ema()
  │   │  │  ├─ 最新close > EMA20?
  │   │  │  └─ EMA20上向き?
  │   │  │     └─ NG → return {signal: False, reason: "日足環境NG"}
  │   │  │
  │   │  ├─ calculate_ema() ────┐
  │   │  ├─ calculate_atr()     │  4時間足の計算
  │   │  │                      │
  │   │  ├─ EMAタッチ判定 ──────┤
  │   │  │  └─ low <= EMA20 <= high?
  │   │  │     └─ NO → return {signal: False, reason: "EMAタッチなし"}
  │   │  │
  │   │  ├─ is_bullish_engulfing() ┐
  │   │  ├─ is_bullish_hammer()    │  トリガーパターン判定
  │   │  │                          │
  │   │  └─ どちらかTrue?
  │   │     └─ NO → return {signal: False, reason: "トリガーパターンなし"}
  │   │     └─ YES → return {signal: True, pattern: "...", ...}
  │   │
  │   └─ シグナル成立?
  │      └─ YES → signals_found に追加
  │
  └─ signals_found が空でない?
     └─ YES → 各シグナルをLINE送信
     └─ NO → "3通貨すべてで条件不成立"
```

### 主要関数の説明

#### 1. `fetch_data(symbol, interval, outputsize)`
**目的:** Twelve Data APIから過去データを取得

**入力:**
- `symbol`: 通貨ペア（例: "USD/JPY"）
- `interval`: 時間足（"4h" または "1day"）
- `outputsize`: 取得本数

**処理:**
1. APIリクエスト送信
2. JSONレスポンスをパース
3. DataFrameに変換（datetime, open, high, low, close）
4. 古い順にソート

**出力:**
```python
DataFrame:
  datetime              open      high      low       close
  2026-02-14 09:00:00  152.670   152.929   152.664   152.735
  2026-02-14 13:00:00  152.735   152.850   152.600   152.780
  ...
```

#### 2. `calculate_ema(series, period)`
**目的:** 指数移動平均（EMA）を計算

**処理:** `pandas.ewm()` を使用した指数加重移動平均

**出力:** EMA値のSeries

#### 3. `calculate_atr(df, period=14)`
**目的:** Average True Range（ボラティリティ指標）を計算

**処理:**
1. True Range計算:
   - TR1 = high - low
   - TR2 = |high - 前日close|
   - TR3 = |low - 前日close|
   - TR = max(TR1, TR2, TR3)
2. TRの14期間EMA

**出力:** ATR値のSeries

#### 4. `check_daily_environment(d1)`
**目的:** 日足で上昇トレンドか判定

**判定:**
```python
latest["close"] > latest["ema20"]  # 価格がEMA上
AND
latest["ema20"] > prev["ema20"]    # EMAが上向き
```

**出力:**
- `True`: 上昇トレンド（エントリー可能）
- `False`: 下落トレンドまたはレンジ（エントリー不可）

#### 5. `is_bullish_engulfing(prev, curr)`
**目的:** 強気の包み足パターン検出

**条件:**
```python
前足が陰線: prev["close"] < prev["open"]
AND
現在足が陽線: curr["close"] > curr["open"]
AND
包み込む: curr["close"] >= prev["open"] AND curr["open"] <= prev["close"]
```

#### 6. `is_bullish_hammer(row)`
**目的:** ハンマーパターン検出

**条件:**
```python
陽線: close > open
AND
下ヒゲが長い: lower_wick >= body * 1.5
AND
上ヒゲが短い: lower_wick >= upper_wick * 2.0
```

#### 7. `check_signal(h4, d1)`
**目的:** 総合的なシグナル判定

**処理順序:**
1. 日足環境チェック → NG なら即return
2. 4時間足の計算（EMA, ATR）
3. EMAタッチチェック → なし なら即return
4. トリガーパターンチェック → なし なら即return
5. すべてOK → シグナル成立

**出力例:**
```python
# シグナルなしの場合
{
  "signal": False,
  "reason": "日足環境NG"  # または "EMAタッチなし" / "トリガーパターンなし"
}

# シグナル成立の場合
{
  "signal": True,
  "pattern": "Engulfing",  # または "Hammer"
  "close": 152.735,
  "ema20": 152.680,
  "atr": 0.285,
  "datetime": "2026-02-14 13:00:00"
}
```

## 📤 アウトプット詳細

### 1. コンソール出力

#### パターン1: シグナルなし（全通貨）
```
=== V2シグナルチェック開始 ===

[USD/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ 日足環境NG

[EUR/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ 日足環境NG

[GBP/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ 日足環境NG

=== シグナルなし ===
3通貨すべてで条件不成立
```

#### パターン2: 一部通貨でシグナル成立
```
=== V2シグナルチェック開始 ===

[USD/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ✅ シグナル検出

[EUR/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ EMAタッチなし

[GBP/JPY] チェック中...
  4H足: 200本, 日足: 100本取得
  ❌ トリガーパターンなし

=== 1件のシグナルを通知 ===
✅ USD/JPY 通知送信完了
```

#### パターン3: エラー発生時
```
[USD/JPY] チェック中...
  ⚠️ エラー: API error: {"status":"error","message":"Rate limit exceeded"}
```

### 2. LINE通知

#### 通知内容の構成
```
🚨 EUR/JPY V2シグナル検出
パターン: Engulfing          ← Engulfing または Hammer
価格: 163.450                ← 現在の終値
EMA20: 163.280               ← 4時間足のEMA20
ATR: 0.285                   ← ボラティリティ指標
時刻: 2026-02-14 13:00:00    ← シグナル発生時刻
```

#### 情報の読み方

**パターン:**
- `Engulfing`: 強気の包み足 → 強い反転シグナル
- `Hammer`: ハンマー → 底打ちシグナル

**価格とEMA20の関係:**
- 価格がEMA20に近い = 押し目買いのチャンス
- 例: 価格163.450、EMA20が163.280 → 約17pips上

**ATR:**
- 大きい（例: 0.5以上）→ ボラティリティ高い、SL広め
- 小さい（例: 0.2以下）→ ボラティリティ低い、SL狭め

**時刻:**
- 4時間足なので、次の足（4時間後）までに判断可能

### 3. GitHub Actions出力

#### 正常終了時
```
Run python app.py
=== V2シグナルチェック開始 ===
...
=== シグナルなし ===
3通貨すべてで条件不成立

✓ Run python app.py  (completed in 3s)
```

#### エラー時
```
Run python app.py
[USD/JPY] チェック中...
  ⚠️ エラー: ...

✗ Run python app.py  (failed)
```

### 4. バックテスト出力

#### trades_v2.csv
```csv
symbol,entry_time,exit_time,entry_price,exit_price,units,sl,tp1,tp2,outcome,pnl_yen,r_mult,bars_held
USD/JPY,2024-02-28 03:00:00,2024-02-29 11:00:00,150.443,150.066,5000,150.066,150.820,151.198,mix,0.0,0.0,9
USD/JPY,2024-04-10 15:00:00,2024-04-10 19:00:00,151.803,152.319,8000,151.545,152.061,152.319,win,3098.9,1.43,2
...
```

**カラム説明:**
- `outcome`: win（利益）/ loss（損失）/ mix（TP1後にSL）/ timeout（未決済）
- `pnl_yen`: 損益（円）
- `r_mult`: リスクリワード倍率（1.0 = 想定リスクと同額の利益）
- `bars_held`: 保有期間（足数）

#### equity_v2.csv
```csv
trade_num,cumulative_pips
0,0
1,-30
2,-5
3,25
...
```

**用途:** 資産曲線のグラフ化に使用

## 🐛 デバッグ情報

### よくある出力とその意味

| 出力 | 意味 | 対処 |
|------|------|------|
| `❌ 日足環境NG` | 日足が上昇トレンドでない | 正常。待機 |
| `❌ EMAタッチなし` | 価格がEMA20から離れている | 正常。待機 |
| `❌ トリガーパターンなし` | Engulfing/Hammerが出ていない | 正常。待機 |
| `⚠️ エラー: API error` | APIエラー | APIキー確認、レート制限確認 |
| `⚠️ エラー: 'values' not in data` | データ取得失敗 | 通貨ペア名確認、API制限確認 |

### デバッグモード

より詳細なログを見たい場合、`app.py` に以下を追加:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🧪 バックテスト実行

### V2戦略（推奨）

```bash
python3 backtest_v2.py
```

オプション:
```bash
python3 backtest_v2.py \
  --days 720 \
  --symbols "USD/JPY,EUR/JPY,GBP/JPY" \
  --risk-pct 0.005 \
  --atr-mult-sl 1.5
```

### V1戦略（比較用）

```bash
python3 backtest_multi.py
```

## 📊 V1 vs V2 比較

| 項目 | V1（固定SL/TP） | V2（ATR適応型） |
|------|----------------|----------------|
| トレード数 | 1,229回 | 292回 |
| 勝率 | 32.3% | 43.5% |
| PF | 0.95 ❌ | 1.57 ✅ |
| 総損益 | -1,140 pips | +129,509円 |
| フィルター | なし | 日足環境 |
| SL/TP | 固定30/60pips | ATR適応型 |

**結論:** V2は厳選したトレードで高い勝率とPFを実現

## ⚙️ カスタマイズ

### 通貨ペア変更

`app.py` の11行目:
```python
SYMBOLS = ["USD/JPY", "EUR/JPY", "GBP/JPY"]
```

### パラメータ調整

```python
EMA_PERIOD = 20      # EMAの期間
ATR_PERIOD = 14      # ATRの期間
```

バックテストでの調整:
```python
--risk-pct 0.005     # 1トレードあたりのリスク（0.5%）
--atr-mult-sl 1.5    # ATR倍率（SL幅）
```

## 🔔 通知頻度

V2は**厳格なフィルタリング**を行うため：

- **平均:** 月に約12回（3通貨合計）
- **通貨ごと:** 月に約4回
- **質重視:** 勝率43%、PF 1.57の高品質なシグナル

「日足環境NG」が多いのは**正常**です。無駄なトレードを避けています。

## 🛡️ リスク管理

### バックテストでの設定

- 初期資金: 436,000円
- リスク/トレード: 0.5%（2,180円）
- 最大ドローダウン: -18,434円（-4.2%）

### 実運用の推奨

1. **デモ口座で検証**（最低1ヶ月）
2. **少額から開始**
3. **リスクは1%以下**
4. **資金管理を厳守**

## 📝 ライセンス

個人利用のみ。商用利用禁止。

## 🙏 謝辞

- Twelve Data API（市場データ提供）
- LINE Messaging API（通知機能）

---

**作成日:** 2026年2月14日
**戦略バージョン:** V2（ATR適応型・部分決済）
**バックテスト期間:** 2023年5月〜2026年2月（720日間）
