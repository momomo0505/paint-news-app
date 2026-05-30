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
    # 中国の塗装業界動向（最大市場・競合動向）
    'China coatings OR "Chinese paint" industry OR "China automotive refinish"',
    # インドの塗装業界動向（急成長市場）
    'India coatings OR "Indian paint" industry OR "India automotive" coatings market',
    # EU・ヨーロッパの規制・技術動向
    'Europe coatings OR "EU coatings" regulation OR "European paint" industry OR REACH coatings',
    # 航空機塗装（機体塗装・防食・航空宇宙）
    '"aerospace coating" OR "aircraft painting" OR "aircraft coating" OR "aviation finish"',
    # 鉄鋼・重防食・橋梁・船舶塗装
    '"steel coating" OR "anti-corrosion coating" OR "marine coating" OR "bridge painting" OR "heavy-duty coating"',
    # 風力発電・再生可能エネルギー向け塗装
    '"wind turbine coating" OR "wind blade coating" OR "offshore coating" OR "renewable energy coating"',
    # 建設機械・農業機械・産業機械塗装
    '"construction equipment" coating OR "heavy equipment" painting OR "agricultural machinery" coating',
    # 塗装ロボット・自動化・デジタル
    '"painting robot" OR "coating robot" OR "automated painting" OR "robotic coating" OR "Industry 4.0" coating',
    # 鉄道車両・バス塗装
    '"rail coating" OR "railway painting" OR "train coating" OR "transit vehicle" painting',
    # 電気機器・制御盤・配電盤塗装
    '"electrical enclosure" coating OR "control panel" painting OR "switchgear" coating',
    # 塗料原材料（ナフサ・樹脂・顔料）の市場動向
    'paint raw material OR "titanium dioxide" market OR "resin coating" supply OR naphtha "paint industry"',
    # 自動車メーカーの生産・販売動向（塗装需要の最大顧客）
    'Toyota OR Honda OR Nissan OR Volkswagen OR "General Motors" OR Stellantis production output OR "vehicle production" 2026',
    # 航空機メーカーの受注・製造動向（機体塗装需要）
    'Boeing OR Airbus aircraft orders OR production OR "aircraft manufacturing" 2026',
    # 建設機械メーカーの市場動向（建機塗装需要）
    'Komatsu OR Caterpillar OR "Hitachi Construction" OR "construction equipment" market OR demand 2026',
    # 鉄道車両メーカーの受注・更新動向
    'Alstom OR Siemens OR Bombardier OR CRRC "rolling stock" OR "railway vehicle" production OR order 2026',
    # 風力発電の設備投資・導入動向（ブレード・タワー塗装需要）
    '"wind power" OR "wind energy" installation OR "offshore wind" capacity 2026',
    # 造船・船舶業界の景気動向（船体塗装需要）
    'shipbuilding orders OR "ship construction" market OR "dry dock" 2026',
]

# 特定ニュースサイトを対象にした Google News RSS 検索（国内一般メディア）
# 各サイトの塗装・塗料業界関連記事を対象に絞り込む
DOMESTIC_SITE_SPECIFIC_KEYWORDS = [
    # 日本経済新聞（建設・不動産・素材・自動車業界を中心に塗装関連を収集）
    "site:nikkei.com 塗装 OR 塗料 OR 板金 OR 建築塗装 OR 補修塗装",
    # 47ニュース（地域の塗装業界・建設関連ニュース）
    "site:47news.jp 塗装 OR 塗料 OR 板金 OR 建築塗装",
    # CBCニュース（東海地域の自動車・整備・塗装業界）
    "site:hicbc.com 塗装 OR 塗料 OR 自動車整備 OR 板金",
    # TBSニュース
    "site:newsdig.tbs.co.jp 塗装 OR 塗料 OR 板金 OR 補修",
    # FNN（フジニュースネットワーク）
    "site:fnn.jp 塗装 OR 塗料 OR 板金 OR 建築塗装",
]

# 塗装業界専門サイト（直接スクレイピングで全記事を収集）
INDUSTRY_NEWS_SITES = [
    {
        "name": "WEB塗料報知",
        "url": "https://www.e-toryo.co.jp/info/",
        "language": "ja",
    },
    {
        "name": "COATAZ",
        "url": "https://coataz.com/",
        "language": "ja",
    },
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
    # 大手塗料メーカー動向
    "関西ペイント OR 日本ペイント OR 中国塗料",
    # 業界経営・人材
    "板金塗装 人材 経営",
    "塗装業 採用 課題",
    # 航空機・宇宙向け塗装
    "航空機 塗装 防食",
    "航空宇宙 コーティング",
    # 鉄鋼・橋梁・船舶・重防食
    "重防食塗料 鉄鋼",
    "橋梁 塗装 メンテナンス",
    "船舶塗料 防食",
    # 風力発電・再生可能エネルギー
    "風力発電 ブレード 塗装",
    "洋上風力 防食 コーティング",
    # 建設機械・農業機械
    "建設機械 塗装 工業",
    "農業機械 塗料 防錆",
    # 塗装ロボット・自動化
    "塗装ロボット 自動化",
    "ロボット塗装 工場",
    # 鉄道・バス車両
    "鉄道車両 塗装 メンテナンス",
    "バス 塗装 更新",
    # 制御盤・電気機器
    "制御盤 塗装 防錆",
    "配電盤 コーティング",
    # 原材料・ナフサ・顔料
    "ナフサ 塗料 原材料",
    "酸化チタン 塗料 市場",
    # ── 需要先メーカーの景気動向（塗装需要に直結） ──────────
    # 自動車メーカー（国内外）の生産・販売動向
    "自動車メーカー 生産台数 動向",
    "トヨタ 生産 販売 業績",
    "ホンダ 日産 生産 動向",
    "自動車 販売台数 国内",
    "自動車産業 設備投資",
    # 航空機メーカー・MRO（機体修理・塗装需要）
    "航空機 受注 製造 国内",
    "三菱航空機 川崎重工 航空",
    "MRO 整備 航空機 市場",
    # 建設機械メーカー（コマツ・日立建機等）
    "建設機械 出荷 受注 動向",
    "コマツ 日立建機 業績 市場",
    "建機 需要 景気 市場",
    # 鉄道車両メーカー（日本車輌・川崎車両等）
    "鉄道車両 受注 製造 市場",
    "日本車輌 川崎車両 鉄道",
    "鉄道 車両更新 新造 動向",
    # 風力発電・再生可能エネルギー設備投資
    "洋上風力 国内 設備投資 導入",
    "風力発電 新設 市場 動向",
    "再生可能エネルギー 設備 市場",
    # 造船・船舶業界（船体塗装需要）
    "造船 受注 市場 動向",
    "船舶 建造 国内 景気",
]

# 1キーワードグループあたりの最大取得件数
ARTICLES_PER_QUERY = 10

# 最終的にまとめに含める記事数の上限（各カテゴリ）
MAX_ARTICLES = 25           # 海外ニュース上限
MAX_DOMESTIC_ARTICLES = 35  # 国内ニュース上限（新規ソース追加に伴い拡大）
MAX_COMPETITOR_ITEMS = 30

# 検索対象期間（日数 ─ 過去30日間）
SEARCH_DAYS_BACK = 30

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
# 自社メンション検知（アンデックス㈱）
# ──────────────────────────────────────────────
# 自社が取材・掲載された記事を自動検知するためのキーワード
SELF_MENTION_COMPANY_NAME = "アンデックス㈱"
SELF_MENTION_KEYWORDS = [
    "アンデックス 塗装",
    "アンデックス 塗装ブース",
    "アンデックス 塗装設備",
    "アンデックス株式会社",
    "アンデックス 取材",
    "ANDEX 塗装",
    "ANDEX spray booth",
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
    {
        "name": "トリニティ工業",
        "url": "https://www.trinityind.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "明々工業（キュービックシステム）",
        "url": "https://www.cubicsystem.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "ヲサメ工業",
        "url": "https://www.osame.co.jp/index.html",
        "language": "ja",
    },
    # ── 海外メーカー ──────────────────────────
    {
        "name": "WLD（広州ウェイロンダ）",
        "url": "https://ja.wld-spraybooth.com/newslist-1",
        "language": "ja",
    },
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
    {
        "name": "Saicozero",
        "url": "https://saicozero.com/blog/",
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
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")

# 送信先メールアドレス（カンマ区切りで複数指定可）
# 例: "a@example.com,b@example.com,c@example.com"
_notify_raw = os.environ.get("NOTIFY_EMAIL", "")
NOTIFY_EMAILS: list[str] = [e.strip() for e in _notify_raw.split(",") if e.strip()]
NOTIFY_EMAIL: str = NOTIFY_EMAILS[0] if NOTIFY_EMAILS else ""

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
