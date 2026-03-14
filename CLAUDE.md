# CLAUDE.md

## 1. 目的

このリポジトリは、**みんなのFXでの半システム運用**を前提とした、**週足フィルター付き・日足EMA20押し戻り戦略**を実装・運用する。

Claude Code はこのファイルを常時前提として扱い、詳細仕様は `docs/` 配下を参照すること。

詳細参照先:

* 戦略詳細: `docs/strategy.md`
* データ仕様: `docs/data_spec.md`
* 運用方針: `docs/operations.md`
* 実装計画: `docs/implementation_plan.md`

---

## 2. 実装方針

### 基本方針

* 既存の **V4.1（4H足戦略）を全破棄しない**
* **共通部品は流用**し、**日足/週足の戦略ロジックは新規作成**する

### 流用するもの

* Twelve Data 取得処理
* LINE Messaging API 通知処理
* GitHub Actions の基本枠
* ログ出力共通関数
* 環境変数 / Secrets 読み込み

### 新規作成するもの

* 週足 / 日足判定ロジック
* 日足シグナル生成
* `signals` / `raw_fills` / `trades_summary` 集約
* `weekly_review.md` / `monthly_review.md`
* 日足用通知文面
* `strategy_version` 管理

---

## 3. 戦略の中核ルール

### 対象通貨

* USD/JPY
* EUR/JPY
* GBP/JPY

### 使用時間足

* 週足: 大局フィルター
* 日足: エントリー判断

### 使用指標

* Weekly EMA20
* Daily EMA20
* Daily ATR14

### トレンド方向

#### BUY only

* Weekly Close > Weekly EMA20
* Weekly EMA20 slope > 0
* Daily Close > Daily EMA20
* Daily EMA20 slope > 0

#### SELL only

* Weekly Close < Weekly EMA20
* Weekly EMA20 slope < 0
* Daily Close < Daily EMA20
* Daily EMA20 slope < 0

#### NO TRADE

* 上記以外

### EMA slope 定義

* `ema20_today - ema20_yesterday`
* `> 0` で上向き
* `< 0` で下向き

### EMA20近辺の定義

* `abs(Daily Close - Daily EMA20) <= 0.5 * ATR14`

### EMA乖離過大

* `abs(Daily Close - Daily EMA20) > 1.0 * ATR14` → `SKIP [X]`

### パターン定義

#### Bullish Engulfing

* 当日足が陽線
* 前日足が陰線
* 当日実体が前日実体を完全に包む

#### Bearish Engulfing

* 当日足が陰線
* 前日足が陽線
* 当日実体が前日実体を完全に包む

#### Bullish Pin Bar

* 下ヒゲ >= 実体の 2.0 倍
* 上ヒゲ <= 実体の 0.5 倍
* 実体がローソク上部

#### Bearish Pin Bar

* 上ヒゲ >= 実体の 2.0 倍
* 下ヒゲ <= 実体の 0.5 倍
* 実体がローソク下部

### 追いかけエントリー回避

* `signal_range > 1.5 * ATR14` → 見送り

### 週足抵抗/支持フィルター

* BUY時: 直近12週高値までの余地が 1R 未満 → `SKIP [S]`
* SELL時: 直近12週安値までの余地が 1R 未満 → `SKIP [S]`

---

## 4. 損切り・利確・リスク管理

### 損切り

* BUY: シグナル足安値 - 0.1ATR
* SELL: シグナル足高値 + 0.1ATR

### 利確

* TP1 = 1R で 50% 利確
* TP2 = 2R で残り 50% 利確
* TP1 到達後、SL は **建値へ移動**

### リスク

* 1トレード最大損失: 口座残高の 0.5%
* 同時保有: 最大2通貨
* JPYクロス合計リスク: 1.0%まで
* 3連敗で新規停止
* 5連敗でロジック点検

---

## 5. 見送り理由コード

* W = 週足環境NG
* D = 日足環境NG
* A = 週足 / 日足不整合
* P = パターン不成立
* R = RR不足
* X = EMA乖離大
* S = 週足抵抗 / 支持近い
* E = 重要イベント
* O = 既存ポジションあり
* C = 総リスク / 相関超過

**重要:**

* 経済指標リスクは初期版では `manual_check` 扱いでよい
* 「見送り」も必ず成果物として保存する

---

## 6. データと正本

### 判定の正本

* Twelve Data 等の市場データ

### 実績の正本

* みんなのFX 約定履歴CSV

### 実績データの3層

* `signals`
* `raw_fills`
* `trades_summary`

### 必須差分管理

* SignalEntry
* ActualEntry
* EntrySlippage
* SignalGeneratedAt
* NotificationSentAt
* OrderSubmittedAt
* ActualFilledAt

---

## 7. 時刻管理

* 内部時刻は UTC で保持する
* 表示は JST に変換する
* バックテストとライブ判定は同じ日足定義を使う
* DST 前提で固定時刻を決め打ちしない
* 実行時は「時刻固定」よりも「最新日足更新確認」を優先する

### 実行スケジュール方針

* 日次判定は 1日1回
* GitHub Actions は UTC cron で実行
* 実行時に最新日足が更新済みかを確認し、未更新なら判定しない

---

## 8. 秘密情報の扱い

**APIキーやトークンはこのファイルに書かない。**

このリポジトリでは、秘密情報は GitHub Secrets / 環境変数で管理する。

想定環境変数:

* `TWELVE_DATA_API_KEY`
* `LINE_CHANNEL_ACCESS_TOKEN`
* `LINE_CHANNEL_SECRET`
* `LINE_USER_ID` または `LINE_TO`

禁止事項:

* API Key の直書き
* Access Token の直書き
* Channel Secret の直書き
* 個人識別子の生値記載

---

## 9. GitHub Actions / 実装ルール

* `concurrency` を設定し、重複起動を防止する
* ライブ判定 workflow とバックテスト workflow は分離する
* バックテストで API を乱用しない
* 失敗時はログを残す
* `strategy_version` を全出力物に残す
* 判定ロジックとレポートロジックは分離する

---

## 10. 最低限の出力物

* `signals.csv`
* `daily_signal_report.md`
* `raw_fills.csv`
* `trades_summary.csv`
* `weekly_review.md`
* `monthly_review.md`
* 障害ログ

---

## 11. 次の実装順序

1. 日足 / 週足判定ロジック実装
2. シグナル出力と通知実装
3. みんなのFX CSV 取込
4. `raw_fills` / `trades_summary` 集約
5. 週次 / 月次レポート生成
6. Google Sheets / NotebookLM 連携

---

## 12. 実装上の優先順位

次フェーズで優先すべきは戦略追加ではなく、**運用基盤整備** である。

優先順位:

1. 判定基準の固定
2. みんなのFX 実績取込
3. シグナルと実約定の差分管理
4. レポート自動化
5. 障害時運用の明確化
