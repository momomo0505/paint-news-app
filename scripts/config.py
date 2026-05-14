"""
設定ファイル — 塗装業界ニュース自動まとめツール
=================================================
全スクリプト共通の定数・設定値を一元管理する。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# ローカル開発時は .env を自動読み込み（GitHub Actions では環境変数が直接設定される）
load_dotenv()

# ──────────────────────────────────────────────
# プロジェクトパス
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# ──────────────────────────────────────────────
# NewsAPI 設定（海外ニュース）
# ──────────────────────────────────────────────
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
NEWSAPI_BASE_URL = "https://newsapi.org/v2/everything"

# 検索キーワードグループ（OR 結合で使用）
SEARCH_KEYWORD_GROUPS = [
    '"paint booth" OR "spray booth" OR "coating booth"',
    '"industrial coating" OR "powder coating" OR "surface finishing"',
    '"automotive painting" OR "automotive coating" OR "paint shop"',
    '"paint technology" OR "coating technology" OR "painting equipment"',
    '"paint VOC" OR "coating regulation" OR "paint emission"',
]

# 日本国内ニュース用キーワードグループ
DOMESTIC_KEYWORD_GROUPS = [
    "塗装ブース 塗装設備 板金塗装",
    "自動車補修塗装 補修塗料 塗装業界",
    "塗装規制 VOC規制 塗料市場",
    "板金 塗装 ニュース 新製品",
    "自動車補修 塗料 材料 価格",
]

# 1キーワードグループあたりの最大取得件数
ARTICLES_PER_QUERY = 10

# 最終的にまとめに含める記事数の上限（各カテゴリ）
MAX_ARTICLES = 20
MAX_DOMESTIC_ARTICLES = 15
MAX_COMPETITOR_ITEMS = 30

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
# 競合他社・監視対象メーカー設定
# ──────────────────────────────────────────────
COMPETITOR_SITES = [
    # ── 国内メーカー ──────────────────────────
    {
        "name": "アネスト岩田",
        "url": "https://www.anest-iwata.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "吉田工業（燕エアクリーン）",
        "url": "https://www.tsubame-air-clean.jp/toso-booth/",
        "language": "ja",
    },
    {
        "name": "栗田工業",
        "url": "https://kurita-kogyo.co.jp/",
        "language": "ja",
    },
    {
        "name": "BFK",
        "url": "https://www.kk-bfk.com/news",
        "language": "ja",
    },
    {
        "name": "パーカーエンジニアリング",
        "url": "https://www.parker-eng.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "イヤサカ",
        "url": "https://www.iyasaka.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "バンザイ",
        "url": "https://www.banzai.co.jp/news.html",
        "language": "ja",
    },
    {
        "name": "トーコー",
        "url": "https://www.tohkohpro.com/",
        "language": "ja",
    },
    {
        "name": "アイペック（IPEC）",
        "url": "https://www.ipec-j.co.jp/",
        "language": "ja",
    },
    {
        "name": "大気社",
        "url": "https://www.taikisha.co.jp/news/",
        "language": "ja",
    },
    # ── 海外メーカー ──────────────────────────
    {
        "name": "Global Finishing Solutions",
        "url": "https://www.globalfinishing.com/news",
        "language": "en",
    },
    {
        "name": "USI Italia",
        "url": "https://www.usiitalia.com/en/news/",
        "language": "en",
    },
]

# ──────────────────────────────────────────────
# Claude API 設定
# ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 1024

# ──────────────────────────────────────────────
# メール送信設定 (Gmail SMTP)
# ──────────────────────────────────────────────
FROM_EMAIL = os.environ.get("FROM_EMAIL", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")

# ──────────────────────────────────────────────
# GitHub Pages 設定
# ──────────────────────────────────────────────
PAGES_BASE_URL = os.environ.get(
    "PAGES_BASE_URL",
    "https://your-username.github.io/paint-news-app/",
)

# ──────────────────────────────────────────────
# ロギング
# ──────────────────────────────────────────────
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
