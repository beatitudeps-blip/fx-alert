# Google Sheets / Docs / NotebookLM 連携ガイド

## 概要

GitHub Actions で生成されるシグナルログを Google Sheets / Docs に自動反映し、
NotebookLM で構造化ソースとして活用する。

## アーキテクチャ

```
GitHub Actions (UTC 23:00)
  ├── run_daily_signal.py      → data/daily_signal_log.csv
  ├── export_to_google.py      → Google Sheets (FX_Daily_Signal_Log)
  └── build_daily_summary.py   → Google Docs  (FX_Daily_Summary_Latest)
                                  + data/reports/daily_summary_YYYY-MM-DD.txt

NotebookLM ソース:
  1. strategy_overview       (手動作成 Google Docs)
  2. FX_Daily_Summary_Latest (自動更新)
  3. FX_Weekly_Review_Latest (将来自動化)
  4. FX_Monthly_Review       (将来自動化)
```

## Google Cloud セットアップ

### 1. プロジェクト作成
- Google Cloud Console でプロジェクトを作成（または既存を使用）
- 以下の API を有効化:
  - Google Sheets API
  - Google Docs API
  - Google Drive API

### 2. Service Account 作成
- IAM & Admin → Service Accounts → 作成
- 名前: `fx-alert-automation`
- ロール: 不要（Drive/Sheets/Docs は共有で制御）
- JSON キーをダウンロード

### 3. Google Drive フォルダ準備
- Google Drive に `FX_Trading_NotebookLM` フォルダを作成
- フォルダを service account のメールアドレスと共有（編集者）

### 4. Google Sheets 準備
- `FX_Daily_Signal_Log` スプレッドシートを作成
- service account のメールアドレスと共有（編集者）
- スプレッドシート ID をメモ（URL の `/d/XXXXX/edit` の XXXXX 部分）

### 5. Google Docs 準備
- `FX_Daily_Summary_Latest` ドキュメントを作成
- service account のメールアドレスと共有（編集者）
- ドキュメント ID をメモ

### 6. GitHub Secrets 登録

| Secret名 | 値 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | service account JSON キーの中身（全文） |
| `GOOGLE_SHEETS_SPREADSHEET_ID` | スプレッドシート ID |
| `GOOGLE_DAILY_SUMMARY_DOC_ID` | ドキュメント ID |
| `GOOGLE_WEEKLY_REVIEW_DOC_ID` | （将来用） |
| `GOOGLE_DRIVE_FOLDER_ID` | （将来用） |

## ローカル開発

### 環境変数 (.env)
```
GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/service-account.json
GOOGLE_SHEETS_SPREADSHEET_ID=xxxxx
GOOGLE_DAILY_SUMMARY_DOC_ID=xxxxx
```

### テスト実行
```bash
# Sheets エクスポート (dry-run)
python scripts/export_to_google.py --dry-run

# 日次サマリー (ローカルファイルのみ)
python scripts/build_daily_summary.py --local-only

# 日次サマリー (dry-run: テキスト表示のみ)
python scripts/build_daily_summary.py --dry-run
```

## スクリプト一覧

| スクリプト | 役割 |
|---|---|
| `scripts/google_client.py` | Google API 認証ヘルパー |
| `scripts/summary_renderer.py` | ログ読み込み・要約・テキスト生成の共通関数 |
| `scripts/export_to_google.py` | daily_signal_log.csv → Google Sheets 追記 |
| `scripts/build_daily_summary.py` | 日次サマリー → Google Docs + ローカル保存 |

## summary_renderer.py の共通関数

| 関数 | 用途 |
|---|---|
| `load_daily_signal_log()` | CSV 全行読み込み |
| `filter_by_date()` | 指定日のフィルタ |
| `filter_recent_days()` | 直近N日分のフィルタ |
| `summarize_signals()` | status 別件数集計 |
| `summarize_reason_codes()` | reason_code 出現回数集計 |
| `render_daily_summary_text()` | 日次サマリーテキスト生成 |
| `render_weekly_review_text()` | 週次レビューテキスト生成（骨格） |

## NotebookLM での使い方

1. NotebookLM で新規ノートブック作成
2. ソース追加:
   - Google Docs: `FX_Daily_Summary_Latest`
   - Google Docs: `strategy_overview`（手動作成の戦略概要）
3. 毎日のサマリーが自動更新されるため、NotebookLM で最新状況を確認可能

## 将来拡張

- `build_weekly_review.py`: 週次レビューの自動生成・Docs 更新
- `build_monthly_review.py`: 月次レビューの自動生成
- NotebookLM Enterprise API 対応（notebook 作成・ソース追加の自動化）
