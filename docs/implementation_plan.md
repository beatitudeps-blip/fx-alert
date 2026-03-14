# implementation_plan.md
## FX半システム運用 実装計画書

---

## 1. 目的
本ファイルは、FX半システム運用を既存の `fx-alert` リポジトリ上で段階的に実装するための計画を定義する。

対象は以下。
- 既存 V4.1 資産の扱い
- 新規実装範囲
- 実装順序
- フェーズ分割
- テスト方針
- リリース方針
- 運用開始条件

本ファイルは `CLAUDE.md`、`strategy.md`、`data_spec.md`、`operations.md` を実装タスクへ落とし込むための計画正本である。

---

## 2. 前提

### 2.1 リポジトリ前提
対象リポジトリは `fx-alert` とする。

既存資産として以下が存在する前提で進める。
- `src/`
- `scripts/`
- `.github/`
- 既存 V4.1 の4H足ロジック
- Twelve Data 取得処理
- LINE Messaging API 通知処理
- GitHub Actions 実行基盤

### 2.2 実装方針
- 既存 V4.1 を全破棄しない
- 共通部品は流用する
- 日足 / 週足戦略ロジックは新規実装する
- ライブ運用系とバックテスト系は分離する
- 仕様変更前に docs を更新する

---

## 3. 流用するもの

以下は既存資産を流用候補とする。

- Twelve Data API 呼び出し処理
- LINE Messaging API 送信処理
- GitHub Actions ワークフロー雛形
- Secrets / 環境変数読み込み処理
- 共通ログ処理
- 既存の設定読み込み処理
- 補助的なユーティリティ関数

流用時の原則:
- そのまま流用できるなら使う
- 戦略依存が強いものは共通化せず分離する
- 4H足戦略固有ロジックは持ち込まない

---

## 4. 新規作成するもの

以下は新規作成対象とする。

- 週足 / 日足トレンド判定ロジック
- EMA20近辺判定
- Engulfing / Pin Bar 検出
- 日足シグナル組み立て処理
- `signals.csv` 出力
- `daily_signal_report_YYYYMMDD.md` 出力
- みんなのFX 約定履歴CSV標準化処理
- `raw_fills.csv` 更新処理
- `trades_summary.csv` 集約処理
- `weekly_review_YYYYMMDD.md` 出力
- `monthly_review_YYYYMM.md` 出力
- `error_log.csv` 出力
- `strategy_version` の一貫管理
- 日足更新確認処理
- 実績とシグナルの紐付け処理

---

## 5. 推奨ディレクトリ方針

初期方針として、以下のような責務分離を推奨する。

```text
fx-alert/
  CLAUDE.md
  docs/
    strategy.md
    data_spec.md
    operations.md
    implementation_plan.md
  src/
    common/
    daily_strategy/
    reporting/
    broker_import/
  scripts/
  data/
  tests/
  .github/workflows/
```

### 5.1 役割

* `src/common/`: API、通知、共通ユーティリティ
* `src/daily_strategy/`: 日足 / 週足判定ロジック
* `src/reporting/`: 日次 / 週次 / 月次レポート生成
* `src/broker_import/`: みんなのFX CSV取込
* `data/`: ローカル検証用の中間ファイルやバックテスト用CSV
* `tests/`: テストコード
* `.github/workflows/`: GitHub Actions

---

## 6. 実装フェーズ全体像

### フェーズ1

シグナル生成基盤を作る。

* 日足 / 週足判定
* シグナル生成
* 日次通知
* `signals.csv`
* `daily_signal_report`

### フェーズ2

実績記録基盤を作る。

* みんなのFX CSV取込
* `raw_fills.csv`
* `trades_summary.csv`
* シグナルとの紐付け

### フェーズ3

レビュー基盤を作る。

* `weekly_review.md`
* `monthly_review.md`
* Google Sheets 連携しやすい出力
* NotebookLM 投入しやすい出力

### フェーズ4

運用品質を上げる。

* エラーハンドリング強化
* 再試行強化
* テスト拡充
* 必要に応じて指標連携や高度化

---

## 7. フェーズ1 詳細

### 7.1 目的

戦略仕様どおりの日次シグナルを安定生成できるようにする。

### 7.2 完了条件

以下を満たしたら完了とする。

* 3通貨を対象に日次シグナル判定ができる
* `ENTRY_OK` / `SKIP` / `NO_DATA` / `ERROR` が出せる
* 理由コードが出せる
* `signals.csv` が保存される
* `daily_signal_report_YYYYMMDD.md` が出力される
* LINE通知が送れる
* `error_log.csv` に異常が残る

### 7.3 タスク

1. 既存 Twelve Data 取得処理の確認
2. 日足 / 週足データ取得関数の整備
3. EMA20 / ATR14 計算処理の確認または実装
4. WEEKLY / DAILY トレンド判定実装
5. Engulfing / Pin Bar 検出実装
6. EMA距離 / ATR比率計算実装
7. シグナル判定オブジェクト組み立て
8. `signals.csv` 出力実装
9. 日次レポートMarkdown生成実装
10. LINE通知実装
11. 日足更新確認実装
12. エラーログ実装
13. GitHub Actions `daily_signal.yml` 作成 / 修正

---

## 8. フェーズ2 詳細

### 8.1 目的

実績の正本を整備し、シグナルと約定を結び付けられるようにする。

### 8.2 完了条件

* みんなのFX CSV を取り込める
* `raw_fills.csv` が更新できる
* `fill_id` 重複防止がある
* `matched_signal_id` を付与できる
* `trade_id` を生成できる
* `trades_summary.csv` が生成できる
* TP1 / TP2 / SL / 建値移動の結果を集約できる

### 8.3 タスク

1. みんなのFX CSV の列調査
2. 生CSV → 標準化マッピング実装
3. `fill_id` 生成ルール実装
4. `raw_fills.csv` 更新処理実装
5. シグナルとの紐付けルール実装
6. `trade_id` 生成実装
7. 部分決済集約ロジック実装
8. `trades_summary.csv` 出力実装
9. import 用 workflow または script 作成
10. 取込失敗時の `error_log.csv` 実装

---

## 9. フェーズ3 詳細

### 9.1 目的

週次・月次の振り返りを自動生成できるようにする。

### 9.2 完了条件

* `weekly_review_YYYYMMDD.md` が生成される
* `monthly_review_YYYYMM.md` が生成される
* 勝率 / 総R / 総損益 / 理由コード別件数が集計できる
* 通貨別成績が出せる
* ルール違反有無を出せる

### 9.3 タスク

1. `signals.csv` 集計処理実装
2. `trades_summary.csv` 集計処理実装
3. 週次KPI集計実装
4. 月次KPI集計実装
5. 理由コード別件数集計実装
6. 通貨別成績集計実装
7. 週次レポートMarkdown生成実装
8. 月次レポートMarkdown生成実装
9. `weekly_review.yml` / `monthly_review.yml` 作成

---

## 10. フェーズ4 詳細

### 10.1 目的

安定運用できる品質まで引き上げる。

### 10.2 候補タスク

* エラー種別の精緻化
* 再試行制御の改善
* ログ出力の統一
* テストケース追加
* スリッページ分析強化
* MFE / MAE 管理追加
* event_risk の半自動化
* Sheets 連携自動化
* NotebookLM 投入用の要約テンプレート改善

---

## 11. 実装順序の推奨

最優先順は以下。

1. 日足 / 週足判定ロジック
2. シグナル出力
3. 日次通知
4. エラーログ
5. みんなのFX CSV取込
6. `raw_fills` / `trades_summary`
7. 週次 / 月次レビュー
8. 可視化 / 連携強化

理由:

* まずシグナルが出ないと運用が始まらない
* 次に実績がないと改善できない
* 最後に可視化や連携を整える

---

## 12. テスト方針

### 12.1 基本方針

* ロジック単体テストを優先する
* 外部APIや通知は結合テストで確認する
* バックテストはロジック妥当性確認用であり、単体テスト代替にはしない

### 12.2 最低限テストすべき対象

* WEEKLY_UP / DOWN / NEUTRAL 判定
* DAILY_UP / DOWN / NEUTRAL 判定
* Engulfing 判定
* Pin Bar 判定
* EMA距離判定
* 追いかけエントリー判定
* 週足抵抗 / 支持フィルター
* reason_codes の付与
* `signal_id` / `fill_id` / `trade_id` 生成
* `pnl_r` 計算
* CSV標準化処理

### 12.3 テストデータ

* 小さな固定サンプルOHLC
* 固定CSVサンプル
* TP1 / TP2 / SL / 建値移動を含むサンプル
* 見送りケースのサンプル

---

## 13. バックテスト方針

### 13.1 基本方針

* バックテストはライブ判定と同じロジックを使う
* ただしデータ取得は API ではなく CSV を使う
* 日足定義はライブと一致させる
* `strategy_version` を固定する

### 13.2 フェーズ

* フェーズ1完了後に簡易バックテスト
* フェーズ2完了後に実運用との差異確認
* フェーズ3完了後に週次 / 月次レビューと整合確認

### 13.3 出したい指標

* 勝率
* 総R
* 平均R
* PF
* 最大DD
* 最大連敗
* 通貨別成績
* 理由コード別見送り件数

---

## 14. workflow 方針

### 14.1 推奨workflow

* `daily_signal.yml`
* `import_broker_csv.yml`
* `weekly_review.yml`
* `monthly_review.yml`
* `backtest.yml`

### 14.2 原則

* ライブ運用系とバックテスト系は分離
* `concurrency` を必須化
* 失敗時はログを残す
* artifacts は最小限
* secrets は GitHub Secrets 管理

---

## 15. strategy_version 方針

### 15.1 基本方針

すべての主要出力物に `strategy_version` を持たせる。

初期値:

* `D1_W1_EMA20_PULLBACK_V1`

### 15.2 変更ルール

* 売買ルールが変わったら version を更新
* データ仕様だけの軽微修正なら version は維持でもよい
* 週次 / 月次レビューでは version を明示する

---

## 16. リリース方針

### 16.1 段階的リリース

* いきなり本番運用しない
* フェーズ1ではシグナルだけ確認してもよい
* フェーズ2で実績取込まで確認する
* フェーズ3でレビューまで回してから安定運用へ入る

### 16.2 最初の運用開始条件

以下を満たしたら開始してよい。

* `daily_signal.yml` が安定動作
* `signals.csv` が出る
* 通知が届く
* `error_log.csv` が出る
* 少なくとも1回、みんなのFX CSV取込が成功している

---

## 17. 完了判定

この計画の「初期完成」は、以下をすべて満たした状態とする。

* 日次シグナルが自動生成される
* LINE通知が届く
* 見送り理由が保存される
* みんなのFX CSV を標準化できる
* `raw_fills.csv` と `trades_summary.csv` が更新される
* 週次 / 月次レビューが生成される
* 主要エラーが `error_log.csv` に残る
* docs と実装の齟齬がない

---

## 18. Claude Code への実務指示

Claude Code は以下の順で進めること。

1. `CLAUDE.md` を前提として読む
2. `docs/strategy.md` を参照して売買ロジックを実装する
3. `docs/data_spec.md` を参照して CSV / Markdown 出力を実装する
4. `docs/operations.md` を参照して workflow / 時刻管理 / 障害時処理を実装する
5. 本ファイルの順番でフェーズを進める
6. 実装中に仕様変更が必要な場合、先に docs 更新案を出す
7. 仕様を暗黙に変更しない

---

## 19. 最終方針

このファイルは、FX半システム運用における実装計画の正本である。
実装順序、フェーズ、完了条件を変更する場合は、必ず本ファイルを先に更新すること。
