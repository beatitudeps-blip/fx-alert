# バッチ通知（LINE無料枠節約設計）

## 概要

LINE公式アカウントの無料枠（**200通/月**）を守るため、**3通貨の結果を1通にまとめて送信**します。

## 主な機能

### 1. 3通貨を1通にまとめる
- EUR/JPY、USD/JPY、GBP/JPYの判定結果（シグナル or 見送り）を1つのメッセージに集約
- messages配列は1要素のみ（textメッセージ1件）

### 2. bar_dtデデュープ
- 同一の4H足確定時刻（bar_dt）では再送しない
- スクリプトを誤って2回実行しても、送信は1回だけ
- `data/notification_state.json` に `last_sent_bar_dt` を保存

### 3. 見送りも短く通知
- シグナルがない通貨も「見送り理由」を1〜2行で記載
- 全通貨見送りでも通知送信（シグナルなしでもチェック完了を確認できる）

### 4. 月間送信数の計算

**4H足確定後に1回実行**:
- 1日6回（JST 1:05, 5:05, 9:05, 13:05, 17:05, 21:05）
- 月間: 6回/日 × 31日 = **186通**
- **無料枠200通以内** ✅

**15分毎（禁止例）**:
- 1日96回（24時間 × 4回/時）
- 月間: 96回/日 × 31日 = **2,976通**
- **無料枠を大幅超過** ❌

## 設定（config/minnafx.yaml）

```yaml
notifier:
  aggregate_one_message: true           # 3通貨を1通にまとめる
  include_skips: true                   # 見送りも通知
  send_on_new_closed_bar_only: true     # 同一bar_dtで再送しない
  state_path: "data/notification_state.json"
  max_text_length: 3500                 # LINEテキスト上限（5000）の余裕
  compress_skip_lines: true             # 見送りを1〜2行に圧縮
```

## 使い方

### dry-run（標準出力のみ）

```bash
python3 scripts/run_signal.py --dry-run --symbols EUR/JPY,USD/JPY,GBP/JPY
```

### LINE送信

```bash
python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY
```

### cron設定（推奨）

**⚠️ 重要**: cron設定前に、実際のbar_dt（確定4H足時刻）をログで確認してください：

```bash
# 初回確認（必須）
python3 scripts/run_signal.py --dry-run --symbols USD/JPY,EUR/JPY,GBP/JPY --log-level INFO
# → 出力の【確定足】時刻を確認
```

**Twelve Data APIは UTC 03:00, 07:00, 11:00, 15:00, 19:00, 23:00 区切り（検証済み）**
- JST変換: **00:00, 04:00, 08:00, 12:00, 16:00, 20:00**
- cron設定: `5 0,4,8,12,16,20 * * *`

```bash
# Twelve Data API（検証済みパターン）
5 0,4,8,12,16,20 * * * cd /path/to/fx-alert && /usr/bin/python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY >> logs/signal.log 2>&1
```

**⚠️ 注意**:
- 15分毎（`*/15`）は禁止！無料枠を大幅超過します
- 実際のbar_dtに合わせてcron時刻を調整すること

## テスト

```bash
python3 scripts/test_batch_notify.py
```

**検証項目**:
1. ✅ バッチメッセージ生成（3通貨まとめ）
2. ✅ bar_dtデデュープ（同一4Hバーで再送しない）
3. ✅ 全通貨見送りでも短文通知

## 通知例

### シグナル1、見送り2の場合

```
📊 4H足確定通知（3通貨）

【確定足】2026-02-15 12:00 JST
【次足始値】2026-02-15 16:00 JST
【実行時刻】2026-02-15 13:05:00 JST

🚨 EUR/JPY 🔼 買いシグナル

パターン: Bullish Engulfing
エントリー: 163.249円（仲値163.245＋コスト）
推奨数量: 8,000通貨 = 0.8Lot
リスク: 464円（0.5%）

SL: 163.191円 (-5.8pips)
TP1: 163.295円 (+5.0pips) → 50%利確
TP2: 163.345円 (+10.0pips) → 残玉決済
→ TP1後、SLを建値へ移動

スプレッド: 0.4pips（固定帯）
想定コスト: 48円
EMA20: 163.150, ATR: 0.050

操作: みんなのFX→新規→成行→買い→0.8Lot→発注

========================================

【見送り】
・USD/JPY: 日足環境NG（レンジ）
・GBP/JPY: スプレッド超過（14.9 pips > 2.25 pips）

【サマリー】
シグナル: 1通貨
見送り: 2通貨
合計: 3通貨

※次回通知は次の4H足確定後
※LINE無料枠（200通/月）節約のため集約送信
```

### 全通貨見送りの場合

```
📊 4H足確定通知（3通貨）

【確定足】2026-02-15 12:00 JST
【次足始値】2026-02-15 16:00 JST
【実行時刻】2026-02-15 13:05:00 JST

【見送り】
・EUR/JPY: 日足環境NG
・USD/JPY: EMAタッチなし
・GBP/JPY: パターン不成立

【サマリー】
シグナル: 0通貨
見送り: 3通貨
合計: 3通貨

※次回通知は次の4H足確定後
※LINE無料枠（200通/月）節約のため集約送信
```

## 実装詳細

### src/notify_line.py

**新規メソッド**:
- `create_batch_message()`: 3通貨分の結果を1通にまとめる
- `_is_bar_already_sent(bar_dt)`: bar_dtデデュープチェック
- `_mark_bar_sent(bar_dt)`: 送信済みマーク
- `_format_signal_block()`: シグナル詳細ブロック生成

### scripts/run_signal.py

**変更点**:
- 通貨ごとにループして結果収集（`results` リスト）
- 最後に `create_batch_message()` で1通にまとめる
- `--send` 時のみ bar_dtデデュープ適用

## トラブルシューティング

### 「同一bar_dtで既に送信済み」と表示される

正常な動作です。同じ4H足確定時刻では再送しません。次の4H足確定後に再度実行してください。

### テストで送信したい場合

state_fileを削除してリセット:

```bash
rm data/notification_state.json
python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY
```

### 月間送信数の確認

```bash
# state_fileを確認
cat data/notification_state.json

# last_sent_bar_dt をチェック
# 1日6回 × 31日 = 186通で無料枠内
```

## まとめ

- ✅ **1回の4H確定につき最大1通** → bar_dtデデュープ
- ✅ **3通貨を1通にまとめる** → aggregate_one_message
- ✅ **見送りも短く通知** → compress_skip_lines
- ✅ **月186通で無料枠内** → 4H足確定後1日6回実行
- ✅ **textメッセージ1件のみ** → messages配列は1要素

**実運用可能** 🎉
