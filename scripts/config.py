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
    # ── 新規追加：顧客業界の幅広い動向把握 ──────────────
    # 鉄鋼業界（板・形鋼の生産・価格動向）
    '"steel industry" OR "steelmaker" OR "steel production" OR "steel market" OR "steel demand" 2026',
    # 制御盤・分電盤・スイッチギア業界
    '"control panel" manufacturer OR "switchgear" industry OR "distribution board" market OR "electrical enclosure" manufacturer 2026',
    # 半導体製造装置（TEL・ASML・Applied Materials等。半導体メーカー自体は除外）
    '"semiconductor equipment" OR "wafer fabrication equipment" OR "Tokyo Electron" OR "Applied Materials" OR ASML OR "Lam Research" market 2026',
    # 造船業界・より幅広い動向
    'shipbuilding industry OR "ship order" OR "vessel construction" OR shipyard market 2026',
    # 航空機業界・機体製造（川重・新明和・三菱など）
    '"aircraft manufacturing" OR "aerospace manufacturing" OR "Kawasaki" aircraft OR "Mitsubishi Aircraft" OR "Shin Meiwa" 2026',
    # 航空機内装・整備（JAMCO・JAL・ANA・Airbus MRO）
    'JAMCO OR "aircraft interior" OR "aircraft MRO" OR "aviation maintenance" OR "aircraft overhaul" 2026',
    # 鉄道業界（国内外・車両更新・インフラ投資）
    '"railway industry" OR "rail market" OR "rolling stock" OR "train manufacturer" OR "metro" procurement 2026',
    # 防衛・防衛産業（武器輸出・防衛装備品）
    '"defense industry" OR "defence industry" OR "military equipment" OR "weapons export" OR "defense budget" OR "defense spending" 2026',
    # 架装業界（特装車・上物製造）
    '"truck body" manufacturer OR "special vehicle" OR "vehicle upfitter" OR "special purpose vehicle" OR "vehicle superstructure" 2026',
    # 建設機械業界（より幅広い市場動向）
    '"construction machinery" industry OR "construction equipment" market OR "heavy machinery" demand OR Komatsu OR Caterpillar 2026',
    # バッテリー・全固体電池業界
    '"solid-state battery" OR "all-solid-state battery" OR "battery industry" OR "EV battery" OR "battery market" OR "energy storage" 2026',
]

# 海外ニュース収集用 Google News RSS キーワード（英語）
# ※NewsAPI はフリープランで 100リクエスト/日の制限があるため、
#   Google News RSS を主力とし NewsAPI はフォールバック用途に限定する。
OVERSEAS_RSS_KEYWORDS = [
    # 塗装ブース・設備（最も業界固有）
    '"spray booth" OR "paint booth" OR "coating booth" finishing',
    # 自動車補修塗装
    '"automotive refinish" OR "collision repair" coating',
    # ボディショップ経営
    '"body shop" business OR "auto body" industry OR "collision center"',
    # 工業塗装全般
    '"industrial coatings" OR "industrial painting" OR "powder coating" industry',
    # 主要塗料ブランド動向
    'Axalta OR PPG OR "BASF Coatings" OR Sikkens OR "Kansai Paint" OR "Nippon Paint" coatings',
    # 塗料市場分析
    '"coatings market" OR "paint market" analysis OR forecast OR trend 2026',
    # EV・次世代車両
    '"electric vehicle" coating OR EV "body shop" OR "autonomous vehicle" repair',
    # 環境規制・技術革新
    '"coatings industry" VOC OR regulation OR sustainability OR waterborne',
    # 航空機塗装
    '"aerospace coating" OR "aircraft coating" OR "aviation finish"',
    # 鉄鋼・重防食・船舶
    '"anti-corrosion coating" OR "marine coating" OR "steel coating" OR "bridge painting"',
    # 風力発電向けコーティング
    '"wind turbine coating" OR "wind blade coating" OR "offshore coating"',
    # 建設機械・重機向け塗装
    '"construction equipment" coating OR "heavy equipment" painting',
    # 塗装ロボット・自動化
    '"painting robot" OR "automated painting" OR "robotic coating" OR "Industry 4.0" coating',
    # 鉄道・バス車両
    '"rail coating" OR "railway painting" OR "train coating"',
    # 塗料原材料
    '"titanium dioxide" OR "resin coating" OR naphtha "paint industry"',
    # 自動車メーカー生産動向（塗装需要の最大顧客）
    'Toyota OR Honda OR Volkswagen OR "General Motors" "vehicle production" 2026',
    # 航空機メーカー動向
    'Boeing OR Airbus aircraft orders OR production 2026',
    # 建設機械メーカー
    'Komatsu OR Caterpillar OR "construction equipment" market 2026',
    # 造船・船舶
    'shipbuilding orders OR "ship construction" market 2026',
    # 鉄鋼業界
    '"steel industry" OR "steel production" OR "steel market" 2026',
    # 防衛産業
    '"defense industry" OR "military equipment" OR "defense budget" 2026',
    # バッテリー・全固体電池
    '"solid-state battery" OR "EV battery" OR "battery market" 2026',
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
# COATAZ はクライアントサイドレンダリング（HTMLにリンクが含まれない）ため
# requests + BeautifulSoup では収集できず、対象から除外している。
INDUSTRY_NEWS_SITES = [
    {
        "name": "WEB塗料報知",
        "url": "https://www.e-toryo.co.jp/info/",
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
    # ── 新規追加：顧客業界の幅広い動向把握 ──────────────
    # 鉄鋼業界
    "鉄鋼業界 動向 市場",
    "鉄鋼メーカー 受注 生産 業績",
    "日本製鉄 JFEスチール 神戸製鋼 動向",
    # 制御盤・分電盤業界
    "制御盤業界 市場 動向",
    "分電盤 配電盤 市場 メーカー",
    "制御盤メーカー 受注 設備投資",
    # 半導体製造装置業界（半導体メーカーではなく装置メーカー）
    "半導体製造装置 市場 動向",
    "東京エレクトロン 業績 受注",
    "半導体装置 国内メーカー 受注 設備",
    # 造船業界（幅広い動向）
    "造船業界 受注 景気 市場",
    "国内造船 新造船 建造量",
    # 航空機業界・機体製造
    "川崎重工 新明和工業 三菱 航空機 受注",
    "航空機製造 機体 国内 動向",
    "航空宇宙 製造 設備投資 市場",
    # 航空機内装・MRO（整備・修理・オーバーホール）
    "JAMCO 航空機 内装 動向",
    "JAL ANA 航空機整備 MRO 投資",
    "航空機 MRO 整備 市場 動向",
    # 鉄道業界（国内外）
    "鉄道業界 動向 市場 受注",
    "鉄道車両メーカー 受注 製造 動向",
    "海外鉄道 インフラ 受注 日本",
    # 防衛関連業界
    "防衛産業 動向 受注 市場",
    "武器輸出 防衛装備品 解禁",
    "防衛関連 設備投資 受注 景気",
    "防衛省 装備品 調達 動向",
    # 架装業界（特装車・上物）
    "架装業界 特装車 動向 市場",
    "架装メーカー 受注 特装",
    "特装車 消防車 高所作業車 架装",
    # 建設機械業界（幅広い動向）
    "建設機械業界 市場 景気 動向",
    "コマツ 日立建機 住友建機 業績",
    "建機 需要 受注 国内外",
    # バッテリー・全固体電池業界
    "全固体電池 市場 開発 量産",
    "バッテリー業界 電池 市場 動向",
    "EV電池 全固体 トヨタ パナソニック 開発",
    "蓄電池 市場 設備投資 動向",
]

# NewsAPI の1キーワードグループあたりの取得件数
ARTICLES_PER_QUERY = 10

# Google News RSS は検索語の一致度に関わらず最大100件を返し、後半は
# 「そのサイトの新着記事」で埋まる。上位のみ採用して無関係記事の流入を防ぐ。
RSS_ITEMS_PER_KEYWORD = 12
SITE_SPECIFIC_ITEMS_PER_KEYWORD = 15

# 関連性フィルタにかける記事プールの上限。
# フィルタ通過率は1割前後のため、最終掲載数より十分多く確保する。
DOMESTIC_POOL_SIZE = 240
OVERSEAS_POOL_SIZE = 150

# 最終的にまとめに含める記事数の上限（関連性フィルタ通過後に適用）
MAX_ARTICLES = 25
MAX_DOMESTIC_ARTICLES = 25
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
    {
        "name": "サンワ・リノテック",
        "url": "https://sanwa-renotech.com/",
        "language": "ja",
        "section_include": ["NEWS"],
    },
    {
        "name": "大塚刷毛製造（マルテー）",
        "url": "https://www.maru-t.co.jp/news/",
        "language": "ja",
    },
    {
        "name": "サンエス工業",
        "url": "https://www.sanesu-ind.co.jp/news/",
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
    {
        "name": "RTT Finishing Solutions",
        "url": "https://rttsolutions.com/blog/",
        "language": "en",
    },
    {
        "name": "Rohner Finishing Systems",
        "url": "https://www.rohnerspraybooths.com/blog",
        "language": "en",
    },
    {
        "name": "Junair Spraybooths",
        "url": "https://www.junair-spraybooths.co.uk/information/blog/",
        "language": "en",
    },
    {
        "name": "Termomeccanica GL",
        "url": "https://termomeccanicagl.com/",
        "language": "it",
    },
    {
        "name": "Bostec",
        "url": "https://www.bostec.co.uk/",
        "language": "en",
    },
    {
        "name": "Unitech Machinery",
        "url": "https://unitechmachinery.co.uk/resources/news/",
        "language": "en",
    },
    {
        "name": "AFC Finishing Systems",
        "url": "https://afc-ca.com/",
        "language": "en",
    },
    {
        "name": "Marathon Finishing Systems",
        "url": "https://marathonspraybooths.com/",
        "language": "en",
    },
    {
        "name": "Autoke Machinery Equipment",
        "url": "https://sprayboothmanufacturer.com/news/",
        "language": "en",
    },
]

# ──────────────────────────────────────────────
# Claude API 設定
# ──────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 1024

# ──────────────────────────────────────────────
# メール送信設定 (SMTP 汎用)
# ──────────────────────────────────────────────
FROM_EMAIL = os.environ.get("FROM_EMAIL", "")

# SMTP サーバー設定
# SMTP_HOST を指定しない場合は Gmail SMTP にフォールバック（後方互換）
SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))

# SMTP 認証ユーザー名（省略時は FROM_EMAIL を使用）
SMTP_USER: str = os.environ.get("SMTP_USER", "") or FROM_EMAIL

# SMTP パスワード（SMTP_PASSWORD を優先、未設定時は GMAIL_APP_PASSWORD にフォールバック）
SMTP_PASSWORD: str = (
    os.environ.get("SMTP_PASSWORD", "")
    or os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
)

# 後方互換用エイリアス（既存コードが参照している場合のため残す）
GMAIL_APP_PASSWORD: str = SMTP_PASSWORD

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
