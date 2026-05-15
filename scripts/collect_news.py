"""
ニュース収集モジュール
================================================================

機能:
- 海外ニュース: NewsAPI（英語）で塗装業界ニュースを取得
- 国内ニュース: Google News RSS（feedparser）で日本語ニュースを取得
- 重複記事の排除（URL ベース + タイトル類似度）
- 記事品質のフィルタリング
- 公開日の新しい順でソート
"""

from __future__ import annotations

import calendar
import logging
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

from scripts.config import (
    NEWSAPI_KEY,
    NEWSAPI_BASE_URL,
    SEARCH_KEYWORD_GROUPS,
    DOMESTIC_RSS_KEYWORDS,
    DOMESTIC_SITE_SPECIFIC_KEYWORDS,
    INDUSTRY_NEWS_SITES,
    ARTICLES_PER_QUERY,
    MAX_ARTICLES,
    MAX_DOMESTIC_ARTICLES,
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
        skip_filter: bool = False,
    ) -> None:
        self.title = title
        self.description = description
        self.url = url
        self.source = source
        self.published_at = published_at
        self.image_url = image_url
        # True の場合、関連性フィルタをバイパスして必ずレポートに含める
        # (塗装業界専門サイト・指定メディアのサイト特化検索記事に設定)
        self.skip_filter: bool = skip_filter

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
            "skip_filter": self.skip_filter,
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
        if response.status_code == 429:
            # フリープランの日次クオータ枯渇 — 待機しても回復しないためNoneを返して早期終了を促す
            logger.warning("NewsAPI 日次クオータ超過 (429)。このクエリをスキップ: q=%s", query[:50])
            return None  # type: ignore[return-value]
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

    for i, query in enumerate(SEARCH_KEYWORD_GROUPS):
        if i > 0:
            time.sleep(1.0)
        result = _fetch_articles_for_query(query, from_date, to_date)
        if result is None:
            # 429（日次クオータ枯渇）— 残りは全部スキップ
            logger.warning("NewsAPI クオータ枯渇を検出。残りキーワードグループをスキップします。")
            break
        all_articles.extend(result)

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


def _parse_rss_date(entry: Any) -> datetime:
    """RSS エントリの公開日を datetime に変換する。"""
    JST = timezone(timedelta(hours=9))
    published = getattr(entry, "published_parsed", None)
    if published:
        try:
            ts = calendar.timegm(published)
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(JST)
        except Exception:
            pass
    return datetime.now(JST)


def _clean_rss_summary(html: str) -> str:
    """Google News RSSの要約HTMLからテキストを抽出する。"""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:300]


def collect_domestic_news() -> list[Article]:
    """
    国内塗装業界ニュースを複数のソースから収集する。

    収集元:
    - Google News RSS（汎用キーワード検索）
    - Google News RSS（日経・47ニュース・CBC・TBS・FNN サイト特化検索）
    - WEB塗料報知・COATAZ 直接スクレイピング

    Returns:
        list[Article]: 最大 MAX_DOMESTIC_ARTICLES 件の記事リスト（新しい順）
    """
    JST = timezone(timedelta(hours=9))
    cutoff = datetime.now(JST) - timedelta(days=SEARCH_DAYS_BACK)
    base_url = "https://news.google.com/rss/search"

    all_articles: list[Article] = []

    # ── 汎用キーワード検索（既存） ──
    for keyword in DOMESTIC_RSS_KEYWORDS:
        params = {
            "q": keyword,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        logger.info("Google News RSS 検索: %s", keyword)

        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.warning("RSS 取得エラー (%s): %s", keyword, exc)
            continue

        entries = getattr(feed, "entries", [])
        logger.info("  取得: %d 件", len(entries))

        for entry in entries:
            pub_dt = _parse_rss_date(entry)
            if pub_dt < cutoff:
                continue

            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            summary_html = getattr(entry, "summary", "") or ""
            description = _clean_rss_summary(summary_html)

            link = getattr(entry, "link", "") or ""

            source_info = getattr(entry, "source", None)
            if source_info and hasattr(source_info, "title"):
                source = source_info.title
            else:
                source = "Google News"

            all_articles.append(
                Article(
                    title=title,
                    description=description,
                    url=link,
                    source=source,
                    published_at=pub_dt.isoformat(),
                )
            )

        # Google に負荷をかけないよう短い待機
        time.sleep(0.5)

    # ── サイト特化検索（日経・47ニュース・CBC・TBS・FNN） ──
    logger.info("--- サイト特化ニュース収集開始 ---")
    site_articles = collect_site_specific_domestic_news()
    all_articles.extend(site_articles)

    # ── 業界専門サイト直接スクレイピング（塗料報知・COATAZ） ──
    logger.info("--- 業界専門サイト収集開始 ---")
    industry_articles = collect_industry_site_news()
    all_articles.extend(industry_articles)

    logger.info("国内合計（重複排除前）: %d 件", len(all_articles))

    unique_articles = _deduplicate_articles(all_articles)
    logger.info("国内重複排除後: %d 件", len(unique_articles))

    def _sort_key(article: Article) -> datetime:
        try:
            return datetime.fromisoformat(article.published_at)
        except (ValueError, AttributeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    unique_articles.sort(key=_sort_key, reverse=True)
    result = unique_articles[:MAX_DOMESTIC_ARTICLES]
    logger.info("国内最終記事数: %d 件", len(result))
    return result


_SCRAPE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

_DATE_PATTERNS = [
    r"(\d{4})[./年](\d{1,2})[./月](\d{1,2})",  # 2026.05.14 / 2026/05/14 / 2026年5月14日
    r"(\d{4})-(\d{1,2})-(\d{1,2})",              # 2026-05-14
]


def _scrape_parse_date(text: str) -> datetime | None:
    """テキストから日付を抽出して datetime を返す。"""
    JST = timezone(timedelta(hours=9))
    for pattern in _DATE_PATTERNS:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d, tzinfo=JST)
        except ValueError:
            continue
    return None


def collect_site_specific_domestic_news() -> list[Article]:
    """
    日経・47ニュース・CBC・TBS・FNN など指定ニュースサイトを対象に
    Google News RSS で国内塗装業界関連ニュースを収集する。

    Returns:
        list[Article]: 取得した記事リスト（重複排除前）
    """
    JST = timezone(timedelta(hours=9))
    cutoff = datetime.now(JST) - timedelta(days=SEARCH_DAYS_BACK)
    base_url = "https://news.google.com/rss/search"
    all_articles: list[Article] = []

    for keyword in DOMESTIC_SITE_SPECIFIC_KEYWORDS:
        params = {
            "q": keyword,
            "hl": "ja",
            "gl": "JP",
            "ceid": "JP:ja",
        }
        url = base_url + "?" + urllib.parse.urlencode(params)
        logger.info("サイト特化 Google News RSS 検索: %s", keyword[:60])

        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.warning("RSS 取得エラー (%s): %s", keyword[:40], exc)
            continue

        entries = getattr(feed, "entries", [])
        logger.info("  取得: %d 件", len(entries))

        for entry in entries:
            pub_dt = _parse_rss_date(entry)
            if pub_dt < cutoff:
                continue

            title = getattr(entry, "title", "").strip()
            if not title:
                continue

            summary_html = getattr(entry, "summary", "") or ""
            description = _clean_rss_summary(summary_html)
            link = getattr(entry, "link", "") or ""

            source_info = getattr(entry, "source", None)
            if source_info and hasattr(source_info, "title"):
                source = source_info.title
            else:
                # キーワードの site: 部分からソース名を推定
                site_match = re.search(r"site:([^\s]+)", keyword)
                source = site_match.group(1) if site_match else "Google News"

            all_articles.append(
                Article(
                    title=title,
                    description=description,
                    url=link,
                    source=source,
                    published_at=pub_dt.isoformat(),
                    # 一般メディアの記事は広義フィルタを通す（skip_filter=False）
                )
            )

        time.sleep(0.5)

    logger.info("サイト特化ニュース取得（重複排除前）: %d 件", len(all_articles))
    return all_articles


def collect_industry_site_news() -> list[Article]:
    """
    塗装業界専門サイト（WEB塗料報知・COATAZ）を直接スクレイピングして
    最新記事を収集する。

    Returns:
        list[Article]: 取得した記事リスト（重複排除前）
    """
    JST = timezone(timedelta(hours=9))
    cutoff = datetime.now(JST) - timedelta(days=SEARCH_DAYS_BACK)
    all_articles: list[Article] = []

    for site in INDUSTRY_NEWS_SITES:
        name = site["name"]
        url = site["url"]
        logger.info("業界専門サイト収集: %s (%s)", name, url)

        try:
            resp = requests.get(url, headers=_SCRAPE_HEADERS, timeout=20)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding
            soup = BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.warning("%s: ページ取得失敗: %s", name, exc)
            continue

        # リンクと日付を含むアイテムを抽出（check_competitors.py と同様のアプローチ）
        found = 0
        seen_urls: set[str] = set()

        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            link = urljoin(url, href)
            if link in seen_urls:
                continue

            title = a_tag.get_text(strip=True)
            if len(title) < 5:
                continue

            # 周辺テキストから日付を探す
            parent = a_tag.parent
            parent_text = parent.get_text(separator=" ", strip=True) if parent else ""
            date = _scrape_parse_date(parent_text) or _scrape_parse_date(title)

            if date is None or date < cutoff:
                continue

            seen_urls.add(link)
            all_articles.append(
                Article(
                    title=title[:200],
                    description="",
                    url=link,
                    source=name,
                    published_at=date.isoformat(),
                    skip_filter=True,  # 業界専門サイトの記事はフィルタをバイパス
                )
            )
            found += 1

        logger.info("  %s: %d 件取得", name, found)
        time.sleep(1.0)

    logger.info("業界専門サイト取得（重複排除前）: %d 件", len(all_articles))
    return all_articles


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("=== 海外ニュース ===")
    articles = collect_news()
    for i, a in enumerate(articles, 1):
        print(f"{i}. [{a.source}] {a.title}")
        print(f"   {a.url}")
        print()
    print("=== 国内ニュース ===")
    domestic = collect_domestic_news()
    for i, a in enumerate(domestic, 1):
        print(f"{i}. [{a.source}] {a.title}")
        print(f"   {a.url}")
        print()
