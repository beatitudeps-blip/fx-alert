# GitHub Actions セットアップガイド

## 📋 前提条件

- GitHubリポジトリ作成済み
- TwelveData APIキー取得済み
- LINE Messaging API設定済み

---

## 🔐 ステップ1: GitHub Secretsの設定

リポジトリ設定 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

以下の3つのSecretを登録：

### 1. TWELVEDATA_API_KEY
- **値**: TwelveData APIキー
- **取得先**: https://twelvedata.com/

### 2. LINE_CHANNEL_ACCESS_TOKEN  
- **値**: LINE Messaging API チャンネルアクセストークン
- **取得方法**:
  1. LINE Developers Console (https://developers.line.biz/)
  2. チャンネル作成 → Messaging API
  3. チャンネルアクセストークン（長期）を発行

### 3. LINE_USER_ID
- **値**: 自分のLINE User ID
- **取得方法**:
  1. LINE公式アカウントを友だち追加
  2. 任意のメッセージを送信
  3. Webhook URLで受信したJSONから `source.userId` を取得

---

## 📁 ステップ2: ファイル配置確認

```
fx-alert/
├── .github/
│   └── workflows/
│       └── fx-alert.yml         ✅ 作成済み
├── scripts/
│   └── run_fx_alert.py          ✅ 作成済み
├── src/
│   ├── notify_line.py           ✅ 既存
│   ├── config_loader.py         ✅ 既存
│   └── signal_detector.py       ⚠️ 未実装（TODO）
├── config/
│   └── minnafx.yaml             ✅ 既存
├── data/
│   ├── notification_state.json  （自動生成）
│   └── results_v4/
│       └── risk_050_500k/       ✅ 最新バックテスト結果
├── requirements.txt             ✅ 既存
└── README.md                    （更新推奨）
```

---

## ⚙️ ステップ3: 実行スケジュール

### 自動実行タイミング（JST）

| JST時刻 | UTC時刻 | 4H足 | 確定時刻 | 実行時刻 |
|---------|---------|------|----------|----------|
| 0:00 | 15:00 (前日) | 20:00足 | 0:00 | 0:05 |
| 4:00 | 19:00 (前日) | 0:00足 | 4:00 | 4:05 |
| 8:00 | 23:00 (前日) | 4:00足 | 8:00 | 8:05 |
| 12:00 | 03:00 | 8:00足 | 12:00 | 12:05 |
| 16:00 | 07:00 | 12:00足 | 16:00 | 16:05 |
| 20:00 | 11:00 | 16:00足 | 20:00 | 20:05 |

**cron設定**: `5 15,19,23,3,7,11 * * *` (UTC)

---

## 🧪 ステップ4: 動作テスト

### 手動実行でテスト

1. GitHubリポジトリ → **Actions** タブ
2. "FX Alert - 4H Signal Detection" ワークフロー選択
3. **Run workflow** → **Run workflow** ボタンクリック
4. Dry runを有効にしてテスト: `dry_run: true`

### ログ確認

- Actions → 該当のワークフロー実行 → ログ確認
- エラーがあれば **Artifacts** にログが保存される

---

## 🔄 ステップ5: notification_state.json の動作確認

### 初回実行後

```bash
# ローカルで確認
git pull
cat data/notification_state.json
```

**期待される内容**:
```json
{
  "last_signals": {},
  "last_sent_bar_dt": "2024-XX-XXTXX:00:00+09:00"
}
```

### シグナル送信後

```json
{
  "last_signals": {
    "EUR/JPY|LONG|2024-XX-XXTXX:00:00+09:00": "2024-XX-XXTXX:05:23"
  },
  "last_sent_bar_dt": "2024-XX-XXTXX:00:00+09:00"
}
```

**重要**: 同じシグナルは2度送信されません！

---

## ⚠️ トラブルシューティング

### 1. Workflowが実行されない

**原因**: リポジトリが非アクティブ（60日以上更新なし）  
**対策**: 手動でワークフローを1回実行

### 2. LINE通知が送信されない

**チェックリスト**:
- [ ] GitHub Secretsに認証情報登録済み
- [ ] LINE公式アカウントを友だち追加済み
- [ ] Webhook URLが正しく設定されている
- [ ] dry_runがfalseになっている

### 3. notification_state.jsonがコミットされない

**原因**: Git permissionsエラー  
**対策**:
```yaml
permissions:
  contents: write  # これが必要！
```

### 4. API制限エラー

**TwelveData無料プラン制限**:
- 800 API calls/day
- 8 calls/minute

**1日のAPI使用量**: 6回実行 × 2通貨 × 2エンドポイント = 24 calls/day（余裕あり）

---

## 📊 モニタリング

### 定期チェック項目

1. **月次パフォーマンスレビュー**
   - PF ≥ 1.7
   - Violations = 0
   - DD ≤ 想定範囲

2. **週次ログ確認**
   - Actions → ワークフロー実行ログ
   - エラーがないか確認

3. **通知重複チェック**
   - 同じシグナルが2回送信されていないか
   - notification_state.jsonの増加を確認

---

## 🚀 本番運用開始チェックリスト

- [ ] GitHub Secrets登録完了
- [ ] 手動実行でDry runテスト成功
- [ ] 手動実行で実際のLINE通知受信確認
- [ ] notification_state.jsonの自動コミット動作確認
- [ ] src/signal_detector.py 実装完了（TODO）
- [ ] 初期資金50万円をみんなのFXに入金
- [ ] 緊急停止手順を確認

---

## 🛑 緊急停止方法

### Workflowを一時停止

1. リポジトリ → **Actions**
2. "FX Alert - 4H Signal Detection" 選択
3. 右上 **︙** → **Disable workflow**

### 完全停止

```bash
# .github/workflows/fx-alert.yml を削除
git rm .github/workflows/fx-alert.yml
git commit -m "停止: FX Alert workflow"
git push
```

---

## 📝 次のステップ

1. ✅ GitHub Actions設定完了
2. ⏳ src/signal_detector.py 実装（4H足シグナル検出ロジック）
3. ⏳ 本番運用開始
4. ⏳ 月次パフォーマンスレビュー

---

**作成日**: 2026-02-15  
**最終更新**: 2026-02-15
