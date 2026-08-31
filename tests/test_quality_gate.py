"""
品質ゲートのテスト
================================================================

使い方:
    python tests/test_quality_gate.py           # オフラインテストのみ
    python tests/test_quality_gate.py --online  # 実サイトへの接続検証も実行

オフラインテスト:
    - 日付パース・URL日付抽出・URL正規化の単体テスト
    - 合成データでのゲート動作（古い記事除外・重複除外・正常記事保持）
    - 実際の 2026-08-31 号データ（docs/articles-2026-08-31.json）に
      含まれる重複記事が検出されることの確認

オンラインテスト（--online）:
    - 2026-08-31 号に混入した日刊工業新聞の古い記事 URL から
      実公開日が抽出できることの確認
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_news import Article
from scripts.quality_gate import (
    extract_url_date,
    fetch_page_date,
    normalize_url,
    parse_flexible_date,
    run_quality_gate,
)

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 9, 1, 12, 0, tzinfo=JST)

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  OK   {name}")
    else:
        _failed += 1
        print(f"  FAIL {name}  {detail}")


def make_article(
    title: str,
    url: str,
    published_at: str,
    title_ja: str = "",
) -> Article:
    a = Article(
        title=title,
        description="",
        url=url,
        source="test",
        published_at=published_at,
    )
    a.title_ja = title_ja
    return a


def test_date_parsing() -> None:
    print("--- 日付パース ---")
    d = parse_flexible_date("2026-08-29T10:00:00+09:00")
    check("ISO形式", d is not None and d.year == 2026 and d.month == 8)

    d = parse_flexible_date("2017年12月6日")
    check("和暦風表記", d is not None and (d.year, d.month, d.day) == (2017, 12, 6))

    d = parse_flexible_date("2017/12/06")
    check("スラッシュ区切り", d is not None and d.year == 2017)

    check("不正文字列はNone", parse_flexible_date("no date here") is None)
    check("空文字はNone", parse_flexible_date("") is None)


def test_url_date_extraction() -> None:
    print("--- URL日付抽出 ---")
    d = extract_url_date("https://example.com/news/2017/12/05/some-article")
    check("/YYYY/MM/DD/形式", d is not None and (d.year, d.month, d.day) == (2017, 12, 5))

    d = extract_url_date("https://www.taikisha.co.jp/news/20260827_955.html")
    check("YYYYMMDD形式", d is not None and (d.year, d.month, d.day) == (2026, 8, 27))

    d = extract_url_date("https://response.jp/article/2026/08/27/415808.html")
    check("記事パス中の日付", d is not None and (d.year, d.month) == (2026, 8))

    check(
        "日付なしURLはNone",
        extract_url_date("https://www.nikkan.co.jp/articles/view/341569") is None,
    )
    check(
        "記事IDを日付と誤認しない",
        extract_url_date("https://newscast.jp/news/7279637") is None,
    )


def test_url_normalization() -> None:
    print("--- URL正規化 ---")
    a = normalize_url("https://www.nikkan.co.jp/articles/view/454469?gnr_footer=10939")
    b = normalize_url("https://nikkan.co.jp/articles/view/454469/")
    check("トラッキングparam・www・末尾スラッシュを無視", a == b, f"{a} != {b}")

    a = normalize_url("https://www.maru-t.co.jp/news/article.php?d=326")
    b = normalize_url("https://www.maru-t.co.jp/news/article.php?d=325")
    check("意味のあるクエリは保持", a != b)


def test_gate_synthetic() -> None:
    print("--- ゲート動作（合成データ） ---")

    fresh = make_article(
        "Fresh news", "https://example.com/a", "2026-08-25T00:00:00+09:00", "新しいニュース"
    )
    stale_stored = make_article(
        "Old by stored date", "https://example.com/b", "2025-01-15T00:00:00+09:00", "古い記事1"
    )
    stale_url = make_article(
        "Old by URL date",
        "https://example.com/2017/12/05/old-article",
        "2026-08-26T00:00:00+09:00",  # 保存日付は偽装されて新しい
        "古い記事2",
    )
    unknown_date = make_article(
        "Unknown date", "https://example.com/c", "", "日付不明の記事"
    )
    dup_url_1 = make_article(
        "Dup A", "https://www.example.com/dup?utm_source=x", "2026-08-27T00:00:00+09:00", "重複A"
    )
    dup_url_2 = make_article(
        "Dup A again", "https://example.com/dup/", "2026-08-27T00:00:00+09:00", "重複Aの別URL表記"
    )
    dup_title_1 = make_article(
        "PPG leadership reshuffle", "https://example.com/d1", "2026-08-27T00:00:00+09:00",
        "PPGインダストリーズの経営陣刷新、「割安株」としての真価が問われる",
    )
    dup_title_2 = make_article(
        "PPG leadership reshuffle - Simply Wall St", "https://example.com/d2", "2026-08-28T00:00:00+09:00",
        "PPGインダストリーズの経営陣刷新、「割安株」としての真価が問われる",
    )

    old_competitor = {
        "company": "テスト社",
        "date": datetime(2024, 3, 1, tzinfo=JST),
        "title": "古い競合ニュース",
        "url": "https://example.com/comp-old",
    }
    fresh_competitor = {
        "company": "テスト社",
        "date": datetime(2026, 8, 20, tzinfo=JST),
        "title": "新しい競合ニュース",
        "url": "https://example.com/comp-new",
    }

    result = run_quality_gate(
        competitor_items=[old_competitor, fresh_competitor],
        domestic_articles=[fresh, stale_stored, stale_url, unknown_date],
        overseas_articles=[dup_url_1, dup_url_2, dup_title_1, dup_title_2],
        self_mention_articles=[],
        verify_online=False,
        now=NOW,
    )

    domestic_titles = [a.title for a in result.domestic_articles]
    overseas_titles = [a.title for a in result.overseas_articles]

    check("新しい記事は保持", "Fresh news" in domestic_titles)
    check("日付不明の記事は保持（誤除外しない）", "Unknown date" in domestic_titles)
    check("保存日付が古い記事を除外", "Old by stored date" not in domestic_titles)
    check("URL日付が古い記事を除外（日付偽装対策）", "Old by URL date" not in domestic_titles)
    check("URL重複を除外", len([t for t in overseas_titles if t.startswith("Dup A")]) == 1)
    check(
        "翻訳後タイトル重複を除外",
        len([t for t in overseas_titles if "PPG" in t]) == 1,
    )
    check("古い競合ニュースを除外", len(result.competitor_items) == 1)
    # 除外対象: 保存日付が古い1件 + URL日付が古い1件 + URL重複1件
    #          + タイトル重複1件 + 古い競合1件 = 5件
    check(
        "除外理由が記録される",
        len(result.removed) == 5,
        f"removed={len(result.removed)}: {result.removed}",
    )
    for line in result.removed:
        print(f"       除外: {line}")


def test_gate_on_real_20260831_data() -> None:
    print("--- 実データ検証（2026-08-31号の海外記事） ---")
    json_path = ROOT / "docs" / "articles-2026-08-31.json"
    if not json_path.exists():
        print("  SKIP docs/articles-2026-08-31.json がありません")
        return

    data = json.loads(json_path.read_text(encoding="utf-8"))
    articles = []
    for d in data:
        a = make_article(d["title"], d["url"], d["published_at"], d.get("title_ja", ""))
        articles.append(a)

    result = run_quality_gate(
        competitor_items=[],
        domestic_articles=[],
        overseas_articles=articles,
        self_mention_articles=[],
        verify_online=False,
        now=datetime(2026, 8, 31, 12, 0, tzinfo=JST),
    )

    # 8/31号には PPG経営陣刷新（3回掲載）・カラフルコミュニティ（2回）・
    # 自動車補修塗料市場（2回）などの重複が実在した
    check(
        f"実在した重複を検出（{len(result.removed)}件除外）",
        len(result.removed) >= 3,
        f"removed={result.removed}",
    )
    for line in result.removed:
        print(f"       除外: {line}")


def test_online_real_old_articles() -> None:
    print("--- オンライン検証（8/31号に混入した実際の古い記事） ---")

    # 2026-08-31 号の国内欄に「2026年8月」の日付で掲載されていたが、
    # 実際には数年前の記事だったもの（日刊工業新聞の記事IDが古い）
    suspicious_urls = [
        "https://www.nikkan.co.jp/articles/view/341569",
        "https://www.nikkan.co.jp/articles/view/347474",
        "https://www.nikkan.co.jp/articles/view/454469",
    ]
    # 同じ号に載っていた本当に新しい記事（比較用）
    fresh_url = "https://www.nikkan.co.jp/articles/view/790024"

    cutoff = NOW - timedelta(days=31)

    old_detected = 0
    for url in suspicious_urls:
        d = fetch_page_date(url)
        print(f"       {url} -> {d}")
        if d is not None and d < cutoff:
            old_detected += 1
    check(
        f"古い記事の実公開日を検出（{old_detected}/{len(suspicious_urls)}件）",
        old_detected >= 1,
        "1件も古い日付を抽出できませんでした",
    )

    d = fetch_page_date(fresh_url)
    print(f"       {fresh_url} -> {d}")
    check(
        "新しい記事を誤って古い判定しない",
        d is None or d >= cutoff,
        f"page date = {d}",
    )


def main() -> None:
    # Windows コンソール (cp932) でも除外理由の記号等を出力できるようにする
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    online = "--online" in sys.argv

    test_date_parsing()
    test_url_date_extraction()
    test_url_normalization()
    test_gate_synthetic()
    test_gate_on_real_20260831_data()

    if online:
        test_online_real_old_articles()
    else:
        print("--- オンライン検証はスキップ（--online で実行） ---")

    print()
    print(f"結果: {_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
