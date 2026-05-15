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

# 海外ニュース検索キーワードグループ（営業・経営戦略情報を広く収集）
SEARCH_KEYWORD_GROUPS = [
    # 塗装ブース・設備（最も業界固有）
    '"paint booth" OR "spray booth" OR "coating booth" OR "finishing booth"',
    # 自動車補修塗装・ボディショップ経営
    '"automotive refinish" OR "automotive refinishing" OR "collision repair" coating',
    # ボディショップ・修理業界の経営・市場動向
    '"body shop" business OR "collision center" management OR "auto body" industry',
    # 工業塗装（産業用）
    '"industrial coatings" OR "industrial painting" OR "powder coating" industry',
    # 塗料メーカー・主要ブランドの動向
    'Axalta OR "PPG Refinish" OR "BASF Coatings" OR Sikkens OR Glasurit OR Standox',
    # 塗料市場分析・市場予測
    '"coatings market" OR "paint market" analysis OR forecast OR trend 2026',
    # EV・次世代車両と塗装業界の変化
    '"electric vehicle" coating OR EV "body shop" OR "autonomous vehicle" repair',
    # 環境規制・技術革新
    '"coatings industry" (VOC OR regulation OR innovation OR waterborne OR "carbon neutral")',
    # 水性・環境対応塗料の普及
    '"waterborne coatings" OR "water-based paint" automotive OR "low VOC" refinish',
]

# 国内ニュース収集用 Google News RSS キーワード
# 営業・経営戦略立案に役立つ幅広い業界情報を収集
DOMESTIC_RSS_KEYWORDS = [
    # 塗装設備・ブース
    "塗装ブース 自動車",
    "スプレーブース 工業塗装",
    "塗装設備 新製品",
    # 補修塗装・板金業界の動向
    "板金塗装 業界動向",
    "自動車補修塗装 市場",
    "鈑金塗装 経営",
    # 塗料・素材市場
    "補修塗料 新製品",
    "塗料市場 動向",
    "水性塗料 自動車補修",
    # 環境規制・カーボンニュートラル
    "VOC規制 塗装",
    "カーボンニュートラル 塗料",
    # EV・次世代技術
    "EV 塗装 車体",
    "塗装 DX 自動化",
    # 大手塗料メーカー動向（競合・仕入れ先情報）
    "関西ペイント OR 日本ペイント OR 中国塗料",
    # 業界経営・人材
    "板金塗装 人材 経営",
    "塗装業 採用 課題",
]

# 1キーワードグループあたりの最大取得件数
ARTICLES_PER_QUERY = 10

# 最終的にまとめに含める記事数の上限（各カテゴリ）
MAX_ARTICLES = 25           # 海外ニュース上限（拡充に伴い増加）
MAX_DOMESTIC_ARTICLES = 20  # 国内ニュース上限（拡充に伴い増加）
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
