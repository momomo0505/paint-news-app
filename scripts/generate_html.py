"""
HTML生成モジュール — 翻訳済み記事をHTMLファイルに出力する
=========================================================

機能:
- Jinja2テンプレートを使用したHTML生成
- カテゴリ別の統計情報
- 日付フォーマットの日本語変換
- 過去のレポートへのインデックスページ生成（キーワード検索付き）
- 1年以上経過したレポートの自動削除
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from scripts.collect_news import Article
from scripts.config import DOCS_DIR, PAGES_BASE_URL, SEARCH_DAYS_BACK, TEMPLATES_DIR
from scripts.translate_summarize import CATEGORIES

logger = logging.getLogger(__name__)

# 日本時間 (JST = UTC+9)
JST = timezone(timedelta(hours=9))

# 検索インデックスファイルのパス
SEARCH_INDEX_PATH = DOCS_DIR / "search-index.json"

# レポート保持期間（日数）
REPORT_RETENTION_DAYS = 365


# ──────────────────────────────────────────────
# ユーティリティ
# ──────────────────────────────────────────────
def _format_date_ja(iso_date: str) -> str:
    """ISO 8601 日付文字列を日本語形式に変換する。"""
    try:
        dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
        dt_jst = dt.astimezone(JST)
        return dt_jst.strftime("%Y年%m月%d日")
    except (ValueError, AttributeError):
        return iso_date


def _count_categories(articles: list[Article]) -> dict[str, dict[str, Any]]:
    """記事のカテゴリ別カウントを集計する。"""
    counts: dict[str, dict[str, Any]] = {}
    for key, label in CATEGORIES.items():
        count = sum(1 for a in articles if a.category == key)
        counts[key] = {"label": label, "count": count}
    return counts


def _prepare_article_data(articles: list[Article]) -> list[dict[str, Any]]:
    """テンプレートに渡す記事データを整形する。"""
    prepared: list[dict[str, Any]] = []
    for article in articles:
        data = article.to_dict()
        data["published_at_formatted"] = _format_date_ja(article.published_at)
        prepared.append(data)
    return prepared


# ──────────────────────────────────────────────
# HTML生成
# ──────────────────────────────────────────────
def generate_weekly_report(
    articles: list[Article],
    output_filename: str | None = None,
    *,
    competitor_items: list[dict] | None = None,
    domestic_articles: list[Article] | None = None,
    self_mention_articles: list[Article] | None = None,
    weekly_digest: str = "",
) -> Path:
    """
    週間レポートのHTMLファイルを生成する。

    Args:
        articles: 翻訳済みの海外記事リスト
        output_filename: 出力ファイル名（省略時は日付ベースで自動生成）
        competitor_items: 競合他社ニュース項目リスト
        domestic_articles: 国内ニュース記事リスト

    Returns:
        Path: 生成したHTMLファイルのパス
    """
    now_jst = datetime.now(JST)

    if output_filename is None:
        output_filename = f"weekly-news-{now_jst.strftime('%Y-%m-%d')}.html"

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOCS_DIR / output_filename

    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("weekly_report.html")

    period_end = now_jst
    period_start = period_end - timedelta(days=SEARCH_DAYS_BACK)

    # 競合ニュースを会社別にグループ化
    competitor_by_company: dict[str, list[dict]] = {}
    for item in (competitor_items or []):
        company = item["company"]
        competitor_by_company.setdefault(company, []).append(item)

    context = {
        # 自社メンション記事
        "self_mention_articles": _prepare_article_data(self_mention_articles or []),
        "total_self_mention": len(self_mention_articles or []),
        # 海外ニュース
        "articles": _prepare_article_data(articles),
        # 国内ニュース
        "domestic_articles": _prepare_article_data(domestic_articles or []),
        # 競合ニュース（生の dict リスト）
        "competitor_items": competitor_items or [],
        "competitor_by_company": competitor_by_company,
        # 共通
        "issue_date": now_jst.strftime("%Y年%m月%d日"),
        "period_start": period_start.strftime("%Y/%m/%d"),
        "period_end": period_end.strftime("%Y/%m/%d"),
        "year": now_jst.year,
        "category_counts": _count_categories(articles),
        "category_labels": CATEGORIES,
        "total_articles": len(articles),
        "total_domestic": len(domestic_articles or []),
        "total_competitor": len(competitor_items or []),
        "pages_base_url": PAGES_BASE_URL.rstrip("/"),
        "weekly_digest": weekly_digest,
        "weekly_digest_lines": [line for line in weekly_digest.splitlines() if line.strip()],
    }

    html_content = template.render(**context)
    output_path.write_text(html_content, encoding="utf-8")
    logger.info("HTMLレポート生成: %s", output_path)

    _cleanup_old_reports()
    _update_search_index(
        now_jst,
        output_filename,
        competitor_items or [],
        domestic_articles or [],
        articles,
        self_mention_articles or [],
    )
    _update_index_page(now_jst)

    return output_path


# ──────────────────────────────────────────────
# 古いレポートの自動削除
# ──────────────────────────────────────────────
def _cleanup_old_reports(max_days: int = REPORT_RETENTION_DAYS) -> None:
    """指定日数より古いレポートHTMLファイルを削除する（デフォルト1年）。"""
    cutoff = datetime.now(JST) - timedelta(days=max_days)
    deleted = 0
    for f in list(DOCS_DIR.glob("weekly-news-*.html")):
        date_str = f.stem.replace("weekly-news-", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=JST)
            if dt < cutoff:
                f.unlink()
                logger.info("古いレポートを削除: %s", f.name)
                deleted += 1
        except ValueError:
            pass
    if deleted:
        logger.info("古いレポート %d 件を削除しました", deleted)


# ──────────────────────────────────────────────
# 検索インデックス更新
# ──────────────────────────────────────────────
def _update_search_index(
    now: datetime,
    filename: str,
    competitor_items: list[dict],
    domestic_articles: list[Article],
    overseas_articles: list[Article],
    self_mention_articles: list[Article],
) -> None:
    """docs/search-index.json に今週分のエントリを追加/更新する。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # 既存インデックスを読み込む
    if SEARCH_INDEX_PATH.exists():
        try:
            existing: list[dict] = json.loads(SEARCH_INDEX_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = []
    else:
        existing = []

    date_str = now.strftime("%Y-%m-%d")
    label = now.strftime("%Y年%m月%d日号")

    # 今週分の記事タイトルを収集
    articles_list: list[dict] = []
    for item in competitor_items:
        title = item.get("title", "")
        if title:
            articles_list.append({"title": title, "section": "競合"})
    for a in domestic_articles:
        title = a.title_ja or a.title
        if title:
            articles_list.append({"title": title, "section": "国内"})
    for a in overseas_articles:
        title = a.title_ja or a.title
        if title:
            articles_list.append({"title": title, "section": "海外"})
    for a in self_mention_articles:
        title = a.title_ja or a.title
        if title:
            articles_list.append({"title": title, "section": "自社"})

    new_entry = {
        "date": date_str,
        "label": label,
        "filename": filename,
        "articles": articles_list,
    }

    # 同一日付のエントリがあれば置換、なければ先頭に追加
    updated = [e for e in existing if e.get("date") != date_str]
    updated.insert(0, new_entry)

    # 1年以上前のエントリを削除
    cutoff_str = (datetime.now(JST) - timedelta(days=REPORT_RETENTION_DAYS)).strftime("%Y-%m-%d")
    updated = [e for e in updated if e.get("date", "") >= cutoff_str]

    SEARCH_INDEX_PATH.write_text(
        json.dumps(updated, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("検索インデックス更新: %d 件のレポート", len(updated))


# ──────────────────────────────────────────────
# インデックスページ（バックナンバー一覧）
# ──────────────────────────────────────────────
INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="ja">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>塗装業界ウィークリーニュース — アーカイブ</title>
    <style>
        *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans",
                         "Noto Sans JP", sans-serif;
            background: #f8f9fa;
            color: #1a1a2e;
            line-height: 1.7;
        }
        .container {
            max-width: 660px;
            margin: 0 auto;
            padding: 40px 20px;
        }
        h1 {
            font-size: 1.5rem;
            font-weight: 700;
            margin-bottom: 8px;
        }
        .subtitle {
            color: #6b7280;
            font-size: 0.9rem;
            margin-bottom: 28px;
        }
        /* 検索エリア */
        .search-wrap {
            position: relative;
            margin-bottom: 24px;
        }
        .search-wrap input {
            width: 100%;
            padding: 12px 16px 12px 42px;
            border: 1px solid #d1d5db;
            border-radius: 8px;
            font-size: 0.95rem;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
            background: #fff;
        }
        .search-wrap input:focus {
            border-color: #2563eb;
            box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
        }
        .search-wrap .icon {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            color: #9ca3af;
            font-size: 1rem;
            pointer-events: none;
        }
        #search-status {
            font-size: 0.85rem;
            color: #6b7280;
            margin-bottom: 16px;
            min-height: 20px;
        }
        /* レポート一覧 */
        .issue-list {
            list-style: none;
        }
        .issue-list li {
            margin-bottom: 8px;
        }
        .issue-list li.hidden {
            display: none;
        }
        .issue-list a {
            display: block;
            padding: 14px 20px;
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            text-decoration: none;
            color: #1a1a2e;
            font-weight: 500;
            transition: box-shadow 0.2s, border-color 0.2s;
        }
        .issue-list a:hover {
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.07);
            border-color: #d1d5db;
        }
        .issue-list .date {
            color: #6b7280;
            font-size: 0.85rem;
            font-weight: 400;
        }
        .match-count {
            display: inline-block;
            margin-left: 8px;
            background: #2563eb;
            color: #fff;
            border-radius: 12px;
            padding: 1px 8px;
            font-size: 0.75rem;
            font-weight: 600;
        }
        .match-titles {
            margin-top: 6px;
            font-size: 0.82rem;
            color: #374151;
            line-height: 1.5;
        }
        .match-titles span {
            display: inline-block;
            margin-right: 4px;
            margin-bottom: 2px;
            padding: 1px 6px;
            background: #f0f4ff;
            border-radius: 4px;
        }
        .no-result {
            text-align: center;
            padding: 40px 0;
            color: #9ca3af;
            font-size: 0.95rem;
            display: none;
        }
        footer {
            margin-top: 40px;
            text-align: center;
            font-size: 0.8rem;
            color: #6b7280;
        }
    </style>
</head>
<body>
<div class="container">
    <h1>🎨 塗装業界ウィークリーニュース</h1>
    <p class="subtitle">過去のレポート一覧</p>

    <div class="search-wrap">
        <span class="icon">🔍</span>
        <input type="text" id="search-input"
               placeholder="キーワードで記事を検索（例：BASF、EV、脱炭素）"
               autocomplete="off">
    </div>
    <p id="search-status"></p>

    <ul class="issue-list" id="issue-list">
        {issue_items}
    </ul>
    <p class="no-result" id="no-result">該当するレポートが見つかりませんでした。</p>

    <footer>
        <p>© {year} 塗装業界ニュース自動まとめツール</p>
    </footer>
</div>

<script>
(function () {
    var searchInput = document.getElementById('search-input');
    var statusEl = document.getElementById('search-status');
    var noResult = document.getElementById('no-result');
    var items = document.querySelectorAll('#issue-list li');

    // 検索インデックスを読み込む
    var indexData = [];
    fetch('search-index.json?t=' + Date.now())
        .then(function (r) { return r.json(); })
        .then(function (data) { indexData = data; })
        .catch(function () { indexData = []; });

    function normalize(s) {
        return (s || '').toLowerCase();
    }

    function search(keyword) {
        var kw = normalize(keyword.trim());

        if (!kw) {
            // キーワードなし → 全件表示・詳細非表示
            items.forEach(function (li) {
                li.classList.remove('hidden');
                var detail = li.querySelector('.match-titles');
                if (detail) detail.remove();
                var badge = li.querySelector('.match-count');
                if (badge) badge.remove();
            });
            statusEl.textContent = '';
            noResult.style.display = 'none';
            return;
        }

        var matched = 0;
        items.forEach(function (li) {
            var filename = li.dataset.filename || '';
            var entry = indexData.find(function (e) { return e.filename === filename; });
            var matchedTitles = [];

            if (entry && entry.articles) {
                matchedTitles = entry.articles.filter(function (a) {
                    return normalize(a.title).indexOf(kw) !== -1;
                });
            }

            // ファイル名(日付)でも検索
            var dateMatch = normalize(li.dataset.date || '').indexOf(kw) !== -1
                         || normalize(li.dataset.label || '').indexOf(kw) !== -1;

            var hit = matchedTitles.length > 0 || dateMatch;

            if (hit) {
                li.classList.remove('hidden');
                matched++;

                // 既存バッジ・詳細を削除してから再描画
                var oldBadge = li.querySelector('.match-count');
                if (oldBadge) oldBadge.remove();
                var oldDetail = li.querySelector('.match-titles');
                if (oldDetail) oldDetail.remove();

                if (matchedTitles.length > 0) {
                    var link = li.querySelector('a');
                    var badge = document.createElement('span');
                    badge.className = 'match-count';
                    badge.textContent = matchedTitles.length + '件';
                    link.appendChild(badge);

                    // 最大5件のタイトル表示
                    var detail = document.createElement('div');
                    detail.className = 'match-titles';
                    matchedTitles.slice(0, 5).forEach(function (a) {
                        var sp = document.createElement('span');
                        sp.textContent = '[' + a.section + '] ' + a.title.slice(0, 40) + (a.title.length > 40 ? '…' : '');
                        detail.appendChild(sp);
                    });
                    link.appendChild(detail);
                }
            } else {
                li.classList.add('hidden');
            }
        });

        if (matched === 0) {
            noResult.style.display = 'block';
            statusEl.textContent = '';
        } else {
            noResult.style.display = 'none';
            statusEl.textContent = matched + ' 件のレポートがヒットしました';
        }
    }

    var timer;
    searchInput.addEventListener('input', function () {
        clearTimeout(timer);
        timer = setTimeout(function () { search(searchInput.value); }, 250);
    });
})();
</script>
</body>
</html>
"""


def _update_index_page(now: datetime) -> None:
    """docs/ 内の全レポートをリストするインデックスページを生成する。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    report_files = sorted(
        DOCS_DIR.glob("weekly-news-*.html"),
        reverse=True,
    )

    if not report_files:
        logger.info("レポートファイルが存在しないため、インデックス生成をスキップ")
        return

    items_html_parts: list[str] = []
    for f in report_files:
        date_str = f.stem.replace("weekly-news-", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = dt.strftime("%Y年%m月%d日号")
        except ValueError:
            display_date = date_str

        items_html_parts.append(
            f'        <li data-filename="{f.name}" data-date="{date_str}" data-label="{display_date}">'
            f'<a href="{f.name}">'
            f'<span class="date">{display_date}</span> — '
            f"塗装業界ウィークリーニュース</a></li>"
        )

    issue_items = "\n".join(items_html_parts)
    index_html = INDEX_TEMPLATE.replace("{issue_items}", issue_items).replace(
        "{year}", str(now.year)
    )

    index_path = DOCS_DIR / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    logger.info("インデックスページ更新: %s", index_path)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # テスト用のダミーデータ
    test_articles = [
        Article(
            title="New Paint Booth Technology",
            description="A new technology...",
            url="https://example.com/1",
            source="Coating World",
            published_at="2026-02-20T10:00:00Z",
        ),
    ]
    test_articles[0].title_ja = "新しい塗装ブース技術がエネルギー消費を30%削減"
    test_articles[0].summary_ja = (
        "大手メーカーが開発した新型スプレーブースは、"
        "エネルギーコストを大幅に削減しながら仕上がり品質を向上させます。"
        "この技術は従来のブースと比較して30%のエネルギー削減を実現し、"
        "同時にVOC排出量も低減します。"
    )
    test_articles[0].category = "equipment"

    path = generate_weekly_report(test_articles)
    print(f"Generated: {path}")
