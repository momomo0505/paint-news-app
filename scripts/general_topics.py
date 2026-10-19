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
import re
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
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
    GENERAL_TOPIC_SIMILARITY_THRESHOLD,
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


def load_manual_topics(path=MANUAL_TOPICS_PATH, report_date: str | None = None) -> list[dict]:
    """
    未掲載の手動登録エントリを返す。

    "published" が空のものに加えて、"published" が今回のレポート日付（report_date）と
    同じものも「未掲載」として扱う。同じ号を作り直したとき（手動での再生成の直後に
    GitHub Actions が同じ日に走った場合など）に、手動登録した記事が消えないようにするため。
    """
    pending = [
        e for e in _read_manual_file(path)
        if not e.get("published") or (report_date and e.get("published") == report_date)
    ]
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
        if entry.get("url", "").strip().rstrip("/") in targets and entry.get("published") != date_str:
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
# 「市場規模が○○億ドルに」のような市場予測レポート・PR 記事の見出しパターン。
# Claude にも「選ばない」と伝えているが、確実に外すためコード側でも弾く
_MARKET_REPORT_RE = re.compile(
    r"(市場|マーケット).{0,20}(規模|予測|成長率|拡大|CAGR|年平均)|"
    r"(規模|予測).{0,10}(市場|マーケット)|"
    r"(億|兆)(米)?ドル規模|調査レポート|市場調査|レポート(を)?(発行|発表|公開)"
)


def _looks_like_market_report(title: str) -> bool:
    """見出しが市場予測レポート・調査レポートの PR っぽければ True。"""
    return bool(_MARKET_REPORT_RE.search(title))


# プレスリリース配信ページ（企業の宣伝文がそのまま載る）の URL パターン
_PR_URL_RE = re.compile(r"prtimes\.jp|/external-pr/|/prtimes/|/pressrelease/|/press_release/|atpress\.ne\.jp|dreamnews\.jp")


def _looks_like_press_release(url: str) -> bool:
    """URL がプレスリリース配信ページっぽければ True。"""
    return bool(_PR_URL_RE.search(url))


def _is_within_days(published_at: str, days: int) -> bool:
    """ISO 形式の日付文字列が「今から days 日以内」なら True（解釈できなければ True）。"""
    if not published_at:
        return True
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)
    return dt >= datetime.now(JST) - timedelta(days=days)


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
            if _looks_like_market_report(title):
                logger.debug("市場レポートっぽいため除外: %s", title)
                continue
            if _looks_like_press_release(link):
                logger.debug("プレスリリース配信ページのため除外: %s", title)
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
# 同じ話題かどうかの判定（重複掲載を防ぐ）
# ──────────────────────────────────────────────
_PUNCT_RE = re.compile(r"[\s\u3000、。，．,.:：;；!！?？「」『』【】（）()\[\]｜|/／\-－~〜・…\"'“”‘’]+")


def _normalize_for_compare(title: str) -> str:
    """見出しを比較用に正規化する（空白・記号を除き、英数字は小文字に）。"""
    return _PUNCT_RE.sub("", title).lower()


def _char_bigrams(text: str) -> set[str]:
    """文字 2-gram の集合を返す。日本語は分かち書きが無いので 2-gram が扱いやすい。"""
    if len(text) < 2:
        return {text} if text else set()
    return {text[i : i + 2] for i in range(len(text) - 1)}


def topic_similarity(title_a: str, title_b: str) -> float:
    """2 つの見出しがどれくらい似ているか（0〜1）。

    文字 2-gram の Jaccard 係数と、文字列全体の一致率（SequenceMatcher）の
    大きい方を返す。前者は語順が違っても同じ固有名詞を含めば高くなり、
    後者は言い回しが近い見出しに強い。
    """
    a = _normalize_for_compare(title_a)
    b = _normalize_for_compare(title_b)
    if not a or not b:
        return 0.0
    ga, gb = _char_bigrams(a), _char_bigrams(b)
    jaccard = len(ga & gb) / len(ga | gb) if (ga | gb) else 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    return max(jaccard, ratio)


# 「特徴的な語」として扱う文字列: 漢字 3 文字以上、またはカタカナ 3 文字以上の連なり
_TERM_RE = re.compile(r"[\u4e00-\u9fff]{3,}|[\u30a0-\u30ff\u30fc]{3,}")

# どのニュースにも出てくる一般的な語（これが共通しても同じ話題とはみなさない）
_GENERIC_TERMS = {
    "実証実験", "実用化", "世界初", "新技術", "本格始動", "開発加速", "商用運航", "社会実装",
    "航続距離", "打ち上げ", "新製品", "発表会", "可能性", "技術開発", "製造業", "次世代",
    "ニュース", "メディア", "サービス", "システム", "ビジネス", "レポート", "プロジェクト",
    "テクノロジー", "デザイン", "グローバル", "スタート", "リリース", "インタビュー", "クルマ",
    "日本経済新聞", "日刊工業新聞", "クロステック", "イーロン", "マスク",
}


# よく出てくるテーマの言い換え辞書。見出しにどれかが含まれていれば同じテーマ名を付ける。
# （Claude の判定がぶれても、ここにあるテーマは必ず 1 件にまとまる）
_THEME_KEYWORDS: dict[str, tuple[str, ...]] = {
    "空飛ぶクルマ": ("空飛ぶ", "eVTOL", "空中で回転", "飛行デモ", "エアモビリティ", "空モビリティ"),
    "ロケット打ち上げ": ("ロケット", "打ち上げ", "スペースX", "SpaceX", "ファルコン", "JAXA", "衛星", "スターリンク"),
    "核融合": ("核融合", "フュージョン"),
    "全固体電池": ("全固体", "次世代電池"),
    "自動運転": ("自動運転", "ロボタクシー", "無人運転"),
    "ヒューマノイド": ("ヒューマノイド", "人型ロボット", "オプティマス", "Optimus", "Unitree"),
    "生成AI×製造": ("生成AI", "AIエージェント", "コパイロット"),
    "新型EV": ("新型EV", "航続距離", "EV新型", "新型電気自動車"),
}


def themes_of(title: str) -> set[str]:
    """見出しが辞書のどのテーマに当てはまるか返す（複数可・無ければ空集合）。"""
    lowered = title.lower()
    return {
        theme
        for theme, words in _THEME_KEYWORDS.items()
        if any(w.lower() in lowered for w in words)
    }


def distinctive_terms(title: str) -> set[str]:
    """見出しから話題を特徴づける語（核融合・全固体電池・ロードスター など）を取り出す。"""
    terms = {t for t in _TERM_RE.findall(title) if t not in _GENERIC_TERMS}
    # テーマ名も特徴語として扱う（# は通常の語とぶつからない印）
    terms |= {f"#{theme}" for theme in themes_of(title)}
    return terms


def is_same_topic(
    title_a: str,
    title_b: str,
    threshold: float = GENERAL_TOPIC_SIMILARITY_THRESHOLD,
) -> bool:
    """
    「同じ話題」かどうかを判定する。

    次のどちらかに当てはまれば同じ話題とみなす:
      1. 見出し全体の類似度がしきい値以上（言い回しが近い）
      2. 特徴的な語（漢字 3 文字以上・カタカナ 3 文字以上）を共有している
         例: 「核融合」「全固体電池」「自動運転」「ロードスター」「ヒューマノイド」
    2 は Claude の判定が失敗したときの保険で、少し厳しめ（同じ分野なら 1 件）に働く。
    """
    if topic_similarity(title_a, title_b) >= threshold:
        return True
    return bool(distinctive_terms(title_a) & distinctive_terms(title_b))


def drop_duplicate_topics(
    articles: list[Article],
    exclude_titles: list[str] | None = None,
) -> list[Article]:
    """
    並び順を保ったまま、同じ話題の記事を 1 件に絞る（コードによる機械的チェック）。

    - exclude_titles（手動登録・他セクションの見出し）と似ている記事は外す
    - 先に残した記事と似ている記事も外す（先頭ほど優先）
    """
    kept: list[Article] = []
    blocked = list(exclude_titles or [])
    for a in articles:
        dup_of = next((t for t in blocked if is_same_topic(a.title, t)), None)
        if dup_of:
            logger.info("同じ話題のため除外: %s ≈ %s", a.title[:40], dup_of[:40])
            continue
        kept.append(a)
        blocked.append(a.title)
    return kept


def _group_same_topics_with_claude(
    articles: list[Article],
    fixed_titles: list[str] | None = None,
) -> list[Article]:
    """
    Claude に「同じ話題（テーマ）の記事」をまとめてもらい、各グループの先頭だけ残す。

    見出しの文字が似ていなくても同じ話題（例: 「核融合ベンチャーに出資」と
    「ヘリカル型核融合の実証装置」はどちらも“核融合”の話題）を検出する第 2 のチェック。
    同じ出来事だけでなく、同じテーマが何件も並ばないようにするのが目的。

    fixed_titles には手動登録など「必ず載る」見出しを渡す。これと同じ話題の
    自動記事は落とす（fixed 側は落とさない）。
    失敗した場合はそのまま返す（機械的チェックは別途かかっている）。
    """
    fixed = list(fixed_titles or [])
    if (len(articles) + len(fixed)) < 2 or not articles or not ANTHROPIC_API_KEY:
        return articles

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # 先頭に「必ず載る見出し」を並べ、その後ろに自動選別の記事を並べる
    # （番号が小さいほど優先されるので、固定分は必ず残る）
    all_titles = fixed + [a.title for a in articles]
    items_text = "\n".join(
        f"{i + 1}. {t}" + ("（掲載確定）" if i < len(fixed) else "")
        for i, t in enumerate(all_titles)
    )
    prompt = f"""以下は社内向けレポートの「気になる話題」コーナーに載せる候補の見出しです。
読者が「また同じ話か」と感じないよう、【同じ話題】の記事をグループにまとめてください。

【同じ話題とみなす例】
- 同じ出来事・同じ発表・同じ製品（媒体や言い回しが違っても同じ）
- 同じテーマ・同じ技術分野の記事（例: 核融合の記事が 3 件 → 1 グループ、
  空飛ぶクルマ／eVTOL の記事が 2 件 → 1 グループ、自動運転の実証実験が 2 件 → 1 グループ）
- 同じ企業の同じ領域の話（例: トヨタの自動運転戦略とトヨタの空飛ぶクルマ参入）

【別の話題とみなす例】
- 分野が大きく違うもの（例: ロケット打ち上げ と ヒューマノイドロボット）
- 同じ「クルマ」でも、EV の新型車発表 と 自動運転の実証実験 は別

見出しリスト:
{items_text}

2 件以上からなるグループだけを、番号の配列の配列で JSON のみ返してください。
例: [[1, 4], [2, 7, 9]]
該当がなければ [] と返してください。"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # 説明文や ``` が混ざっていても、最初の [ から最後の ] までを配列として読む
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end == -1:
            raise ValueError(f"配列が見つかりません: {text[:80]}")
        groups = json.loads(text[start : end + 1])
        if not isinstance(groups, list):
            raise ValueError("配列ではありません")
        logger.info("同一話題グルーピング結果: %s", json.dumps(groups, ensure_ascii=False)[:120])
    except Exception as exc:
        logger.warning("同一話題グルーピングに失敗（スキップ）: %s", exc)
        return articles

    # 各グループで最も順位の高い（番号が小さい）ものだけ残す
    offset = len(fixed)
    remove: set[int] = set()
    for group in groups:
        try:
            ids = sorted({int(n) - 1 for n in group if 0 <= int(n) - 1 < len(all_titles)})
        except (TypeError, ValueError):
            continue
        for idx in ids[1:]:
            if idx < offset:
                continue  # 掲載確定分は落とさない
            remove.add(idx - offset)
            logger.info(
                "同じ話題のため除外（Claude判定）: %s ≈ %s",
                all_titles[idx][:40], all_titles[ids[0]][:40],
            )
    return [a for i, a in enumerate(articles) if i not in remove]


# ──────────────────────────────────────────────
# Claude による選別・要約
# ──────────────────────────────────────────────
def curate_general_topics(
    candidates: list[Article],
    max_count: int,
    exclude_titles: list[str] | None = None,
    fixed_titles: list[str] | None = None,
) -> list[Article]:
    """
    候補から「社内で話題になりそうな」記事を最大 max_count 件選ぶ。

    Args:
        exclude_titles: 他セクションに載る見出しなど「選んではいけない話題」
        fixed_titles:   手動登録など「同じコーナーに必ず載る見出し」。
                        これと同じテーマの記事はテーマ重複として落とす

    重複対策は 3 段構え:
      1. Claude に「同じ話題は 1 件だけ」と指示して、少し多め（max_count + 5）に選ばせる
      2. 見出しの類似度でコード側が機械的に重複を落とす（drop_duplicate_topics）
      3. Claude にもう一度「同じ話題（テーマ）のグループ」を判定させて残りの重複を落とす
    最後に max_count 件に切り詰める。
    """
    if not candidates or max_count <= 0:
        return []

    # 候補同士の重複もまず機械的に減らしておく（Claude に渡すリストを短くする）
    candidates = drop_duplicate_topics(candidates, exclude_titles)
    if not candidates:
        return []

    if not ANTHROPIC_API_KEY:
        logger.warning("ANTHROPIC_API_KEY 未設定のため話題ニュースは新着順 %d 件を採用", max_count)
        return candidates[:max_count]

    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # 重複を落とした後でも max_count 件残るよう多めに選ばせる
    # （10 件狙いで 14 件選ばせたら重複除去後 8 件になったことがあるため、余裕を大きめに取る）
    pick_count = min(len(candidates), max_count + max(5, max_count))
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
最大{pick_count}件を選んでください。

【選ぶ基準】
- モビリティ（新型車・空飛ぶクルマ・自動運転）、ロボット、AI、宇宙、ものづくり、
  新技術・新製品など、前向きで雑談のネタになる話題
- 多くのメディアが取り上げている注目度の高いニュースを優先
- 【最重要】同じ話題は 1 件だけにする。同じ出来事・同じ製品はもちろん、
  同じテーマ（例: 核融合、空飛ぶクルマ、自動運転の実証）の記事も 1 件に絞る
  （最も分かりやすい見出しのものを選ぶ）
- 分野が偏らないように散らす（例: クルマばかりにせず、ロボット・宇宙・AI なども混ぜる）
- 見出しが簡潔で内容が伝わる記事を優先する

【選ばない記事】
- 政治・事件・事故・災害・芸能・スポーツ
- 株価・決算・市場予測レポート・PR記事・セミナー告知
- ライブ配信の告知・番組表のような見出し、見出しだけでは内容が分からないもの
{exclude_text}

記事リスト（番号. 見出し | 媒体 | 日付）:
{items_text}

選んだ記事の番号を、面白い順にカンマ区切りで返してください（最大{pick_count}件）。
該当なしなら「なし」と返してください。番号のみ返してください。"""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        logger.info("話題ニュース選別結果: %s", text[:120])
        if "なし" in text:
            return []
        indices: list[int] = []
        for n in text.replace("，", ",").split(","):
            n = n.strip()
            if n.isdigit() and int(n) - 1 not in indices:
                indices.append(int(n) - 1)
        selected = [candidates[i] for i in indices if 0 <= i < len(candidates)]
    except Exception as exc:
        logger.error("話題ニュース選別エラー（新着順で採用）: %s", exc)
        selected = candidates[:pick_count]

    # 2 段目: 見出し類似度で機械的に重複を落とす
    selected = drop_duplicate_topics(selected, exclude_titles)
    # 3 段目: Claude に「同じ話題（テーマ）」をまとめてもらう。
    # fixed_titles（手動登録分）と同じテーマの自動記事もここで落ちる
    selected = _group_same_topics_with_claude(selected, fixed_titles=fixed_titles)
    return selected[:max_count]


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
            max_tokens=3000,  # 最大 10 件 × 80 字程度の JSON が収まる余裕を持たせる
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
    report_date: str | None = None,
) -> tuple[list[Article], list[str]]:
    """
    今週の「気になる話題」を組み立てる。

    Args:
        past_articles: dedup_history.load_published_history() の結果。
                       過去に掲載済みの URL・タイトルは候補から外す。
        exclude_titles: 今週の他セクションに載る見出し（話題かぶり防止）
        max_count: 手動登録分を含めた最大掲載数
        report_date: 今回のレポート日付（YYYY-MM-DD）。同じ日付で掲載済みの
                     手動登録記事も再掲載の対象にする（同じ号の作り直し用）

    Returns:
        (articles, manual_urls): 掲載記事と、掲載した手動登録 URL のリスト
    """
    session = requests.Session()

    # ── 1. 手動登録（必ず掲載） ──
    manual_articles: list[Article] = []
    for entry in load_manual_topics(report_date=report_date):
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
            candidates,
            remaining,
            exclude_titles=manual_titles + (exclude_titles or []),
            fixed_titles=manual_titles,
        )

        if auto_articles:
            # Google News のリダイレクト URL を実 URL に解決し、
            # 記事ページの概要文を取り込んで要約の材料にする
            resolve_google_news_urls(auto_articles)
            fresh: list[Article] = []
            for a in auto_articles:
                # 実 URL がプレスリリース配信ページだった場合はここで外す
                if _looks_like_press_release(a.url):
                    logger.info("プレスリリース配信ページのため除外: %s", a.title[:40])
                    continue
                meta = fetch_article_metadata(a.url, session)
                if meta and meta.get("description"):
                    a.description = meta["description"]
                if meta and meta.get("published_at"):
                    a.published_at = meta["published_at"]
                # 記事ページの実際の公開日が古かった（RSS の日付が再配信日だった）場合は外す
                if not _is_within_days(a.published_at, GENERAL_TOPIC_DAYS_BACK):
                    logger.info("実際の公開日が古いため除外: %s (%s)", a.title[:40], a.published_at[:10])
                    continue
                fresh.append(a)
            auto_articles = fresh

    # 念のため最終チェック: 手動登録分を優先しつつ、同じ話題が 2 件残らないようにする
    auto_articles = drop_duplicate_topics(auto_articles, [a.title for a in manual_articles])
    articles = manual_articles + auto_articles
    if articles:
        summarize_general_topics(articles)

    logger.info(
        "気になる話題: %d 件（手動 %d / 自動 %d）",
        len(articles), len(manual_articles), len(auto_articles),
    )
    return articles, manual_urls
