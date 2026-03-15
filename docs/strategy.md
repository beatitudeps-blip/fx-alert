# strategy.md
## FX半システム運用 戦略仕様書
### 週足フィルター付き・日足EMA20押し戻り戦略

---

## 1. 目的
本戦略は、みんなのFXでの半システム運用を前提に、週足で大局を絞り、日足で押し目・戻りだけを狙う順張り戦略を実装するための仕様である。

目的は以下。
- 無理なエントリーを減らす
- 大負けを避ける
- 再現性のあるルールで運用する
- 実績を記録し、改善可能な形にする
- まずは安定運用を作り、その先で年20%前後を目指す

---

## 2. 対象通貨
当面の対象通貨は以下の3通貨とする。

- USD/JPY
- AUD/JPY

通貨追加は、既存2通貨で十分な検証と実運用実績が出てから行う。

---

## 3. 使用時間足
- 週足: 大局フィルター
- 日足: エントリー判断
- 執行: 翌営業日ベース

---

## 4. 使用指標
- Weekly EMA20
- Daily EMA20
- Daily ATR14

ATRは日足ベースで計算する。

---

## 5. 戦略の基本思想
本戦略は、以下の考え方に基づく。

- 週足と日足が同方向のときだけ入る
- 日足EMA20近辺までの押し・戻りのみを狙う
- 伸び切った場所を追いかけない
- 逆張りしない
- 両建てしない
- 同一通貨の重複エントリーをしない
- 見送りも重要な判断として保存する

---

## 6. トレンド判定

### 6.1 週足トレンド

#### WEEKLY_UP
以下をすべて満たすこと。
- Weekly Close > Weekly EMA20
- Weekly EMA20 slope > 0

#### WEEKLY_DOWN
以下をすべて満たすこと。
- Weekly Close < Weekly EMA20
- Weekly EMA20 slope < 0

#### WEEKLY_NEUTRAL
上記以外。

### 6.2 日足トレンド

#### DAILY_UP
以下をすべて満たすこと。
- Daily Close > Daily EMA20
- Daily EMA20 slope > 0

#### DAILY_DOWN
以下をすべて満たすこと。
- Daily Close < Daily EMA20
- Daily EMA20 slope < 0

#### DAILY_NEUTRAL
上記以外。

### 6.3 EMA slope の定義
EMA slope は以下で定義する。

```text
ema20_today - ema20_yesterday
```

* `> 0` の場合は上向き
* `< 0` の場合は下向き
* `= 0` の場合は横ばい扱い

---

## 7. 売買方向ルール

### BUY only

以下をすべて満たすこと。

* WEEKLY_UP
* DAILY_UP

### SELL only

以下をすべて満たすこと。

* WEEKLY_DOWN
* DAILY_DOWN

### NO TRADE

以下のいずれか。

* 週足と日足が不整合
* 週足がNEUTRAL
* 日足がNEUTRAL
* 重要な見送り条件に該当

---

## 8. EMA20距離フィルター

### 8.1 有効範囲

押し・戻りの有効条件として、EMA20からの距離が以下の範囲内であること。

```text
0.2 * ATR14 <= abs(Daily Close - Daily EMA20) <= 1.2 * ATR14
```

下限（0.2 * ATR14）未満の場合：EMA20に近すぎてエントリー効率が悪い。
上限（1.2 * ATR14）超過の場合：乖離過大として見送り。理由コード `X`。

---

## 9. エントリーパターン

### 9.1 Bullish Engulfing

以下をすべて満たすこと。

* 当日足が陽線
* 前日足が陰線
* 当日実体が前日実体を完全に包む

実装条件例:

```text
today_close > today_open
prev_close < prev_open
today_open <= prev_close
today_close >= prev_open
```

### 9.2 Bearish Engulfing

以下をすべて満たすこと。

* 当日足が陰線
* 前日足が陽線
* 当日実体が前日実体を完全に包む

実装条件例:

```text
today_close < today_open
prev_close > prev_open
today_open >= prev_close
today_close <= prev_open
```

### 9.3 Bullish Pin Bar

以下をすべて満たすこと。

* 下ヒゲ >= 実体の 2.0 倍
* 上ヒゲ <= 実体の 0.5 倍
* 実体がローソク上部にある

実装上は以下の概念を用いる。

```text
body = abs(close - open)
upper_wick = high - max(open, close)
lower_wick = min(open, close) - low
```

条件:

```text
lower_wick >= 2.0 * body
upper_wick <= 0.5 * body
close > open
```

※ body が極端に小さい場合のゼロ除算には注意すること。

### 9.4 Bearish Pin Bar

以下をすべて満たすこと。

* 上ヒゲ >= 実体の 2.0 倍
* 下ヒゲ <= 実体の 0.5 倍
* 実体がローソク下部にある

条件:

```text
upper_wick >= 2.0 * body
lower_wick <= 0.5 * body
close < open
```

---

## 10. エントリー条件

### 10.1 BUY候補

以下をすべて満たすこと。

* WEEKLY_UP
* DAILY_UP
* EMA距離フィルター通過（0.2ATR <= 距離 <= 1.2ATR）
* Bullish Engulfing または Bullish Pin Bar が成立
* 追いかけエントリー条件に該当しない
* 週足抵抗フィルターに該当しない
* 既存ポジション条件に違反しない
* 総リスク上限に違反しない

### 10.2 SELL候補

以下をすべて満たすこと。

* WEEKLY_DOWN
* DAILY_DOWN
* EMA距離フィルター通過（0.2ATR <= 距離 <= 1.2ATR）
* Bearish Engulfing または Bearish Pin Bar が成立
* 追いかけエントリー条件に該当しない
* 週足支持フィルターに該当しない
* 既存ポジション条件に違反しない
* 総リスク上限に違反しない

### 10.3 エントリー価格（指値）

シグナル確定後、ATRオフセットによる指値エントリーを使用する。

```text
BUY:  entry_price = Daily Close - 0.25 * ATR14
SELL: entry_price = Daily Close + 0.25 * ATR14
```

翌営業日中に指値が約定しなかった場合はシグナル無効とする。

---

## 11. 追いかけエントリー回避

シグナル足の値幅が大きすぎる場合は、追いかけとみなして見送る。

条件:

```text
signal_range = signal_high - signal_low
signal_range > 1.5 * ATR14
```

上記に該当する場合は見送り。

理由コードは、初期版では `X` に含めてもよいが、必要に応じて将来専用コードを追加してもよい。

---

## 12. 週足の抵抗 / 支持フィルター

### 12.1 BUY時

以下に該当する場合は見送り。

```text
recent_12w_high - entry_price < 1R
```

ここで `recent_12w_high` は直近12週の最高値。
理由コードは `S`。

### 12.2 SELL時

以下に該当する場合は見送り。

```text
entry_price - recent_12w_low < 1R
```

ここで `recent_12w_low` は直近12週の最安値。
理由コードは `S`。

---

## 13. 損切り・利確

### 13.1 初期損切り

#### BUY

```text
SL = signal_low - 0.1 * ATR14
```

#### SELL

```text
SL = signal_high + 0.1 * ATR14
```

### 13.2 利確

* TP1 = 1.5R で 50% 利確
* TP2 = 3.0R で残り 50% 利確

### 13.3 TP1到達後のSL

TP1到達後は、残りポジションの損切りを建値へ移動する。

```text
SL = entry_price
```

初期版では `+0.2R` などにはせず、建値固定とする。

### 13.4 タイムストップ

TP1/TP2/SL いずれにも到達せず 7営業日が経過した場合、終値で強制決済する。

```text
holding_days >= 7 → TIME_STOP（終値決済）
```

* SL/TP が同一バーで到達した場合は SL/TP が優先
* exit_reason = `TIME_STOP`
* バックテスト検証済み: PF net 1.78（タイムストップなし 1.57 から改善）

### 13.5 指値注文有効期限

指値エントリーは 1日足バー（1営業日）のみ有効。翌日に約定しなかった場合はシグナル無効とする。

```text
order_expiry = 1 bar
```

* フォワードテストでは order_status = `EXPIRED` として記録

---

## 14. リスク管理

### 14.1 1トレードあたり

* 最大損失は口座残高の 0.5%

### 14.2 同時保有

* 最大 2通貨

### 14.3 総リスク

* JPYクロス全体の合計リスクは 1.0% まで

### 14.4 連敗管理

* 3連敗で新規停止
* 5連敗でロジック点検

---

## 15. ポジション管理ルール

* 両建て禁止
* 同一通貨の重複エントリー禁止
* 既存ポジションがある場合は新規シグナルを見送る
* 合計リスク超過時は見送る

理由コード:

* `O` = 既存ポジションあり
* `C` = 総リスク / 相関超過

---

## 16. 経済指標リスク

初期版では、経済指標リスクの自動判定は行わず、`manual_check` とする。

対象例:

* FOMC
* 米CPI
* 米雇用統計
* 日銀政策決定会合

初期版の扱い:

* 自動判定結果に `event_risk = manual_check` を出力
* 最終執行前にユーザーが確認する
* 見送り時は理由コード `E`

---

## 17. 見送り理由コード

本戦略で使う理由コードは以下。

* `W` = 週足環境NG
* `D` = 日足環境NG
* `A` = 週足 / 日足不整合
* `P` = パターン不成立
* `R` = RR不足
* `X` = EMA乖離大 / 値幅過大
* `S` = 週足抵抗 / 支持近い
* `E` = 重要イベント
* `O` = 既存ポジションあり
* `C` = 総リスク / 相関超過

---

## 18. 自動チェックシート出力項目

Claude Code は各通貨ごとに最低限以下を出力する。

* Weekly trend
* Daily trend
* Alignment
* Pullback to EMA20
* ATR distance
* Pattern detected
* Weekly room
* Existing position
* Correlation risk
* Event risk
* Final decision
* Reason codes

---

## 19. 執行タイミング

* 判定は日次1回
* GitHub Actions で UTC cron 実行
* 実行時に最新日足が更新済みかを確認する
* 未更新であれば判定しない

具体的な cron や時刻管理の詳細は `operations.md` に記載する。

---

## 20. 時刻管理の原則

* 内部時刻は UTC で保持
* 表示は JST
* バックテストとライブ判定は同じ日足定義を使う
* DST込みで固定時刻を決め打ちしない
* 判定の正本は市場データ提供元の足とする

詳細は `operations.md` に記載する。

---

## 21. 実績管理との関係

本戦略の結果は以下の3層で管理する。

* `signals`
* `raw_fills`
* `trades_summary`

列仕様の詳細は `data_spec.md` に記載する。

---

## 22. strategy_version

本戦略を実装する際は、すべての出力物に `strategy_version` を付与すること。

初期版の推奨値例:

```text
D1_W1_EMA20_PULLBACK_V1
```

---

## 23. 実装上の注意

* APIキーやトークンはコードやMarkdownに直書きしない
* Twelve Data 取得処理、LINE Messaging API 通知処理、GitHub Actions 基盤は既存資産を流用可能
* 戦略ロジック本体は新規作成とする
* 見送りも必ず保存する
* バックテストでは API を乱用せず、CSVベースで行う

---

## 24. フォワードテスト運用ルール

### 24.1 停止ルール

* **6連敗で一時停止**: 新規エントリーを停止し、戦略の状態を確認する
* **DD 10%超で一時停止**: 口座残高が初期資金から10%以上減少した場合、新規停止
* **最初の20トレードはパラメータ変更禁止**: 統計的に有意なサンプルが集まるまで変更しない

### 24.2 記録項目

フォワードテスト中は以下をすべて記録する（`forward_test_log.csv`）:

* signal_id, pair, signal_date
* order_status: PENDING → FILLED / EXPIRED
* filled_date, filled_price
* exit_date, exit_price, exit_reason (SL / BE / TP2 / TIME_STOP)
* holding_days
* pnl_r, pnl_jpy
* tp1_reached, tp1_date

### 24.3 イベントリスク確認

以下の主要イベント前は手動確認を行う（`event_risk = manual_check`）:

* FOMC（米連邦公開市場委員会）
* US CPI（米消費者物価指数）
* US NFP（米雇用統計）
* BOJ（日銀政策決定会合）
* RBA（豪州準備銀行）

将来的にはカレンダーAPI連携で自動判定する。

---

## 25. 今後の拡張候補

初期版では以下は見送るが、将来拡張候補とする。

* Inside Bar の追加
* 経済指標カレンダーの自動連携
* 週足支持抵抗の高度検出
* 通貨間相関の高度評価
* +0.2R などの動的ストップ調整
* トレーリングストップ

---

## 26. 最終方針

初期版はシンプル・明確・再現性重視で実装する。
曖昧な裁量はできるだけ排除し、必要な裁量は `manual_check` として明示する。

このファイルは戦略仕様の正本であり、実装時にルール変更する場合は必ず更新すること。
