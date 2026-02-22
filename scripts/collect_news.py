"""
ニュース収集モジュール — NewsAPI から塗装業界ニュースを取得する
================================================================

機能:
- 複数キーワードグループで検索し、網羅性を高める
- 重複記事の排除（URL ベース + タイトル類似度）
- 記事品質のフィルタリング（タイトル・説明文の存在チェック）
- 公開日の新しい順でソート
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from difflib import SequenceMatcher

import requests

from scripts.config import (
    NEWSAPI_KEY,
    NEWSAPI_BASE_URL,
    SEARCH_KEYWORD_GROUPS,
    ARTICLES_PER_QUERY,
    MAX_ARTICLES,
    SEARCH_DAYS_BACK,
    EXCLUDED_DOMAINS,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# データ型
# ──────────────────────────────────────────────
class Article:
    """取得した記事を表現するデータクラス。"""

    def __init__(
        self,
        title: str,
        description: str,
        url: str,
        source: str,
        published_at: str,
        image_url: str | None = None,
    ) -> None:
        self.title = title
        self.description = description
        self.url = url
        self.source = source
        self.published_at = published_at
        self.image_url = image_url

        # 翻訳・要約後に設定されるフィールド
        self.title_ja: str = ""
        self.summary_ja: str = ""
        self.category: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "image_url": self.image_url,
            "title_ja": self.title_ja,
            "summary_ja": self.summary_ja,
            "category": self.category,
        }

    def __repr__(self) -> str:
        return f"Article(title={self.title!r}, source={self.source!r})"


# ──────────────────────────────────────────────
# 重複判定
# ──────────────────────────────────────────────
def _is_similar_title(title_a: str, title_b: str, threshold: float = 0.75) -> bool:
    """2つのタイトルが類似しているかどうかを判定する。"""
    return SequenceMatcher(None, title_a.lower(), title_b.lower()).ratio() >= threshold


def _deduplicate_articles(articles: list[Article]) -> list[Article]:
    """URL とタイトル類似度に基づいて重複記事を排除する。"""
    seen_urls: set[str] = set()
    unique_articles: list[Article] = []

    for article in articles:
        # URL ベースの重複チェック
        normalized_url = article.url.rstrip("/").lower()
        if normalized_url in seen_urls:
            logger.debug("URL重複で除外: %s", article.title)
            continue

        # タイトル類似度ベースの重複チェック
        is_duplicate = False
        for existing in unique_articles:
            if _is_similar_title(article.title, existing.title):
                logger.debug(
                    "タイトル類似で除外: %s ≈ %s",
                    article.title,
                    existing.title,
                )
                is_duplicate = True
                break

        if not is_duplicate:
            seen_urls.add(normalized_url)
            unique_articles.append(article)

    return unique_articles


# ──────────────────────────────────────────────
# 記事品質フィルタ
# ──────────────────────────────────────────────
def _is_valid_article(raw: dict[str, Any]) -> bool:
    """記事データの品質チェック。"""
    title = raw.get("title") or ""
    description = raw.get("description") or ""
    url = raw.get("url") or ""

    # タイトルまたは説明文が空、URLが無い場合は除外
    if not title.strip() or not url.strip():
        return False

    # "[Removed]" などの無効な記事を除外（NewsAPI が返すことがある）
    if title.strip().lower() == "[removed]":
        return False
    if description.strip().lower() == "[removed]":
        return False

    return True


# ──────────────────────────────────────────────
# NewsAPI 呼び出し
# ──────────────────────────────────────────────
def _fetch_articles_for_query(
    query: str,
    from_date: str,
    to_date: str,
    page_size: int = ARTICLES_PER_QUERY,
) -> list[Article]:
    """1つのキーワードグループに対して NewsAPI を呼び出す。"""

    excluded = ",".join(EXCLUDED_DOMAINS)

    params: dict[str, Any] = {
        "q": query,
        "from": from_date,
        "to": to_date,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": page_size,
        "apiKey": NEWSAPI_KEY,
    }
    if excluded:
        params["excludeDomains"] = excluded

    logger.info("NewsAPI 検索: q=%s, from=%s, to=%s", query, from_date, to_date)

    try:
        response = requests.get(NEWSAPI_BASE_URL, params=params, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.error("NewsAPI リクエストエラー: %s", exc)
        return []

    data = response.json()

    if data.get("status") != "ok":
        logger.error(
            "NewsAPI エラーレスポンス: %s — %s",
            data.get("code"),
            data.get("message"),
        )
        return []

    raw_articles = data.get("articles", [])
    logger.info("取得件数: %d 件 (キーワード: %s)", len(raw_articles), query[:50])

    articles: list[Article] = []
    for raw in raw_articles:
        if not _is_valid_article(raw):
            continue
        articles.append(
            Article(
                title=raw["title"].strip(),
                description=(raw.get("description") or "").strip(),
                url=raw["url"].strip(),
                source=(raw.get("source", {}).get("name") or "Unknown").strip(),
                published_at=raw.get("publishedAt", ""),
                image_url=raw.get("urlToImage"),
            )
        )

    return articles


# ──────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────
def collect_news() -> list[Article]:
    """
    全キーワードグループからニュースを収集し、
    重複排除・ソート済みの記事リストを返す。

    Returns:
        list[Article]: 最大 MAX_ARTICLES 件の記事リスト（新しい順）
    """
    if not NEWSAPI_KEY:
        logger.error("NEWSAPI_KEY が設定されていません。")
        raise ValueError("環境変数 NEWSAPI_KEY を設定してください。")

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=SEARCH_DAYS_BACK)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    all_articles: list[Article] = []

    for query in SEARCH_KEYWORD_GROUPS:
        articles = _fetch_articles_for_query(query, from_date, to_date)
        all_articles.extend(articles)

    logger.info("全キーワードグループ合計: %d 件", len(all_articles))

    # 重複排除
    unique_articles = _deduplicate_articles(all_articles)
    logger.info("重複排除後: %d 件", len(unique_articles))

    # 公開日の新しい順でソート
    def _parse_date(article: Article) -> datetime:
        try:
            return datetime.fromisoformat(
                article.published_at.replace("Z", "+00:00")
            )
        except (ValueError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    unique_articles.sort(key=_parse_date, reverse=True)

    # 上限数に制限
    result = unique_articles[:MAX_ARTICLES]
    logger.info("最終記事数: %d 件", len(result))

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    articles = collect_news()
    for i, a in enumerate(articles, 1):
        print(f"{i}. [{a.source}] {a.title}")
        print(f"   {a.url}")
        print(f"   {a.published_at}")
        print()
