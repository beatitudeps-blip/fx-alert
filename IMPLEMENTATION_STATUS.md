# みんなのFX実運用対応 実装状況

**実装日**: 2026-02-15
**ステータス**: ✅ 全機能完成、実運用可能

---

## ✅ 完成した機能

### 1. 設定ファイル管理
- **[config/minnafx.yaml](config/minnafx.yaml)**: みんなのFX完全対応
  - 取引単位: 1Lot=10,000通貨、最小0.1Lot、0.1Lot刻み
  - スプレッド: 固定帯/拡大帯時間帯、3通貨の広告スプレッド
  - メンテナンス: 日次/週次メンテ時間（約定不可）
  - スワップ: ignore/fixed_table/daily_csv 3モード

- **[src/config_loader.py](src/config_loader.py)**: YAML読み込み + バリデーション
  - `get_advertised_spread_sen(symbol, dt)`: 時刻に応じて固定/拡大を自動判定
  - `is_maintenance_window(dt)`: メンテナンス時間判定
  - `is_widened_window(dt)`: 拡大帯判定（月曜7:00特例対応）

### 2. ブローカーコストモデル
- **[src/broker_costs/minnafx.py](src/broker_costs/minnafx.py)**: みんなのFX専用コスト計算
  - `get_spread_pips(symbol, dt)`: 時刻/曜日に応じたスプレッド
  - `calculate_execution_price()`: bid/ask + slippage込み実行価格
  - `calculate_exit_price()`: 決済価格
  - `calculate_fill_costs()`: spread_cost + slippage_cost分解
  - `calculate_swap_jpy()`: スワップ計算（3モード対応）
  - `is_tradable(dt)`: メンテナンス時間除外
  - `should_skip_entry(symbol, dt)`: スプレッドフィルター

### 3. 厳格な0.5%リスク管理
- **[src/position_sizing.py](src/position_sizing.py)**: 違反ゼロ保証
  - `calculate_position_size_strict()`:
    - 理論数量計算
    - 0.1Lot（1,000通貨）刻みで切り捨て
    - 丸め後に0.5%超過チェック
    - 超過なら1段階切り下げ
    - **violations = 0 を保証**
  - `units_to_lots()` / `lots_to_units()`: 単位変換

### 4. LINE通知（発注ガイド形式）
- **[src/notify_line.py](src/notify_line.py)**: 詳細な発注手順
  - シグナル情報（パターン、時刻）
  - **エントリー**: 注文種別（成行/逆指値）、推奨価格、失効条件
  - **リスク**: 口座残高、最大損失、推奨数量（通貨/Lot）、想定コスト
  - **エグジット**: 初期SL、TP1条件+利確率、建値移動、TP2/Trail、TimeStop、日足反転Exit
  - **コスト**: スプレッド（固定/拡大）、スリッページ
  - **操作手順**: 1行ガイド
  - **重複防止**: `{symbol}|{side}|{signal_dt}` で state管理

### 5. シグナル検出→LINE通知
- **[scripts/run_signal.py](scripts/run_signal.py)**: 完全統合済み
  - config/minnafx.yaml 読み込み ✅
  - Twelve Data API シグナル検出 ✅
  - notify_line.create_signal_message() 統合 ✅
  - `--dry-run` / `--send` オプション ✅
  - メンテナンス時間判定（見送り） ✅
  - スプレッドフィルター適用 ✅
  - 重複通知防止（state管理） ✅

### 6. V4統合バックテスト
- **[src/backtest_v4_integrated.py](src/backtest_v4_integrated.py)**: 新コア完全統合
  - config_loader 使用 ✅
  - MinnafxCostModel 使用 ✅
  - メンテナンス時間中は fills 生成しない ✅
  - position_sizing.calculate_position_size_strict() 使用 ✅
  - **violations = 0 を保証** ✅
  - スキップ追跡（maintenance/spread_filter/position_size） ✅
  - run_id別出力分離 ✅

- **[scripts/run_backtest_v4.py](scripts/run_backtest_v4.py)**: 実行スクリプト
  - CLI: `--start-date`, `--end-date`, `--symbols`, `--run-id`
  - 出力: `data/results_v4/{run_id}/{symbol}/`
    - trades.csv, fills.csv, equity_curve.csv
    - skipped_signals.csv, summary.json

### 7. バッチ通知（LINE無料枠節約設計）
- **設定**: [config/minnafx.yaml](config/minnafx.yaml) notifier セクション
  - aggregate_one_message: true（3通貨を1通にまとめる） ✅
  - include_skips: true（見送りも短く通知） ✅
  - send_on_new_closed_bar_only: true（bar_dtデデュープ） ✅
  - compress_skip_lines: true（見送りを1〜2行に圧縮） ✅

- **API**: [src/notify_line.py](src/notify_line.py)
  - create_batch_message()（集約通知生成） ✅
  - _is_bar_already_sent()（bar_dtデデュープチェック） ✅
  - _mark_bar_sent()（送信済みマーク） ✅
  - _format_signal_block()（シグナル詳細ブロック生成） ✅

- **統合**: [scripts/run_signal.py](scripts/run_signal.py)
  - 3通貨ループで結果収集（signal or skip） ✅
  - create_batch_message()で1通にまとめる ✅
  - bar_dtデデュープ適用 ✅

- **月間送信数**:
  - 1日6回（4H足確定後）× 31日 = **186通/月** ✅
  - LINE無料枠200通/月以内 ✅

### 8. 統合テスト

- **[scripts/test_batch_notify.py](scripts/test_batch_notify.py)**: バッチ通知テスト
  - バッチメッセージ生成（3通貨まとめ） ✅
  - bar_dtデデュープ（同一4Hバーで再送しない） ✅
  - 全通貨見送りでも短文通知 ✅
  - **全テスト合格** ✅

- **[scripts/test_signal_integration.py](scripts/test_signal_integration.py)**: シグナル統合テスト
  - 設定読み込み ✅
  - コストモデル（スプレッド固定/拡大） ✅
  - ポジションサイジング（violations=0） ✅
  - LINE通知生成（全必須項目） ✅
  - 重複通知防止 ✅
  - スプレッドフィルター ✅
  - メンテナンス時間判定 ✅

- **[scripts/test_backtest_v4_integration.py](scripts/test_backtest_v4_integration.py)**: V4バックテストテスト
  - モジュールインポート ✅
  - 設定とコストモデル ✅
  - 厳格ポジションサイジング（violations=0） ✅
  - バックテストとLINE通知の一致確認 ✅
  - run_id出力分離 ✅
  - **全テスト合格** ✅

---

## 🎉 実装完了機能

---

## 📋 設定ファイルの使い方

### スプレッド判定例
```python
from src.config_loader import load_broker_config
from datetime import datetime
from zoneinfo import ZoneInfo

config = load_broker_config()

# JST 10:00 → 固定帯
dt_fixed = datetime(2026, 2, 15, 10, 0, tzinfo=ZoneInfo("Asia/Tokyo"))
spread = config.get_advertised_spread_sen("USD/JPY", dt_fixed)
# → 0.2銭

# JST 7:30 → 拡大帯
dt_widened = datetime(2026, 2, 15, 7, 30, tzinfo=ZoneInfo("Asia/Tokyo"))
spread = config.get_advertised_spread_sen("USD/JPY", dt_widened)
# → 3.9銭
```

### ポジションサイジング例
```python
from src.config_loader import load_broker_config
from src.position_sizing import calculate_position_size_strict, units_to_lots

config = load_broker_config()

units, risk_jpy, valid = calculate_position_size_strict(
    equity_jpy=100000.0,
    entry_price=150.0,
    sl_price=149.0,
    risk_pct=0.005,  # 0.5%
    config=config,
    symbol="USD/JPY"
)

lots = units_to_lots(units, config, "USD/JPY")
print(f"推奨: {lots:.1f}Lot ({units:,.0f}通貨), リスク: {risk_jpy:,.0f}円")
# 違反チェック
assert risk_jpy <= 100000.0 * 0.005  # 必ず満たす
```

### LINE通知生成例
```python
from src.notify_line import LineNotifier
from src.config_loader import load_broker_config

config = load_broker_config()
notifier = LineNotifier(
    line_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"],
    line_user_id=os.environ["LINE_USER_ID"],
    config=config
)

msg = notifier.create_signal_message(
    symbol="EUR/JPY",
    side="LONG",
    pattern="Bullish Engulfing",
    signal_dt=signal_datetime,
    entry_price_mid=163.245,
    sl_price_mid=162.420,
    tp1_price_mid=164.070,
    tp2_price_mid=164.895,
    atr=0.687,
    ema20=162.980,
    equity_jpy=100000.0,
    risk_pct=0.005
)

if msg:
    notifier.send_line(msg)  # 本番送信
    # または
    print(msg)  # dry-run
```

---

## 🚀 実運用ガイド

### 1. 環境セットアップ（初回のみ）

```bash
# 依存パッケージインストール
pip3 install pyyaml requests pandas

# LINE環境変数設定（.bashrc または .zshrc に追加）
export LINE_CHANNEL_ACCESS_TOKEN="your_token_here"
export LINE_USER_ID="your_user_id_here"
export TWELVEDATA_API_KEY="your_api_key_here"
```

### 2. シグナル検出実行（cron定期実行推奨）

```bash
# dry-run（LINEに送信しない、標準出力のみ）
python3 scripts/run_signal.py --dry-run --symbols EUR/JPY,USD/JPY,GBP/JPY

# 本番実行（LINE通知送信）
python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY
```

**cron設定例** (4H足確定後に自動実行、LINE無料枠節約):

**Twelve Data API 検証済み**: UTC 03:00, 07:00, 11:00, 15:00, 19:00, 23:00 区切り
- JST変換: **00:00, 04:00, 08:00, 12:00, 16:00, 20:00**
- cron設定: `5 0,4,8,12,16,20 * * *`

```bash
# Twelve Data API（検証済みパターン）- 1日6回 = 月186通
5 0,4,8,12,16,20 * * * cd /path/to/fx-alert && /usr/bin/python3 scripts/run_signal.py --send --symbols EUR/JPY,USD/JPY,GBP/JPY >> logs/signal.log 2>&1
```

**⚠️ 注意**:
- 15分毎（`*/15`）は禁止！無料枠200通/月を超える
- 実際のbar_dtに合わせてcron時刻を調整すること
- bar_dtデデュープで二重送信防止

### 3. バックテスト実行

```bash
# V4統合バックテスト（違反ゼロ保証）
python3 scripts/run_backtest_v4.py \
  --start-date 2025-01-01 \
  --end-date 2026-02-14 \
  --symbols EUR/JPY,USD/JPY,GBP/JPY \
  --run-id production_test_20260215

# 結果確認
ls -R data/results_v4/production_test_20260215/
```

**出力ファイル**:
- `data/results_v4/{run_id}/{symbol}/trades.csv` - トレード一覧
- `data/results_v4/{run_id}/{symbol}/fills.csv` - 約定詳細
- `data/results_v4/{run_id}/{symbol}/equity_curve.csv` - 資産曲線
- `data/results_v4/{run_id}/{symbol}/skipped_signals.csv` - 見送りシグナル
- `data/results_v4/{run_id}/{symbol}/summary.json` - パフォーマンスサマリー

### 4. 統合テスト実行

```bash
# シグナル統合テスト
python3 scripts/test_signal_integration.py

# V4バックテスト統合テスト
python3 scripts/test_backtest_v4_integration.py
```

### 5. トラブルシューティング

**メンテナンス時間に見送られる**:
- JST 06:50-07:10（平日）、06:00-06:25（月曜）は約定不可
- JST 土曜 12:00-18:00 は週次メンテナンス

**スプレッド拡大で見送られる**:
- 拡大帯（JST 07:10-08:00, 05:00-06:50）はスプレッドフィルター適用
- 固定帯の2.5倍超過で自動見送り

**violations チェックエラー**:
- 0.5%超過は自動的に1段階切り下げ
- それでも超過なら position_size_invalid でスキップ
- skipped_signals.csv で確認可能

---

## 📦 必要なパッケージ

```bash
# requirements.txt に追加
pyyaml>=6.0
requests>=2.31.0
pandas>=2.0.0
```

---

## ✅ 完成状況

**実装完成度**: 100% 🎉
- ✅ コア機能（config_loader, broker_costs, position_sizing, notify_line）
- ✅ シグナル検出スクリプト（run_signal.py）
- ✅ V4統合バックテスト（backtest_v4_integrated.py）
- ✅ 統合テスト（全テスト合格）

**品質保証**:
- ✅ violations = 0 保証（厳格0.5%リスク管理）
- ✅ メンテナンス時間除外
- ✅ スプレッドフィルター適用
- ✅ バックテストとLINE通知の執行ルール一致
- ✅ 重複通知防止（bar_dtデデュープ）
- ✅ run_id別出力分離（上書き防止）
- ✅ LINE無料枠節約（月186通で無料枠内）

**実運用可能**: ✅
- scripts/run_signal.py を cron で定期実行（4H足確定後1日6回）
- 3通貨の結果を1通にまとめて送信（バッチ通知）
- LINE通知で発注ガイド受信
- みんなのFX仕様完全対応
