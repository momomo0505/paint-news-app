"""
翻訳・要約モジュール — Claude API で記事を日本語に翻訳・要約する
================================================================

機能:
- 記事タイトルの日本語翻訳
- 記事内容の3-5行日本語要約
- 記事カテゴリの自動分類
- レート制限への配慮（リトライ付き）
- バッチ処理による効率化
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from scripts.config import ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS
from scripts.collect_news import Article

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# カテゴリ定義
# ──────────────────────────────────────────────
CATEGORIES = {
    "equipment": "塗装設備",
    "technology": "塗装技術",
    "automotive": "自動車塗装",
    "aerospace": "航空機・宇宙",
    "industrial": "工業塗装",
    "regulation": "環境規制",
    "market": "市場動向",
    "company": "企業ニュース",
    "other": "その他",
}

# ──────────────────────────────────────────────
# プロンプト
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """\
あなたは塗装・コーティング業界の専門翻訳者兼アナリストです。
英語のニュース記事を日本語に翻訳・要約する際、以下のルールに従ってください：

1. タイトルは自然な日本語に翻訳する（意訳可）
2. 要約は3〜5行で、記事の核心を的確に伝える
3. 塗装・コーティング業界の専門用語は適切な日本語訳を使用する
4. カテゴリは以下から1つ選択する:
   - equipment: 塗装設備（ブース、乾燥炉、スプレーガン、ロボット等）
   - technology: 塗装技術（新工法、防食技術、研究開発等）
   - automotive: 自動車塗装（補修塗装、ボディショップ、EV車体等）
   - aerospace: 航空機・宇宙・防衛向け塗装・コーティング
   - industrial: 工業塗装（鉄鋼・船舶・橋梁・風力・建機・鉄道・制御盤等）
   - regulation: 環境規制（VOC、排出規制、安全基準、カーボンニュートラル等）
   - market: 市場動向（業界統計、需要予測、原材料市場等）
   - company: 企業ニュース（買収、新製品、人事、業績等）
   - other: その他

回答は必ず以下のJSON形式で返してください:
{
  "title_ja": "日本語タイトル",
  "summary_ja": "3〜5行の日本語要約",
  "category": "カテゴリキー"
}
"""


def _build_user_prompt(article: Article) -> str:
    """記事データからユーザープロンプトを構築する。"""
    parts = [
        f"Title: {article.title}",
        f"Source: {article.source}",
    ]
    if article.description:
        parts.append(f"Description: {article.description}")
    parts.append(f"URL: {article.url}")

    return "\n".join(parts)


# ──────────────────────────────────────────────
# Claude API 呼び出し（リトライ付き）
# ──────────────────────────────────────────────
def _call_claude_with_retry(
    client: anthropic.Anthropic,
    article: Article,
    max_retries: int = 3,
    base_delay: float = 2.0,
) -> dict[str, str]:
    """
    Claude API を呼び出して翻訳・要約結果を取得する。
    レート制限時は指数バックオフでリトライする。
    """
    user_prompt = _build_user_prompt(article)

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=CLAUDE_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )

            # レスポンスからテキストを抽出
            text = response.content[0].text.strip()

            # JSON パース（コードブロックで囲まれている場合に対応）
            if text.startswith("```"):
                # ```json ... ``` のパターンに対応
                lines = text.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```") and not in_block:
                        in_block = True
                        continue
                    if line.startswith("```") and in_block:
                        break
                    if in_block:
                        json_lines.append(line)
                text = "\n".join(json_lines)

            result = json.loads(text)

            # 必要なキーが存在するか検証
            required_keys = {"title_ja", "summary_ja", "category"}
            if not required_keys.issubset(result.keys()):
                missing = required_keys - result.keys()
                logger.warning("不足キー: %s（記事: %s）", missing, article.title[:40])
                # デフォルト値で補完
                result.setdefault("title_ja", article.title)
                result.setdefault("summary_ja", article.description or "（要約なし）")
                result.setdefault("category", "other")

            # カテゴリの正規化
            if result["category"] not in CATEGORIES:
                result["category"] = "other"

            return result

        except anthropic.RateLimitError:
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "レート制限に到達。%0.1f秒後にリトライ（%d/%d）",
                delay,
                attempt + 1,
                max_retries,
            )
            time.sleep(delay)

        except anthropic.APIError as exc:
            logger.error("Claude API エラー: %s（記事: %s）", exc, article.title[:40])
            if attempt < max_retries - 1:
                time.sleep(base_delay)
            else:
                raise

        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning(
                "レスポンス解析エラー: %s（記事: %s, attempt %d/%d）",
                exc,
                article.title[:40],
                attempt + 1,
                max_retries,
            )
            if attempt < max_retries - 1:
                time.sleep(base_delay)

    # 全リトライ失敗時のフォールバック
    logger.error("翻訳失敗（フォールバック使用）: %s", article.title[:60])
    return {
        "title_ja": article.title,
        "summary_ja": article.description or "（翻訳に失敗しました）",
        "category": "other",
    }


# ──────────────────────────────────────────────
# 関連性フィルタ（海外ニュース用）
# ──────────────────────────────────────────────
def filter_relevant_articles(
    articles: list[Article],
    language: str = "en",
    batch_size: int = 50,
) -> list[Article]:
    """
    Claude API を使って塗装業界に無関係な記事を除外する。

    収集した記事プールは数百件になるため、一定件数ごとに分割して判定する。
    1回のプロンプトに詰め込みすぎると判定精度と応答の安定性が落ちる。

    Args:
        articles: フィルタ対象の記事リスト
        language: "en"（海外）または "ja"（国内）
        batch_size: 1回の判定に含める記事数

    Returns:
        list[Article]: 業界関連記事のみ
    """
    if not articles:
        return []

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため関連性フィルタをスキップ")
        return articles

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    kept: list[Article] = []
    for start in range(0, len(articles), batch_size):
        batch = articles[start: start + batch_size]
        kept.extend(_filter_relevant_batch(client, batch, language))
        if start + batch_size < len(articles):
            time.sleep(1.0)

    logger.info(
        "関連性フィルタ（%s）合計: %d件 → %d件（除外: %d件）",
        language,
        len(articles),
        len(kept),
        len(articles) - len(kept),
    )
    return kept


def _filter_relevant_batch(
    client: anthropic.Anthropic,
    articles: list[Article],
    language: str,
) -> list[Article]:
    """関連性フィルタの1バッチ分を判定する。"""
    items_text = "\n".join(
        f"{i + 1}. {a.title} | {a.description[:120]}"
        for i, a in enumerate(articles)
    )

    if language == "ja":
        prompt = f"""以下の日本語ニュース記事リストを確認し、塗装・塗料・コーティング業界またはその関連産業に関係する記事を選んでください。

【必ず除外する記事】
- スポーツの試合結果・選手移籍情報（野球・サッカー・競馬・ゴルフ等）
- 芸能・エンタメ・音楽・映画・ドラマ（製造業との接点がないもの）
- グルメ・レシピ・旅行・観光・天気
- ネイルアート・美容・ファッション（工業用コーティングを除く）
- 政治・選挙・外交（製造業・産業への影響がないもの）
- 株価・株式・証券・IRニュース（業界動向でないもの）
- ★建築塗装・外壁塗装・屋根塗装・室内塗装・住宅リフォーム塗装（戸建て・マンション・ビルの外壁・屋根・内装を対象としたもの）
- ★家庭向けDIY塗装・ペンキ塗り（消費者向け）
- ★塗装業者の集客・見積もり・業者比較サービス（外壁塗装業者向け）

【含める記事（少しでも関連があれば積極的に含める）】
塗装設備・技術:
- 塗装ブース・スプレーブース・乾燥炉・塗装設備の新製品・技術
- 塗装ロボット・自動塗装・工場自動化・DX
- 粉体塗装・液体塗装・電着塗装・UV硬化塗装

補修塗装・自動車:
- 板金塗装・自動車補修塗装・自動車整備業界（※これは含める）
- EV普及・次世代車体・衝突修理業界への影響

工業・産業向け塗装（※これらは含める）:
- 航空機・宇宙機体の塗装・防食コーティング
- 鉄鋼・橋梁・パイプライン・プラント向け重防食塗料
- 船舶・海洋構造物の防食塗料
- 風力発電ブレード・洋上設備のコーティング・防食
- 建設機械・農業機械・重機の塗装（※機械の塗装であり建築塗装ではない）
- 鉄道車両・バス・公共交通車両の塗装・更新
- 制御盤・配電盤・電気機器の防錆・塗装

塗料市場・原材料:
- 塗料メーカー（関西ペイント・日本ペイント・中国塗料・アクサルタ等）の事業・製品・業績
- ナフサ・酸化チタン・樹脂・顔料・溶剤等の塗料原材料動向
- 原油・石油化学・中東情勢（塗料原材料コストに影響）
- 環境規制・VOC・カーボンニュートラル・廃液処理
- 労働力不足・人材採用・賃金動向（製造・工業塗装業界の経営課題）
- 中国・インド・EU・米国の塗装・製造業動向

需要先メーカー・顧客業界の景気動向（塗装需要に直結するため含める）:
- 自動車メーカー（トヨタ・ホンダ・日産・VW・GM等）の生産台数・販売動向・設備投資
- 航空機メーカー（ボーイング・エアバス・三菱・川崎重工・新明和工業等）の受注・製造動向
- 航空機内装（JAMCO等）・MRO（JAL・ANAの整備・修理・オーバーホール）市場
- 建設機械メーカー（コマツ・キャタピラー・日立建機等）の出荷・受注・市場動向
- 鉄道車両メーカー（日本車輌・川崎車両・アルストム・シーメンス・CRRC等）の受注・車両更新
- 風力発電・洋上風力の設備投資・新設・導入動向（国内外問わず）
- 造船・船舶業界の受注・建造動向（国内外問わず）
- 鉄鋼業界（日本製鉄・JFEスチール・神戸製鋼等）の生産・受注・市場動向（鉄鋼製品は塗装対象）
- 制御盤・分電盤・配電盤メーカーの市場動向（電気機器は塗装・防錆対象）
- 半導体製造装置メーカー（東京エレクトロン・ASML等）の受注・設備投資（装置製造に塗装工程あり）
- 防衛産業・防衛装備品（武器輸出・防衛予算・航空機・艦艇・装甲車等）の受注・市場動向
- 架装業界（特装車・消防車・高所作業車・タンクローリー等の上物製造）の動向
- バッテリー・全固体電池業界（トヨタ・パナソニック・CATL等）の開発・量産動向

【判断が難しい場合の基準】
「外壁塗装」「屋根塗装」「住宅塗装」「塗り替え」が主テーマ → 除外
「板金塗装」「工業塗装」「防食塗装」「塗装設備」が主テーマ → 含める
「自動車・航空・建機・鉄道・風力・造船・鉄鋼・防衛・架装・バッテリーの生産/受注/景気」が主テーマ → 含める

記事リスト（番号|タイトル|説明）:
{items_text}

塗装・塗料・関連産業に関係する記事番号をカンマ区切りで返してください。
例: 1,3,5
番号のみ返してください。"""
    else:
        prompt = f"""Review the following article list and select articles related to coatings, painting, or finishing technology across industrial/manufacturing sectors.

【EXCLUDE these types strictly】
- Sports news (game results, player transfers, scores)
- Entertainment, celebrity gossip, music, film (no manufacturing angle)
- Food, recipes, travel, tourism
- Nail polish / nail art (cosmetic only)
- PC software called "Paint" (e.g. Microsoft Paint)
- Pure political news with no manufacturing/industry angle
- Stock price / investment / shareholder news
- ★ Architectural / building exterior painting, house painting, residential repainting
  (Articles about painting homes, buildings, facades, roofs for homeowners or contractors)
- ★ Consumer DIY painting / home improvement painting
- ★ House painter services, residential painting contractors, painting estimates for homeowners

【INCLUDE broadly — any article touching these topics】
Core coatings industry:
- Paint booths, spray booths, finishing equipment, drying ovens
- Automotive refinish / collision repair / body shop (INCLUDE - not architectural)
- Industrial liquid coating, powder coating, electrodeposition
- Major coating brands: Axalta, PPG, BASF, Sikkens, Glasurit, Standox, Kansai Paint, Nippon Paint, AkzoNobel, Sherwin-Williams

Coatings by industry sector (all INCLUDE):
- Aerospace / aircraft painting and protective coatings
- Steel, metal, bridge, pipeline anti-corrosion coatings
- Marine / shipbuilding coatings
- Wind turbine / offshore / renewable energy coatings
- Construction machinery, agricultural machinery, heavy equipment coatings
  (NOTE: machinery coatings are industrial, NOT architectural — INCLUDE)
- Railway / rail vehicle / transit coatings
- Electrical enclosures, control panels, switchgear coatings

Technology & innovation:
- Painting robots, automated coating systems, Industry 4.0
- Waterborne, UV-cure, high-solid, powder coatings technology
- VOC regulations, environmental compliance, sustainability in coatings
- Coating adhesion, corrosion protection, surface treatment

Market & business:
- Coatings market analysis, forecasts, M&A (global, China, India, EU, US)
- Raw materials: naphtha, titanium dioxide, resins, pigments for paints
- EV transition impact on automotive coatings and body shops

Customer industry trends (INCLUDE — directly affects coating demand):
- Automotive manufacturer production volumes, sales trends, capital investment
  (Toyota, Honda, Nissan, Volkswagen, GM, Stellantis, Ford, Hyundai, etc.)
- Aircraft manufacturer orders and production trends (Boeing, Airbus, Mitsubishi, Kawasaki, Shin Meiwa)
- Aircraft interior manufacturers (JAMCO, etc.)
- MRO / aircraft maintenance, repair, overhaul market (JAL, ANA, Airbus MRO, etc.)
- Construction equipment manufacturer orders/shipments (Komatsu, Caterpillar, Hitachi Construction, CNH)
- Railway vehicle manufacturer orders and fleet renewal (Alstom, Siemens, Bombardier, CRRC, Kawasaki, Nippon Sharyo)
- Wind power / offshore wind installation and capacity investment trends (global)
- Shipbuilding industry orders and vessel construction trends (global)
- Steel industry production, market trends, major steelmakers (Nippon Steel, JFE, Kobe Steel, POSCO, ArcelorMittal)
  (Steel products are direct coating targets — INCLUDE)
- Control panel / switchgear / distribution board manufacturers and market trends
  (Electrical enclosures are coated for corrosion protection — INCLUDE)
- Semiconductor manufacturing equipment makers (Tokyo Electron, ASML, Applied Materials, Lam Research)
  (Equipment manufacturing involves coating processes — INCLUDE)
- Defense industry: weapons exports, defense budgets, military aircraft, naval vessels, armored vehicles
  (Defense equipment requires specialized coatings — INCLUDE)
- Vehicle body builder / truck body / special vehicle industry (fire trucks, aerial work platforms, tank trucks)
  (Special vehicles require industrial painting — INCLUDE)
- Battery / solid-state battery industry (Toyota, Panasonic, CATL, Samsung SDI)
  (Battery manufacturing equipment and casings require coatings — INCLUDE)

記事リスト（番号|タイトル|説明）:
{items_text}

Return the relevant article numbers as comma-separated values. When in doubt, include the article.
Example: 1,3,5,7
Return numbers only, no other text."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        numbers_text = response.content[0].text.strip()
        logger.info("関連性フィルタ（%s）バッチ結果: %s", language, numbers_text[:200])

        indices = [
            int(n.strip()) - 1
            for n in numbers_text.replace("，", ",").split(",")
            if n.strip().isdigit()
        ]
        filtered = [articles[i] for i in indices if 0 <= i < len(articles)]
        logger.info(
            "  バッチ（%s）: %d件 → %d件", language, len(articles), len(filtered)
        )
        return filtered

    except Exception as exc:
        logger.error("関連性フィルタエラー（このバッチは全件通過）: %s", exc)
        return articles


def deduplicate_articles(
    articles: list[Article],
    language: str = "ja",
) -> list[Article]:
    """
    Claude API を使って同一イベント・同一トピックの重複記事を除去する。

    同じ決算発表・新製品・規制改正などを複数メディアが報道している場合、
    最も情報量の多い1件のみ残してその他を除外する。

    Args:
        articles: 重複チェック対象の記事リスト
        language: "ja"（国内）または "en"（海外）

    Returns:
        list[Article]: 重複除去後の記事リスト
    """
    if len(articles) <= 1:
        return articles

    # まず URL 完全一致で除去
    seen_urls: set[str] = set()
    url_unique: list[Article] = []
    for a in articles:
        if a.url not in seen_urls:
            seen_urls.add(a.url)
            url_unique.append(a)

    if len(url_unique) <= 1:
        return url_unique

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため重複除去をスキップ")
        return url_unique

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    items_text = "\n".join(
        f"{i + 1}. {a.title}"
        for i, a in enumerate(url_unique)
    )

    if language == "ja":
        prompt = f"""以下のニュース記事タイトルリストを確認し、同じ出来事・イベント・トピックを複数メディアが重複して報道しているグループを特定してください。
各グループから最も情報量が多いと思われる記事を1件だけ残し、残りは除外します。

【重複とみなす典型例】
- 同一企業の同じ決算発表・業績報告（複数のニュースサイトが同じ発表を報道）
- 同一製品・サービスの発表（複数媒体が同じニュースを転載）
- 同一の法改正・規制変更
- 同じ展示会・イベントの告知

記事リスト:
{items_text}

残す記事の番号（重複を除去した後に残すもの）をカンマ区切りで返してください。
例: 1,3,5,7,9
番号のみ返してください。他の文言は不要です。"""
    else:
        prompt = f"""Review the following news article titles and identify groups of articles covering the exact same event, announcement, or topic (e.g., the same earnings report, product launch, or regulation covered by multiple outlets).

For each duplicate group, keep only the most informative article (usually the one with the most specific or detailed title).

Article list:
{items_text}

Return the numbers of articles to KEEP (after removing duplicates) as comma-separated values.
Example: 1,3,5,7,9
Return numbers only, no other text."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        numbers_text = response.content[0].text.strip()
        logger.info("重複除去（%s）結果: %s", language, numbers_text[:200])

        indices = [
            int(n.strip()) - 1
            for n in numbers_text.replace("，", ",").split(",")
            if n.strip().isdigit()
        ]

        deduplicated = [url_unique[i] for i in indices if 0 <= i < len(url_unique)]
        logger.info(
            "重複除去（%s）: %d件 → %d件（除外: %d件）",
            language,
            len(url_unique),
            len(deduplicated),
            len(url_unique) - len(deduplicated),
        )
        return deduplicated if deduplicated else url_unique

    except Exception as exc:
        logger.error("重複除去エラー（フォールバック: 全件返却）: %s", exc)
        return url_unique


def summarize_domestic_articles(
    articles: list[Article],
    batch_size: int = 10,
) -> list[Article]:
    """
    国内ニュース記事を Claude API で要約する（1〜2文）。
    title_ja と summary_ja を設定して返す。

    一度に多数の記事を要約させると応答が max_tokens に達して JSON が途中で
    途切れるため、一定件数ごとに分割して要約する。

    Args:
        articles: 国内ニュース記事リスト（日本語）
        batch_size: 1回の要約に含める記事数

    Returns:
        list[Article]: summary_ja が設定された記事リスト
    """
    if not articles:
        return []

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため要約をスキップ")
        for a in articles:
            a.title_ja = a.title
            a.summary_ja = a.description[:120] if a.description else ""
        return articles

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for start in range(0, len(articles), batch_size):
        batch = articles[start: start + batch_size]
        _summarize_domestic_batch(client, batch)
        if start + batch_size < len(articles):
            time.sleep(1.0)

    logger.info("国内記事要約完了: %d件", len(articles))
    return articles


def _summarize_domestic_batch(
    client: anthropic.Anthropic,
    articles: list[Article],
) -> None:
    """国内記事1バッチ分を要約し、各記事に summary_ja を設定する。"""
    items_text = "\n".join(
        f"{i + 1}. タイトル: {a.title}\n   詳細: {a.description[:200]}"
        for i, a in enumerate(articles)
    )

    prompt = f"""以下の日本語ニュース記事を各1〜2文で要約してください。
塗装業界の専門家向けに、記事の要点を分かりやすく伝えてください。
文末は「。」で締めてください。

記事リスト:
{items_text}

以下のJSON形式のみで返してください（説明文は不要）:
[{{"id": 1, "summary": "1〜2文の要約"}}, {{"id": 2, "summary": "1〜2文の要約"}}]"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # コードブロックを除去
        if "```" in text:
            lines = text.split("\n")
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith("```"):
                    in_block = not in_block
                    continue
                if in_block:
                    json_lines.append(line)
            text = "\n".join(json_lines)

        summaries = json.loads(text)
        summary_map = {int(s["id"]): s["summary"] for s in summaries}

        for i, article in enumerate(articles):
            article.title_ja = article.title
            article.summary_ja = summary_map.get(i + 1, article.description[:120] or "")

    except Exception as exc:
        logger.error("国内記事要約エラー（このバッチはフォールバック）: %s", exc)
        for article in articles:
            article.title_ja = article.title
            article.summary_ja = article.description[:150] if article.description else ""


# ──────────────────────────────────────────────
# 事業影響分析
# ──────────────────────────────────────────────
def analyze_articles_impact(
    articles: list[Article],
    batch_size: int = 12,
) -> list[Article]:
    """
    各記事についてアンデックス㈱への事業影響を Claude で分析する。

    塗装業界・競合・市場・規制・原材料・顧客産業など多角的視点から
    各記事の影響を 50〜80 字で生成し、article.impact_ja に格納する。

    Args:
        articles: 分析対象記事リスト（title_ja / summary_ja 設定済み推奨）
        batch_size: 1回の Claude 呼び出しに含める最大記事数

    Returns:
        list[Article]: impact_ja が設定された記事リスト
    """
    if not ANTHROPIC_API_KEY or not articles:
        return articles

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    for batch_start in range(0, len(articles), batch_size):
        batch = articles[batch_start: batch_start + batch_size]

        items_text = "\n".join(
            f"{i + 1}. 【{a.title_ja or a.title}】\n   {(a.summary_ja or a.description)[:200]}"
            for i, a in enumerate(batch)
        )

        prompt = f"""あなたはアンデックス㈱（塗装ブース・塗装設備メーカー、主要顧客：自動車補修・工業塗装分野）の経営・営業戦略コンサルタントです。

以下のニュース記事それぞれについて、アンデックス㈱への事業影響を分析してください。

【分析の視点（複数の角度から考察すること）】
- 塗装設備の需要増減・販売機会への影響
- 競合メーカーや業界勢力図の変化
- 技術革新・規制変化による製品戦略への示唆
- 原材料・部品調達コストへの影響
- 顧客産業（自動車・航空・建機・造船・鉄道・風力等）の景気動向の影響
- 新市場・新規顧客開拓の機会またはリスク
- 経営・人材・DX面での示唆

【注意】
- 塗装業界に限らず、マクロ経済・産業政策・エネルギー・物流など幅広い視点を取り入れること
- 直接関係がない記事でも、間接的な波及効果を考察すること
- 各分析は 50〜80 字の日本語で、簡潔かつ実務的に記述すること

記事リスト:
{items_text}

以下のJSON形式のみで返してください（説明文・マークダウン不要）:
[{{"id": 1, "impact": "50〜80字の影響分析"}}, {{"id": 2, "impact": "影響分析"}}, ...]"""

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=3000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            # コードブロック除去
            if "```" in text:
                lines = text.split("\n")
                json_lines, in_block = [], False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block:
                        json_lines.append(line)
                text = "\n".join(json_lines)

            impact_list = json.loads(text)
            impact_map = {int(item["id"]): item["impact"] for item in impact_list}

            for i, article in enumerate(batch):
                article.impact_ja = impact_map.get(i + 1, "")

            logger.info(
                "影響分析完了: batch %d〜%d (%d件)",
                batch_start + 1,
                batch_start + len(batch),
                len(batch),
            )

        except Exception as exc:
            logger.warning("影響分析エラー（バッチ %d〜）: %s", batch_start + 1, exc)
            # フォールバック: impact_ja を空のままにする

        if batch_start + batch_size < len(articles):
            time.sleep(1.5)

    return articles


def analyze_competitor_impact(competitor_items: list[dict]) -> list[dict]:
    """
    競合他社ニュースについてアンデックス㈱への事業影響を分析する。

    Args:
        competitor_items: 競合ニュースの dict リスト

    Returns:
        list[dict]: impact_ja キーが追加された dict リスト
    """
    if not ANTHROPIC_API_KEY or not competitor_items:
        return competitor_items

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    batch_size = 10
    for batch_start in range(0, len(competitor_items), batch_size):
        batch = competitor_items[batch_start: batch_start + batch_size]

        items_text = "\n".join(
            f"{i + 1}. 【{item.get('company', '')}】{item.get('title', '')}"
            for i, item in enumerate(batch)
        )

        prompt = f"""アンデックス㈱（塗装ブース・塗装設備メーカー）の立場から、以下の競合・関連メーカーのニュースそれぞれについて事業影響を分析してください。

【分析の視点】
- 競合との差別化・脅威・機会
- 市場シェア・顧客への影響
- 技術・製品戦略への示唆
- 営業活動・提案活動への活かし方

各分析は 40〜70 字の日本語で、簡潔かつ実務的に記述してください。

競合ニュースリスト:
{items_text}

以下のJSON形式のみで返してください:
[{{"id": 1, "impact": "影響分析"}}, {{"id": 2, "impact": "影響分析"}}, ...]"""

        try:
            response = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()

            if "```" in text:
                lines = text.split("\n")
                json_lines, in_block = [], False
                for line in lines:
                    if line.startswith("```"):
                        in_block = not in_block
                        continue
                    if in_block:
                        json_lines.append(line)
                text = "\n".join(json_lines)

            impact_list = json.loads(text)
            impact_map = {int(item["id"]): item["impact"] for item in impact_list}

            for i, item in enumerate(batch):
                item["impact_ja"] = impact_map.get(i + 1, "")

        except Exception as exc:
            logger.warning("競合影響分析エラー: %s", exc)
            for item in batch:
                item.setdefault("impact_ja", "")

        if batch_start + batch_size < len(competitor_items):
            time.sleep(1.5)

    return competitor_items


def generate_weekly_digest(
    competitor_items: list[dict],
    domestic_articles: list[Article],
    overseas_articles: list[Article],
) -> str:
    """
    収集した全ニュースをもとに塗装業界の週次総括コメントを生成する。

    重要トレンド 3〜5 点を箇条書きで返す。HTML 表示用に改行コードを含む文字列。

    Returns:
        str: 週次総括テキスト（空の場合は ""）
    """
    if not ANTHROPIC_API_KEY:
        return ""

    all_titles = []
    for item in competitor_items[:10]:
        all_titles.append(f"[競合] {item.get('company', '')}：{item.get('title', '')[:60]}")
    for a in domestic_articles[:10]:
        all_titles.append(f"[国内] {a.title_ja or a.title[:60]}")
    for a in overseas_articles[:10]:
        all_titles.append(f"[海外] {a.title_ja or a.title[:60]}")

    if not all_titles:
        return ""

    titles_text = "\n".join(all_titles)

    prompt = f"""あなたは塗装・コーティング業界の専門アナリストです。

今週収集された業界ニュースの見出し一覧を以下に示します。

{titles_text}

これらを踏まえ、今週の塗装業界で特に注目すべきトレンド・動向を 3〜5 点にまとめてください。

【要件】
- 各ポイントは 60〜120 字で具体的に記述すること
- 塗装業界に限らず、マクロ経済・エネルギー・規制・顧客産業（自動車・航空・建機等）の動向も視野に入れること
- 「今週何が起きているか」を客観的に整理すること
- 箇条書き形式で、各項目の冒頭にアイコン（●や▶など）を付けること

回答は日本語の箇条書きのみ（JSON不要）で返してください。"""

    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        digest = response.content[0].text.strip()
        logger.info("週次総括生成完了: %d 文字", len(digest))
        return digest
    except Exception as exc:
        logger.warning("週次総括生成エラー: %s", exc)
        return ""


# ──────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────
def translate_and_summarize(
    articles: list[Article],
    delay_between_calls: float = 1.0,
) -> list[Article]:
    """
    記事リストを Claude API で翻訳・要約する。

    Args:
        articles: 翻訳対象の記事リスト
        delay_between_calls: API 呼び出し間の待機秒数

    Returns:
        list[Article]: 翻訳済みの記事リスト（title_ja, summary_ja, category が設定済み）
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY が設定されていません。")
        raise ValueError("環境変数 ANTHROPIC_API_KEY を設定してください。")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    total = len(articles)
    logger.info("翻訳・要約開始: %d 件", total)

    for i, article in enumerate(articles, 1):
        logger.info(
            "[%d/%d] 翻訳中: %s",
            i,
            total,
            article.title[:60],
        )

        result = _call_claude_with_retry(client, article)

        article.title_ja = result["title_ja"]
        article.summary_ja = result["summary_ja"]
        article.category = result["category"]

        logger.info(
            "  → %s [%s]",
            article.title_ja[:40],
            CATEGORIES.get(article.category, "その他"),
        )

        # レート制限対策の待機（最後の記事では不要）
        if i < total and delay_between_calls > 0:
            time.sleep(delay_between_calls)

    logger.info("翻訳・要約完了: %d 件", total)
    return articles


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # テスト用のダミー記事
    test_articles = [
        Article(
            title="New Paint Booth Technology Reduces Energy Consumption by 30%",
            description="A leading manufacturer has developed a new spray booth design "
            "that significantly cuts energy costs while improving finish quality.",
            url="https://example.com/news/1",
            source="Coating World",
            published_at="2026-02-20T10:00:00Z",
        ),
    ]

    results = translate_and_summarize(test_articles)
    for a in results:
        print(f"Title (JA): {a.title_ja}")
        print(f"Summary (JA): {a.summary_ja}")
        print(f"Category: {a.category}")
