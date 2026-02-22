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
