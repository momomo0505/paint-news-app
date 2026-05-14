"""
メール送信モジュール — Gmail SMTP で週間レポートのリンクを通知する
================================================================

機能:
- HTMLメールによる美しい通知
- レポートへの直接リンク
- 記事数・カテゴリサマリーの表示
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


# ──────────────────────────────────────────────
# メール本文テンプレート
# ──────────────────────────────────────────────
def _build_email_html(
    articles: list[Article],
    report_url: str,
    issue_date: str,
) -> str:
    """通知メールのHTML本文を構築する。"""

    cat_summary_parts: list[str] = []
    for key, label in CATEGORIES.items():
        count = sum(1 for a in articles if a.category == key)
        if count > 0:
            cat_summary_parts.append(f"{label}: {count}件")
    cat_summary = " ｜ ".join(cat_summary_parts) if cat_summary_parts else ""

    preview_items = ""
    for article in articles[:5]:
        preview_items += (
            f'<li style="margin-bottom:6px;">'
            f'<a href="{article.url}" style="color:#2563eb;text-decoration:none;">'
            f"{article.title_ja}</a></li>\n"
        )

    return f"""\
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;">
  <div style="max-width:600px;margin:40px auto;padding:0 16px;">

    <div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:32px;">
      <p style="margin:0 0 4px;font-size:0.85rem;color:#6b7280;">塗装業界ウィークリーニュース</p>
      <h1 style="margin:0 0 20px;font-size:1.4rem;font-weight:700;color:#1a1a2e;">
        🎨 {issue_date}号
      </h1>

      <p style="margin:0 0 8px;color:#374151;">
        今週は <strong>{len(articles)}件</strong> の記事を収集しました。
      </p>
      {f'<p style="margin:0 0 20px;font-size:0.85rem;color:#6b7280;">{cat_summary}</p>' if cat_summary else ''}

      {f"""
      <div style="background:#f9fafb;border-radius:6px;padding:16px 20px;margin-bottom:24px;">
        <p style="margin:0 0 10px;font-weight:600;color:#1a1a2e;">今週の注目記事</p>
        <ul style="margin:0;padding-left:18px;color:#374151;font-size:0.9rem;">
          {preview_items}
        </ul>
        {f'<p style="margin:10px 0 0;font-size:0.8rem;color:#6b7280;">他 {len(articles)-5} 件の記事...</p>' if len(articles) > 5 else ''}
      </div>
      """ if articles else ''}

      <div style="text-align:center;">
        <a href="{report_url}"
           style="display:inline-block;padding:12px 28px;background:#2563eb;color:#fff;
                  border-radius:6px;text-decoration:none;font-weight:600;font-size:0.95rem;">
          レポートを読む →
        </a>
      </div>
    </div>

    <p style="text-align:center;margin-top:20px;font-size:0.75rem;color:#9ca3af;">
      このメールは塗装業界ニュース自動まとめツールにより送信されています。<br>
      <a href="{PAGES_BASE_URL}" style="color:#9ca3af;">過去のレポート一覧</a>
    </p>
  </div>
</body>
</html>"""


# ──────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────
def send_notification(
    articles: list[Article],
    report_filename: str,
) -> bool:
    """
    週間レポートの通知メールを Gmail SMTP で送信する。

    Args:
        articles: レポートに含まれる記事リスト
        report_filename: 生成されたHTMLファイル名

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
    subject = f"🎨 塗装業界ニュース {issue_date}号 — {len(articles)}件の記事"
    html_body = _build_email_html(articles, report_url, issue_date)

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
            title="Test Article",
            description="Test description",
            url="https://example.com",
            source="Test Source",
            published_at="2026-05-14T08:00:00Z",
        )
    ]
    test_articles[0].title_ja = "テスト記事"
    test_articles[0].summary_ja = "これはテスト記事です。"
    test_articles[0].category = "technology"

    success = send_notification(test_articles, "weekly-news-2026-05-14.html")
    print(f"Send result: {success}")
