"""
メインスクリプト — 塗装業界ニュース自動まとめツール
=====================================================

全モジュールを統合して以下のパイプラインを実行する:
1. ニュース収集 (NewsAPI)
2. 翻訳・要約 (Claude API)
3. HTML生成
4. メール通知 (SendGrid)

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

from scripts.collect_news import Article, collect_news
from scripts.config import DOCS_DIR, LOG_LEVEL
from scripts.generate_html import generate_weekly_report
from scripts.send_email import send_notification
from scripts.translate_summarize import translate_and_summarize

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
    ニュース収集→翻訳→HTML生成→メール送信のパイプラインを実行する。

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

    # ────────────────────────
    # Step 1: ニュース収集
    # ────────────────────────
    logger.info("")
    logger.info("━━━ Step 1/4: ニュース収集 ━━━")

    if dry_run:
        logger.info("ドライラン: ダミーデータを使用します")
        articles = _create_dummy_articles()
    else:
        articles = collect_news()

    if not articles:
        logger.warning("ニュースが見つかりませんでした。処理を終了します。")
        return

    logger.info("収集完了: %d 件", len(articles))

    # ────────────────────────
    # Step 2: 翻訳・要約
    # ────────────────────────
    logger.info("")
    logger.info("━━━ Step 2/4: 翻訳・要約 ━━━")

    if dry_run:
        logger.info("ドライラン: 翻訳済みダミーデータを使用します")
    else:
        articles = translate_and_summarize(articles)

    logger.info("翻訳完了: %d 件", len(articles))

    # ────────────────────────
    # Step 3: HTML生成
    # ────────────────────────
    logger.info("")
    logger.info("━━━ Step 3/4: HTML生成 ━━━")

    report_path = generate_weekly_report(articles)
    report_filename = report_path.name

    logger.info("HTML生成完了: %s", report_path)

    # JSON保存（デバッグ用）
    if save_json:
        _save_articles_json(articles)

    # ────────────────────────
    # Step 4: メール送信
    # ────────────────────────
    logger.info("")
    logger.info("━━━ Step 4/4: メール送信 ━━━")

    if not send_email:
        logger.info("メール送信はスキップされました (--no-email)")
    elif dry_run:
        logger.info("ドライラン: メール送信をスキップします")
    else:
        try:
            success = send_notification(articles, report_filename)
            if success:
                logger.info("メール送信完了")
            else:
                logger.error("メール送信に失敗しました")
        except Exception as exc:
            logger.error("メール送信エラー: %s", exc)
            # メール送信の失敗はパイプライン全体を止めない
            # HTML は生成済みなので、レポート自体は利用可能

    # ────────────────────────
    # 完了
    # ────────────────────────
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
