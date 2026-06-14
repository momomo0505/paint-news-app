"""
メール送信モジュール — SMTP で週間レポートのリンクを通知する
================================================================

機能:
- 3セクション構成（競合ニュース / 国内ニュース / 海外ニュース）
- 海外リンクは Google 翻訳経由に自動変換
- 任意の SMTP サーバーに対応（社内メールサーバー・Gmail 等）
  - ポート 465: SSL 接続
  - ポート 587 / その他: STARTTLS 接続
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
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASSWORD,
    NOTIFY_EMAILS,
    PAGES_BASE_URL,
)
from scripts.translate_summarize import CATEGORIES

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))


def _google_translate_url(url: str) -> str:
    """英語URLをGoogle翻訳経由URLに変換する。"""
    return f"https://translate.google.com/translate?sl=en&tl=ja&u={url}"


# ──────────────────────────────────────────────
# セクション別HTML生成ヘルパー
# ──────────────────────────────────────────────
def _build_self_mention_section(self_mention_articles: list[Article]) -> str:
    if not self_mention_articles:
        return ""

    rows = ""
    for article in self_mention_articles:
        url = article.url
        title = article.title_ja or article.title
        summary = article.summary_ja or article.description[:100] or ""
        rows += (
            '<li style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #fde68a;">'
            '<p style="margin:0 0 4px;font-size:0.9rem;color:#1a1a2e;font-weight:600;">' + title[:100] + "</p>"
            + (
                '<p style="margin:0 0 6px;font-size:0.85rem;color:#4b5563;line-height:1.5;">' + summary[:200] + "</p>"
                if summary else ""
            )
            + '<a href="' + url + '" style="font-size:0.8rem;color:#d97706;text-decoration:none;font-weight:600;">記事を読む →</a>'
            "</li>\n"
        )

    return (
        '<div style="margin-bottom:28px;background:#fffbeb;border:1px solid #fde68a;'
        'border-left:4px solid #f59e0b;border-radius:8px;padding:16px 20px;">'
        '<h2 style="margin:0 0 6px;font-size:1rem;font-weight:700;color:#92400e;">'
        "★ 弊社（アンデックス㈱）関連記事</h2>"
        '<p style="margin:0 0 12px;font-size:0.8rem;color:#b45309;">'
        "弊社が取材・掲載された記事が見つかりました。社内への共有をご検討ください。</p>"
        '<ul style="margin:0;padding:0;list-style:none;">' + rows + "</ul>"
        "</div>"
    )


def _build_competitor_section(competitor_items: list[dict]) -> str:
    if not competitor_items:
        return ""

    rows = ""
    for item in competitor_items[:10]:
        date_str = item["date"].strftime("%m/%d") if hasattr(item["date"], "strftime") else str(item["date"])[:10]
        url = item.get("url", "#")
        title = item.get("title", "（タイトルなし）")
        company = item.get("company", "")
        read_label = "翻訳して読む →" if item.get("language") == "en" else "詳細を読む →"
        rows += (
            '<li style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #f3f4f6;">'
            '<div style="margin-bottom:4px;">'
            '<span style="font-size:0.75rem;color:#9ca3af;margin-right:6px;">' + date_str + "</span>"
            '<span style="font-size:0.8rem;background:#fef3c7;color:#92400e;padding:1px 6px;border-radius:3px;">' + company + "</span>"
            "</div>"
            '<p style="margin:0 0 4px;font-size:0.9rem;color:#1a1a2e;font-weight:500;">' + title[:80] + "</p>"
            '<a href="' + url + '" style="font-size:0.8rem;color:#2563eb;text-decoration:none;">' + read_label + "</a>"
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
        summary = article.summary_ja or article.description[:100] or ""
        rows += (
            '<li style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #f3f4f6;">'
            '<p style="margin:0 0 4px;font-size:0.9rem;color:#1a1a2e;font-weight:500;">' + title[:80] + "</p>"
            + (
                '<p style="margin:0 0 6px;font-size:0.85rem;color:#4b5563;line-height:1.5;">' + summary[:150] + "</p>"
                if summary else ""
            )
            + '<a href="' + url + '" style="font-size:0.8rem;color:#2563eb;text-decoration:none;">記事を読む →</a>'
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
        summary = article.summary_ja or ""
        rows += (
            '<li style="margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #f3f4f6;">'
            '<p style="margin:0 0 4px;font-size:0.9rem;color:#1a1a2e;font-weight:500;">' + title[:80] + "</p>"
            + (
                '<p style="margin:0 0 6px;font-size:0.85rem;color:#4b5563;line-height:1.5;">' + summary[:150] + "</p>"
                if summary else ""
            )
            + '<a href="' + translated_url + '" style="font-size:0.8rem;color:#2563eb;text-decoration:none;">翻訳して読む →</a>'
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
    self_mention_articles: list[Article] | None = None,
    weekly_digest: str = "",
) -> str:
    """通知メールのHTML本文を構築する（自社記事 + 3セクション構成）。"""

    summary_text = (
        "競合: " + str(len(competitor_items or [])) + "件 ｜ "
        "国内: " + str(len(domestic_articles or [])) + "件 ｜ "
        "海外: " + str(len(articles)) + "件"
    )

    # 週次総括ブロック
    digest_html = ""
    if weekly_digest:
        lines = [l for l in weekly_digest.splitlines() if l.strip()]
        rows = "".join(
            '<li style="font-size:0.875rem;color:#1e3a5f;line-height:1.7;padding:4px 0;'
            'border-bottom:1px solid #e0f2fe;">' + line + "</li>\n"
            for line in lines
        )
        digest_html = (
            '<div style="margin-bottom:24px;background:#f0f9ff;border:1px solid #bae6fd;'
            'border-left:4px solid #0284c7;border-radius:8px;padding:16px 20px;">'
            '<h3 style="margin:0 0 10px;font-size:0.95rem;font-weight:700;color:#0c4a6e;">'
            "🧠 今週のポイント</h3>"
            '<ul style="margin:0;padding:0;list-style:none;">' + rows + "</ul>"
            "</div>"
        )

    self_mention_html = _build_self_mention_section(self_mention_articles or [])
    competitor_html = _build_competitor_section(competitor_items or [])
    domestic_html = _build_domestic_section(domestic_articles or [])
    overseas_html = _build_overseas_section(articles)

    self_mention_badge = ""
    if self_mention_articles:
        self_mention_badge = (
            '<span style="display:inline-block;margin-left:8px;padding:2px 8px;'
            'background:#f59e0b;color:#fff;border-radius:12px;font-size:0.75rem;font-weight:700;">'
            "★ 弊社掲載あり</span>"
        )

    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n'
        '<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>\n'
        '<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,\'Hiragino Sans\',\'Noto Sans JP\',sans-serif;">\n'
        '  <div style="max-width:620px;margin:40px auto;padding:0 16px;">\n'
        '    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:32px;">\n'
        '      <p style="margin:0 0 4px;font-size:0.85rem;color:#6b7280;">塗装業界ニュースレポート</p>\n'
        '      <h1 style="margin:0 0 6px;font-size:1.4rem;font-weight:700;color:#1a1a2e;">'
        "🎨 " + issue_date + "号" + self_mention_badge + "</h1>\n"
        '      <p style="margin:0 0 16px;font-size:0.85rem;color:#6b7280;">' + summary_text + "</p>\n"
        '      <div style="text-align:center;margin-bottom:28px;">'
        '<a href="' + report_url + '" '
        'style="display:inline-block;padding:12px 28px;background:#2563eb;color:#ffffff !important;'
        'border-radius:6px;text-decoration:none;font-weight:600;font-size:0.95rem;">'
        "フルレポートを読む →</a></div>\n"
        + digest_html
        + self_mention_html
        + competitor_html
        + domestic_html
        + overseas_html
        +         '      <div style="text-align:center;margin-top:8px;">'
        '<a href="' + report_url + '" '
        'style="display:inline-block;padding:12px 28px;background:#2563eb;color:#ffffff !important;'
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
    self_mention_articles: list[Article] | None = None,
    weekly_digest: str = "",
    no_articles: bool = False,
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
    if not NOTIFY_EMAILS:
        raise ValueError("環境変数 NOTIFY_EMAIL を設定してください。")
    if not SMTP_PASSWORD:
        raise ValueError("環境変数 SMTP_PASSWORD（または GMAIL_APP_PASSWORD）を設定してください。")

    now_jst = datetime.now(JST)
    issue_date = now_jst.strftime("%Y年%m月%d日")
    report_url = f"{PAGES_BASE_URL.rstrip('/')}/{report_filename}"
    recipients = NOTIFY_EMAILS

    total_count = len(articles) + len(domestic_articles or []) + len(competitor_items or [])

    if no_articles or total_count == 0:
        subject = f"🎨 塗装業界ニュース {issue_date}号 — 本日の取得件数: 0件"
        html_body = (
            "<!DOCTYPE html><html lang='ja'><head><meta charset='UTF-8'></head>"
            "<body style='font-family:sans-serif;padding:32px;'>"
            "<h2>🎨 塗装業界ニュース — " + issue_date + "号</h2>"
            "<p>本日は各ソース（競合サイト・国内RSS・NewsAPI）からの記事取得件数が 0件 でした。</p>"
            "<ul>"
            "<li>Google News RSSが一時的に結果を返さなかった可能性があります。</li>"
            "<li>明日以降は通常通り配信される見込みです。</li>"
            "</ul>"
            "<p style='color:#6b7280;font-size:0.85rem;'>このメールは自動送信です。スケジュール実行確認用です。</p>"
            "</body></html>"
        )
    else:
        subject = f"🎨 塗装業界ニュース {issue_date}号 — {total_count}件"
        html_body = _build_email_html(
            articles,
            report_url,
            issue_date,
            competitor_items=competitor_items,
            domestic_articles=domestic_articles,
            self_mention_articles=self_mention_articles,
            weekly_digest=weekly_digest,
        )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"塗装業界ニュース <{FROM_EMAIL}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        # ポート 465 は SSL、それ以外は STARTTLS で接続
        if SMTP_PORT == 465:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(FROM_EMAIL, recipients, msg.as_string())
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.ehlo()
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(FROM_EMAIL, recipients, msg.as_string())

        logger.info("メール送信成功: host=%s, to=%s", SMTP_HOST, ", ".join(recipients))
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
