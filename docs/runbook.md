# Runbook

FX半システム運用 実運用手順書

戦略: D1_W1_EMA20_PULLBACK_V1
対象通貨: USD/JPY, EUR/JPY, GBP/JPY

---

## 1. 日次シグナル

### 1.1 自動実行 (GitHub Actions)

- `.github/workflows/daily_signal.yml` が UTC 22:30 (月〜金) に自動起動
- bar_checker が最新日足の更新を確認し、未更新なら判定しない
- 結果は `data/signals.csv` に追記、LINE通知を送信

### 1.2 手動実行

```bash
# dry-run (LINE通知なし)
python scripts/run_daily_signal.py --equity 500000 --dry-run

# 本番 (LINE通知あり)
python scripts/run_daily_signal.py --equity 500000

# 日足未更新でも強制実行
python scripts/run_daily_signal.py --equity 500000 --force
```

必須環境変数:

- `TWELVEDATA_API_KEY`
- `LINE_CHANNEL_ACCESS_TOKEN` (dry-run時は不要)
- `LINE_USER_ID` (dry-run時は不要)

### 1.3 出力物

- `data/signals.csv` — シグナル正本
- `data/error_log.csv` — エラーログ
- `data/daily_state.json` — 連敗数・ポジション状態
- `data/reports/daily_signal_report_YYYYMMDD.md` — 日次レポート

---

## 2. 通知時刻と DST

- cron は UTC 22:30 固定
- Forex 日足クローズは 17:00 ET (標準時 = UTC 22:00 / 夏時間 = UTC 21:00)
- 冬時間: 日足確定の約30分後に通知 (JST 07:30頃)
- 夏時間: 日足確定の約1.5時間後に通知 (JST 07:30頃)
- このズレは仕様として許容する
- bar_checker が日足更新を確認するため、未確定足での判定は起きない

---

## 3. みんなのFX CSV 取込

### 3.1 CSVの準備

1. みんなのFXにログイン
2. 約定履歴 → CSV ダウンロード
3. ダウンロードしたファイルを任意の場所に保存

### 3.2 取込実行

```bash
# 基本
python scripts/import_broker_csv.py path/to/minnafx_export.csv

# 戦略対象通貨のみ
python scripts/import_broker_csv.py path/to/minnafx_export.csv --strategy-only

# 出力先指定
python scripts/import_broker_csv.py path/to/minnafx_export.csv --output-dir data/
```

### 3.3 出力物

- `data/raw_fills.csv` — 約定データ (標準化済み)
- `data/trades_summary.csv` — トレード集約

### 3.4 注意

- 同じCSVを2回取り込んでも `fill_id` で重複排除される
- シグナルとの紐付けは `matched_signal_id` で自動マッチング
- パースエラーがあれば `error_log.csv` に記録される

---

## 4. 週次レビュー生成

```bash
# 指定日を含む週のレビューを生成
python scripts/generate_review.py weekly 2026-03-09

# 出力先指定
python scripts/generate_review.py weekly 2026-03-09 --output-dir reports/
```

出力: `data/reports/weekly_review_YYYYMMDD.md`

---

## 5. 月次レビュー生成

```bash
# 指定月のレビューを生成
python scripts/generate_review.py monthly 2026-03

# 出力先指定
python scripts/generate_review.py monthly 2026-03 --output-dir reports/
```

出力: `data/reports/monthly_review_YYYYMM.md`

月次レビューには Improvement Candidates (自動改善提案) が含まれる。

---

## 6. ERROR / NO_DATA 時の確認ポイント

### 6.1 NO_DATA

- 原因: Twelve Data API からデータ取得失敗、または日足未更新
- 確認: GitHub Actions のログで API レスポンスを確認
- 対応: 一時的なら次回実行で自動復旧。継続する場合は API キーやレート制限を確認

### 6.2 ERROR

- 原因: 判定ロジックの例外、通知失敗、CSV出力失敗など
- 確認:
  1. `data/error_log.csv` の `stage` / `severity` / `message` を確認
  2. GitHub Actions の実行ログを確認
- 対応:
  - `DATA_FETCH` → API キー / ネットワーク確認
  - `SIGNAL_BUILD` → ロジックバグの可能性。ログを確認し修正
  - `NOTIFY` → LINE トークン / ユーザーID を確認

### 6.3 無通知

- 「通知が来ない = シグナルなし」ではない
- GitHub Actions の実行履歴を必ず確認する
- workflow 自体が失敗していないか確認する

---

## 7. 実運用での最小確認手順

### 毎日 (平日)

1. LINE通知を確認
2. ENTRY_OK があれば:
   - 通貨ペア、方向、エントリー価格、SL、TP1、TP2、ロットを確認
   - event_risk (経済指標) を手動確認
   - みんなのFXで手動発注
3. 通知が来なければ:
   - GitHub Actions の実行履歴を確認
   - `data/error_log.csv` を確認

### 毎週

1. 週次レビューを生成して確認
2. 連敗数を確認 (3連敗で新規停止ルール)
3. ポジション状況を確認 (同時保有最大2通貨)

### 毎月

1. 月次レビューを生成して確認
2. Improvement Candidates を確認
3. 5連敗があればロジック点検
4. みんなのFX CSV を取り込み、シグナルと実績の差分を確認

---

## 8. 環境変数の管理

### ローカル実行

- `.env` ファイルに設定 (`.gitignore` 済み)
- `cp .env.example .env` でテンプレートから作成

### GitHub Actions

- リポジトリの Settings → Secrets and variables → Actions に設定
- 必要な Secrets:
  - `TWELVEDATA_API_KEY`
  - `LINE_CHANNEL_ACCESS_TOKEN`
  - `LINE_USER_ID`

### 禁止事項

- API Key / Token をコードや Markdown に直書きしない
- `.env` を git commit しない

---

## 9. 手動発注の手順

ENTRY_OK シグナルを受けたら:

1. 通知内容を確認: 通貨ペア、方向 (BUY/SELL)、エントリー価格
2. 経済指標を手動確認 (FOMC, 米CPI, 雇用統計, 日銀会合など)
3. チャートに違和感がないか確認
4. みんなのFX で発注:
   - 通貨ペア選択
   - 売買方向
   - ロット数 (通知記載の推奨数量)
   - SL 注文
   - TP1 注文 (50%利確)
5. TP1 到達後: SL を建値に移動、TP2 を設定

シグナルが出ても発注は任意。見送った場合は理由を記録しておくと振り返りに有用。
