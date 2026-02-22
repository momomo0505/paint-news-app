"""
設定ファイル — 塗装業界ニュース自動まとめツール
=================================================
全スクリプト共通の定数・設定値を一元管理する。
"""

import os
from pathlib import Path

# ──────────────────────────────────────────────
# プロジェクトパス
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# ──────────────────────────────────────────────
# NewsAPI 設定
# ──────────────────────────────────────────────
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"

# 検索キーワードグループ（OR 結合で使用）
# 各グループから取得し、重複排除して品質の高い結果を得る
SEARCH_KEYWORD_GROUPS = [
    # 塗装設備系
    '"paint booth" OR "spray booth" OR "coating booth"',
    # 塗装技術系
    '"industrial coating" OR "powder coating" OR "surface finishing"',
    # 自動車塗装系
    '"automotive painting" OR "automotive coating" OR "paint shop"',
    # 塗装業界動向
    '"paint technology" OR "coating technology" OR "painting equipment"',
    # 環境規制・VOC関連
    '"paint VOC" OR "coating regulation" OR "paint emission"',
]

# 1キーワードグループあたりの最大取得件数
ARTICLES_PER_QUERY = 10

# 最終的にまとめに含める記事数の上限
MAX_ARTICLES = 20

# 検索対象期間（日数 ─ 過去7日間）
SEARCH_DAYS_BACK = 7

# 除外するドメイン（低品質・無関係なソースを除外）
EXCLUDED_DOMAINS = [
    "youtube.com",
    "tiktok.com",
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "pinterest.com",
]

# ──────────────────────────────────────────────
# Claude API 設定
# ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 1024

# ──────────────────────────────────────────────
# SendGrid 設定
# ──────────────────────────────────────────────
SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")

# ──────────────────────────────────────────────
# GitHub Pages 設定
# ──────────────────────────────────────────────
# GitHub Pages で公開する場合のベースURL
# 例: https://<username>.github.io/<repo>/
GITHUB_PAGES_BASE_URL = os.environ.get(
    "GITHUB_PAGES_BASE_URL",
    "https://your-username.github.io/paint-news-app/",
)

# ──────────────────────────────────────────────
# ロギング
# ──────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
