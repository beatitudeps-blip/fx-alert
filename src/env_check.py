"""
環境変数チェックユーティリティ

.env ファイル対応と明確なエラーメッセージを提供
"""
import os
import sys
from pathlib import Path
from typing import Optional, List


def load_dotenv_if_exists():
    """
    .env ファイルが存在すれば読み込む（python-dotenv使用）
    存在しなければ無視
    """
    try:
        from dotenv import load_dotenv
        env_path = Path(__file__).parent.parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            return True
        return False
    except ImportError:
        # python-dotenvがインストールされていない場合は無視
        return False


def check_api_key(required: bool = True) -> Optional[str]:
    """
    TWELVEDATA_API_KEY の存在確認

    Args:
        required: Trueなら未設定時にエラー終了、Falseなら警告のみ

    Returns:
        APIキー（存在する場合）
    """
    api_key = os.environ.get("TWELVEDATA_API_KEY")

    if not api_key:
        if required:
            print("=" * 80, file=sys.stderr)
            print("❌ エラー: TWELVEDATA_API_KEY が設定されていません", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("", file=sys.stderr)
            print("以下のいずれかの方法で設定してください：", file=sys.stderr)
            print("", file=sys.stderr)
            print("【方法1】.env ファイルを作成（推奨）", file=sys.stderr)
            print("  1. .env.example をコピー:", file=sys.stderr)
            print("     cp .env.example .env", file=sys.stderr)
            print("  2. .env を編集して実際のキーを設定", file=sys.stderr)
            print("", file=sys.stderr)
            print("【方法2】環境変数として直接設定", file=sys.stderr)
            print("  export TWELVEDATA_API_KEY=\"your_api_key_here\"", file=sys.stderr)
            print("", file=sys.stderr)
            print("【方法3】crontab で直接設定（cron実行時）", file=sys.stderr)
            print("  TWELVEDATA_API_KEY=your_key", file=sys.stderr)
            print("  5 0,4,8,12,16,20 * * * cd /path/to/fx-alert && python3 ...", file=sys.stderr)
            print("", file=sys.stderr)
            print("⚠️ 注意: cronはシェルの設定ファイル（.bashrc/.zshrc）を読みません！", file=sys.stderr)
            print("        crontab内で直接設定するか、.envファイルを使用してください。", file=sys.stderr)
            print("", file=sys.stderr)
            print("APIキーの取得: https://twelvedata.com/", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            sys.exit(2)
        else:
            print("⚠️ 警告: TWELVEDATA_API_KEY が設定されていません", file=sys.stderr)

    return api_key


def check_line_credentials(required: bool = True) -> tuple[Optional[str], Optional[str]]:
    """
    LINE通知用の認証情報確認

    Args:
        required: Trueなら未設定時にエラー終了、Falseなら警告のみ

    Returns:
        (LINE_CHANNEL_ACCESS_TOKEN, LINE_USER_ID)
    """
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    missing = []
    if not token:
        missing.append("LINE_CHANNEL_ACCESS_TOKEN")
    if not user_id:
        missing.append("LINE_USER_ID")

    if missing:
        if required:
            print("=" * 80, file=sys.stderr)
            print(f"❌ エラー: 以下の環境変数が設定されていません: {', '.join(missing)}", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("", file=sys.stderr)
            print("LINE通知を使用する場合、以下を設定してください：", file=sys.stderr)
            print("", file=sys.stderr)
            print("【方法1】.env ファイルに追加（推奨）", file=sys.stderr)
            print("  LINE_CHANNEL_ACCESS_TOKEN=your_token_here", file=sys.stderr)
            print("  LINE_USER_ID=your_user_id_here", file=sys.stderr)
            print("", file=sys.stderr)
            print("【方法2】環境変数として設定", file=sys.stderr)
            print("  export LINE_CHANNEL_ACCESS_TOKEN=\"...\"", file=sys.stderr)
            print("  export LINE_USER_ID=\"...\"", file=sys.stderr)
            print("", file=sys.stderr)
            print("⚠️ 注意: cronはシェルの設定ファイルを読みません！", file=sys.stderr)
            print("", file=sys.stderr)
            print("ヒント: --dry-run モードではLINE認証は不要です", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            sys.exit(2)
        else:
            print(f"⚠️ 警告: {', '.join(missing)} が設定されていません", file=sys.stderr)

    return token, user_id


def print_env_status():
    """現在の環境変数設定状況を表示"""
    print("📋 環境変数設定状況")
    print("-" * 60)

    api_key = os.environ.get("TWELVEDATA_API_KEY")
    print(f"TWELVEDATA_API_KEY: {'✅ 設定済み' if api_key else '❌ 未設定'}")

    line_token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    print(f"LINE_CHANNEL_ACCESS_TOKEN: {'✅ 設定済み' if line_token else '❌ 未設定'}")

    line_user = os.environ.get("LINE_USER_ID")
    print(f"LINE_USER_ID: {'✅ 設定済み' if line_user else '❌ 未設定'}")

    print("-" * 60)
