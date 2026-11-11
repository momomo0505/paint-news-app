"""
競合他社・監視対象メーカー ニュースチェックモジュール
========================================================
各メーカーの公式サイトをスクレイピングし、
過去 SEARCH_DAYS_BACK 日以内の更新情報を取得する。

COMPETITOR_SITES の各サイトは以下の任意キーで取得方法を切り替えられる:
    rss:               指定すると HTML ではなく RSS フィードから取得する
                       （一覧ページに日付が無い WordPress サイト向け）
    month_only_dates:  True にすると「2026.08」のような年月だけの日付も
                       受け付ける（日付を月単位でしか出さないサイト向け）
"""

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from scripts.config import COMPETITOR_SITES, SEARCH_DAYS_BACK

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 日付パターン（各サイトで使われる形式に対応）
DATE_PATTERNS = [
    (r"(\d{4})[./年](\d{1,2})[./月](\d{1,2})", "%Y-%m-%d"),   # 2026.05.14 / 2026/05/14 / 2026年5月14日
    (r"(\d{4})-(\d{1,2})-(\d{1,2})", "%Y-%m-%d"),              # 2026-05-14
    (r"([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})", "en_month"),   # May 14, 2026 / Sep 19, 2026
    (r"(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})", "en_day_month"),  # 19 Sep 2026
    (r"(\d{1,2})\s+([A-Z][a-z]{2})\b", "en_day_month_noyear"),  # 19 Sep（年なし）
]

EN_MONTHS = {
    "January": 1, "February": 2, "March": 3, "April": 4,
    "May": 5, "June": 6, "July": 7, "August": 8,
    "September": 9, "October": 10, "November": 11, "December": 12,
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4,
    "Jun": 6, "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

# ナビリンクなどを誤ってニュース見出しとみなさないための除外タイトル
_GENERIC_TITLES = {
    "会社案内",
    "ホーム",
    "お問い合わせ",
    "contact",
    "news",
    "ニュース",
    "privacy policy",
    "プライバシーポリシー",
    "採用情報",
    "もっと見る",
    "read more",
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

# 1件のニュース項目を囲む要素と判定する上限リンク数。
# 一覧全体を囲む要素まで遡って先頭記事の日付を拾うのを防ぐ。
MAX_LINKS_PER_ITEM = 3

# 項目の日付・見出しを探して遡る祖先の最大段数
MAX_ANCESTOR_DEPTH = 4

HEADING_TAGS = re.compile(r"^h[1-6]$")

# 年月だけの日付（2026.08 / 2026年8月）。日付の後ろに日が続かないものだけ対象
MONTH_ONLY_PATTERN = re.compile(r"(\d{4})[./年](\d{1,2})(?![./月]?\s*\d)")

# JS で Cookie を発行してから本来のページへ飛ばす簡易アクセス制限
# （江蘇長虹のサイトなど）。このトークン名が本文にあれば Cookie を付けて再取得する。
_COOKIE_GATE_TOKEN = "visitToken"
_COOKIE_GATE_HASH_RE = re.compile(r"md5_hash\s*=\s*['\"]([0-9a-f]+)['\"]")


def _month_only_date(text: str) -> datetime | None:
    """
    「2026.08」のように年月しか書かれていない日付を datetime にする。

    日が分からないので、その月の末日（当月なら今日）とみなす。
    月初の日付にすると月後半の更新を 14 日ウィンドウで取りこぼすため、
    「多少長く表示されても見逃さない」側に倒している。
    """
    m = MONTH_ONLY_PATTERN.search(text)
    if not m:
        return None
    try:
        year, month = int(m.group(1)), int(m.group(2))
        if not 1 <= month <= 12:
            return None
        now = datetime.now(JST)
        last_day = calendar.monthrange(year, month)[1]
        candidate = datetime(year, month, last_day, tzinfo=JST)
        if candidate > now:
            candidate = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return candidate
    except ValueError:
        return None


def _parse_date(text: str, allow_month_only: bool = False) -> datetime | None:
    """
    テキストから日付を抽出して datetime を返す。見つからなければ None。

    allow_month_only=True のときだけ年月のみの表記（2026.08）も受け付ける。
    既定で無効なのは、本文中の「2026年8月より発売」のような文言を
    日付と誤認して項目を増やさないため。
    """
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
            if fmt == "en_day_month":
                month = EN_MONTHS.get(m.group(2), 0)
                if month == 0:
                    continue
                return datetime(int(m.group(3)), month, int(m.group(1)), tzinfo=JST)
            if fmt == "en_day_month_noyear":
                month = EN_MONTHS.get(m.group(2), 0)
                if month == 0:
                    continue
                now = datetime.now(JST)
                candidate = datetime(now.year, month, int(m.group(1)), tzinfo=JST)
                if candidate > now + timedelta(days=2):
                    candidate = candidate.replace(year=now.year - 1)
                return candidate
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            return datetime(y, mo, d, tzinfo=JST)
        except (ValueError, KeyError):
            continue
    if allow_month_only:
        return _month_only_date(text)
    return None


def _make_google_translate_url(url: str, lang: str) -> str:
    """海外サイトのリンクを Google 翻訳経由に変換する（日本語以外は全言語対応）。"""
    if lang != "ja":
        sl = lang if lang else "auto"
        return f"https://translate.google.com/translate?sl={sl}&tl=ja&u={url}"
    return url


def _fetch_page(url: str) -> BeautifulSoup | None:
    """URLを取得してBeautifulSoupオブジェクトを返す。失敗時は None。"""
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(url, timeout=REQUEST_TIMEOUT)

        # JS で Cookie を発行する簡易ゲート（独自ステータス 319 で空ページが返る）。
        # ページ内のハッシュをそのまま Cookie に入れて再取得すると本来のページが取れる。
        gate = _COOKIE_GATE_HASH_RE.search(resp.text) if _COOKIE_GATE_TOKEN in resp.text else None
        if gate:
            logger.info("Cookie ゲートを検出。トークンを付けて再取得: %s", url)
            session.cookies.set(_COOKIE_GATE_TOKEN, gate.group(1), domain=urlparse(url).hostname)
            resp = session.get(url, timeout=REQUEST_TIMEOUT)

        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning("ページ取得失敗 %s: %s", url, e)
        return None


def _fetch_rss_items(rss_url: str) -> list[dict]:
    """
    RSS フィードからニュース項目を取得する。

    一覧ページに日付が表示されないサイト（エコム・NCC など WordPress 系）は
    HTML からは日付が取れないため、同じサイトが配信している RSS を使う。
    返り値の形式は _extract_news_items と同じ。
    """
    try:
        feed = feedparser.parse(rss_url, request_headers=HEADERS)
    except Exception as e:
        logger.warning("RSS 取得失敗 %s: %s", rss_url, e)
        return []

    items = []
    for entry in getattr(feed, "entries", []):
        parsed = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
        if not parsed:
            continue
        try:
            date = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc).astimezone(JST)
        except Exception:
            continue
        title = _clean_title(getattr(entry, "title", "") or "")[:80]
        link = getattr(entry, "link", "") or rss_url
        if not title or _is_generic_title(title):
            continue
        items.append({"date": date, "title": title, "url": link, "raw_text": title})
    return items


def _clean_title(text: str) -> str:
    """
    タイトルの先頭・末尾に付く日付とカテゴリ表記を取り除く。

    一覧のマークアップをそのまま拾うと
    「防爆協働ロボット導入のお知らせ 2026.09.10 お知らせ」のように
    日付・カテゴリがタイトルに混ざるため整形する。
    """
    date_edge = r"\d{4}\s*[./年-]\s*\d{1,2}\s*[./月-]\s*\d{1,2}\s*日?"
    cleaned = re.sub(rf"^\s*{date_edge}\s*", "", text)
    # 末尾は「日付 + カテゴリ名」の並びになることが多い
    cleaned = re.sub(rf"\s*{date_edge}\s*[#＃]?\S{{0,10}}\s*$", "", cleaned)
    # 先頭に付くカテゴリラベル（NEWS / イベント / お知らせ 等）を除去
    cleaned = re.sub(
        r"^(NEWS|イベント|お知らせ|IR|リリース|新商品|商品関連情報)\s*",
        "",
        cleaned,
    )
    return cleaned.strip() or text.strip()


def _item_blocks(node):
    """要素から上に向かって「1件のニュース項目」とみなせる祖先を順に返す。"""
    for _ in range(MAX_ANCESTOR_DEPTH):
        if node is None or node.name in ("body", "html"):
            return
        # リンクを多数含む要素は一覧全体なので、これ以上は遡らない
        if len(node.find_all("a", href=True)) > MAX_LINKS_PER_ITEM:
            return
        yield node
        node = node.parent


def _find_item_date(a_tag, allow_month_only: bool = False) -> datetime | None:
    """
    リンクに対応する日付を探す。

    リンク自身のテキスト → 1件分とみなせる近い祖先 の順に見る。
    直接の親を無条件に使うと、一覧全体を囲む要素から先頭記事の日付を
    拾って全項目が同じ日付になる（正英製作所のサイトで発生）。
    """
    date = _parse_date(a_tag.get_text(separator=" ", strip=True), allow_month_only)
    if date:
        return date

    for block in _item_blocks(a_tag.parent):
        date = _parse_date(block.get_text(separator=" ", strip=True), allow_month_only)
        if date:
            return date
    return None


def _find_heading_link(block):
    """ブロック内の見出し（h1〜h6）に含まれるリンクを返す。"""
    for heading in block.find_all(HEADING_TAGS):
        a_tag = heading.find("a", href=True)
        if a_tag:
            return a_tag
    return None


def _find_text_link(block):
    """ブロック内で最も長いテキストを持つリンクを返す。"""
    candidates = [
        a for a in block.find_all("a", href=True)
        if len(a.get_text(strip=True)) >= 6
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda a: len(a.get_text(strip=True)))


def _text_right_after_date(block) -> str:
    """
    日付要素（<time> / <datetime>）の直後に置かれた「素のテキスト」を返す。

    日本スピンドルのように
        <li><datetime>2026.10.26</datetime>見出し<br><p>本文 <a>関連リンク</a></p></li>
    と、見出しがリンクにもタグにも包まれていないサイト向け。
    最初のタグ（<br> や <p>）に当たった時点で打ち切るので、
    本文や「展示会ホームページはこちら」のようなリンク文言は混ざらない。
    """
    date_el = block.find(["time", "datetime"])
    if date_el is None:
        return ""
    parts = []
    for sib in date_el.next_siblings:
        if getattr(sib, "name", None):  # タグに当たったら終わり
            break
        parts.append(str(sib))
    return " ".join("".join(parts).split())


def _is_generic_title(title: str) -> bool:
    """メニュー項目など、ニュース見出しとして不適切なタイトルかを判定する。"""
    return title.strip().lower() in _GENERIC_TITLES


def _pick_item_title(block) -> tuple[str, str | None]:
    """
    1件分のブロックから見出しとリンク先を取り出す。

    専用クラス（info_title 等）があればそれを優先し、
    なければブロック内で最も長いリンクトを採用する。
    ナビの先頭リンク（会社案内など）を誤って拾うのを防ぐ。
    """
    titled = block.find(class_=re.compile(r"(info_title|news__ttl|rss_title|title)", re.I))
    if titled:
        text = titled.get_text(strip=True)
        link = titled if titled.name == "a" and titled.get("href") else titled.find("a", href=True)
        if link is None:
            link = titled.find_parent("a", href=True)
        if text:
            return text, (link["href"] if link else None)

    # 日付の直後に見出しが素のテキストで置かれている構造（日本スピンドルなど）。
    # 項目専用のリンクが無いので URL は一覧ページ自身になる（呼び出し側で base_url に解決）。
    plain = _text_right_after_date(block)
    if len(plain) >= 6:
        return plain, None

    a_tag = _find_heading_link(block)
    if a_tag:
        return a_tag.get_text(strip=True), a_tag.get("href")

    # 見出し(h1〜h6)はあるがリンクを内包せず、<a> がカード全体を囲んでいる構造
    # （江蘇長虹など）。見出しの文字をタイトルにし、リンクは外側の <a> から取る。
    heading = block.find(HEADING_TAGS)
    if heading and heading.get_text(strip=True):
        outer = heading.find_parent("a", href=True) or block.find("a", href=True)
        return heading.get_text(strip=True), (outer.get("href") if outer else None)

    a_tag = _find_text_link(block) or block.find("a", href=True)
    if a_tag:
        return a_tag.get_text(strip=True), a_tag.get("href")
    return block.get_text(separator=" ", strip=True), None


def _extract_news_items(
    soup: BeautifulSoup, base_url: str, allow_month_only: bool = False
) -> list[dict]:
    """
    ページからニュース項目を抽出する。
    日付・タイトル・リンクのセットを返す。

    allow_month_only=True のサイトでは年月だけの日付も項目として扱う。
    """
    items = []

    # ── 戦略1: <li> タグの中に日付パターンが含まれるものを検索 ──
    for li in soup.find_all("li"):
        # ナビ全体・メガメニューなど、リンクを多数含む要素は除外する
        if len(li.find_all("a", href=True)) > MAX_LINKS_PER_ITEM:
            continue
        text = li.get_text(separator=" ", strip=True)
        date = _parse_date(text, allow_month_only)
        if not date:
            continue

        raw_title, href = _pick_item_title(li)
        title = _clean_title(raw_title or text)[:80]
        if _is_generic_title(title):
            continue
        link = urljoin(base_url, href or base_url)
        items.append({"date": date, "title": title, "url": link, "raw_text": text})

    # ── 戦略2: <dl>/<dt>/<dd> パターン（日付がdtに入るサイト向け） ──
    for dt in soup.find_all("dt"):
        date = _parse_date(dt.get_text(strip=True), allow_month_only)
        if not date:
            continue
        dd = dt.find_next_sibling("dd")
        if not dd:
            continue
        a_tag = dd.find("a", href=True)
        if a_tag:
            title = _clean_title(a_tag.get_text(strip=True))[:80]
            link = urljoin(base_url, a_tag["href"])
        else:
            title = _clean_title(dd.get_text(strip=True))[:80]
            link = base_url
        if _is_generic_title(title):
            continue
        raw = dt.get_text(strip=True) + " " + dd.get_text(strip=True)
        items.append({"date": date, "title": title, "url": link, "raw_text": raw})

    # ── 戦略3: class名に "news" を含む div / section 内のリンク ──
    for container in soup.find_all(
        True,
        class_=re.compile(r"news|release|topics|update|info", re.I),
    ):
        for a_tag in container.find_all("a", href=True):
            text = a_tag.get_text(separator=" ", strip=True)
            parent_text = a_tag.parent.get_text(separator=" ", strip=True) if a_tag.parent else text
            date = _find_item_date(a_tag, allow_month_only)
            if not date:
                continue
            title = _clean_title(text)[:80] or parent_text[:80]
            if _is_generic_title(title):
                continue
            link = urljoin(base_url, a_tag["href"])
            items.append({"date": date, "title": title, "url": link, "raw_text": parent_text})

    # ── 戦略4: <time> 要素を起点に項目を組み立てる ──
    # 日付を <time> で持ち、クラス名に news 等を含まないサイト向け（タクボなど）
    for time_tag in soup.find_all("time"):
        date = (
            _parse_date(time_tag.get("datetime", ""), allow_month_only)
            or _parse_date(time_tag.get_text(strip=True), allow_month_only)
        )
        if not date:
            continue

        # 「本文ページへのリンク」のような汎用リンクを拾わないよう、
        # 見出しリンクを優先し、見つからない場合のみ長いリンクで代替する
        heading_link = None
        text_link = None
        for block in _item_blocks(time_tag.parent):
            heading_link = _find_heading_link(block)
            if heading_link is not None:
                break
            if text_link is None:
                text_link = _find_text_link(block)

        a_tag = heading_link or text_link
        if a_tag is None:
            continue

        raw_text = a_tag.parent.get_text(separator=" ", strip=True) if a_tag.parent else ""
        title = _clean_title(a_tag.get_text(strip=True))[:80]
        if _is_generic_title(title):
            continue
        items.append(
            {
                "date": date,
                "title": title,
                "url": urljoin(base_url, a_tag["href"]),
                "raw_text": f"{time_tag.get_text(strip=True)} {raw_text}",
            }
        )

    # 重複除去（URL基準。末尾スラッシュの有無は同一記事とみなす）
    # 項目専用リンクが無く URL が一覧ページ自身になる項目は、タイトルも含めて区別する
    page_key = base_url.rstrip("/").lower()
    seen = set()
    unique = []
    for item in items:
        key = item["url"].rstrip("/").lower()
        if key == page_key:
            key = f"{key}#{item['title']}"
        if key not in seen:
            seen.add(key)
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
        section_include = site.get("section_include", [])
        rss_url = site.get("rss")
        allow_month_only = bool(site.get("month_only_dates", False))
        logger.info("監視中: %s (%s)", company, rss_url or url)

        if rss_url:
            # RSS 指定サイトは HTML を読まずフィードから項目を取る
            items = _fetch_rss_items(rss_url)
            if not items:
                logger.warning("%s: RSS から項目を取得できませんでした", company)
                continue
        else:
            soup = _fetch_page(url)
            if soup is None:
                logger.warning("%s: ページ取得スキップ", company)
                continue
            items = _extract_news_items(soup, url, allow_month_only)

        recent = [i for i in items if i["date"] >= cutoff]

        # section_include が指定されている場合は raw_text でフィルター
        if section_include:
            recent = [
                item for item in recent
                if any(kw in item.get("raw_text", "") for kw in section_include)
            ]

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
