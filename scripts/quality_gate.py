"""
品質ゲートモジュール — レポート公開前の最終確認
================================================================

背景:
    Google News RSS は古い記事を「最近の日付」で返すことがあり
    （例: 2026-08-31 号に 2017 年の日刊工業新聞記事が混入）、
    RSS の日付だけに頼った収集時フィルタでは防ぎきれない。
    また重複除去は URL 解決・翻訳より前に走るため、解決後に
    同一 URL となる記事や翻訳後に同一タイトルとなる記事が残る。

機能:
    1. 日付ゲート — 掲載予定の全記事について、実際の公開日が
       MAX_AGE_DAYS 以内であることを3段階で検証する。
         a. 保存済みの published_at
         b. 記事 URL に含まれる年月日（例: /2017/12/05/）
         c. 記事ページ本体のメタデータ（article:published_time /
            JSON-LD datePublished / <time datetime> / 掲載日表記）
       いずれかで「古い」と確定した記事を除外する。
       日付が確認できない記事は除外しない（誤除外を防ぐため）。
    2. 重複ゲート — 正規化 URL の一致（全セクション横断）と
       タイトル類似度（同一セクション内）で重複を除外する。

main.py の Step 5.5（レポート生成直後）から呼び出され、
違反があった場合はレポートを再生成する。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from urllib.parse import parse_qsl, urlencode, urlparse

import requests
from bs4 import BeautifulSoup

from scripts.collect_news import Article

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# 掲載を許可する記事の最大経過日数（2週間 — これより古いニュースは表示しない）
MAX_AGE_DAYS = 14

# 記事ページ取得の設定
_FETCH_TIMEOUT = 15
_FETCH_WORKERS = 8
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

# URL から除去するトラッキング系クエリパラメータ
_TRACKING_PARAMS = re.compile(
    r"^(utm_\w+|gnr_footer|fbclid|gclid|yclid|t_sid|cmpid|ref|share)$", re.I
)

# タイトル類似度の閾値（最終ゲートなので高めに設定し誤除外を防ぐ）
_TITLE_SIMILARITY_THRESHOLD = 0.9


# ──────────────────────────────────────────────
# 日付パース
# ──────────────────────────────────────────────
def _to_aware(dt: datetime) -> datetime:
    """naive datetime に JST を付与する。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=JST)
    return dt


def _sane(dt: datetime | None) -> datetime | None:
    """明らかに不正な年（2000年以前・遠い未来）を弾く。"""
    if dt is None:
        return None
    if dt.year < 2000 or dt.year > datetime.now(JST).year + 1:
        return None
    return dt


def parse_flexible_date(value: str | None) -> datetime | None:
    """ISO・日本語表記など様々な形式の日付文字列を datetime に変換する。"""
    if not value or not isinstance(value, str):
        return None
    s = value.strip()

    try:
        return _sane(_to_aware(datetime.fromisoformat(s.replace("Z", "+00:00"))))
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d %H:%M",
        "%Y/%m/%d",
        "%Y年%m月%d日",
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
    ):
        try:
            return _sane(_to_aware(datetime.strptime(s, fmt)))
        except ValueError:
            continue

    m = re.search(r"(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})", s)
    if m:
        try:
            return _sane(
                datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=JST)
            )
        except ValueError:
            pass
    return None


def extract_url_date(url: str) -> datetime | None:
    """記事 URL のパスに含まれる年月日を抽出する（例: /2017/12/05/, 20171205）。"""
    path = urlparse(url).path

    m = re.search(r"/(20\d{2})[/\-](\d{1,2})(?:[/\-](\d{1,2}))?(?=[/\-._]|$)", path)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        d = int(m.group(3)) if m.group(3) else 1
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return _sane(datetime(y, mo, d, tzinfo=JST))
            except ValueError:
                pass

    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", path)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            try:
                return _sane(datetime(y, mo, d, tzinfo=JST))
            except ValueError:
                pass
    return None


# ──────────────────────────────────────────────
# 記事ページからの公開日抽出
# ──────────────────────────────────────────────
def _find_date_published_in_jsonld(node: object) -> str | None:
    """JSON-LD 構造から datePublished を再帰的に探す。"""
    if isinstance(node, dict):
        value = node.get("datePublished")
        if isinstance(value, str):
            return value
        for child in node.values():
            found = _find_date_published_in_jsonld(child)
            if found:
                return found
    elif isinstance(node, list):
        for child in node:
            found = _find_date_published_in_jsonld(child)
            if found:
                return found
    return None


def extract_page_date(html: str) -> datetime | None:
    """記事ページの HTML から公開日を抽出する。見つからなければ None。"""
    soup = BeautifulSoup(html, "lxml")

    # 1. meta タグ（最も信頼できる）
    meta_selectors = [
        {"property": "article:published_time"},
        {"property": "og:article:published_time"},
        {"itemprop": "datePublished"},
        {"name": "pubdate"},
        {"name": "publishdate"},
        {"name": "publish-date"},
        {"name": "date"},
        {"name": "dc.date"},
        {"name": "dc.date.issued"},
        {"name": "sailthru.date"},
    ]
    for attrs in meta_selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            dt = parse_flexible_date(tag["content"])
            if dt:
                return dt

    # 2. JSON-LD の datePublished
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        value = _find_date_published_in_jsonld(data)
        if value:
            dt = parse_flexible_date(value)
            if dt:
                return dt

    # 3. <time datetime="..."> の最初の1つ
    time_tag = soup.find("time", attrs={"datetime": True})
    if time_tag:
        dt = parse_flexible_date(time_tag["datetime"])
        if dt:
            return dt

    # 4. 「掲載日」「公開日」等のラベル付き日付（国内サイト向け）
    text = soup.get_text(" ", strip=True)[:4000]
    m = re.search(
        r"(?:掲載日|公開日|配信日|発行日)\D{0,10}?(20\d{2})[/年.\-](\d{1,2})[/月.\-](\d{1,2})",
        text,
    )
    if m:
        try:
            return _sane(
                datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=JST)
            )
        except ValueError:
            pass

    # 5. 本文冒頭の括弧付き日付（日刊工業新聞などの「(2017/12/6 05:00)」形式）
    m = re.search(
        r"[（(]\s*(20\d{2})/(\d{1,2})/(\d{1,2})[^)）]{0,20}[)）]",
        text[:1500],
    )
    if m:
        try:
            return _sane(
                datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), tzinfo=JST)
            )
        except ValueError:
            pass

    return None


def fetch_page_date(url: str, session: requests.Session | None = None) -> datetime | None:
    """記事ページを取得して実際の公開日を返す。取得失敗時は None。"""
    getter = session or requests
    try:
        resp = getter.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return extract_page_date(resp.text)
    except Exception as exc:
        logger.debug("公開日検証: ページ取得失敗 %s (%s)", url[:80], exc)
        return None


# ──────────────────────────────────────────────
# Google 翻訳プロキシでの表示可否チェック（海外ニュース用）
# ──────────────────────────────────────────────
# 海外記事のリンクは Google 翻訳（translate.goog プロキシ）経由で開くため、
# 翻訳元サイトが Cloudflare 等の Bot 対策で Google のプロキシを弾いていると
# 「チャレンジの試行回数の上限を超えました」等が表示され記事が読めない。
# 掲載前に翻訳プロキシ URL を実際に取得し、表示できない記事を除外する。

# <title> タグに現れるチャレンジページの痕跡（記事本文との誤判定を防ぐため
# タイトルのみで判定する）
_UNTRANSLATABLE_TITLE_MARKERS = [
    "just a moment",
    "attention required",
    "access denied",
]

# 本文・スクリプト中に現れるチャレンジページ固有の痕跡
_UNTRANSLATABLE_BODY_MARKERS = [
    "cf_chl_opt",           # Cloudflare チャレンジページのインラインスクリプト
    "cf-chl-bypass",
    "verifying you are human",
    "verify you are human",
    "enable javascript and cookies to continue",
    # チャレンジ失敗時に表示される日本語メッセージ（添付スクリーンショットと同じもの）
    "チャレンジの試行回数",
]

_TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def build_translate_proxy_url(
    url: str,
    source_lang: str = "en",
    target_lang: str = "ja",
) -> str:
    """
    記事 URL を Google 翻訳プロキシ（translate.goog）の URL に変換する。

    レポートのリンク（translate.google.com/translate?u=...）はこの
    プロキシ URL にリダイレクトされるため、事前チェックはこちらを直接叩く。
    ホスト名の変換規則: 「-」→「--」、「.」→「-」、末尾に .translate.goog
    """
    parsed = urlparse(url)
    host = parsed.netloc.split(":")[0].lower()
    proxy_host = host.replace("-", "--").replace(".", "-") + ".translate.goog"
    query = f"_x_tr_sl={source_lang}&_x_tr_tl={target_lang}&_x_tr_hl=ja"
    if parsed.query:
        query = parsed.query + "&" + query
    path = parsed.path or "/"
    return f"https://{proxy_host}{path}?{query}"


def check_translatable(url: str, session: requests.Session | None = None) -> bool:
    """
    記事が Google 翻訳プロキシで表示できるかを確認する。

    判定基準:
    - プロキシが 4xx/5xx を返す → 表示不可（False）
      ※429（レート制限）はチェック側の問題の可能性が高いため除外しない
    - ページ内に Cloudflare 等のチャレンジ画面の痕跡がある → 表示不可（False）
    - ネットワークエラー等で確認できない場合 → True（誤除外を防ぐ）
    """
    getter = session or requests
    proxy_url = build_translate_proxy_url(url)
    try:
        resp = getter.get(proxy_url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
    except Exception as exc:
        logger.debug("翻訳可否チェック: 取得失敗のため掲載継続 %s (%s)", url[:80], exc)
        return True

    if resp.status_code == 429:
        logger.debug("翻訳可否チェック: レート制限のため判定保留 %s", url[:80])
        return True

    if resp.status_code >= 400:
        logger.info("翻訳不可 (HTTP %d): %s", resp.status_code, url[:80])
        return False

    head = resp.text[:20000].lower()

    title_match = _TITLE_TAG_RE.search(head)
    if title_match:
        title = title_match.group(1)
        for marker in _UNTRANSLATABLE_TITLE_MARKERS:
            if marker in title:
                logger.info("翻訳不可 (タイトル: %s): %s", marker, url[:80])
                return False

    for marker in _UNTRANSLATABLE_BODY_MARKERS:
        if marker in head:
            logger.info("翻訳不可 (チャレンジ検出: %s): %s", marker, url[:80])
            return False

    return True


def filter_untranslatable_articles(articles: list[Article]) -> list[Article]:
    """
    Google 翻訳プロキシで表示できない海外記事を除外する。

    main.py で翻訳・要約の前段（URL 解決の後）に呼び出すことで、
    表示できない記事に Claude API のコストを使わずに済む。

    Returns:
        list[Article]: 翻訳ページが表示できる記事のみ
    """
    if not articles:
        return articles

    logger.info("翻訳可否チェック開始: %d 件", len(articles))
    session = requests.Session()

    results: dict[str, bool] = {}
    with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
        futures = {pool.submit(check_translatable, a.url, session): a for a in articles}
        for future in as_completed(futures):
            article = futures[future]
            try:
                results[article.url] = future.result()
            except Exception:
                results[article.url] = True  # 判定不能時は誤除外を避ける

    kept: list[Article] = []
    for article in articles:
        if results.get(article.url, True):
            kept.append(article)
        else:
            logger.warning("翻訳不可のため除外: %s", article.title[:60])

    removed = len(articles) - len(kept)
    if removed:
        logger.info("翻訳可否チェック: %d 件を除外しました", removed)
    else:
        logger.info("翻訳可否チェック: 全記事が表示可能です")
    return kept


# ──────────────────────────────────────────────
# URL 正規化・タイトル類似度
# ──────────────────────────────────────────────
def normalize_url(url: str) -> str:
    """重複判定用に URL を正規化する（トラッキングパラメータ除去など）。"""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return url.strip().lower()

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = parsed.path.rstrip("/")

    query_pairs = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if not _TRACKING_PARAMS.match(k)
    ]
    query = urlencode(sorted(query_pairs))

    normalized = f"{host}{path}"
    if query:
        normalized += f"?{query}"
    return normalized.lower()


def _display_title(article: Article) -> str:
    """重複判定に使うタイトル（翻訳済みがあればそちらを優先）。"""
    return (article.title_ja or article.title or "").strip()


def _titles_similar(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() >= _TITLE_SIMILARITY_THRESHOLD


# ──────────────────────────────────────────────
# ゲート本体
# ──────────────────────────────────────────────
@dataclass
class GateResult:
    """品質ゲートの実行結果。"""

    competitor_items: list[dict]
    domestic_articles: list[Article]
    overseas_articles: list[Article]
    self_mention_articles: list[Article]
    removed: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.removed


def _check_article_age(
    article: Article,
    cutoff: datetime,
    page_date: datetime | None,
) -> str | None:
    """記事が古い場合は理由文字列を、問題なければ None を返す。"""
    stored = parse_flexible_date(article.published_at)
    if stored and stored < cutoff:
        return f"保存日付が期限超過 ({stored.date()})"

    url_date = extract_url_date(article.url)
    if url_date and url_date < cutoff:
        return f"URL中の日付が期限超過 ({url_date.date()})"

    if page_date and page_date < cutoff:
        return f"記事ページの公開日が期限超過 ({page_date.date()})"

    return None


def run_quality_gate(
    *,
    competitor_items: list[dict],
    domestic_articles: list[Article],
    overseas_articles: list[Article],
    self_mention_articles: list[Article],
    verify_online: bool = True,
    max_age_days: int = MAX_AGE_DAYS,
    now: datetime | None = None,
) -> GateResult:
    """
    レポート掲載予定の全記事に品質ゲートを適用する。

    Args:
        competitor_items: 競合ニュース項目（dict, "date" は datetime）
        domestic_articles: 国内記事
        overseas_articles: 海外記事
        self_mention_articles: 自社メンション記事
        verify_online: True の場合、記事ページを取得して実公開日を検証する
        max_age_days: 掲載を許可する最大経過日数
        now: 現在時刻（テスト用に差し替え可能）

    Returns:
        GateResult: 除外後の各リストと除外理由の一覧
    """
    current = now or datetime.now(JST)
    cutoff = current - timedelta(days=max_age_days)
    removed: list[str] = []

    logger.info("品質ゲート開始: 掲載期限 %s 以降 / オンライン検証=%s",
                cutoff.strftime("%Y-%m-%d"), verify_online)

    # ── 1. 競合ニュース（date は収集時にサイトから直接取得済み） ──
    kept_competitors: list[dict] = []
    for item in competitor_items:
        item_date = item.get("date")
        if isinstance(item_date, datetime) and _to_aware(item_date) < cutoff:
            removed.append(
                f"[競合] {item.get('company', '')}: {str(item.get('title', ''))[:60]}"
                f" — 日付が期限超過 ({_to_aware(item_date).date()})"
            )
            continue
        kept_competitors.append(item)

    # ── 2. 記事リストの日付検証（必要ならページ取得で実公開日を確認） ──
    sections: list[tuple[str, list[Article]]] = [
        ("自社", self_mention_articles),
        ("国内", domestic_articles),
        ("海外", overseas_articles),
    ]

    page_dates: dict[str, datetime | None] = {}
    if verify_online:
        all_articles = [a for _, articles in sections for a in articles]
        # 保存日付・URL 日付だけで除外が確定する記事はページ取得を省略する
        need_fetch = []
        for a in all_articles:
            stored = parse_flexible_date(a.published_at)
            url_date = extract_url_date(a.url)
            if (stored and stored < cutoff) or (url_date and url_date < cutoff):
                continue
            need_fetch.append(a)

        if need_fetch:
            logger.info("品質ゲート: 記事ページの公開日を検証中（%d件）...", len(need_fetch))
            session = requests.Session()
            with ThreadPoolExecutor(max_workers=_FETCH_WORKERS) as pool:
                futures = {
                    pool.submit(fetch_page_date, a.url, session): a for a in need_fetch
                }
                for future in as_completed(futures):
                    article = futures[future]
                    try:
                        page_dates[article.url] = future.result()
                    except Exception:
                        page_dates[article.url] = None

    kept_sections: dict[str, list[Article]] = {}
    for label, articles in sections:
        kept: list[Article] = []
        for article in articles:
            reason = _check_article_age(
                article, cutoff, page_dates.get(article.url)
            )
            if reason:
                removed.append(f"[{label}] {_display_title(article)[:60]} — {reason}")
                continue
            kept.append(article)
        kept_sections[label] = kept

    # ── 3. 重複除去（URL は全セクション横断、タイトルは同一セクション内） ──
    seen_urls: set[str] = set()
    for item in kept_competitors:
        seen_urls.add(normalize_url(str(item.get("original_url") or item.get("url") or "")))

    deduped_sections: dict[str, list[Article]] = {}
    for label in ("自社", "国内", "海外"):
        kept: list[Article] = []
        for article in kept_sections[label]:
            key = normalize_url(article.url)
            if key in seen_urls:
                removed.append(
                    f"[{label}] {_display_title(article)[:60]} — URL重複"
                )
                continue

            dup_of = next(
                (
                    existing
                    for existing in kept
                    if _titles_similar(_display_title(article), _display_title(existing))
                ),
                None,
            )
            if dup_of is not None:
                removed.append(
                    f"[{label}] {_display_title(article)[:60]} — タイトル重複"
                    f" (既掲載: {_display_title(dup_of)[:40]})"
                )
                continue

            seen_urls.add(key)
            kept.append(article)
        deduped_sections[label] = kept

    if removed:
        logger.warning("品質ゲート: %d 件を除外しました", len(removed))
    else:
        logger.info("品質ゲート: 全記事が基準を満たしています")

    return GateResult(
        competitor_items=kept_competitors,
        domestic_articles=deduped_sections["国内"],
        overseas_articles=deduped_sections["海外"],
        self_mention_articles=deduped_sections["自社"],
        removed=removed,
    )
