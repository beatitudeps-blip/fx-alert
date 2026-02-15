# FX Alert System - みんなのFX実運用対応

**EMA20反発 + プライスアクション戦略**による自動FXシグナル検出・LINE通知システム

---

## 📊 概要

EUR/JPY、USD/JPYの2通貨ペアを**4時間ごとに自動監視**し、みんなのFX仕様に完全対応したシグナルをLINE通知で配信します。

### 📈 最新バックテスト結果（改善版パラメータ）

**期間**: 2024-01-01 ~ 2026-02-14 (2.1年間)

| 指標 | EUR/JPY | USD/JPY | 合計 |
|------|---------|---------|------|
| トレード数 | 67 | 63 | **130** |
| 勝率 | 50.7% | 49.2% | **50.0%** |
| PF | 1.73 | 1.49 | **1.61** |
| 損益 | +10,709円 | +6,705円 | **+17,414円** |
| 年率リターン | +5.1% | +3.2% | **+8.3%** |
| 最大DD | 1.86% | 2.03% | **2.03%** |

**推奨パラメータ**: ATR 1.0 × リスク 0.5% × TP1 1.5R × TP2 3.0R

---

## 🚀 クイックスタート

### 1. 環境変数設定

```bash
# .env ファイルを作成（推奨）
cp .env.example .env

# .env を編集して以下を設定
TWELVEDATA_API_KEY=your_api_key_here
LINE_CHANNEL_ACCESS_TOKEN=your_line_token_here
LINE_USER_ID=your_line_user_id_here
```

または、環境変数として直接設定：

```bash
export TWELVEDATA_API_KEY="your_api_key"
export LINE_CHANNEL_ACCESS_TOKEN="your_line_token"
export LINE_USER_ID="your_line_user_id"
```

### 2. dry-runで動作確認

```bash
# APIキーのみで実行可能（LINE認証不要）
python3 scripts/run_signal.py --dry-run --symbols EUR/JPY,USD/JPY --log-level INFO
```

### 3. bar_dt（確定4H足時刻）を確認

dry-runの出力から以下を確認：
```
確定4H足時刻（bar_dt）: 2026-02-15 12:00 JST
💡 cron設定のヒント: Twelve Data APIは通常 JST 00:00, 04:00, 08:00... → cron「5 0,4,8,12,16,20 * * *」
```

### 4. cron設定

**Twelve Data API検証済み**: UTC 03:00, 07:00, 11:00, 15:00, 19:00, 23:00 区切り
- JST: **00:00, 04:00, 08:00, 12:00, 16:00, 20:00**

```bash
# crontabを編集
crontab -e

# 以下を追加（環境変数を直接設定）
TWELVEDATA_API_KEY=your_api_key_here
LINE_CHANNEL_ACCESS_TOKEN=your_line_token_here
LINE_USER_ID=your_line_user_id_here

# JST 0:05, 4:05, 8:05, 12:05, 16:05, 20:05 に実行（1日6回）
5 0,4,8,12,16,20 * * * cd /Users/mitsuru/fx-alert && python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY >> logs/signal.log 2>&1
```

⚠️ **重要**: cronはシェルの設定ファイル（.bashrc/.zshrc）を読みません！crontab内で直接環境変数を設定してください。

### 5. ログ確認

```bash
# リアルタイムでログ監視
tail -f logs/signal.log

# 最新の通知内容を確認
tail -50 logs/signal.log
```

---

## 🎯 戦略の仕組み

### 1. 日足環境フィルター

**日足で上昇トレンド**の時のみエントリー：

```
✅ 日足環境OK = 以下の両方を満たす
  1. 最新の終値 > EMA20（日足）
  2. 最新のEMA20 > 前日のEMA20（EMA20が上向き）
```

### 2. 4時間足エントリー条件

1. **EMAタッチ**: 価格がEMA20に触れている
2. **トリガーパターン**: Bullish Engulfing または Hammer

### 3. リスク管理（みんなのFX完全対応）

- **0.5%厳格リスク管理**: 違反ゼロ保証
- **0.1Lot刻み**: 丸め後に再チェック
- **スプレッド**: 固定帯/拡大帯を自動判定
- **メンテナンス時間**: 約定不可時間を除外
- **スリッページ**: 片道0.2pips考慮

### 4. エグジット戦略

- **TP1**: SL幅 × 1.5R → 50%利確
- **TP2**: SL幅 × 3.0R → 残り50%決済
- **TP1後**: SLを建値に移動

---

## 📋 ディレクトリ構成

```
fx-alert/
├── .env.example                    # 環境変数テンプレート
├── config/
│   └── minnafx.yaml                # みんなのFX設定（スプレッド/メンテ/スワップ）
├── src/
│   ├── env_check.py                # 環境変数チェック（改善版）
│   ├── config_loader.py            # 設定ローダー
│   ├── broker_costs/
│   │   └── minnafx.py              # みんなのFXコストモデル
│   ├── position_sizing.py          # 厳格0.5%リスク管理
│   ├── notify_line.py              # LINE通知（バッチ通知対応）
│   ├── strategy.py                 # シグナル判定ロジック
│   └── backtest_v4_integrated.py   # V4統合バックテスト
├── scripts/
│   ├── run_signal.py               # シグナル検出→LINE通知（実運用）
│   ├── run_backtest_v4.py          # バックテスト実行
│   ├── check_data_availability.py  # データ範囲確認
│   └── demo_batch_notifications.py # バッチ通知デモ
├── data/
│   ├── notification_state.json     # 重複防止state（bar_dtデデュープ）
│   └── results_v4/                 # バックテスト結果
└── README.md                       # このファイル
```

---

## 🔧 詳細設定

### config/minnafx.yaml

みんなのFX仕様を完全定義：

```yaml
broker_name: "みんなのFX"
lot_size_units: 10000       # 1Lot = 10,000通貨
min_lot_size: 1000          # 最小0.1Lot
lot_step_size: 1000         # 0.1Lot刻み

# スプレッド設定（時間帯別）
spreads:
  fixed_window:
    start_time: "08:00"     # JST 08:00〜
    end_time: "05:00"       # 翌日05:00（翌日）
  widened_window:
    - {start: "07:10", end: "08:00"}   # 早朝拡大帯
    - {start: "05:00", end: "06:50"}   # 深夜拡大帯
  advertised:
    "USD/JPY": {fixed: 0.2, widened: 3.9}   # 銭
    "EUR/JPY": {fixed: 0.4, widened: 9.9}
    "GBP/JPY": {fixed: 0.9, widened: 14.9}

# メンテナンス時間（約定不可）
maintenance:
  daily:
    weekday: {start: "06:50", end: "07:10"}
    monday: {start: "06:00", end: "06:25"}
  weekly:
    saturday: {start: "12:00", end: "18:00"}
```

---

## 📱 LINE通知の内容

### シグナル通知例

```
📊 4H足確定通知（2通貨）

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
・USD/JPY: [E] 日足環境NG

【サマリー】
シグナル: 1通貨
見送り: 1通貨
合計: 2通貨

【次回チェック】2026-02-15 20:05 JST

※理由コード: [E]=環境NG [S]=スプレッド [M]=メンテ [P]=ロット不足 [R]=リスク超過
※LINE無料枠（200通/月）節約のため集約送信
```

### 見送り理由コード

| コード | 意味 | 例 |
|-------|------|-----|
| **[E]** | 環境NG | 日足環境NG、EMAタッチなし、パターン不成立 |
| **[S]** | スプレッド超過 | 14.9pips > 2.25pips |
| **[M]** | メンテナンス | メンテナンス時間中 |
| **[P]** | ロット不足 | 最小ロット未満 |
| **[R]** | リスク超過 | 0.5%超過 |

---

## 🧪 バックテスト実行

### 改善版パラメータで実行

```bash
python3 scripts/run_backtest_v4.py \
  --start-date 2024-01-01 \
  --end-date 2026-02-14 \
  --symbols EUR/JPY,USD/JPY \
  --run-id my_test \
  --equity 100000 \
  --risk-pct 0.005 \
  --atr-mult 1.0 \
  --tp1-r 1.5 \
  --tp2-r 3.0
```

### 結果確認

```bash
# サマリー確認
cat data/results_v4/my_test/EUR_JPY/summary.json

# トレード一覧
cat data/results_v4/my_test/EUR_JPY/trades.csv

# 見送りシグナル
cat data/results_v4/my_test/EUR_JPY/skipped_signals.csv
```

---

## ⚙️ カスタマイズ

### パラメータ調整

| パラメータ | 現行 | 推奨範囲 | 効果 |
|-----------|------|---------|------|
| `--atr-mult` | 1.0 | 0.8-1.2 | SL距離（小さい=タイトなSL） |
| `--risk-pct` | 0.005 | 0.005-0.007 | 1トレードのリスク率 |
| `--tp1-r` | 1.5 | 1.2-2.0 | TP1距離（R倍数） |
| `--tp2-r` | 3.0 | 2.0-4.0 | TP2距離（R倍数） |

### 通貨ペア変更

GBP/JPYを追加する場合：

```bash
python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY
```

⚠️ **注意**: GBP/JPYはボラティリティが高く、サイズスキップが多発します。

---

## 📊 パフォーマンス比較

### 現行設定 vs 改善版設定

| 設定 | ATR | リスク | トレード数 | 年率 | DD | violations |
|------|-----|--------|-----------|------|-----|-----------|
| **現行** | 1.2 | 0.5% | 78 | +4.4% | 2.36% | 2件 |
| **改善版** | **1.0** | **0.5%** | **130** | **+8.3%** | **2.03%** | 7件 ⚠️ |

**結論**: 改善版はトレード数1.7倍、年率2倍に改善。violations修正後は実運用推奨。

---

## 🛡️ リスク管理

### 厳格な0.5%リスク管理

```python
# position_sizing.py
def calculate_position_size_strict(equity_jpy, entry_price, sl_price, risk_pct, config, symbol):
    # 1. 理論数量計算
    # 2. 0.1Lot刻みで切り捨て
    # 3. 丸め後に0.5%超過チェック
    # 4. 超過なら1段階切り下げ
    # → violations = 0 を保証
```

### バッチ通知でLINE無料枠節約

- **3通貨を1通にまとめる**（aggregate_one_message）
- **bar_dtデデュープ**（同一4Hバーで再送しない）
- **1日6回実行 × 31日 = 186通/月**（無料枠200通以内 ✅）

---

## 🔍 トラブルシューティング

### Q: 環境変数が設定されていないエラー

```
❌ エラー: TWELVEDATA_API_KEY が設定されていません
```

**解決**:
1. `.env` ファイルを作成: `cp .env.example .env`
2. `.env` に実際のキーを設定
3. cron実行時は、crontab内で直接設定

### Q: cronが実行されない

**確認項目**:
1. `crontab -l` でcronが登録されているか
2. 絶対パス使用: `/usr/bin/python3`（`which python3`で確認）
3. 環境変数をcrontab内で設定しているか
4. ログファイルのパーミッション: `mkdir -p logs && chmod 755 logs`

### Q: 毎回送信されてしまう（デデュープが効かない）

**原因**: state_fileのパス問題

**解決**:
```bash
# state_fileを確認
cat data/notification_state.json
# → last_sent_bar_dt が記録されているか確認
```

### Q: violationsが発生する

**現状**: ATR 1.0 + リスク 0.5%で7件検出

**対策**: position_sizing.pyの修正が必要（調査中）

---

## 📚 ドキュメント

- **[CRON_SETUP_GUIDE.md](CRON_SETUP_GUIDE.md)**: cron設定の詳細ガイド
- **[BATCH_NOTIFY_README.md](BATCH_NOTIFY_README.md)**: バッチ通知の仕組み
- **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)**: 実装状況
- **[THREE_WAY_COMPARISON.md](THREE_WAY_COMPARISON.md)**: パラメータ3設定比較
- **[PROFITABILITY_SUMMARY.md](PROFITABILITY_SUMMARY.md)**: 収益性分析

---

## 📝 ライセンス

個人利用のみ。商用利用禁止。

## 🙏 謝辞

- [Twelve Data API](https://twelvedata.com/) - 市場データ提供
- [LINE Messaging API](https://developers.line.biz/) - 通知機能

---

**作成日**: 2026年2月15日
**バージョン**: V4統合版（みんなのFX完全対応）
**推奨設定**: ATR 1.0 × リスク 0.5% × EUR/JPY + USD/JPY

