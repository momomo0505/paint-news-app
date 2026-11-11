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

from scripts.check_competitors import _clean_title, _extract_news_items, _parse_date

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


SANWA_HTML = """
<section class="information_list" id="main_column">
<ul class="information_list">
<li class="post">
<a href="https://sanwa-renotech.com/information/4620/">
<time>2026.09.30</time>
<label>イベント</label>
<span class="info_title">志摩機械☆万博　EXPO2026に出展いたします</span>
</a>
</li>
<li class="post">
<a href="https://sanwa-renotech.com/information/4617/">
<time>2026.09.22</time>
<label>イベント</label>
<span class="info_title">2026オクムラ祭りwith日立建機日本に出展いたします</span>
</a>
</li>
<li class="post">
<a href="https://sanwa-renotech.com/information/4607/">
<time>2026.09.28</time>
<label>NEWS</label>
<span class="info_title">システムメンテナンスに伴うサイト一時停止のお知らせ</span>
</a>
</li>
</ul>
</section>
"""


def test_sanwa_information_list() -> None:
    print("--- サンワ・リノテックお知らせ一覧 ---")
    items = extract(SANWA_HTML, "https://sanwa-renotech.com/information/")

    expo = by_title(items, "志摩機械")
    okumura = by_title(items, "オクムラ祭り")
    maint = by_title(items, "システムメンテナンス")
    check("イベント出展（9/30）を抽出できる", expo is not None, f"titles={[i['title'] for i in items]}")
    check(
        "9/30の日付が正しい",
        expo is not None and expo["date"].strftime("%Y-%m-%d") == "2026-09-30",
        f"{expo}",
    )
    check("イベント出展（9/22）を抽出できる", okumura is not None)
    check("NEWSも抽出できる", maint is not None)
    check(
        "タイトルにカテゴリ名が残らない",
        expo is not None and not expo["title"].startswith("イベント"),
        f"{expo['title'] if expo else None}",
    )
    check(
        "同一記事が日付抽出経路の違いで重複しない",
        len([i for i in items if "志摩機械" in i["title"]]) == 1,
        f"titles={[i['title'] for i in items]}",
    )


BANZAI_NAV_HTML = """
<ul class="nav">
  <li class="dropdown"><a href="/company.html">会社案内</a>
    <ul><li><a href="/company.html">会社概要</a></li></ul>
  </li>
</ul>
<dl>
  <dt class="rss_date">2026/09/30</dt>
  <dd class="rss_title"><a href="/media/a67"><span>新商品</span>エレクトリックタイヤリフター　発売開始</a></dd>
</dl>
"""


def test_banzai_skips_nav_title() -> None:
    print("--- バンザイ（ナビ誤検知の防止） ---")
    items = extract(BANZAI_NAV_HTML, "https://www.banzai.co.jp/news.html")
    titles = [i["title"] for i in items]
    check("会社案内をニュースにしない", not any("会社案内" == t for t in titles), f"titles={titles}")
    check("新商品ニュースは残す", any("タイヤリフター" in t for t in titles), f"titles={titles}")


# ──────────────────────────────────────────────
# 江蘇長虹型: <a> がカード全体を囲み、見出し <h3> にリンクが無い
# ──────────────────────────────────────────────
CHANGHONG_HTML = """
<ul class="xypg-news-list">
  <li>
    <a href="https://www.echanghong.com/news/475.html" title="长虹菲迪亚亮相SURCAR">
      <div class="img1"><img src="x.png" alt=""></div>
      <div class="wz">
        <div class="tit">
          <h3>长虹菲迪亚亮相SURCAR，带来全新电芯UV光铠绝缘技术喷印融合方案</h3>
          <div class="date">2026-09-23 17:32:06</div>
        </div>
        <div class="info">近日，SURCAR亚洲国际汽车涂装峰会在上海举行，长虹菲迪亚受邀出席并发表主题演讲...</div>
        <div class="more"><span>查看更多 +</span></div>
      </div>
    </a>
  </li>
</ul>
"""


def test_changhong_heading_without_link() -> None:
    print("--- 江蘇長虹型（カード全体リンク + 見出し） ---")
    items = extract(CHANGHONG_HTML, "https://www.echanghong.com/news/3/")
    item = items[0] if items else None
    check("項目が抽出される", item is not None, f"len={len(items)}")
    check(
        "見出しの文字だけがタイトルになる（日付・本文が混ざらない）",
        item is not None and item["title"] == "长虹菲迪亚亮相SURCAR，带来全新电芯UV光铠绝缘技术喷印融合方案",
        f"{item['title'] if item else None}",
    )
    check(
        "外側の <a> のリンク先を使う",
        item is not None and item["url"] == "https://www.echanghong.com/news/475.html",
        f"{item['url'] if item else None}",
    )
    check(
        "日付が正しい",
        item is not None and item["date"].strftime("%Y-%m-%d") == "2026-09-23",
    )


# ──────────────────────────────────────────────
# 明治機械型: 日付が「2026.08」のように年月のみ
# ──────────────────────────────────────────────
MEIJI_HTML = """
<ul class="headline">
  <li class="clfix tt_01">
    <div class="date">2026.08</div>
    <div class="detail"><a href="/topics/detail/145">【新発売】新型低圧霧化ハンドスプレーガン｜F111Lシリーズ発売。</a> <span>NEW!</span></div>
  </li>
  <li class="clfix tt_01">
    <div class="date">2024.03</div>
    <div class="detail"><a href="/topics/detail/120">古いお知らせ</a></div>
  </li>
</ul>
"""


def test_month_only_dates() -> None:
    print("--- 年月のみの日付（明治機械型） ---")
    # 既定（フラグなし）では年月だけの日付は無視する → 既存サイトの挙動を変えない
    default_items = extract(MEIJI_HTML, "https://www.meijiair.co.jp/topics/")
    check("フラグなしでは年月だけの項目を拾わない", len(default_items) == 0, f"len={len(default_items)}")

    soup = BeautifulSoup(MEIJI_HTML, "lxml")
    items = _extract_news_items(soup, "https://www.meijiair.co.jp/topics/", allow_month_only=True)
    new = by_title(items, "F111L")
    old = by_title(items, "古いお知らせ")
    check("フラグありなら項目を拾う", new is not None and old is not None, f"titles={[i['title'] for i in items]}")
    check(
        "過去月は月末の日付になる",
        old is not None and old["date"].strftime("%Y-%m-%d") == "2024-03-31",
        f"{old['date'] if old else None}",
    )
    check(
        "リンク先が解決される",
        new is not None and new["url"] == "https://www.meijiair.co.jp/topics/detail/145",
        f"{new['url'] if new else None}",
    )

    check(
        "本文中の「2026年8月より発売」は年月日付として扱わない（日が続く表記は対象外）",
        _parse_date("新モデル、2026年8月1日より発売開始", allow_month_only=True).day == 1,
    )
    check(
        "フル日付がある場合はそちらを優先する",
        _parse_date("2026.08 2026.08.25 更新", allow_month_only=True).day == 25,
    )


# ──────────────────────────────────────────────
# 日本スピンドル型: 日付の直後に素のテキストで見出し、個別リンク無し
# ──────────────────────────────────────────────
SPINDLE_HTML = """
<div id="panel1" class="tab_panel"><ul>
  <li class="newItem">
    <datetime>2026.10.26</datetime>
    ケミカルマテリアルJapan2026に出展いたします。<br>
    <p>　2026年11月26日(木)～27日(金)、東京ビッグサイトにて開催される展示会に出展いたします。<br>
      <a href="https://www.chemmate.jp/" target="_blank">展示会ホームページはこちら</a>　<a href="https://f-vr.jp/cmj/2026/">来場事前登録はこちら</a>
    </p>
  </li>
  <li class="newItem">
    <datetime>2026.10.23</datetime>
    EcoVadisから「ブロンズ」評価を取得しました。<br>
    <p>　今後もサステナビリティ推進に積極的に取り組みます。</p>
  </li>
</ul></div>
"""


def test_spindle_plain_text_title() -> None:
    print("--- 日本スピンドル型（日付直後の素のテキスト見出し） ---")
    items = extract(SPINDLE_HTML, "https://www.spindle.co.jp/")
    titles = [i["title"] for i in items]
    check("個別リンクが無くても2件とも抽出される", len(items) == 2, f"titles={titles}")
    check(
        "日付直後のテキストが見出しになる（関連リンク文言を拾わない）",
        "ケミカルマテリアルJapan2026に出展いたします。" in titles
        and not any("ホームページはこちら" in t for t in titles),
        f"titles={titles}",
    )
    check(
        "リンク先は一覧ページ自身になる",
        all(i["url"] == "https://www.spindle.co.jp/" for i in items),
        f"urls={[i['url'] for i in items]}",
    )
    eco = by_title(items, "EcoVadis")
    check(
        "日付が項目ごとに付く",
        eco is not None and eco["date"].strftime("%Y-%m-%d") == "2026-10-23",
        f"{eco}",
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
    test_sanwa_information_list()
    test_banzai_skips_nav_title()
    test_changhong_heading_without_link()
    test_month_only_dates()
    test_spindle_plain_text_title()
    test_clean_title()

    print()
    print(f"結果: {_passed} passed, {_failed} failed")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
