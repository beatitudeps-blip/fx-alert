#!/usr/bin/env python3
"""
Google API 認証ヘルパー
service account JSON で Sheets / Docs / Drive に接続する。

認証情報の優先順位:
  1. 環境変数 GOOGLE_SERVICE_ACCOUNT_JSON (JSON文字列)
  2. 環境変数 GOOGLE_SERVICE_ACCOUNT_FILE (ファイルパス)
  3. .env の GOOGLE_SERVICE_ACCOUNT_FILE
"""
import json
import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive",
]


def _get_credentials():
    """service account 認証情報を取得する。"""
    from google.oauth2.service_account import Credentials

    # 1. JSON文字列（GitHub Secrets 用）
    json_str = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if json_str:
        info = json.loads(json_str)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    # 2. ファイルパス
    json_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
    if json_path and Path(json_path).exists():
        return Credentials.from_service_account_file(json_path, scopes=SCOPES)

    # 3. .env からの読み込み（ローカル開発用）
    try:
        from dotenv import load_dotenv
        load_dotenv()
        json_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
        if json_path and Path(json_path).exists():
            return Credentials.from_service_account_file(json_path, scopes=SCOPES)
    except ImportError:
        pass

    raise RuntimeError(
        "Google credentials not found. "
        "Set GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_SERVICE_ACCOUNT_FILE."
    )


def get_gspread_client():
    """gspread クライアントを返す。"""
    import gspread
    creds = _get_credentials()
    return gspread.authorize(creds)


def get_docs_service():
    """Google Docs API サービスを返す。"""
    from googleapiclient.discovery import build
    creds = _get_credentials()
    return build("docs", "v1", credentials=creds, cache_discovery=False)


def get_drive_service():
    """Google Drive API サービスを返す。"""
    from googleapiclient.discovery import build
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_env(key: str, required: bool = True) -> str:
    """環境変数を取得する。required=True なら未設定時にエラー。"""
    val = os.environ.get(key, "")
    if required and not val:
        raise RuntimeError(f"Environment variable {key} is not set.")
    return val
