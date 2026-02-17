# cron設定ガイド（初回必読）

## ⚠️ 重要: 初回確認作業（必須）

cron設定前に、**実際のbar_dt（確定4H足時刻）をログで確認**してください。

### なぜ確認が必要？

**Twelve Data APIは通常UTC区切りで4H足を生成**します。つまり：
- UTC 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 で確定
- JSTに変換すると **09:00, 13:00, 17:00, 21:00, 01:00, 05:00** になります

しかし、API仕様やデータソースによって異なる可能性があるため、**実データで確認**することが重要です。

---

## 📋 確認手順

### 1. dry-runで確定足時刻を確認

```bash
python3 scripts/run_signal.py --dry-run --symbols USD/JPY,EUR/JPY,GBP/JPY --log-level INFO
```

### 2. ログ出力を確認

以下のようなログが出力されます：

```
確定4H足時刻（bar_dt）: 2026-02-15 09:00 JST
次足始値: 2026-02-15 13:00 JST
💡 cron設定のヒント: この確定足時刻が 01:00, 05:00, 09:00... なら cron「5 1,5,9,13,17,21 * * *」
```

または

```
確定4H足時刻（bar_dt）: 2026-02-15 03:00 JST
次足始値: 2026-02-15 07:00 JST
💡 cron設定のヒント: この確定足時刻が 03:00, 07:00, 11:00... なら cron「5 3,7,11,15,19,23 * * *」
```

### 3. cron時刻を決定

| 確定足時刻（JST） | cron設定 | 備考 |
|------------------|---------|------|
| **00:00, 04:00, 08:00, 12:00, 16:00, 20:00** | `5 0,4,8,12,16,20 * * *` | **Twelve Data API（確認済み）** UTC 03:00, 07:00, 11:00, 15:00, 19:00, 23:00 |
| **01:00, 05:00, 09:00, 13:00, 17:00, 21:00** | `5 1,5,9,13,17,21 * * *` | UTC 16:00, 20:00, 00:00, 04:00, 08:00, 12:00 |
| **03:00, 07:00, 11:00, 15:00, 19:00, 23:00** | `5 3,7,11,15,19,23 * * *` | UTC 18:00, 22:00, 02:00, 06:00, 10:00, 14:00 |
| **その他** | 実際の時刻に合わせる | ログの確定足時刻 + 5分 |

---

## 🚀 cron設定（例）

### ケース1: JST 01:00, 05:00, 09:00, 13:00, 17:00, 21:00 で確定する場合

```bash
# crontabを編集
crontab -e

# 以下を追加（確定後5分に実行）
5 1,5,9,13,17,21 * * * cd /path/to/fx-alert && /usr/bin/python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY >> logs/signal.log 2>&1
```

### ケース2: JST 03:00, 07:00, 11:00, 15:00, 19:00, 23:00 で確定する場合

```bash
# crontabを編集
crontab -e

# 以下を追加（確定後5分に実行）
5 3,7,11,15,19,23 * * * cd /path/to/fx-alert && /usr/bin/python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY >> logs/signal.log 2>&1
```

---

## ✅ cron設定後の確認

### 1. cron登録確認

```bash
crontab -l
```

### 2. ログ確認（次回実行後）

```bash
tail -f logs/signal.log
```

以下が表示されれば成功：
```
確定4H足時刻（bar_dt）: 2026-02-15 09:00 JST
結果: シグナル X通貨、見送り Y通貨
✅ LINE送信完了（1通）
```

### 3. 重複送信チェック

同じ4Hバーで2回実行しても、以下のログが出れば正常：
```
⚠️ 同一4Hバーで既に送信済み（bar_dtデデュープ）
```

---

## 💰 月間送信数の確認

**1日6回実行の場合**:
- 6回/日 × 31日 = **186通/月**
- LINE無料枠200通/月以内 ✅

**⚠️ 禁止例: 15分毎（`*/15`）**:
- 96回/日 × 31日 = **2,976通/月**
- LINE無料枠を大幅超過 ❌

---

## 🔧 トラブルシューティング

### Q: cronが実行されない

**確認項目**:
1. crontab登録されているか: `crontab -l`
2. 絶対パス使用しているか: `/usr/bin/python3`（`which python3`で確認）
3. 環境変数設定されているか: LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID, TWELVEDATA_API_KEY
4. ログファイルのパーミッション: `mkdir -p logs && chmod 755 logs`

**環境変数をcronに渡す方法**:
```bash
# crontabの先頭に追加
LINE_CHANNEL_ACCESS_TOKEN="your_token"
LINE_USER_ID="your_user_id"
TWELVEDATA_API_KEY="your_api_key"

5 1,5,9,13,17,21 * * * cd /path/to/fx-alert && /usr/bin/python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY >> logs/signal.log 2>&1
```

### Q: 毎回送信されてしまう（デデュープが効かない）

**原因**: state_fileのパス問題

**解決**:
```bash
# 絶対パス指定
python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY

# state_fileを確認
cat data/notification_state.json
# {"last_sent_bar_dt": "2026-02-15T09:00:00+09:00", ...}
```

### Q: 確定足時刻がずれる

**原因**: タイムゾーン設定の問題

**解決**:
```bash
# Pythonのタイムゾーン確認
python3 -c "from zoneinfo import ZoneInfo; from datetime import datetime; print(datetime.now(ZoneInfo('Asia/Tokyo')))"

# システムタイムゾーン確認
date
```

---

## 📝 まとめ

1. ✅ **dry-runで確定足時刻を確認**（初回必須）
2. ✅ **cron時刻を確定足 + 5分に設定**
3. ✅ **1日6回実行で月186通（無料枠内）**
4. ✅ **bar_dtデデュープで二重送信防止**
5. ✅ **ログで動作確認**

**実運用準備完了** 🎉
