"""
メインスクリプト — 塗装業界ニュース自動まとめツール
=====================================================

全モジュールを統合して以下のパイプラインを実行する:
1. 競合他社ニュース監視 (Webスクレイピング)
2. 国内ニュース収集 (NewsAPI 日本語)
3. 海外ニュース収集 (NewsAPI 英語)
4. 翻訳・要約 (Claude API)
5. HTML生成
6. メール通知 (Gmail SMTP)

使い方:
    python -m scripts.main              # 全パイプライン実行
    python -m scripts.main --no-email   # メール送信なしで実行
    python -m scripts.main --dry-run    # 実際のAPI呼び出しなしでテスト
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.check_competitors import check_all_competitors
from scripts.collect_news import Article, collect_domestic_news, collect_news, collect_self_mention_news
from scripts.config import DOCS_DIR, LOG_LEVEL
from scripts.generate_html import generate_weekly_report
from scripts.send_email import send_notification
from scripts.translate_summarize import (
    deduplicate_articles,
    filter_relevant_articles,
    summarize_domestic_articles,
    translate_and_summarize,
)

# 日本時間
JST = timezone(timedelta(hours=9))

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# ロギング設定
# ──────────────────────────────────────────────
def _setup_logging(level: str = LOG_LEVEL) -> None:
    """ロギングを設定する。"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


# ──────────────────────────────────────────────
# ドライラン用のダミーデータ
# ──────────────────────────────────────────────
def _create_dummy_articles() -> list[Article]:
    """ドライラン用のサンプル記事を生成する。"""
    samples = [
        {
            "title": "Revolutionary Paint Booth Design Cuts Energy Use by 40%",
            "description": "A new booth design uses advanced airflow patterns to significantly reduce energy consumption while maintaining superior finish quality.",
            "url": "https://example.com/news/1",
            "source": "Coating World",
            "published_at": "2026-02-20T10:00:00Z",
            "title_ja": "革新的な塗装ブース設計がエネルギー使用量を40%削減",
            "summary_ja": "新型ブース設計は先進的な気流パターンを活用し、優れた仕上がり品質を維持しながらエネルギー消費を大幅に削減します。従来の設計と比較して40%の省エネを達成し、塗装業界の持続可能性向上に貢献することが期待されています。自動車製造業を中心に、幅広い産業での採用が見込まれます。",
            "category": "equipment",
        },
        {
            "title": "Global Automotive Coatings Market Expected to Reach $12B by 2030",
            "description": "New market research report highlights strong growth in automotive OEM coatings driven by EV production and sustainability requirements.",
            "url": "https://example.com/news/2",
            "source": "Paint & Coatings Industry",
            "published_at": "2026-02-19T14:30:00Z",
            "title_ja": "世界の自動車用塗料市場が2030年までに120億ドルに到達する見込み",
            "summary_ja": "最新の市場調査レポートによると、自動車OEM用塗料市場はEV生産の拡大と持続可能性要件の強化により力強い成長が見込まれています。水性塗料やパウダーコーティングの需要が特に増加しており、アジア太平洋地域が最大の成長市場となっています。主要メーカーは低VOC製品の開発を加速しています。",
            "category": "market",
        },
        {
            "title": "New EU VOC Regulations to Impact Industrial Coating Operations",
            "description": "European Union announces stricter VOC emission limits for industrial painting facilities, effective 2027.",
            "url": "https://example.com/news/3",
            "source": "European Coatings Journal",
            "published_at": "2026-02-18T09:15:00Z",
            "title_ja": "EU新VOC規制が産業用塗装作業に影響を与える見通し",
            "summary_ja": "欧州連合は産業用塗装施設に対するVOC排出制限を厳格化する新規制を発表しました。2027年から施行予定のこの規制は、現行基準から排出量を25%削減することを求めています。塗装設備メーカーや塗料メーカーは対応技術の開発を急いでおり、日本の塗装業界にも波及する可能性があります。",
            "category": "regulation",
        },
    ]

    articles: list[Article] = []
    for s in samples:
        a = Article(
            title=s["title"],
            description=s["description"],
            url=s["url"],
            source=s["source"],
            published_at=s["published_at"],
        )
        a.title_ja = s["title_ja"]
        a.summary_ja = s["summary_ja"]
        a.category = s["category"]
        articles.append(a)

    return articles


# ──────────────────────────────────────────────
# 結果の保存（デバッグ用）
# ──────────────────────────────────────────────
def _save_articles_json(articles: list[Article]) -> None:
    """翻訳済み記事をJSONファイルに保存する（デバッグ・ログ用）。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    now_jst = datetime.now(JST)
    json_path = DOCS_DIR / f"articles-{now_jst.strftime('%Y-%m-%d')}.json"

    data = [a.to_dict() for a in articles]
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("記事データ保存: %s", json_path)


# ──────────────────────────────────────────────
# メインパイプライン
# ──────────────────────────────────────────────
def run_pipeline(
    *,
    send_email: bool = True,
    dry_run: bool = False,
    save_json: bool = True,
) -> None:
    """
    競合監視→国内ニュース→海外ニュース→翻訳→HTML生成→メール送信のパイプラインを実行する。

    Args:
        send_email: メール送信を行うか
        dry_run: ドライラン（API呼び出しなし、ダミーデータ使用）
        save_json: 記事データをJSONに保存するか
    """
    now_jst = datetime.now(JST)
    logger.info("=" * 60)
    logger.info("塗装業界ニュース自動まとめツール 実行開始")
    logger.info("実行日時: %s (JST)", now_jst.strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("モード: %s", "ドライラン" if dry_run else "本番")
    logger.info("=" * 60)

    # ────────────────────────────────────────
    # Step 1: 競合他社ニュース監視
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 1/6: 競合他社ニュース監視 ━━━")

    if dry_run:
        competitor_items = []
        logger.info("ドライラン: 競合監視スキップ")
    else:
        try:
            competitor_items = check_all_competitors()
            logger.info("競合監視完了: %d 件", len(competitor_items))
        except Exception as exc:
            logger.error("競合監視エラー: %s", exc)
            competitor_items = []

    # ────────────────────────────────────────
    # Step 1.5: 自社メンション検知
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 1.5/6: 自社メンション検知（アンデックス㈱）━━━")

    if dry_run:
        self_mention_articles: list[Article] = []
        logger.info("ドライラン: 自社メンション検知スキップ")
    else:
        try:
            self_mention_articles = collect_self_mention_news()
            if self_mention_articles:
                logger.info("自社関連記事 発見: %d 件 ★", len(self_mention_articles))
            else:
                logger.info("自社関連記事: 今週は掲載なし")
        except Exception as exc:
            logger.error("自社メンション検知エラー: %s", exc)
            self_mention_articles = []

    # ────────────────────────────────────────
    # Step 2: 国内ニュース収集 → フィルタ → 要約
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 2/6: 国内ニュース収集 ━━━")

    if dry_run:
        domestic_articles: list[Article] = []
        logger.info("ドライラン: 国内ニュース収集スキップ")
    else:
        try:
            domestic_articles = collect_domestic_news()
            logger.info("国内ニュース収集完了: %d 件", len(domestic_articles))

            if domestic_articles:
                # skip_filter=True の記事（指定メディア・業界専門サイト）はフィルタをバイパス
                trusted = [a for a in domestic_articles if a.skip_filter]
                to_filter = [a for a in domestic_articles if not a.skip_filter]
                logger.info(
                    "フィルタ対象: %d件 / バイパス（指定メディア）: %d件",
                    len(to_filter),
                    len(trusted),
                )

                if to_filter:
                    logger.info("国内ニュース関連性フィルタ実行中（%d件）...", len(to_filter))
                    to_filter = filter_relevant_articles(to_filter, language="ja")
                    logger.info("フィルタ後: %d件", len(to_filter))

                domestic_articles = trusted + to_filter

            if domestic_articles:
                logger.info("国内ニュース重複除去中（%d件）...", len(domestic_articles))
                domestic_articles = deduplicate_articles(domestic_articles, language="ja")
                logger.info("重複除去後: %d件", len(domestic_articles))

            if domestic_articles:
                logger.info("国内ニュース一括要約中...")
                domestic_articles = summarize_domestic_articles(domestic_articles)
                logger.info("国内ニュース要約完了: %d件", len(domestic_articles))

        except Exception as exc:
            logger.error("国内ニュース収集エラー: %s", exc)
            domestic_articles = []

    # ────────────────────────────────────────
    # Step 3: 海外ニュース収集
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 3/6: 海外ニュース収集 ━━━")

    if dry_run:
        logger.info("ドライラン: ダミーデータを使用します")
        overseas_articles = _create_dummy_articles()
    else:
        try:
            overseas_articles = collect_news()
            logger.info("海外ニュース収集完了: %d 件", len(overseas_articles))
        except Exception as exc:
            logger.error("海外ニュース収集エラー: %s", exc)
            overseas_articles = []

    total_found = len(competitor_items) + len(domestic_articles) + len(overseas_articles)
    logger.info("収集合計: 競合=%d 国内=%d 海外=%d", len(competitor_items), len(domestic_articles), len(overseas_articles))

    if total_found == 0:
        logger.warning("全カテゴリでニュースが見つかりませんでした。「記事なし」通知メールを送信します。")
        # 記事0件でもメール送信（cron実行の確認のため）
        if send_email and not dry_run:
            try:
                send_notification([], f"no-news-{now_jst.strftime('%Y-%m-%d')}.html",
                                  competitor_items=[], domestic_articles=[], no_articles=True)
            except Exception as exc:
                logger.error("通知メール送信エラー: %s", exc)
        return

    # ────────────────────────────────────────
    # Step 4: 関連性フィルタ → 翻訳・要約（海外ニュースのみ）
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 4/6: 関連性フィルタ → 翻訳・要約 ━━━")

    if dry_run:
        logger.info("ドライラン: 翻訳済みダミーデータを使用します")
    else:
        if overseas_articles:
            logger.info("関連性フィルタ実行中（%d件）...", len(overseas_articles))
            overseas_articles = filter_relevant_articles(overseas_articles)
            logger.info("フィルタ後: %d件", len(overseas_articles))

        if overseas_articles:
            logger.info("海外ニュース重複除去中（%d件）...", len(overseas_articles))
            overseas_articles = deduplicate_articles(overseas_articles, language="en")
            logger.info("重複除去後: %d件 → 翻訳・要約開始", len(overseas_articles))
            overseas_articles = translate_and_summarize(overseas_articles)
        logger.info("翻訳完了: %d 件", len(overseas_articles))

    # ────────────────────────────────────────
    # Step 5: HTML生成
    # ────────────────────────────────────────
    logger.info("")
    logger.info("━━━ Step 5/6: HTML生成・メール送信 ━━━")

    report_path = generate_weekly_report(
        overseas_articles,
        competitor_items=competitor_items,
        domestic_articles=domestic_articles,
        self_mention_articles=self_mention_articles,
    )
    report_filename = report_path.name
    logger.info("HTML生成完了: %s", report_path)

    if save_json:
        _save_articles_json(overseas_articles)

    # ────────────────────────────────────────
    # Step 6: メール送信
    # ────────────────────────────────────────
    if not send_email:
        logger.info("メール送信はスキップされました (--no-email)")
    elif dry_run:
        logger.info("ドライラン: メール送信をスキップします")
    else:
        try:
            success = send_notification(
                overseas_articles,
                report_filename,
                competitor_items=competitor_items,
                domestic_articles=domestic_articles,
                self_mention_articles=self_mention_articles,
            )
            if success:
                logger.info("メール送信完了")
            else:
                logger.error("メール送信に失敗しました")
        except Exception as exc:
            logger.error("メール送信エラー: %s", exc)

    logger.info("")
    logger.info("=" * 60)
    logger.info("パイプライン完了")
    logger.info("レポートファイル: %s", report_path)
    logger.info("=" * 60)


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main() -> None:
    """コマンドラインインターフェース。"""
    parser = argparse.ArgumentParser(
        description="塗装業界ニュース自動まとめツール",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="メール送信をスキップする",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="ドライラン（API呼び出しなし、ダミーデータ使用）",
    )
    parser.add_argument(
        "--no-json",
        action="store_true",
        help="記事データのJSON保存をスキップする",
    )
    parser.add_argument(
        "--log-level",
        default=LOG_LEVEL,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="ログレベル（デフォルト: INFO）",
    )

    args = parser.parse_args()
    _setup_logging(args.log_level)

    try:
        run_pipeline(
            send_email=not args.no_email,
            dry_run=args.dry_run,
            save_json=not args.no_json,
        )
    except KeyboardInterrupt:
        logger.info("中断されました。")
        sys.exit(1)
    except Exception as exc:
        logger.exception("パイプラインエラー: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
