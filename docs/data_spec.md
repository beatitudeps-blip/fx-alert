# data_spec.md
## FX半システム運用 データ仕様書

---

## 1. 目的
本ファイルは、FX半システム運用におけるデータ保存・集計・レポート生成の仕様を定義する。

対象は以下。
- シグナル記録
- 約定生データ記録
- トレード集約データ記録
- 日次 / 週次 / 月次レポート
- 障害ログ
- Google Sheets 連携用データ

本ファイルは `strategy.md` の戦略仕様を実装・記録するためのデータ正本仕様である。

---

## 2. 基本方針

### 2.1 データの3層構造
実績管理は以下の3層で行う。

1. `signals`
2. `raw_fills`
3. `trades_summary`

### 2.2 正本
- 判定の正本: 市場データ提供元（例: Twelve Data）
- 実績の正本: みんなのFX 約定履歴CSV

### 2.3 時刻
- 内部保持: UTC
- 表示用: JST
- CSVには原則として UTC と JST の両方を持たず、内部正本列を UTC とする
- ユーザー向け Markdown レポートでは JST 表示を許可する

### 2.4 strategy_version
すべての主要出力物に `strategy_version` を付与すること。

初期推奨値:
- `D1_W1_EMA20_PULLBACK_V1`

### 2.5 エンコーディング
- 文字コード: UTF-8
- 改行コード: LF
- 区切り文字: カンマ `,`
- 小数点: `.`

---

## 3. 共通ルール

### 3.1 命名
CSVファイル名の基本形は以下とする。

- `signals.csv`
- `raw_fills.csv`
- `trades_summary.csv`
- `error_log.csv`

日次・週次・月次 Markdown の基本形は以下とする。

- `daily_signal_report_YYYYMMDD.md`
- `weekly_review_YYYYMMDD.md`
- `monthly_review_YYYYMM.md`

### 3.2 通貨ペア表記
通貨ペアは以下のいずれかに統一すること。

推奨:
- `USDJPY`
- `EURJPY`
- `GBPJPY`

表示用 Markdown では `USD/JPY` などに整形してもよいが、CSV正本は `USDJPY` 形式を推奨する。

### 3.3 売買方向
- `BUY`
- `SELL`

### 3.4 シグナル判定
- `ENTRY_OK`
- `SKIP`
- `NO_DATA`
- `ERROR`

### 3.5 トレード結果
- `WIN`
- `LOSS`
- `BREAKEVEN`
- `PARTIAL_WIN`
- `OPEN`
- `CANCELLED`

---

## 4. signals.csv 仕様

### 4.1 目的
`signals.csv` は、各実行時点における通貨ごとのシグナル判定結果を保存する。
エントリーの有無だけでなく、見送り理由も必ず残す。

### 4.2 単位
- 1行 = 1回の判定実行 × 1通貨

たとえば3通貨を日次判定した場合、1日あたり最大3行追加される。

### 4.3 列定義

| 列名 | 型 | 必須 | 説明 |
|---|---|---:|---|
| signal_id | string | 必須 | シグナルID。一意キー |
| run_id | string | 必須 | 実行単位ID |
| strategy_version | string | 必須 | 戦略バージョン |
| generated_at_utc | datetime | 必須 | 判定生成時刻 UTC |
| generated_date_jst | date | 必須 | 表示用のJST日付 |
| pair | string | 必須 | 通貨ペア |
| weekly_trend | string | 必須 | `WEEKLY_UP`, `WEEKLY_DOWN`, `WEEKLY_NEUTRAL` |
| daily_trend | string | 必須 | `DAILY_UP`, `DAILY_DOWN`, `DAILY_NEUTRAL` |
| alignment | string | 必須 | `BUY_ONLY`, `SELL_ONLY`, `NO_TRADE` |
| close_price | float | 必須 | 判定足終値 |
| daily_ema20 | float | 必須 | 日足EMA20 |
| weekly_ema20 | float | 必須 | 週足EMA20 |
| atr14 | float | 必須 | 日足ATR14 |
| ema_distance_abs | float | 必須 | `abs(close - daily_ema20)` |
| ema_distance_atr_ratio | float | 必須 | `ema_distance_abs / atr14` |
| pullback_ok | boolean | 必須 | EMA20近辺条件を満たすか |
| pattern_name | string | 必須 | `BULLISH_ENGULFING`, `BEARISH_ENGULFING`, `BULLISH_PIN_BAR`, `BEARISH_PIN_BAR`, `NONE` |
| pattern_detected | boolean | 必須 | パターン成立有無 |
| signal_high | float | 任意 | シグナル足高値 |
| signal_low | float | 任意 | シグナル足安値 |
| signal_range | float | 任意 | `signal_high - signal_low` |
| signal_range_atr_ratio | float | 任意 | `signal_range / atr14` |
| weekly_room_price | float | 任意 | 週足抵抗/支持までの余地価格 |
| weekly_room_r | float | 任意 | 週足余地をR換算した値 |
| event_risk | string | 必須 | 初期版は `manual_check` |
| position_status | string | 必須 | `NO_POSITION`, `POSITION_EXISTS` |
| correlation_risk | string | 必須 | `OK`, `EXCEEDED`, `NOT_CHECKED` |
| decision | string | 必須 | `ENTRY_OK`, `SKIP`, `NO_DATA`, `ERROR` |
| reason_codes | string | 必須 | 見送り理由コードを `;` 区切りで保存 |
| entry_side | string | 任意 | `BUY`, `SELL`, 空欄 |
| planned_entry_price | float | 任意 | 想定エントリー価格 |
| planned_sl_price | float | 任意 | 想定SL価格 |
| planned_tp1_price | float | 任意 | 想定TP1価格 |
| planned_tp2_price | float | 任意 | 想定TP2価格 |
| planned_risk_pips | float | 任意 | 1R相当のpips |
| planned_risk_price | float | 任意 | 1R相当の価格差 |
| planned_risk_jpy | float | 任意 | 想定損失額 |
| planned_lot | float | 任意 | 想定ロット/数量 |
| signal_note | string | 任意 | 備考 |
| source_data_timestamp_utc | datetime | 任意 | 使用した最新足の時刻 |
| created_by | string | 任意 | 生成元識別子 |
| updated_at_utc | datetime | 任意 | 更新時刻 |

### 4.4 主キー
- 主キー: `signal_id`

### 4.5 推奨 signal_id 形式
以下のような一意な形式を推奨する。

```text
{strategy_version}_{pair}_{generated_at_utc}
```

例:

```text
D1_W1_EMA20_PULLBACK_V1_USDJPY_2026-03-14T22:10:00Z
```

### 4.6 reason_codes のルール

複数理由は `;` 区切りで保存する。

例:

```text
A;S
P
X;E
```

理由がない場合:

* `ENTRY_OK` の場合は空欄でもよい
* または `NONE` としてもよい
* 実装ではどちらかに統一すること。推奨は空欄

---

## 5. raw_fills.csv 仕様

### 5.1 目的

`raw_fills.csv` は、みんなのFXの約定履歴CSVを取り込んだ生データ、または生データを標準化した正本テーブルである。

### 5.2 単位

* 1行 = 1約定

分割決済がある場合、約定ごとに複数行になる。

### 5.3 列定義

| 列名 | 型 | 必須 | 説明 |
|---|---|---:|---|
| fill_id | string | 必須 | 約定行ID。一意キー |
| broker | string | 必須 | `MINNA_NO_FX` |
| broker_account_name | string | 任意 | 口座識別名 |
| broker_raw_file_name | string | 任意 | 取込元ファイル名 |
| broker_raw_row_no | integer | 任意 | 取込元行番号 |
| imported_at_utc | datetime | 必須 | 取込時刻 UTC |
| execution_time_utc | datetime | 必須 | 約定時刻 UTC |
| execution_time_jst | datetime | 任意 | 約定時刻 JST 表示用 |
| pair | string | 必須 | 通貨ペア |
| side | string | 必須 | `BUY` or `SELL` |
| fill_type | string | 必須 | `ENTRY`, `EXIT`, `PARTIAL_EXIT`, `STOP_EXIT`, `TAKE_PROFIT_EXIT`, `OTHER` |
| quantity | float | 必須 | 約定数量 |
| price | float | 必須 | 約定価格 |
| gross_realized_pnl_jpy | float | 任意 | 手数料等控除前損益 |
| net_realized_pnl_jpy | float | 任意 | 最終損益 |
| swap_jpy | float | 任意 | スワップ |
| fee_jpy | float | 任意 | 手数料 |
| commission_jpy | float | 任意 | 手数料詳細がある場合 |
| order_type | string | 任意 | `MARKET`, `LIMIT`, `STOP`, `OCO`, `IFD`, `IFO`, `UNKNOWN` |
| broker_position_id | string | 任意 | ブローカー側ポジションID |
| broker_order_id | string | 任意 | ブローカー側注文ID |
| broker_deal_id | string | 任意 | ブローカー側約定ID |
| trade_group_id | string | 任意 | 1トレードに束ねるための内部ID |
| matched_signal_id | string | 任意 | 対応する signal_id |
| strategy_version | string | 任意 | 取込時に判定可能なら格納 |
| import_status | string | 必須 | `IMPORTED`, `PARSE_ERROR`, `DUPLICATE`, `MATCHED`, `UNMATCHED` |
| import_note | string | 任意 | 備考 |
| created_by | string | 任意 | 生成元識別子 |
| updated_at_utc | datetime | 任意 | 更新時刻 |

### 5.4 主キー

* 主キー: `fill_id`

### 5.5 推奨 fill_id 形式

ブローカーの一意キーがあればそれを優先し、なければ内部生成する。

例:

```text
MINNA_NO_FX_USDJPY_2026-03-15T00:05:10Z_BUY_1000_156.235
```

---

## 6. trades_summary.csv 仕様

### 6.1 目的

`trades_summary.csv` は、複数の約定行を1トレード単位で集約した実績正本である。
分析・KPI計算・月次レビューの基準データとする。

### 6.2 単位

* 1行 = 1トレード

ここで1トレードとは、1つのシグナルから開始された建玉と、その全部分決済をまとめた単位を指す。

### 6.3 列定義

| 列名 | 型 | 必須 | 説明 |
|---|---|---:|---|
| trade_id | string | 必須 | トレードID。一意キー |
| signal_id | string | 任意 | 紐付く signal_id |
| run_id | string | 任意 | シグナル実行ID |
| strategy_version | string | 必須 | 戦略バージョン |
| pair | string | 必須 | 通貨ペア |
| side | string | 必須 | `BUY` or `SELL` |
| status | string | 必須 | `OPEN`, `CLOSED`, `CANCELLED` |
| result | string | 必須 | `WIN`, `LOSS`, `BREAKEVEN`, `PARTIAL_WIN`, `OPEN`, `CANCELLED` |
| signal_generated_at_utc | datetime | 任意 | シグナル生成時刻 |
| notification_sent_at_utc | datetime | 任意 | 通知送信時刻 |
| order_submitted_at_utc | datetime | 任意 | 発注時刻 |
| entry_time_utc | datetime | 任意 | 初回エントリー約定時刻 |
| exit_time_utc | datetime | 任意 | 最終決済時刻 |
| pair_trade_date_jst | date | 任意 | JSTベースの管理日 |
| entry_price_planned | float | 任意 | 想定エントリー価格 |
| entry_price_actual | float | 任意 | 実約定平均エントリー価格 |
| entry_slippage | float | 任意 | `actual - planned` |
| initial_sl_price | float | 任意 | 初期SL価格 |
| tp1_price | float | 任意 | TP1価格 |
| tp2_price | float | 任意 | TP2価格 |
| breakeven_sl_enabled | boolean | 任意 | TP1後建値移動の有無 |
| total_entry_quantity | float | 任意 | 総エントリー数量 |
| total_exit_quantity | float | 任意 | 総決済数量 |
| remaining_quantity | float | 任意 | 残数量 |
| risk_price | float | 任意 | 1Rの価格差 |
| risk_pips | float | 任意 | 1Rのpips |
| risk_jpy_planned | float | 任意 | 想定損失額 |
| risk_jpy_actual | float | 任意 | 実損失ベースの1R換算用 |
| gross_pnl_jpy | float | 任意 | 総損益（控除前） |
| net_pnl_jpy | float | 任意 | 総損益（控除後） |
| pnl_r | float | 任意 | `net_pnl_jpy / risk_jpy_planned` |
| swap_jpy | float | 任意 | 合計スワップ |
| fee_jpy | float | 任意 | 合計手数料 |
| max_favorable_excursion | float | 任意 | MFE |
| max_adverse_excursion | float | 任意 | MAE |
| exit_reason | string | 任意 | `TP1_TP2`, `TP1_BE`, `SL`, `MANUAL_EXIT`, `TIME_EXIT`, `UNKNOWN` |
| tp1_hit | boolean | 任意 | TP1到達有無 |
| tp2_hit | boolean | 任意 | TP2到達有無 |
| sl_hit | boolean | 任意 | SL到達有無 |
| rule_violation | boolean | 必須 | ルール逸脱有無 |
| violation_note | string | 任意 | 逸脱内容 |
| event_risk_checked | string | 任意 | `YES`, `NO`, `MANUAL`, `UNKNOWN` |
| decision_source | string | 任意 | `AUTO`, `MANUAL_APPROVED`, `MANUAL_SKIPPED` |
| notes | string | 任意 | 備考 |
| created_at_utc | datetime | 任意 | 作成時刻 |
| updated_at_utc | datetime | 任意 | 更新時刻 |

### 6.4 主キー

* 主キー: `trade_id`

### 6.5 推奨 trade_id 形式

```text
{strategy_version}_{pair}_{entry_time_utc}_{side}
```

例:

```text
D1_W1_EMA20_PULLBACK_V1_USDJPY_2026-03-15T00:05:10Z_BUY
```

---

## 7. signals と raw_fills と trades_summary の紐付けルール

### 7.1 基本方針

* `signals` は判定記録
* `raw_fills` は約定記録
* `trades_summary` は分析記録

### 7.2 推奨紐付け順

1. `signal_id` を基準に、エントリー候補を定義する
2. 発注・約定が発生したら、その約定群に `matched_signal_id` を付ける
3. その `matched_signal_id` をキーに `trade_id` を生成する
4. 部分決済は同一 `trade_id` に集約する

### 7.3 シグナル未約定

シグナルが出ても約定しなかった場合は、`signals.csv` には残し、`trades_summary.csv` には行を作らないか、必要に応じて `CANCELLED` として作成してもよい。
初期版は以下を推奨する。

* 約定なし → `signals` のみ記録
* 実トレードとしては集約しない

---

## 8. daily_signal_report.md 仕様

### 8.1 目的

日次の判定結果を、人が読みやすい形でまとめる。

### 8.2 単位

* 1ファイル = 1日 = 1回の実行

### 8.3 含める内容

最低限以下を含める。

* 実行日時
* strategy_version
* 対象通貨一覧
* 各通貨の判定結果
* ENTRY_OK / SKIP / NO_DATA / ERROR
* 理由コード
* エントリー候補の価格情報
* event_risk の状態
* 備考

### 8.4 推奨構成

```text
# Daily Signal Report

- Run At (UTC):
- Run Date (JST):
- Strategy Version:

## Summary
- Total Pairs:
- Entry OK:
- Skip:
- No Data:
- Error:

## Pair Details
### USDJPY
- Weekly Trend:
- Daily Trend:
- Alignment:
- Pattern:
- Decision:
- Reason Codes:
- Planned Entry:
- Planned SL:
- Planned TP1:
- Planned TP2:
- Event Risk:

### EURJPY
...
```

---

## 9. weekly_review.md 仕様

### 9.1 目的

週次の実績・シグナル状況・見送り理由傾向をまとめる。

### 9.2 単位

* 1ファイル = 1週間

### 9.3 含める内容

* 対象期間
* strategy_version
* シグナル総数
* ENTRY_OK数
* SKIP数
* 実トレード数
* 勝率
* 総損益
* 総R
* 平均R
* 理由コード別件数
* 通貨別成績
* ルール違反有無
* 次週への注意点

### 9.4 推奨構成

```text
# Weekly Review

- Period:
- Strategy Version:

## KPI
- Signals:
- Entry OK:
- Skip:
- Executed Trades:
- Win Rate:
- Gross PnL:
- Net PnL:
- Total R:
- Average R:

## By Pair
- USDJPY:
- EURJPY:
- GBPJPY:

## Skip Reason Breakdown
- A:
- P:
- X:
- S:
...

## Rule Violations
- Count:
- Details:

## Notes
- ...
```

---

## 10. monthly_review.md 仕様

### 10.1 目的

月次の成績を集計し、改善判断に使う。

### 10.2 単位

* 1ファイル = 1か月

### 10.3 含める内容

* 対象月
* strategy_version
* 月間シグナル数
* 月間実トレード数
* 勝率
* PF
* 総損益
* 総R
* 平均利益
* 平均損失
* 最大利益
* 最大損失
* 最大連敗
* 最大DD
* 通貨別成績
* 理由コード別件数
* ルール逸脱一覧
* 改善候補

### 10.4 推奨構成

```text
# Monthly Review

- Month:
- Strategy Version:

## KPI
- Signals:
- Executed Trades:
- Win Rate:
- Profit Factor:
- Gross PnL:
- Net PnL:
- Total R:
- Average Win:
- Average Loss:
- Max Win:
- Max Loss:
- Max Losing Streak:
- Max Drawdown:

## By Pair
- USDJPY:
- EURJPY:
- GBPJPY:

## Skip Reason Breakdown
...

## Rule Violations
...

## Improvement Candidates
1.
2.
3.
```

---

## 11. error_log.csv 仕様

### 11.1 目的

障害・失敗・異常状態を保存し、無通知や無記録を防ぐ。

### 11.2 単位

* 1行 = 1エラー / 1異常イベント

### 11.3 列定義

| 列名 | 型 | 必須 | 説明 |
|---|---|---:|---|
| error_id | string | 必須 | エラーID |
| run_id | string | 任意 | 実行単位ID |
| strategy_version | string | 任意 | 戦略バージョン |
| occurred_at_utc | datetime | 必須 | 発生時刻 |
| stage | string | 必須 | `DATA_FETCH`, `SIGNAL_BUILD`, `NOTIFY`, `IMPORT`, `AGGREGATE`, `REPORT`, `UNKNOWN` |
| severity | string | 必須 | `INFO`, `WARN`, `ERROR`, `FATAL` |
| error_type | string | 必須 | エラー種別 |
| pair | string | 任意 | 通貨ペア |
| message | string | 必須 | エラーメッセージ |
| detail | string | 任意 | 詳細 |
| retry_count | integer | 任意 | 再試行回数 |
| resolved | boolean | 任意 | 解消済みか |
| resolved_at_utc | datetime | 任意 | 解消時刻 |
| created_by | string | 任意 | 生成元識別子 |

### 11.4 主キー

* 主キー: `error_id`

---

## 12. Google Sheets 連携用テーブル方針

### 12.1 シート構成

以下のシート名を推奨する。

* `signals`
* `raw_fills`
* `trades_summary`
* `dashboard`

### 12.2 dashboard 用KPI

最低限以下を出せるようにする。

* 月間損益
* 累積損益
* 総R
* 勝率
* PF
* 最大DD
* 最大連敗
* 通貨別成績
* 理由コード別件数

---

## 13. 値の扱いルール

### 13.1 boolean

CSV上は以下のどちらかに統一すること。

* `TRUE` / `FALSE`
  または
* `1` / `0`

推奨:

* `TRUE` / `FALSE`

### 13.2 空値

* 値がない場合は空欄
* `NULL` 文字列は原則使わない

### 13.3 数値丸め

* 価格: 3〜5桁精度は通貨仕様に応じて保持
* 金額: 小数2桁まででよい
* R値: 小数第3位程度まで保持可

---

## 14. 計算ルール

### 14.1 ema_distance_abs

```text
abs(close_price - daily_ema20)
```

### 14.2 ema_distance_atr_ratio

```text
ema_distance_abs / atr14
```

### 14.3 signal_range

```text
signal_high - signal_low
```

### 14.4 signal_range_atr_ratio

```text
signal_range / atr14
```

### 14.5 entry_slippage

```text
entry_price_actual - entry_price_planned
```

BUY / SELLで解釈差があるため、分析用途では別途不利方向スリッページ指標を追加してもよい。
初期版は単純差分でよい。

### 14.6 pnl_r

```text
net_pnl_jpy / risk_jpy_planned
```

---

## 15. 初期版で必須の列

実装初期フェーズで最低限必要なのは以下。

### signals.csv

* signal_id
* run_id
* strategy_version
* generated_at_utc
* pair
* weekly_trend
* daily_trend
* alignment
* close_price
* daily_ema20
* atr14
* ema_distance_abs
* ema_distance_atr_ratio
* pullback_ok
* pattern_name
* pattern_detected
* event_risk
* decision
* reason_codes
* entry_side
* planned_entry_price
* planned_sl_price
* planned_tp1_price
* planned_tp2_price
* planned_risk_jpy
* planned_lot

### raw_fills.csv

* fill_id
* broker
* imported_at_utc
* execution_time_utc
* pair
* side
* fill_type
* quantity
* price
* net_realized_pnl_jpy
* swap_jpy
* fee_jpy
* order_type
* matched_signal_id
* import_status

### trades_summary.csv

* trade_id
* signal_id
* strategy_version
* pair
* side
* status
* result
* entry_time_utc
* exit_time_utc
* entry_price_planned
* entry_price_actual
* initial_sl_price
* tp1_price
* tp2_price
* risk_jpy_planned
* net_pnl_jpy
* pnl_r
* tp1_hit
* tp2_hit
* sl_hit
* exit_reason
* rule_violation

---

## 16. 将来拡張

将来必要に応じて以下を追加してよい。

* MFE / MAE の厳密管理
* 指標イベント自動判定列
* 通貨間相関指標
* 手動介入詳細
* 画像 / スクリーンショットへの参照
* 複数戦略対応用の strategy_family

---

## 17. 最終方針

このファイルは、FX半システム運用におけるデータ仕様の正本である。
列追加・削除・名称変更を行う場合は、実装と同時ではなく、必ず本ファイルを先に更新すること。
