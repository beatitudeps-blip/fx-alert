"""
LINE通知モジュール（みんなのFX 発注ガイド形式）
詳細なエントリー/エグジット条件、リスク管理、重複防止
"""
import json
import requests
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from .config_loader import BrokerConfig
from .broker_costs.minnafx import MinnafxCostModel
from .position_sizing import calculate_position_size_strict, units_to_lots


class LineNotifier:
    """LINE通知管理クラス"""

    def __init__(
        self,
        line_token: str,
        line_user_id: str,
        config: BrokerConfig,
        state_file: str = "data/notification_state.json"
    ):
        self.line_token = line_token
        self.line_user_id = line_user_id
        self.config = config
        self.cost_model = MinnafxCostModel(config)
        self.state_file = Path(state_file)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        """通知状態をロード（重複防止用）"""
        if self.state_file.exists():
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {"last_signals": {}}

    def _save_state(self):
        """通知状態を保存"""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False, default=str)

    def _generate_signal_key(self, symbol: str, side: str, signal_dt: datetime) -> str:
        """重複チェック用のキーを生成"""
        return f"{symbol}|{side}|{signal_dt.isoformat()}"

    def _is_duplicate(self, signal_key: str) -> bool:
        """重複通知かチェック"""
        return signal_key in self.state["last_signals"]

    def _mark_sent(self, signal_key: str):
        """通知済みとしてマーク"""
        self.state["last_signals"][signal_key] = datetime.now().isoformat()
        self._save_state()

    def _is_bar_already_sent(self, bar_dt: datetime) -> bool:
        """同一4Hバーで既に送信済みかチェック"""
        bar_key = bar_dt.isoformat()
        return self.state.get("last_sent_bar_dt") == bar_key

    def _mark_bar_sent(self, bar_dt: datetime):
        """4Hバーを送信済みとしてマーク"""
        self.state["last_sent_bar_dt"] = bar_dt.isoformat()
        self._save_state()

    def create_signal_message(
        self,
        symbol: str,
        side: str,
        pattern: str,
        signal_dt: datetime,
        entry_price_mid: float,
        sl_price_mid: float,
        tp1_price_mid: float,
        tp2_price_mid: float,
        atr: float,
        ema20: float,
        equity_jpy: float,
        risk_pct: float = 0.005,
        entry_mode: str = "NEXT_OPEN_MARKET",
        exit_config: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        LINE通知メッセージを生成

        Args:
            symbol: 通貨ペア
            side: "LONG" or "SHORT"
            pattern: パターン名（Engulfing/Hammerなど）
            signal_dt: シグナル足時刻（JST）
            entry_price_mid: エントリー仲値
            sl_price_mid: SL仲値
            tp1_price_mid: TP1仲値
            tp2_price_mid: TP2仲値
            atr: ATR
            ema20: EMA20
            equity_jpy: 口座残高
            risk_pct: リスク率
            entry_mode: エントリー方式
            exit_config: エグジット設定

        Returns:
            通知メッセージ（見送りの場合はNone）
        """
        # 重複チェック
        signal_key = self._generate_signal_key(symbol, side, signal_dt)
        if self._is_duplicate(signal_key):
            return None

        # 次足時刻（4H足なら+4時間）
        next_dt = signal_dt + timedelta(hours=4)

        # 実行価格計算（スプレッド + スリッページ）
        entry_price_exec = self.cost_model.calculate_execution_price(
            entry_price_mid, side, symbol, next_dt
        )
        sl_price_exec = self.cost_model.calculate_exit_price(
            sl_price_mid, side, symbol, next_dt
        )

        # ポジションサイジング（厳格0.5%）
        units, actual_risk_jpy, is_valid = calculate_position_size_strict(
            equity_jpy, entry_price_exec, sl_price_exec, risk_pct, self.config, symbol
        )

        # 見送り判定
        should_skip, skip_reason = self.cost_model.should_skip_entry(symbol, next_dt)
        if should_skip or not is_valid:
            # 見送り通知は送らない（またはオプションで送る）
            return None

        lots = units_to_lots(units, self.config, symbol)

        # コスト計算
        spread_cost, slip_cost = self.cost_model.calculate_fill_costs(units, side, symbol, next_dt)
        total_cost = spread_cost + slip_cost

        # スプレッド情報
        spread_pips = self.cost_model.get_spread_pips(symbol, next_dt)
        is_widened = self.config._is_widened_window(next_dt)
        spread_type = "拡大" if is_widened else "固定"

        # pips計算
        entry_sl_pips = abs(entry_price_exec - sl_price_exec) * 100
        entry_tp1_pips = abs(tp1_price_mid - entry_price_mid) * 100
        entry_tp2_pips = abs(tp2_price_mid - entry_price_mid) * 100

        # Exit設定
        if exit_config is None:
            exit_config = {
                "tp1_close_pct": 0.5,
                "move_to_be": True,
                "be_buffer_pips": 0.0,
                "tp2_mode": "FIXED_R",
                "time_stop": None,
                "daily_flip_exit": False
            }

        # メッセージ生成
        direction_jp = "買い" if side == "LONG" else "売り"
        emoji = "🔼" if side == "LONG" else "🔽"

        msg = f"""🚨 {symbol} {emoji} {direction_jp}シグナル

【シグナル情報】
パターン: {pattern}
シグナル足: {signal_dt.strftime('%Y-%m-%d %H:%M JST')}
次足始値: {next_dt.strftime('%Y-%m-%d %H:%M JST')}

【エントリー】
注文種別: {'成行' if entry_mode == 'NEXT_OPEN_MARKET' else '逆指値'}
推奨価格: {entry_price_exec:.3f}円
（仲値 {entry_price_mid:.3f} + コスト）
"""

        if entry_mode == "BREAKOUT_STOP":
            msg += f"""失効条件: N本未約定で失効
"""

        msg += f"""
【リスク管理】
口座残高: {equity_jpy:,.0f}円
最大損失: {actual_risk_jpy:,.0f}円 ({risk_pct*100:.1f}%)
推奨数量: {units:,.0f}通貨 = {lots:.1f}Lot
想定コスト: {total_cost:.0f}円（spread {spread_cost:.0f} + slip {slip_cost:.0f}）

【エグジット条件】
初期SL: {sl_price_exec:.3f}円 (-{entry_sl_pips:.1f}pips)
"""

        # TP1条件
        tp1_pct = exit_config["tp1_close_pct"] * 100
        msg += f"""TP1: {tp1_price_mid:.3f}円 (+{entry_tp1_pips:.1f}pips)
  → {tp1_pct:.0f}%利確 ({units * exit_config['tp1_close_pct']:,.0f}通貨)
"""

        # 建値移動
        if exit_config["move_to_be"]:
            be_buffer = exit_config.get("be_buffer_pips", 0.0)
            be_price = entry_price_exec + (be_buffer * 0.01 if side == "LONG" else -be_buffer * 0.01)
            msg += f"""  → TP1後、SLを建値{be_price:.3f}円へ移動
"""

        # TP2/Trail
        if exit_config["tp2_mode"] == "FIXED_R":
            msg += f"""TP2: {tp2_price_mid:.3f}円 (+{entry_tp2_pips:.1f}pips)
  → 残玉{100 - tp1_pct:.0f}%決済
"""
        elif exit_config["tp2_mode"] == "TRAIL":
            msg += f"""Trail: Chandelier方式でトレール
  → ATR × k をSLとして追従
"""

        # TimeStop
        if exit_config.get("time_stop"):
            msg += f"""
TimeStop: {exit_config['time_stop']}本以内に+0.5R未達なら撤退
"""

        # 日足反転Exit
        if exit_config.get("daily_flip_exit"):
            msg += f"""
日足反転Exit: 日足環境反転でクローズ
"""

        msg += f"""
【みんなのFXコスト前提】
スプレッド: {spread_pips:.1f}pips（{spread_type}帯）
スリッページ: {self.config.get_slippage_pips():.1f}pips

【参考情報】
EMA20: {ema20:.3f}
ATR: {atr:.3f}

【操作手順】
みんなのFX → 新規 → {'成行' if entry_mode == 'NEXT_OPEN_MARKET' else '逆指値'} → {direction_jp} → {lots:.1f}Lot → 発注

※本通知はバックテスト検証済みの執行ルールに基づきます
"""

        # 通知済みマーク
        self._mark_sent(signal_key)

        return msg

    def create_batch_message(
        self,
        run_dt: datetime,
        bar_dt: datetime,
        results: list,
        equity_jpy: float = 100000.0,
        risk_pct: float = 0.005
    ) -> Optional[str]:
        """
        3通貨分の結果を1通にまとめた通知メッセージを生成

        Args:
            run_dt: スクリプト実行時刻（JST）
            bar_dt: 確定4H足時刻（JST）
            results: [{"symbol": str, "status": "SIGNAL"|"SKIP", ...}, ...]
            equity_jpy: 口座残高
            risk_pct: リスク率

        Returns:
            通知メッセージ（送信不要の場合はNone）
        """
        # 同一bar_dtで既に送信済みならスキップ
        if self._is_bar_already_sent(bar_dt):
            return None

        # 設定読み込み
        notifier_config = self.config.config.get("notifier", {})
        max_text_length = notifier_config.get("max_text_length", 3500)
        compress_skip_lines = notifier_config.get("compress_skip_lines", True)
        include_skips = notifier_config.get("include_skips", True)

        # ヘッダー
        next_dt = bar_dt + timedelta(hours=4)
        msg = f"""📊 4H足確定通知（{len(results)}通貨）

【確定足】{bar_dt.strftime('%Y-%m-%d %H:%M JST')}
【次足始値】{next_dt.strftime('%Y-%m-%d %H:%M JST')}
【実行時刻】{run_dt.strftime('%Y-%m-%d %H:%M:%S JST')}

"""

        signal_count = 0
        skip_count = 0

        # シグナルブロック（詳細）
        for result in results:
            if result["status"] == "SIGNAL":
                signal_count += 1
                msg += self._format_signal_block(result, next_dt, equity_jpy, risk_pct)
                msg += "\n" + "="*40 + "\n\n"

        # 見送りブロック（圧縮、理由コード + 相場状態サマリー）
        if include_skips:
            skip_lines = []
            for result in results:
                if result["status"] == "SKIP":
                    skip_count += 1
                    symbol = result["symbol"]
                    reason = result.get("reason", "不明")

                    # 相場状態サマリー
                    close = result.get("close", 0.0)
                    ema20 = result.get("ema20", 0.0)
                    atr = result.get("atr", 0.0)
                    gap_pips = result.get("ema_gap_pips", 0.0)
                    gap_ratio = result.get("ema_gap_atr_ratio", 0.0)
                    state = result.get("market_state", "不明")

                    # 理由コードを抽出して簡潔表示
                    if compress_skip_lines:
                        # スプレッド超過の場合は詳細表示
                        if "スプレッド" in reason and result.get("spread_pips") is not None:
                            spread = result["spread_pips"]
                            threshold = result.get("threshold_pips", 0)
                            skip_lines.append(f"・{symbol}: [S] {spread:.1f}pips > {threshold:.1f}pips")
                        # メンテナンス時間
                        elif "メンテナンス" in reason:
                            skip_lines.append(f"・{symbol}: [M] メンテナンス中")
                        # 日足環境NG
                        elif "日足環境" in reason or "トレンド" in reason:
                            skip_lines.append(f"・{symbol}: [E] 日足環境NG")
                        # EMAタッチなし
                        elif "EMA" in reason:
                            skip_lines.append(f"・{symbol}: [E] EMAタッチなし")
                        # パターン不成立
                        elif "パターン" in reason or "トリガー" in reason:
                            skip_lines.append(f"・{symbol}: [E] パターン不成立")
                        # ポジションサイズ
                        elif "ポジションサイズ" in reason or "最小ロット" in reason:
                            skip_lines.append(f"・{symbol}: [P] 最小ロット未満")
                        # リスク超過
                        elif "リスク超過" in reason:
                            skip_lines.append(f"・{symbol}: [R] リスク超過")
                        # その他
                        else:
                            # 理由を20文字に短縮
                            short_reason = reason[:20] + "..." if len(reason) > 20 else reason
                            skip_lines.append(f"・{symbol}: {short_reason}")

                        # 相場状態サマリー追加
                        if close > 0 and ema20 > 0 and atr > 0:
                            skip_lines.append(f"  → {close:.3f} / EMA {ema20:.3f} / 乖離 {gap_pips:.1f}pips({gap_ratio:.2f}R) / {state}")
                    else:
                        skip_lines.append(f"【{symbol}】見送り\n理由: {reason}")

            if skip_lines:
                msg += "【見送り】\n"
                msg += "\n".join(skip_lines)
                msg += "\n\n"

        # 次回チェック時刻（次のbar_dt + 5分）
        next_check_dt = next_dt + timedelta(hours=4, minutes=5)

        # フッター
        msg += f"""【サマリー】
シグナル: {signal_count}通貨
見送り: {skip_count}通貨
合計: {len(results)}通貨

【次回チェック】{next_check_dt.strftime('%Y-%m-%d %H:%M JST')}

※理由コード: [E]=環境NG [S]=スプレッド [M]=メンテ [P]=ロット不足 [R]=リスク超過
※LINE無料枠（200通/月）節約のため集約送信
"""

        # 長さチェック（超過時はskipをさらに圧縮）
        if len(msg) > max_text_length and compress_skip_lines:
            # skipを1行に圧縮
            msg_parts = msg.split("【見送り】")
            if len(msg_parts) == 2:
                header = msg_parts[0]
                skip_symbols = [r["symbol"] for r in results if r["status"] == "SKIP"]
                compressed_skip = f"【見送り】{', '.join(skip_symbols)}\n\n"
                footer = msg_parts[1].split("【サマリー】")[-1]
                msg = header + compressed_skip + "【サマリー】" + footer

        # bar_dtを送信済みマーク
        self._mark_bar_sent(bar_dt)

        return msg

    def _format_signal_block(
        self,
        result: dict,
        next_dt: datetime,
        equity_jpy: float,
        risk_pct: float
    ) -> str:
        """シグナルの詳細ブロックをフォーマット"""
        symbol = result["symbol"]
        side = result["side"]
        pattern = result["pattern"]
        entry_price_mid = result["entry_price_mid"]
        sl_price_mid = result["sl_price_mid"]
        tp1_price_mid = result["tp1_price_mid"]
        tp2_price_mid = result["tp2_price_mid"]
        atr = result.get("atr", 0.0)
        ema20 = result.get("ema20", 0.0)
        entry_mode = result.get("entry_mode", "NEXT_OPEN_MARKET")
        exit_config = result.get("exit_config", {
            "tp1_close_pct": 0.5,
            "move_to_be": True,
            "be_buffer_pips": 0.0,
            "tp2_mode": "FIXED_R",
            "time_stop": None,
            "daily_flip_exit": False
        })

        # 実行価格計算
        entry_price_exec = self.cost_model.calculate_execution_price(
            entry_price_mid, side, symbol, next_dt
        )
        sl_price_exec = self.cost_model.calculate_exit_price(
            sl_price_mid, side, symbol, next_dt
        )

        # ポジションサイジング
        units, actual_risk_jpy, is_valid = calculate_position_size_strict(
            equity_jpy, entry_price_exec, sl_price_exec, risk_pct, self.config, symbol
        )

        if not is_valid:
            return f"【{symbol}】サイジングエラー（スキップ）"

        lots = units_to_lots(units, self.config, symbol)

        # コスト計算
        spread_cost, slip_cost = self.cost_model.calculate_fill_costs(units, side, symbol, next_dt)
        total_cost = spread_cost + slip_cost

        # スプレッド情報
        spread_pips = self.cost_model.get_spread_pips(symbol, next_dt)
        is_widened = self.config._is_widened_window(next_dt)
        spread_type = "拡大" if is_widened else "固定"

        # pips計算
        entry_sl_pips = abs(entry_price_exec - sl_price_exec) * 100
        entry_tp1_pips = abs(tp1_price_mid - entry_price_mid) * 100
        entry_tp2_pips = abs(tp2_price_mid - entry_price_mid) * 100

        # メッセージ生成
        direction_jp = "買い" if side == "LONG" else "売り"
        emoji = "🔼" if side == "LONG" else "🔽"

        block = f"""🚨 {symbol} {emoji} {direction_jp}シグナル

パターン: {pattern}
エントリー: {entry_price_exec:.3f}円（仲値{entry_price_mid:.3f}＋コスト）
推奨数量: {units:,.0f}通貨 = {lots:.1f}Lot
リスク: {actual_risk_jpy:,.0f}円（{risk_pct*100:.1f}%）

SL: {sl_price_exec:.3f}円 (-{entry_sl_pips:.1f}pips)
TP1: {tp1_price_mid:.3f}円 (+{entry_tp1_pips:.1f}pips) → {exit_config['tp1_close_pct']*100:.0f}%利確
TP2: {tp2_price_mid:.3f}円 (+{entry_tp2_pips:.1f}pips) → 残玉決済
"""
        if exit_config.get("move_to_be"):
            block += f"→ TP1後、SLを建値へ移動\n"

        block += f"""
スプレッド: {spread_pips:.1f}pips（{spread_type}帯）
想定コスト: {total_cost:.0f}円
EMA20: {ema20:.3f}, ATR: {atr:.3f}

操作: みんなのFX→新規→成行→{direction_jp}→{lots:.1f}Lot→発注
"""

        return block

    def send_line(self, message: str) -> bool:
        """
        LINE通知を送信

        Args:
            message: 送信メッセージ

        Returns:
            成功したらTrue
        """
        url = "https://api.line.me/v2/bot/message/push"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.line_token}",
        }
        body = {
            "to": self.line_user_id,
            "messages": [{"type": "text", "text": message}],
        }

        try:
            r = requests.post(url, headers=headers, data=json.dumps(body), timeout=20)
            r.raise_for_status()
            return True
        except Exception as e:
            print(f"LINE送信エラー: {e}")
            return False


if __name__ == "__main__":
    import os
    from zoneinfo import ZoneInfo
    from .config_loader import load_broker_config

    # テスト実行（dry-run）
    config = load_broker_config()

    # ダミーのLINE認証情報
    notifier = LineNotifier(
        line_token="dummy_token",
        line_user_id="dummy_user",
        config=config
    )

    # サンプルシグナル（EUR/JPY LONG）
    signal_dt = datetime(2026, 2, 15, 12, 0, 0, tzinfo=ZoneInfo("Asia/Tokyo"))

    msg = notifier.create_signal_message(
        symbol="EUR/JPY",
        side="LONG",
        pattern="Bullish Engulfing",
        signal_dt=signal_dt,
        entry_price_mid=163.245,
        sl_price_mid=162.420,
        tp1_price_mid=164.070,
        tp2_price_mid=164.895,
        atr=0.687,
        ema20=162.980,
        equity_jpy=100000.0,
        risk_pct=0.005,
        entry_mode="NEXT_OPEN_MARKET",
        exit_config={
            "tp1_close_pct": 0.5,
            "move_to_be": True,
            "be_buffer_pips": 0.0,
            "tp2_mode": "FIXED_R",
            "time_stop": None,
            "daily_flip_exit": False
        }
    )

    if msg:
        print("=== LINE通知サンプル（EUR/JPY） ===")
        print(msg)
    else:
        print("通知なし（重複または見送り）")
