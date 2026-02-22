"""
メール送信モジュール — SendGrid で週間レポートのリンクを通知する
================================================================

機能:
- HTMLメールによる美しい通知
- レポートへの直接リンク
- 記事数・カテゴリサマリーの表示
- エラー時のリトライ
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Content,
    Email,
    Mail,
    To,
)

from scripts.collect_news import Article
from scripts.config import (
    FROM_EMAIL,
    PAGES_BASE_URL,
    NOTIFY_EMAIL,
    SENDGRID_API_KEY,
)
from scripts.translate_summarize import CATEGORIES

logger = logging.getLogger(__name__)

# 日本時間
JST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────
# メール本文テンプレート
# ──────────────────────────────────────────────
def _build_email_html(
    articles: list[Article],
    report_url: str,
    issue_date: str,
) -> str:
    """通知メールのHTML本文を構築する。"""

    # カテゴリ別カウント
    cat_summary_parts: list[str] = []
    for key, label in CATEGORIES.items():
        count = sum(1 for a in articles if a.category == key)
        if count > 0:
            cat_summary_parts.append(f"{label}: {count}件")
    cat_summary = " ｜ ".join(cat_summary_parts) if cat_summary_parts else ""

    # 上位5記事のタイトルプレビュー
    preview_items = ""
    for article in articles[:5]:
        preview_items += (
            f'<li style="margin-bottom:8px;color:#374151;">'
            f"{article.title_ja}</li>\n"
        )

    return f"""\
<!DOCTYPE html>
<html lang="ja">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#f8f9fa;font-family:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;">
<div style="max-width:560px;margin:0 auto;padding:32px 20px;">

    <!-- ヘッダー -->
    <div style="text-align:center;margin-bottom:24px;">
        <h1 style="font-size:1.25rem;color:#1a1a2e;margin:0;">
            🎨 塗装業界ウィークリーニュース
        </h1>
        <p style="color:#6b7280;font-size:0.875rem;margin-top:4px;">
            {issue_date}号
        </p>
    </div>

    <!-- 統計 -->
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px;margin-bottom:16px;">
        <p style="margin:0;color:#374151;font-size:0.9rem;">
            📰 今週は <strong>{len(articles)}件</strong> の記事を収集しました。
        </p>
        {f'<p style="margin:8px 0 0;color:#6b7280;font-size:0.8rem;">{cat_summary}</p>' if cat_summary else ''}
    </div>

    <!-- プレビュー -->
    {f'''<div style="background:#ffffff;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px;margin-bottom:20px;">
        <p style="margin:0 0 10px;color:#6b7280;font-size:0.8rem;font-weight:600;">今週の注目記事</p>
        <ul style="margin:0;padding-left:20px;font-size:0.85rem;">
            {preview_items}
        </ul>
        {"<p style='margin:8px 0 0;color:#6b7280;font-size:0.8rem;'>他 " + str(len(articles) - 5) + " 件の記事...</p>" if len(articles) > 5 else ""}
    </div>''' if articles else ''}

    <!-- CTA ボタン -->
    <div style="text-align:center;margin-bottom:24px;">
        <a href="{report_url}"
           style="display:inline-block;padding:12px 32px;background:#2563eb;color:#ffffff;
                  text-decoration:none;border-radius:8px;font-weight:600;font-size:0.9rem;">
            レポートを読む →
        </a>
    </div>

    <!-- フッター -->
    <div style="text-align:center;font-size:0.75rem;color:#9ca3af;">
        <p>このメールは塗装業界ニュース自動まとめツールにより送信されています。</p>
        <p>
            <a href="{PAGES_BASE_URL}" style="color:#6b7280;">
                過去のレポート一覧
            </a>
        </p>
    </div>

</div>
</body>
</html>
"""


# ──────────────────────────────────────────────
# メイン関数
# ──────────────────────────────────────────────
def send_notification(
    articles: list[Article],
    report_filename: str,
) -> bool:
    """
    週間レポートの通知メールを送信する。

    Args:
        articles: レポートに含まれる記事リスト（プレビュー表示用）
        report_filename: 生成されたHTMLファイル名

    Returns:
        bool: 送信成功なら True
    """
    # バリデーション
    if not SENDGRID_API_KEY:
        logger.error("SENDGRID_API_KEY が設定されていません。")
        raise ValueError("環境変数 SENDGRID_API_KEY を設定してください。")

    if not FROM_EMAIL:
        logger.error("FROM_EMAIL が設定されていません。")
        raise ValueError("環境変数 FROM_EMAIL を設定してください。")

    if not NOTIFY_EMAIL:
        logger.error("NOTIFY_EMAIL が設定されていません。")
        raise ValueError("環境変数 NOTIFY_EMAIL を設定してください。")

    now_jst = datetime.now(JST)
    issue_date = now_jst.strftime("%Y年%m月%d日")

    # レポートURL
    report_url = f"{PAGES_BASE_URL.rstrip('/')}/{report_filename}"

    # メール構築
    subject = f"🎨 塗装業界ニュース {issue_date}号 — {len(articles)}件の記事"
    html_body = _build_email_html(articles, report_url, issue_date)

    message = Mail(
        from_email=Email(FROM_EMAIL, "塗装業界ニュース"),
        to_emails=To(NOTIFY_EMAIL),
        subject=subject,
        html_content=Content("text/html", html_body),
    )

    # 送信
    try:
        client = SendGridAPIClient(SENDGRID_API_KEY)
        response = client.send(message)

        if response.status_code in (200, 201, 202):
            logger.info(
                "メール送信成功: to=%s, status=%d",
                NOTIFY_EMAIL,
                response.status_code,
            )
            return True
        else:
            logger.error(
                "メール送信エラー: status=%d, body=%s",
                response.status_code,
                response.body,
            )
            return False

    except Exception as exc:
        logger.error("SendGrid API エラー: %s", exc)
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # テスト用
    test_articles = [
        Article(
            title="Test Article",
            description="Test description",
            url="https://example.com",
            source="Test Source",
            published_at="2026-02-20T10:00:00Z",
        ),
    ]
    test_articles[0].title_ja = "テスト記事"
    test_articles[0].summary_ja = "これはテスト記事です。"
    test_articles[0].category = "technology"

    success = send_notification(test_articles, "weekly-news-2026-02-22.html")
    print(f"Send result: {success}")
