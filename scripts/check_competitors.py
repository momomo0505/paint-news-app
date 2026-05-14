"""
競合他社・監視対象メーカー ニュースチェックモジュール
========================================================
各メーカーの公式サイトをスクレイピングし、
過去 SEARCH_DAYS_BACK 日以内の更新情報を取得する。
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import COMPETITOR_SITES, SEARCH_DAYS_BACK

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 日付パターン（各サイトで使われる形式に対応）
DATE_PATTERNS = [
    (r"(\d{4})[./年](\d{1,2})[./月](\d{1,2})", "%Y-%m-%d"),   # 2026.05.14 / 2026/05/14 / 2026年5月14日
    (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y-%m-%d"),              # 2026-05-14
    (r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})", "en_month"),   # May 14, 2026
]

EN_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

REQUEST_TIMEOUT = 15


def _parse_date(text: str) -> datetime | None:
    """テキストから日付を抽出して datetime を返す。見つからなければ None。"""
    for pattern, fmt in DATE_PATTERNS:
        m = re.search(pattern, text)
        if not m:
            continue
        try:
            if fmt == "en_month":
                month = EN_MONTHS.get(m.group(1), 0)
                if month == 0:
                    continue
                return datetime(int(m.group(3)), month, int(m.group(2)), tzinfo=JST)
            else:
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                return datetime(y, mo, d, tzinfo=JST)
        except (ValueError, KeyError):
            continue
    return None


def _make_google_translate_url(url: str, lang: str) -> str:
    """海外サイトのリンクを Google 翻訳経由に変換する。"""
    if lang == "en":
        return f"https://translate.google.com/translate?sl=en&tl=ja&u={url}"
    return url


def _fetch_page(url: str) -> BeautifulSoup | None:
    """URLを取得してBeautifulSoupオブジェクトを返す。失敗時は None。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning("ページ取得失敗 %s: %s", url, e)
        return None


def _extract_news_items(soup: BeautifulSoup, base_url: str) -> list[dict]:
    """
    ページからニュース項目を抽出する。
    日付・タイトル・リンクのセットを返す。
    """
    items = []

    # ── 戦略1: <li> タグの中に日付パターンが含まれるものを検索 ──
    for li in soup.find_all("li"):
        text = li.get_text(separator=" ", strip=True)
        date = _parse_date(text)
        if not date:
            continue

        # タイトルとリンクを抽出
        a_tag = li.find("a", href=True)
        if a_tag:
            title = a_tag.get_text(strip=True) or text[:80]
            href = a_tag["href"]
        else:
            title = re.sub(r"\d{4}[./年]\d{1,2}[./月]\d{1,2}[日]?\s*", "", text)[:80]
            href = base_url

        link = urljoin(base_url, href)
        items.append({"date": date, "title": title, "url": link})

    # ── 戦略2: <dl>/<dt>/<dd> パターン（日付がdtに入るサイト向け） ──
    for dt in soup.find_all("dt"):
        date = _parse_date(dt.get_text(strip=True))
        if not date:
            continue
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        a_tag = dd.find("a", href=True)
        if a_tag:
            title = a_tag.get_text(strip=True)
            link = urljoin(base_url, a_tag["href"])
        else:
            title = dd.get_text(strip=True)[:80]
            link = base_url
        items.append({"date": date, "title": title, "url": link})

    # ── 戦略3: class名に "news" を含む div / section 内のリンク ──
    for container in soup.find_all(
        True,
        class_=re.compile(r"news|release|topics|update|info", re.I),
    ):
        for a_tag in container.find_all("a", href=True):
            text = a_tag.get_text(separator=" ", strip=True)
            parent_text = a_tag.parent.get_text(separator=" ", strip=True) if a_tag.parent else text
            date = _parse_date(parent_text) or _parse_date(text)
            if not date:
                continue
            title = text[:80] or parent_text[:80]
            link = urljoin(base_url, a_tag["href"])
            items.append({"date": date, "title": title, "url": link})

    # 重複除去（URL基準）
    seen = set()
    unique = []
    for item in items:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)

    return unique


def check_all_competitors() -> list[dict]:
    """
    全監視サイトをチェックし、過去 SEARCH_DAYS_BACK 日以内の
    ニュース項目リストを返す。

    Returns:
        list[dict]: {
            "company": str,
            "date": datetime,
            "title": str,
            "url": str,
            "language": str,
        }
    """
    cutoff = datetime.now(JST) - timedelta(days=SEARCH_DAYS_BACK)
    results = []

    for site in COMPETITOR_SITES:
        company = site["name"]
        url = site["url"]
        lang = site["language"]
        logger.info("監視中: %s (%s)", company, url)

        soup = _fetch_page(url)
        if soup is None:
            logger.warning("%s: ページ取得スキップ", company)
            continue

        items = _extract_news_items(soup, url)
        recent = [i for i in items if i["date"] >= cutoff]

        if not recent:
            logger.info("%s: 過去%d日以内の更新なし", company, SEARCH_DAYS_BACK)
            continue

        for item in recent:
            display_url = _make_google_translate_url(item["url"], lang)
            results.append(
                {
                    "company": company,
                    "date": item["date"],
                    "title": item["title"],
                    "url": display_url,
                    "original_url": item["url"],
                    "language": lang,
                }
            )
            logger.info("  [%s] %s", item["date"].strftime("%Y-%m-%d"), item["title"][:60])

    results.sort(key=lambda x: x["date"], reverse=True)
    logger.info("競合監視完了: %d件取得", len(results))
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    items = check_all_competitors()
    print(f"\n合計 {len(items)} 件\n")
    for it in items:
        print(f"[{it['company']}] {it['date'].strftime('%Y-%m-%d')} {it['title'][:60]}")
