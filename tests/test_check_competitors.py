"""
競合サイトのニュース抽出ロジックのテスト
================================================================

使い方:
    python tests/test_check_competitors.py

実サイトの HTML 構造を再現した固定データで検証する（ネットワーク不要）。
競合サイト追加時に問題になった以下のケースを回帰テストとして残す:
    - 一覧全体から先頭記事の日付を拾い、全項目が同じ日付になる
      （正英製作所のサイト構造）
    - class名に news 等を含まず <time> で日付を持つため0件になる
      （タクボエンジニアリングのサイト構造）
"""

from __future__ import annotations

import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.check_competitors import _clean_title, _extract_news_items

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


def extract(html: str, base_url: str = "https://example.com/news/") -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    return _extract_news_items(soup, base_url)


def by_title(items: list[dict], keyword: str) -> dict | None:
    return next((i for i in items if keyword in i["title"]), None)


# ──────────────────────────────────────────────
# 正英製作所型: <a class="news__item"> の中に日付がある
# ──────────────────────────────────────────────
SHOEI_HTML = """
<section id="list"><div class="news__list">
  <a class="news__item" href="/news/detail/?id=41">
    <p class="news__accessory">
      <span class="news__date">2026.09.03</span>
      <span class="news__category c-news">お知らせ</span>
    </p>
    <p class="news__ttl">サーモテック2026 出展情報</p>
  </a>
  <a class="news__item" href="/news/detail/?id=40">
    <p class="news__accessory">
      <span class="news__date">2026.07.29</span>
      <span class="news__category c-news">お知らせ</span>
    </p>
    <p class="news__ttl">夏季休暇のお知らせ</p>
  </a>
  <a class="news__item" href="/news/detail/?id=24">
    <p class="news__accessory">
      <span class="news__date">2024.10.15</span>
      <span class="news__category c-news">お知らせ</span>
    </p>
    <p class="news__ttl">本社移転のご案内</p>
  </a>
</div></section>
"""


def test_shoei_structure() -> None:
    print("--- 正英製作所型（項目ごとの日付） ---")
    items = extract(SHOEI_HTML)

    dates = sorted({i["date"].strftime("%Y-%m-%d") for i in items})
    check(
        "項目ごとに別の日付が付く（一覧先頭の日付で埋まらない）",
        len(dates) == 3,
        f"dates={dates}",
    )

    latest = by_title(items, "サーモテック")
    old = by_title(items, "本社移転")
    check(
        "最新項目の日付が正しい",
        latest is not None and latest["date"].strftime("%Y-%m-%d") == "2026-09-03",
        f"{latest}",
    )
    check(
        "2年前の項目が古い日付のまま扱われる",
        old is not None and old["date"].strftime("%Y-%m-%d") == "2024-10-15",
        f"{old}",
    )
    check(
        "リンク先URLが項目ごとに解決される",
        old is not None and old["url"].endswith("/news/detail/?id=24"),
        f"{old['url'] if old else None}",
    )


# ──────────────────────────────────────────────
# タクボ型: <time> で日付、class名に news を含まない
# ──────────────────────────────────────────────
TAKUBO_HTML = """
<div class="content-body">
  <div class="cate-product">
    <p class="article-meta">
      <time class="date">2026年07月30日</time>
      <span class="more"><a href="./archives/2026/20260724.html">本文ページへのリンク</a></span>
    </p>
    <h2><a href="archives/2026/20260724.html">スコッチガン新モデルR26T、2026年8月より発売開始</a></h2>
    <p></p>
  </div>
  <div class="cate-others">
    <p class="article-meta">
      <time class="date">2026年03月24日</time>
      <span class="more"><a href="./archives/2026/20260324.html">本文ページへのリンク</a></span>
    </p>
    <h2><a href="archives/2026/20260324.html">英語版 塗装道ページ 更新しました</a></h2>
    <p>タクボエンジニアリングの技術開発の歴史</p>
  </div>
</div>
"""


def test_takubo_structure() -> None:
    print("--- タクボ型（<time>起点の抽出） ---")
    items = extract(TAKUBO_HTML, "https://www.takubo.co.jp/j/news/")

    check("項目が抽出される（0件にならない）", len(items) >= 2, f"len={len(items)}")

    newest = by_title(items, "スコッチガン")
    check(
        "見出しリンクをタイトルに採用する",
        newest is not None,
        f"titles={[i['title'] for i in items]}",
    )
    check(
        "汎用リンク文言をタイトルにしない",
        not any("本文ページへのリンク" in i["title"] for i in items),
        f"titles={[i['title'] for i in items]}",
    )
    check(
        "<time>の日付が項目に紐づく",
        newest is not None and newest["date"].strftime("%Y-%m-%d") == "2026-07-30",
        f"{newest}",
    )
    check(
        "相対URLが絶対URLに解決される",
        newest is not None
        and newest["url"] == "https://www.takubo.co.jp/j/news/archives/2026/20260724.html",
        f"{newest['url'] if newest else None}",
    )


# ──────────────────────────────────────────────
# 既存パターン（li / dl）が引き続き動くこと
# ──────────────────────────────────────────────
LIST_HTML = """
<ul class="news-list">
  <li><span>2026.09.10</span><a href="/news/1.html">第3回 半導体産業展 出展のお知らせ</a></li>
  <li><span>2026.08.21</span><a href="/news/2.html">事業開発本部移転のお知らせ</a></li>
</ul>
<dl class="topics">
  <dt>2026.09.01</dt><dd><a href="/news/3.html">自己株式の取得状況に関するお知らせ</a></dd>
</dl>
"""


def test_existing_patterns() -> None:
    print("--- 既存パターン（li / dl） ---")
    items = extract(LIST_HTML)

    first = by_title(items, "半導体産業展")
    check("li パターンを抽出できる", first is not None, f"titles={[i['title'] for i in items]}")
    check(
        "li の日付が正しい",
        first is not None and first["date"].strftime("%Y-%m-%d") == "2026-09-10",
        f"{first}",
    )

    dl_item = by_title(items, "自己株式")
    check("dl/dt/dd パターンを抽出できる", dl_item is not None)
    check(
        "dt の日付が正しい",
        dl_item is not None and dl_item["date"].strftime("%Y-%m-%d") == "2026-09-01",
        f"{dl_item}",
    )

    check(
        "同一項目が日付違いで重複しない",
        len({i["url"] for i in items}) == len(items),
        f"urls={[i['url'] for i in items]}",
    )


def test_clean_title() -> None:
    print("--- タイトルの日付除去 ---")
    check(
        "先頭の日付を除去",
        _clean_title("2026.08.27企業情報i-bou MV公開") == "企業情報i-bou MV公開",
        _clean_title("2026.08.27企業情報i-bou MV公開"),
    )
    check(
        "末尾の日付を除去",
        _clean_title("COSMOSハンドルのご紹介 2026.09.09") == "COSMOSハンドルのご紹介",
        _clean_title("COSMOSハンドルのご紹介 2026.09.09"),
    )
    check(
        "末尾の日付+カテゴリを除去",
        _clean_title("防爆協働ロボット導入のお知らせ 2026.09.10 お知らせ")
        == "防爆協働ロボット導入のお知らせ",
        _clean_title("防爆協働ロボット導入のお知らせ 2026.09.10 お知らせ"),
    )
    check(
        "末尾の日付+ハッシュタグ付きカテゴリを除去",
        _clean_title("COSMOSハンドルのご紹介 2026.09.09 #新製品情報")
        == "COSMOSハンドルのご紹介",
        _clean_title("COSMOSハンドルのご紹介 2026.09.09 #新製品情報"),
    )
    check(
        "本文中の年号は残す",
        _clean_title("スコッチガン新モデル、2026年8月より発売開始")
        == "スコッチガン新モデル、2026年8月より発売開始",
        _clean_title("スコッチガン新モデル、2026年8月より発売開始"),
    )
    check("日付だけのタイトルは空にしない", _clean_title("2026.09.09") == "2026.09.09")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    test_shoei_structure()
    test_takubo_structure()
    test_existing_patterns()
    test_clean_title()

    print()
    print(f"結果: {_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
