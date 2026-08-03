"""
過去掲載済みニュースとの重複排除モジュール
==========================================

docs/articles-YYYY-MM-DD.json を遡って参照し、
すでに過去週に掲載されたニュースを今週の収集結果から除外する。

除外基準:
  1. URL が過去記事と完全一致する
  2. タイトルが過去記事と高い類似度（閾値以上）で一致する

タイトル類似度チェックは以下の組み合わせで行う:
  - 新記事の title（元タイトル）vs 過去記事の title（元タイトル）
  - 新記事の title           vs 過去記事の title_ja（日本語タイトル、ある場合）
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from scripts.collect_news import Article

logger = logging.getLogger(__name__)

# デフォルトで遡る週数
DEFAULT_HISTORY_WEEKS = 4


@dataclass(frozen=True)
class _PastEntry:
    """過去掲載済み記事の照合用エントリ（軽量）。"""

    url: str        # 正規化済み URL（小文字・末尾スラッシュ除去）
    title: str      # 元タイトル（英語 or 日本語）
    title_ja: str   # 日本語タイトル（翻訳済みの場合のみ、なければ空文字）
    week: str       # 掲載週の日付文字列（ログ用）


# ──────────────────────────────────────────────
# 内部ユーティリティ
# ──────────────────────────────────────────────

def _normalize_url(url: str) -> str:
    """URL を比較用に正規化する。"""
    return url.strip().rstrip("/").lower()


def _similarity(a: str, b: str) -> float:
    """2文字列の類似度を返す（0.0〜1.0）。大文字小文字を無視。"""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _normalize_title(title: str) -> str:
    """タイトルを類似度比較用に正規化する（記事ソース名の除去など）。

    Google News RSS のタイトルは "記事タイトル - メディア名" 形式になることが多い。
    末尾の " - メディア名" を除去して本文部分だけを比較する。
    """
    # " - メディア名" 部分（最後のハイフン区切り）を除去
    if " - " in title:
        title = title.rsplit(" - ", 1)[0]
    # "|" 区切りも同様に除去
    if " | " in title:
        title = title.rsplit(" | ", 1)[0]
    return title.strip()


# ──────────────────────────────────────────────
# 公開 API
# ──────────────────────────────────────────────

def load_published_history(
    docs_dir: Path,
    exclude_date: str | None = None,
    n_weeks: int = DEFAULT_HISTORY_WEEKS,
) -> list[_PastEntry]:
    """
    過去 N 週分の掲載済み記事を docs/*.json から読み込む。

    Args:
        docs_dir: docs/ ディレクトリのパス（articles-*.json が格納されている）
        exclude_date: 除外する日付文字列（今週分を除くため。例: "2026-08-03"）
        n_weeks: 遡る週数（デフォルト 4 週）

    Returns:
        list[_PastEntry]: 過去掲載済み記事エントリのリスト
    """
    # articles-YYYY-MM-DD.json を日付の新しい順に取得
    json_files = sorted(
        docs_dir.glob("articles-*.json"),
        key=lambda p: p.stem,
        reverse=True,
    )

    past_entries: list[_PastEntry] = []
    loaded_weeks = 0

    for json_file in json_files:
        week_str = json_file.stem.replace("articles-", "")

        if exclude_date and week_str == exclude_date:
            logger.debug("今週分をスキップ: %s", json_file.name)
            continue

        if loaded_weeks >= n_weeks:
            break

        try:
            raw_list: list[dict] = json.loads(json_file.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("過去記事読み込みエラー (%s): %s", json_file.name, exc)
            continue

        count_before = len(past_entries)
        for entry in raw_list:
            url = entry.get("url", "").strip()
            title = entry.get("title", "").strip()
            title_ja = entry.get("title_ja", "").strip()
            if not url and not title:
                continue
            past_entries.append(
                _PastEntry(
                    url=_normalize_url(url),
                    title=_normalize_title(title),
                    title_ja=_normalize_title(title_ja) if title_ja else "",
                    week=week_str,
                )
            )

        loaded_weeks += 1
        logger.info(
            "過去記事読み込み: %s (%d件)",
            json_file.name,
            len(past_entries) - count_before,
        )

    logger.info(
        "過去掲載済み合計: %d 件（%d 週分）",
        len(past_entries),
        loaded_weeks,
    )
    return past_entries


def filter_already_published(
    articles: list[Article],
    past_entries: list[_PastEntry],
    title_threshold: float = 0.82,
    language: str = "ja",
) -> tuple[list[Article], list[Article]]:
    """
    過去掲載済み記事と重複する記事を除外する。

    照合の優先順位:
    1. URL の正規化後完全一致 → 確実に同一記事として除外
    2. タイトル類似度が閾値以上 → 同一ニュースとみなして除外
       - 新記事 title vs 過去記事 title（元タイトル同士）
       - 新記事 title vs 過去記事 title_ja（日本語タイトルがある場合）

    閾値について:
    - 英語タイトルは同一事象でも媒体により表現が揺れやすいため
      threshold を 0.05 低く設定する（デフォルト 0.77）
    - 続報・追加情報など正当に異なる記事が誤除外されるリスクを
      下げるために閾値を調整できる

    Args:
        articles: 今週新たに収集した記事リスト
        past_entries: load_published_history() で取得した過去記事リスト
        title_threshold: タイトル類似度の除外閾値（デフォルト 0.82）
        language: "ja"（国内）または "en"（海外）。英語は 0.05 低い閾値を使用。

    Returns:
        (kept, excluded): 残す記事リストと除外した記事リストのタプル
    """
    if not past_entries:
        logger.info("過去記事データなし — 過去週重複除外をスキップ")
        return articles, []

    # 言語別の閾値調整
    effective_threshold = title_threshold if language == "ja" else max(0.70, title_threshold - 0.05)

    # 高速照合のためのセット・リスト
    past_urls: set[str] = {p.url for p in past_entries}
    # (正規化済みタイトル, 正規化済みtitle_ja, 掲載週) のリスト
    past_titles: list[tuple[str, str, str]] = [
        (p.title, p.title_ja, p.week) for p in past_entries
    ]

    kept: list[Article] = []
    excluded: list[Article] = []

    for article in articles:
        norm_url = _normalize_url(article.url)
        norm_title = _normalize_title(article.title)

        # ── 1. URL 完全一致 ──────────────────────
        if norm_url and norm_url in past_urls:
            logger.info(
                "[過去週重複・URL一致] 除外: %s",
                article.title[:70],
            )
            excluded.append(article)
            continue

        # ── 2. タイトル類似度チェック ─────────────
        matched_week = _check_title_similarity(
            norm_title, past_titles, effective_threshold
        )
        if matched_week is not None:
            logger.info(
                "[過去週重複・タイトル類似（%s週）] 除外: %s",
                matched_week,
                article.title[:70],
            )
            excluded.append(article)
        else:
            kept.append(article)

    logger.info(
        "過去週重複除外（%s）: %d件 → %d件（除外 %d件）",
        language,
        len(articles),
        len(kept),
        len(excluded),
    )
    return kept, excluded


def _check_title_similarity(
    new_title: str,
    past_titles: list[tuple[str, str, str]],
    threshold: float,
) -> str | None:
    """
    新記事タイトルが過去記事タイトルと閾値以上の類似度を持つか確認する。

    Returns:
        一致した過去記事の掲載週文字列。一致なければ None。
    """
    for past_title, past_title_ja, week in past_titles:
        # 元タイトル同士の比較
        if past_title and _similarity(new_title, past_title) >= threshold:
            logger.debug(
                "タイトル類似（%.2f >= %.2f）: 「%s」 ≈ 「%s」（%s週）",
                _similarity(new_title, past_title),
                threshold,
                new_title[:50],
                past_title[:50],
                week,
            )
            return week

        # 新記事の元タイトル vs 過去の日本語タイトル
        if past_title_ja and _similarity(new_title, past_title_ja) >= threshold:
            logger.debug(
                "タイトル類似（title_ja, %.2f >= %.2f）: 「%s」 ≈ 「%s」（%s週）",
                _similarity(new_title, past_title_ja),
                threshold,
                new_title[:50],
                past_title_ja[:50],
                week,
            )
            return week

    return None
