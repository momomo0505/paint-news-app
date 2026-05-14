"""
メール送信モジュール — Gmail SMTP で週間レポートのリンクを通知する
================================================================

機能:
- 3セクション構成（競合ニュース / 国内ニュース / 海外ニュース）
- 海外リンクは Google 翻訳経由に自動変換
- Gmail SMTP (smtplib) を使用（外部サービス不要）
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from scripts.collect_news import Article
from scripts.config import (
    FROM_EMAIL,
    GMAIL_APP_PASSWORD,
    NOTIFY_EMAIL,
    PAGES_BASE_URL,
)
from scripts.translate_summarize import CATEGORIES

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587


def _google_translate_url(url: str) -> str:
    """英語URLをGoogle翻訳経由URLに変換する。"""
    return f"https://translate.google.com/translate?sl=en&tl=ja&u={url}"


# ──────────────────────────────────────────────
# セクション別HTML生成ヘルパー
# ──────────────────────────────────────────────
def _build_competitor_section(competitor_items: list[dict]) -> str:
    if not competitor_items:
        return ""

    rows = ""
    for item in competitor_items[:10]:
        date_str = item["date"].strftime("%m/%d") if hasattr(item["date"], "strftime") else str(item["date"])[:10]
        url = item.get("url", "#")
        title = item.get("title", "（タイトルなし）")
        company = item.get("company", "")
        rows += (
            '<li style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f3f4f6;">'
            '<span style="font-size:0.75rem;color:#9ca3af;margin-right:6px;">' + date_str + "</span>"
            '<span style="font-size:0.8rem;background:#fef3c7;color:#92400e;padding:1px 6px;border-radius:3px;margin-right:6px;">' + company + "</span>"
            '<a href="' + url + '" style="color:#1d4ed8;text-decoration:none;font-size:0.9rem;">' + title[:70] + "</a>"
            "</li>\n"
        )

    more_html = ""
    if len(competitor_items) > 10:
        more_html = '<p style="margin:8px 0 0;font-size:0.8rem;color:#6b7280;">他 ' + str(len(competitor_items) - 10) + " 件...</p>"

    return (
        '<div style="margin-bottom:28px;">'
        '<h2 style="margin:0 0 12px;font-size:1rem;font-weight:700;color:#1a1a2e;'
        'border-left:4px solid #dc2626;padding-left:10px;">'
        "1. 競合他社・関連メーカー動向</h2>"
        '<ul style="margin:0;padding:0;list-style:none;">' + rows + "</ul>"
        + more_html
        + "</div>"
    )


def _build_domestic_section(domestic_articles: list[Article]) -> str:
    if not domestic_articles:
        return ""

    rows = ""
    for article in domestic_articles[:8]:
        url = article.url
        title = article.title_ja or article.title
        rows += (
            '<li style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f3f4f6;">'
            '<a href="' + url + '" style="color:#1d4ed8;text-decoration:none;font-size:0.9rem;">' + title[:80] + "</a>"
            "</li>\n"
        )

    more_html = ""
    if len(domestic_articles) > 8:
        more_html = '<p style="margin:8px 0 0;font-size:0.8rem;color:#6b7280;">他 ' + str(len(domestic_articles) - 8) + " 件...</p>"

    return (
        '<div style="margin-bottom:28px;">'
        '<h2 style="margin:0 0 12px;font-size:1rem;font-weight:700;color:#1a1a2e;'
        'border-left:4px solid #16a34a;padding-left:10px;">'
        "2. 国内塗装業界ニュース</h2>"
        '<ul style="margin:0;padding:0;list-style:none;">' + rows + "</ul>"
        + more_html
        + "</div>"
    )


def _build_overseas_section(articles: list[Article]) -> str:
    if not articles:
        return ""

    rows = ""
    for article in articles[:8]:
        translated_url = _google_translate_url(article.url)
        title = article.title_ja or article.title
        rows += (
            '<li style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f3f4f6;">'
            '<a href="' + translated_url + '" style="color:#1d4ed8;text-decoration:none;font-size:0.9rem;">' + title[:80] + "</a>"
            '<span style="font-size:0.75rem;color:#9ca3af;margin-left:6px;">[翻訳表示]</span>'
            "</li>\n"
        )

    more_html = ""
    if len(articles) > 8:
        more_html = '<p style="margin:8px 0 0;font-size:0.8rem;color:#6b7280;">他 ' + str(len(articles) - 8) + " 件...</p>"

    return (
        '<div style="margin-bottom:28px;">'
        '<h2 style="margin:0 0 12px;font-size:1rem;font-weight:700;color:#1a1a2e;'
        'border-left:4px solid #7c3aed;padding-left:10px;">'
        "3. 海外塗装業界ニュース</h2>"
        '<ul style="margin:0;padding:0;list-style:none;">' + rows + "</ul>"
        + more_html
        + "</div>"
    )


# ──────────────────────────────────────────────
# メール本文テンプレート
# ──────────────────────────────────────────────
def _build_email_html(
    articles: list[Article],
    report_url: str,
    issue_date: str,
    competitor_items: list[dict] | None = None,
    domestic_articles: list[Article] | None = None,
) -> str:
    """通知メールのHTML本文を構築する（3セクション構成）。"""

    total = len(articles) + len(domestic_articles or []) + len(competitor_items or [])
    summary_text = (
        "競合: " + str(len(competitor_items or [])) + "件 ｜ "
        "国内: " + str(len(domestic_articles or [])) + "件 ｜ "
        "海外: " + str(len(articles)) + "件"
    )

    competitor_html = _build_competitor_section(competitor_items or [])
    domestic_html = _build_domestic_section(domestic_articles or [])
    overseas_html = _build_overseas_section(articles)

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n'
        '<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>\n'
        '<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,\'Hiragino Sans\',\'Noto Sans JP\',sans-serif;">\n'
        '  <div style="max-width:620px;margin:40px auto;padding:0 16px;">\n'
        '    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:32px;">\n'
        '      <p style="margin:0 0 4px;font-size:0.85rem;color:#6b7280;">塗装業界ニュースレポート</p>\n'
        '      <h1 style="margin:0 0 6px;font-size:1.4rem;font-weight:700;color:#1a1a2e;">'
        "🎨 " + issue_date + "号</h1>\n"
        '      <p style="margin:0 0 24px;font-size:0.85rem;color:#6b7280;">' + summary_text + "</p>\n"
        + competitor_html
        + domestic_html
        + overseas_html
        + '      <div style="text-align:center;margin-top:8px;">'
        '<a href="' + report_url + '" '
        'style="display:inline-block;padding:12px 28px;background:#2563eb;color:#fff;'
        'border-radius:6px;text-decoration:none;font-weight:600;font-size:0.95rem;">'
        "フルレポートを読む →</a></div>\n"
        "    </div>\n"
        '    <p style="text-align:center;margin-top:20px;font-size:0.75rem;color:#9ca3af;">'
        "このメールは塗装業界ニュース自動まとめツールにより送信されています。<br>"
        '<a href="' + PAGES_BASE_URL + '" style="color:#9ca3af;">過去のレポート一覧</a></p>\n'
        "  </div>\n"
        "</body>\n"
        "</html>"
    )


# ──────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────
def send_notification(
    articles: list[Article],
    report_filename: str,
    *,
    competitor_items: list[dict] | None = None,
    domestic_articles: list[Article] | None = None,
) -> bool:
    """
    週間レポートの通知メールを Gmail SMTP で送信する。

    Args:
        articles: 海外ニュース記事リスト（翻訳済み）
        report_filename: 生成されたHTMLファイル名
        competitor_items: 競合他社ニュース項目リスト
        domestic_articles: 国内ニュース記事リスト

    Returns:
        bool: 送信成功なら True
    """
    if not FROM_EMAIL:
        raise ValueError("環境変数 FROM_EMAIL を設定してください。")
    if not NOTIFY_EMAIL:
        raise ValueError("環境変数 NOTIFY_EMAIL を設定してください。")
    if not GMAIL_APP_PASSWORD:
        raise ValueError("環境変数 GMAIL_APP_PASSWORD を設定してください。")

    now_jst = datetime.now(JST)
    issue_date = now_jst.strftime("%Y年%m月%d日")
    report_url = f"{PAGES_BASE_URL.rstrip('/')}/{report_filename}"

    total_count = len(articles) + len(domestic_articles or []) + len(competitor_items or [])
    subject = f"🎨 塗装業界ニュース {issue_date}号 — {total_count}件"

    html_body = _build_email_html(
        articles,
        report_url,
        issue_date,
        competitor_items=competitor_items,
        domestic_articles=domestic_articles,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"塗装業界ニュース <{FROM_EMAIL}>"
    msg["To"] = NOTIFY_EMAIL
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(GMAIL_SMTP_HOST, GMAIL_SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(FROM_EMAIL, GMAIL_APP_PASSWORD)
            smtp.sendmail(FROM_EMAIL, NOTIFY_EMAIL, msg.as_string())

        logger.info("メール送信成功: to=%s", NOTIFY_EMAIL)
        return True

    except smtplib.SMTPAuthenticationError as exc:
        logger.error("Gmail認証エラー: %s", exc)
        raise
    except smtplib.SMTPException as exc:
        logger.error("SMTP送信エラー: %s", exc)
        raise
    except Exception as exc:
        logger.error("メール送信エラー: %s", exc)
        raise


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s: %(message)s")

    test_articles = [
        Article(
            title="New Paint Booth Technology Reduces Energy Costs",
            description="Test description",
            url="https://example.com/news/1",
            source="Coating World",
            published_at="2026-05-14T08:00:00Z",
        )
    ]
    test_articles[0].title_ja = "新型塗装ブースがエネルギーコストを削減"
    test_articles[0].summary_ja = "これはテスト記事です。"
    test_articles[0].category = "equipment"

    from datetime import datetime, timezone, timedelta
    _JST = timezone(timedelta(hours=9))
    test_competitor = [
        {
            "company": "大気社",
            "date": datetime(2026, 5, 14, tzinfo=_JST),
            "title": "大気社ニュースレター ISSUES #12 を公開しました",
            "url": "https://www.taikisha.co.jp/news/",
            "language": "ja",
        }
    ]

    success = send_notification(
        test_articles,
        "weekly-news-2026-05-14.html",
        competitor_items=test_competitor,
        domestic_articles=[],
    )
    print(f"Send result: {success}")
