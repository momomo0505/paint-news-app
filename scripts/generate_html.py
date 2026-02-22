"""
HTML生成モジュール — 翻訳済み記事をHTMLファイルに出力する
=========================================================

機能:
- Jinja2テンプレートを使用したHTML生成
- カテゴリ別の統計情報
- 日付フォーマットの日本語変換
- 過去のレポートへのインデックスページ生成
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from scripts.collect_news import Article
from scripts.config import DOCS_DIR, TEMPLATES_DIR
from scripts.translate_summarize import CATEGORIES

logger = logging.getLogger(__name__)

# 日本時間 (JST = UTC+9)
JST = timezone(timedelta(hours=9))


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
) -> Path:
    """
    週間レポートのHTMLファイルを生成する。

    Args:
        articles: 翻訳済みの記事リスト
        output_filename: 出力ファイル名（省略時は日付ベースで自動生成）

    Returns:
        Path: 生成したHTMLファイルのパス
    """
    now_jst = datetime.now(JST)

    if output_filename is None:
        output_filename = f"weekly-news-{now_jst.strftime('%Y-%m-%d')}.html"

    # 出力ディレクトリの確保
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DOCS_DIR / output_filename

    # Jinja2 環境セットアップ
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=True,
    )
    template = env.get_template("weekly_report.html")

    # テンプレート変数の構築
    period_end = now_jst
    period_start = period_end - timedelta(days=7)

    context = {
        "articles": _prepare_article_data(articles),
        "issue_date": now_jst.strftime("%Y年%m月%d日"),
        "period_start": period_start.strftime("%Y/%m/%d"),
        "period_end": period_end.strftime("%Y/%m/%d"),
        "year": now_jst.year,
        "category_counts": _count_categories(articles),
        "category_labels": CATEGORIES,
        "total_articles": len(articles),
    }

    # HTML レンダリング
    html_content = template.render(**context)

    # ファイル書き出し
    output_path.write_text(html_content, encoding="utf-8")
    logger.info("HTMLレポート生成: %s", output_path)

    # インデックスページも更新
    _update_index_page(now_jst)

    return output_path


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
            max-width: 600px;
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
            margin-bottom: 32px;
        }
        .issue-list {
            list-style: none;
        }
        .issue-list li {
            margin-bottom: 8px;
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
    <ul class="issue-list">
        {issue_items}
    </ul>
    <footer>
        <p>© {year} 塗装業界ニュース自動まとめツール</p>
    </footer>
</div>
</body>
</html>
"""


def _update_index_page(now: datetime) -> None:
    """docs/ 内の全レポートをリストするインデックスページを生成する。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # 既存のHTMLファイルを取得（weekly-news-*.html）
    report_files = sorted(
        DOCS_DIR.glob("weekly-news-*.html"),
        reverse=True,
    )

    if not report_files:
        logger.info("レポートファイルが存在しないため、インデックス生成をスキップ")
        return

    items_html_parts: list[str] = []
    for f in report_files:
        # ファイル名から日付を抽出: weekly-news-YYYY-MM-DD.html
        date_str = f.stem.replace("weekly-news-", "")
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            display_date = dt.strftime("%Y年%m月%d日号")
        except ValueError:
            display_date = date_str

        items_html_parts.append(
            f'        <li><a href="{f.name}">'
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
