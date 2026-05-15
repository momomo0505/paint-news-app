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
    "regulation": "環境規制",
    "market": "市場動向",
    "company": "企業ニュース",
    "other": "その他",
}

# ──────────────────────────────────────────────
# プロンプト
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """\
あなたは塗装業界の専門翻訳者兼アナリストです。
英語のニュース記事を日本語に翻訳・要約する際、以下のルールに従ってください：

1. タイトルは自然な日本語に翻訳する（意訳可）
2. 要約は3〜5行で、記事の核心を的確に伝える
3. 塗装業界の専門用語は適切な日本語訳を使用する
4. カテゴリは以下から1つ選択する:
   - equipment: 塗装設備（ブース、乾燥炉、スプレーガン等）
   - technology: 塗装技術（新工法、研究開発等）
   - automotive: 自動車塗装（自動車メーカー、車体塗装等）
   - regulation: 環境規制（VOC、排出規制、安全基準等）
   - market: 市場動向（業界統計、需要予測等）
   - company: 企業ニュース（買収、新製品、人事等）
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
) -> list[Article]:
    """
    Claude API を使って塗装業界に無関係な記事を一括除外する。
    全記事をまとめて1回のAPIコールで判定するため低コスト。

    Args:
        articles: フィルタ対象の記事リスト
        language: "en"（海外）または "ja"（国内）

    Returns:
        list[Article]: 業界関連記事のみ
    """
    if not articles:
        return []

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため関連性フィルタをスキップ")
        return articles

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    items_text = "\n".join(
        f"{i + 1}. {a.title} | {a.description[:120]}"
        for i, a in enumerate(articles)
    )

    if language == "ja":
        prompt = f"""以下の日本語ニュース記事リストを確認し、「自動車補修塗装」「工業塗装」「塗装ブース・塗装設備」「塗料製造業界」「板金塗装・自動車整備業界」のいずれかに明確に関連する記事番号のみを選んでください。

【必ず除外する記事】
- スポーツ（野球・サッカー・競馬など）
- 芸能・エンタメ・グルメ・旅行
- 政治・一般社会ニュース（塗装業界と無関係なもの）
- 住宅リフォーム・DIY塗装・インテリア
- ネイルアート・化粧品・美容
- 株価・株式・投資・証券・IR情報（業績発表であっても株式市場に関するもの）

【含めてよい記事】
- 塗装ブース・スプレーブースの新製品・技術
- 板金塗装・自動車補修塗装業界のニュース
- 工業用塗料・粉体塗装・液体塗装
- 塗料メーカー（アクサルタ、関西ペイント、日本ペイント等）の事業・製品・技術動向
- 自動車塗装関連の規制・環境対応
- 整備士・鈑金塗装業者向けの業界情報
- 中国・インド・EU等の塗装業界動向

記事リスト（番号|タイトル|説明）:
{items_text}

塗装業界に関連する記事番号のみをカンマ区切りで返してください。
例: 1,3,5
番号のみ返してください。"""
    else:
        prompt = f"""Review the following article list and select ONLY articles clearly related to: automotive refinish coatings, industrial coatings, paint booths/finishing equipment, paint manufacturing industry, body shop business, or coatings market trends (including China, India, EU).

【EXCLUDE these types of articles】
- Stock price, stock market, investment, securities, shareholder information
- Home/residential painting, DIY, interior decoration
- Nail polish, nail art, cosmetics, skincare
- Art, fine art, watercolor, canvas painting
- Face paint, body paint
- PC/software applications (e.g. Microsoft Paint)
- General company financial reports unrelated to coatings business operations

【INCLUDE these types of articles】
- Spray booth / paint booth technology and products
- Automotive refinish / collision repair industry news
- Industrial powder coating, liquid coating
- Major brands: Axalta / PPG / BASF / Sikkens / Kansai Paint / Nippon Paint
- VOC regulations, environmental compliance in coatings
- Coatings market analysis, forecasts (global, China, India, EU, etc.)
- EV impact on body shops and automotive coatings
- Body shop management, collision repair business trends

記事リスト（番号|タイトル|説明）:
{items_text}

Return ONLY the relevant article numbers as comma-separated values.
Example: 1,3,5,7
Return numbers only, no other text."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        numbers_text = response.content[0].text.strip()
        logger.info("関連性フィルタ（%s）結果: %s", language, numbers_text)

        indices = [
            int(n.strip()) - 1
            for n in numbers_text.split(",")
            if n.strip().isdigit()
        ]
        filtered = [articles[i] for i in indices if 0 <= i < len(articles)]
        logger.info(
            "関連性フィルタ（%s）: %d件 → %d件（除外: %d件）",
            language,
            len(articles),
            len(filtered),
            len(articles) - len(filtered),
        )
        return filtered

    except Exception as exc:
        logger.error("関連性フィルタエラー（フォールバック: 全件返却）: %s", exc)
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
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        numbers_text = response.content[0].text.strip()
        logger.info("重複除去（%s）結果: %s", language, numbers_text)

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


def summarize_domestic_articles(articles: list[Article]) -> list[Article]:
    """
    国内ニュース記事を Claude API で一括要約する（1〜2文）。
    title_ja と summary_ja を設定して返す。

    Args:
        articles: 国内ニュース記事リスト（日本語）

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
            max_tokens=2000,
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

        logger.info("国内記事要約完了: %d件", len(articles))

    except Exception as exc:
        logger.error("国内記事要約エラー（フォールバック使用）: %s", exc)
        for article in articles:
            article.title_ja = article.title
            article.summary_ja = article.description[:150] if article.description else ""

    return articles


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
