"""
気になる話題（塗装業界外トピック）収集モジュール
================================================================

塗装とは直接関係ないが、社内で話題になりそうなニュースを毎週 2〜3 件
レポートに織り交ぜるためのモジュール。

収集元は 2 つ:
  1. 手動登録（docs/manual_topics.json）
     「この記事を載せたい」という URL を書いておくと、次回レポートに必ず掲載する。
     掲載後はファイル内の該当エントリに "published" 日付が書き込まれ、
     次回以降は二重掲載されない。
  2. 自動収集（Google News RSS）
     config.GENERAL_TOPIC_RSS_KEYWORDS で検索した候補の中から、
     Claude が「技術部の社員が面白いと感じそうな話題」を選ぶ。

manual_topics.json の書き方:
    {
      "topics": [
        {"url": "https://example.com/news/123", "note": "空飛ぶ車の話"},
        {"url": "https://example.com/news/456"}
      ]
    }
    ※ "note" は任意（Claude に渡す補足メモ）。"title" を書けばページ取得に
      失敗したときの見出しとして使われる。
"""

from __future__ import annotations

import json
import logging
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from scripts.collect_news import (
    Article,
    _clean_rss_summary,
    _deduplicate_articles,
    _parse_rss_date,
    resolve_google_news_urls,
)
from scripts.config import (
    ANTHROPIC_API_KEY,
    CLAUDE_MODEL,
    EXCLUDED_DOMAINS,
    GENERAL_TOPIC_DAYS_BACK,
    GENERAL_TOPIC_ITEMS_PER_KEYWORD,
    GENERAL_TOPIC_RSS_KEYWORDS,
    MANUAL_TOPICS_PATH,
    MAX_GENERAL_TOPICS,
)
from scripts.quality_gate import extract_page_date

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# カテゴリキー（テンプレートのタグ表示に使う）
CATEGORY_MANUAL = "manual"    # 手動登録（📌 おすすめ）
CATEGORY_GENERAL = "general"  # 自動収集（💡 話題）

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}
_FETCH_TIMEOUT = 15


# ──────────────────────────────────────────────
# 手動登録ファイルの読み書き
# ──────────────────────────────────────────────
def _read_manual_file(path) -> list[dict]:
    """manual_topics.json を読み、エントリのリストを返す（形式の揺れを吸収）。"""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("手動登録ファイルの読み込みに失敗: %s (%s)", path, exc)
        return []

    # {"topics": [...]} と [...] のどちらでも受け付ける
    entries = data.get("topics", []) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return []

    normalized: list[dict] = []
    for entry in entries:
        # URL 文字列だけの行も許容する
        if isinstance(entry, str):
            entry = {"url": entry}
        if isinstance(entry, dict) and str(entry.get("url", "")).startswith("http"):
            normalized.append(entry)
    return normalized


def load_manual_topics(path=MANUAL_TOPICS_PATH) -> list[dict]:
    """未掲載（"published" が空）の手動登録エントリを返す。"""
    pending = [e for e in _read_manual_file(path) if not e.get("published")]
    if pending:
        logger.info("手動登録トピック: %d 件（未掲載）", len(pending))
    return pending


def mark_manual_topics_published(urls: list[str], date_str: str, path=MANUAL_TOPICS_PATH) -> None:
    """掲載済みの手動登録エントリに published 日付を書き込む。"""
    if not urls or not path.exists():
        return
    entries = _read_manual_file(path)
    targets = {u.strip().rstrip("/") for u in urls}
    changed = False
    for entry in entries:
        if entry.get("url", "").strip().rstrip("/") in targets and not entry.get("published"):
            entry["published"] = date_str
            changed = True
    if changed:
        path.write_text(
            json.dumps({"topics": entries}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        logger.info("手動登録トピックを掲載済みに更新: %d 件", len(targets))


# ──────────────────────────────────────────────
# 記事ページからのメタ情報取得
# ──────────────────────────────────────────────
def _meta_content(soup: BeautifulSoup, *selectors: dict) -> str:
    """最初に見つかった meta タグの content を返す。"""
    for attrs in selectors:
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return str(tag["content"]).strip()
    return ""


def parse_article_metadata(html: str, url: str) -> dict:
    """HTML から見出し・概要・媒体名・公開日を取り出す。"""
    soup = BeautifulSoup(html, "lxml")

    # og:title は通常サイト名を含まないのでそのまま使う。
    # <title> しかない場合は「記事タイトル | サイト名」の末尾を落とす。
    title = _meta_content(soup, {"property": "og:title"}, {"name": "twitter:title"})
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
        for sep in (" | ", " - "):
            if sep in title:
                head, _, tail = title.rpartition(sep)
                if head and len(tail) < 40:
                    title = head.strip()
                break

    description = _meta_content(
        soup,
        {"property": "og:description"},
        {"name": "description"},
        {"name": "twitter:description"},
    )
    source = _meta_content(soup, {"property": "og:site_name"}) or urlparse(url).netloc
    published = extract_page_date(html)

    return {
        "title": title,
        "description": description[:300],
        "source": source,
        "published_at": published.isoformat() if published else "",
    }


def fetch_article_metadata(url: str, session: requests.Session | None = None) -> dict | None:
    """記事ページを取得してメタ情報を返す。取得失敗時は None。"""
    getter = session or requests
    try:
        resp = getter.get(url, headers=_HEADERS, timeout=_FETCH_TIMEOUT)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding
        return parse_article_metadata(resp.text, url)
    except Exception as exc:
        logger.warning("記事ページの取得に失敗: %s (%s)", url[:80], exc)
        return None


def _manual_entry_to_article(entry: dict, session: requests.Session) -> Article:
    """手動登録エントリを Article に変換する（ページ取得で見出し等を補完）。"""
    url = entry["url"].strip()
    meta = fetch_article_metadata(url, session) or {}
    title = (entry.get("title") or meta.get("title") or url).strip()
    description = entry.get("note") or meta.get("description") or ""
    published_at = meta.get("published_at") or datetime.now(JST).isoformat()
    article = Article(
        title=title,
        description=description,
        url=url,
        source=meta.get("source") or urlparse(url).netloc,
        published_at=published_at,
        skip_filter=True,
    )
    article.category = CATEGORY_MANUAL
    return article


# ──────────────────────────────────────────────
# 自動収集（Google News RSS）
# ──────────────────────────────────────────────
def collect_general_topic_candidates() -> list[Article]:
    """話題ニュースの候補を Google News RSS から集める（新しい順）。"""
    cutoff = datetime.now(JST) - timedelta(days=GENERAL_TOPIC_DAYS_BACK)
    base_url = "https://news.google.com/rss/search"
    candidates: list[Article] = []

    for keyword in GENERAL_TOPIC_RSS_KEYWORDS:
        params = {"q": keyword, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
        url = base_url + "?" + urllib.parse.urlencode(params)
        logger.info("話題ニュース RSS 検索: %s", keyword)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.warning("RSS 取得エラー (%s): %s", keyword, exc)
            continue

        for entry in getattr(feed, "entries", [])[:GENERAL_TOPIC_ITEMS_PER_KEYWORD]:
            pub_dt = _parse_rss_date(entry)
            if pub_dt is None or pub_dt < cutoff:
                continue
            title = getattr(entry, "title", "").strip()
            link = getattr(entry, "link", "") or ""
            if not title or not link:
                continue
            if any(d in link for d in EXCLUDED_DOMAINS):
                continue
            source_info = getattr(entry, "source", None)
            source = source_info.title if source_info and hasattr(source_info, "title") else "Google News"
            # Google News の見出しは末尾に「 - 媒体名」が付くので外す（媒体名は別途表示する）
            if source and title.endswith(" - " + source):
                title = title[: -len(" - " + source)].strip()
            article = Article(
                title=title,
                description=_clean_rss_summary(getattr(entry, "summary", "") or ""),
                url=link,
                source=source,
                published_at=pub_dt.isoformat(),
            )
            article.category = CATEGORY_GENERAL
            candidates.append(article)
        time.sleep(0.5)

    unique = _deduplicate_articles(candidates)
    unique.sort(key=lambda a: a.published_at, reverse=True)
    logger.info("話題ニュース候補: %d 件（重複除去後）", len(unique))
    return unique


# ──────────────────────────────────────────────
# Claude による選別・要約
# ──────────────────────────────────────────────
def curate_general_topics(
    candidates: list[Article],
    max_count: int,
    exclude_titles: list[str] | None = None,
) -> list[Article]:
    """候補から「社内で話題になりそうな」記事を最大 max_count 件選ぶ。"""
    if not candidates or max_count <= 0:
        return []

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため話題ニュースは新着順 %d 件を採用", max_count)
        return candidates[:max_count]

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    items_text = "\n".join(
        f"{i + 1}. {a.title} | {a.source} | {a.published_at[:10]}"
        for i, a in enumerate(candidates)
    )
    exclude_text = ""
    if exclude_titles:
        exclude_text = (
            "\n【重要】次の記事はすでにレポートに掲載が決まっています。"
            "同じ出来事・同じ製品を扱う記事は（媒体や見出しが違っても）絶対に選ばないでください:\n"
            + "\n".join(f"- {t[:70]}" for t in exclude_titles[:40])
        )

    prompt = f"""以下は今週の一般ニュースの見出し一覧です。
塗装設備メーカー（アンデックス㈱）の社内向け週刊ニュースレポートに、
「塗装とは直接関係ないが、技術部の社員が『へぇ』と興味を持ちそうな話題」として
最大{max_count}件を選んでください。

【選ぶ基準】
- モビリティ（新型車・空飛ぶクルマ・自動運転）、ロボット、AI、宇宙、ものづくり、
  新技術・新製品など、前向きで雑談のネタになる話題
- 多くのメディアが取り上げている注目度の高いニュースを優先
- 同じ出来事は 1 件だけ選ぶ（話題がかぶらないように分野を散らす）
- 見出しが簡潔で内容が伝わる記事を優先する

【選ばない記事】
- 政治・事件・事故・災害・芸能・スポーツ
- 株価・決算・市場予測レポート・PR記事・セミナー告知
- ライブ配信の告知・番組表のような見出し、見出しだけでは内容が分からないもの
{exclude_text}

記事リスト（番号. 見出し | 媒体 | 日付）:
{items_text}

選んだ記事の番号を、面白い順にカンマ区切りで返してください（最大{max_count}件）。
該当なしなら「なし」と返してください。番号のみ返してください。"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        logger.info("話題ニュース選別結果: %s", text[:80])
        if "なし" in text:
            return []
        indices = [
            int(n.strip()) - 1
            for n in text.replace("，", ",").split(",")
            if n.strip().isdigit()
        ]
        selected = [candidates[i] for i in indices if 0 <= i < len(candidates)]
        return selected[:max_count]
    except Exception as exc:
        logger.error("話題ニュース選別エラー（新着順で採用）: %s", exc)
        return candidates[:max_count]


def summarize_general_topics(articles: list[Article]) -> list[Article]:
    """各記事に 1〜2 文の要約（summary_ja）を付ける。"""
    if not articles:
        return []

    for a in articles:
        a.title_ja = a.title_ja or a.title

    if not ANTHROPIC_API_KEY:
        for a in articles:
            a.summary_ja = a.summary_ja or (a.description or "")[:120]
        return articles

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    items_text = "\n".join(
        f"{i + 1}. タイトル: {a.title}\n   概要: {(a.description or '')[:300]}"
        for i, a in enumerate(articles)
    )
    prompt = f"""以下のニュース記事を、社内向け週刊レポートの「気になる話題」コーナー用に
各 1〜2 文（80 字程度）で要約してください。
読者は塗装設備メーカーの社員です。専門用語を避け、何が起きたのかを平易に伝えてください。
文末は「。」で締めてください。

記事リスト:
{items_text}

以下の JSON 形式のみで返してください（説明文は不要）:
[{{"id": 1, "summary": "要約"}}, {{"id": 2, "summary": "要約"}}]"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        if "```" in text:
            text = "\n".join(
                line for line in text.split("\n") if not line.startswith("```")
            )
        summary_map = {int(s["id"]): s["summary"] for s in json.loads(text)}
        for i, a in enumerate(articles):
            a.summary_ja = summary_map.get(i + 1) or (a.description or "")[:120]
    except Exception as exc:
        logger.error("話題ニュース要約エラー（概要で代用）: %s", exc)
        for a in articles:
            a.summary_ja = a.summary_ja or (a.description or "")[:120]
    return articles


# ──────────────────────────────────────────────
# メイン: 手動登録 + 自動収集 → 選別 → 要約
# ──────────────────────────────────────────────
def collect_general_topics(
    past_articles=None,
    exclude_titles: list[str] | None = None,
    max_count: int = MAX_GENERAL_TOPICS,
) -> tuple[list[Article], list[str]]:
    """
    今週の「気になる話題」を組み立てる。

    Args:
        past_articles: dedup_history.load_published_history() の結果。
                       過去に掲載済みの URL・タイトルは候補から外す。
        exclude_titles: 今週の他セクションに載る見出し（話題かぶり防止）
        max_count: 手動登録分を含めた最大掲載数

    Returns:
        (articles, manual_urls): 掲載記事と、掲載した手動登録 URL のリスト
    """
    session = requests.Session()

    # ── 1. 手動登録（必ず掲載） ──
    manual_articles: list[Article] = []
    for entry in load_manual_topics():
        manual_articles.append(_manual_entry_to_article(entry, session))
    manual_urls = [a.url for a in manual_articles]

    # ── 2. 自動収集で残り枠を埋める ──
    remaining = max_count - len(manual_articles)
    auto_articles: list[Article] = []
    if remaining > 0:
        try:
            candidates = collect_general_topic_candidates()
        except Exception as exc:
            logger.error("話題ニュース収集エラー: %s", exc)
            candidates = []

        if candidates and past_articles:
            from scripts.dedup_history import filter_already_published
            candidates, _ = filter_already_published(candidates, past_articles, language="ja")

        # 手動登録と同じ話題は候補から外す（手動分を先頭に置いて確実に伝える）
        manual_titles = [a.title for a in manual_articles]
        auto_articles = curate_general_topics(
            candidates, remaining, exclude_titles=manual_titles + (exclude_titles or [])
        )

        if auto_articles:
            # Google News のリダイレクト URL を実 URL に解決し、
            # 記事ページの概要文を取り込んで要約の材料にする
            resolve_google_news_urls(auto_articles)
            for a in auto_articles:
                meta = fetch_article_metadata(a.url, session)
                if meta and meta.get("description"):
                    a.description = meta["description"]
                if meta and meta.get("published_at"):
                    a.published_at = meta["published_at"]

    articles = manual_articles + auto_articles
    if articles:
        summarize_general_topics(articles)

    logger.info(
        "気になる話題: %d 件（手動 %d / 自動 %d）",
        len(articles), len(manual_articles), len(auto_articles),
    )
    return articles, manual_urls
