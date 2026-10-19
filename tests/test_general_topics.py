"""
「気になる話題」機能のオフラインテスト
================================================================

使い方:
    python -X utf8 tests/test_general_topics.py

確認すること（ネット接続・API キー不要）:
    - docs/manual_topics.json の読み込み（形式の揺れ・未掲載だけを返す）
    - 掲載済みマーク（published 日付の書き込み）
    - 記事ページ HTML からの見出し・概要・媒体名・日付の取り出し
      （og:title は「｜」を含んでもそのまま使う、<title> だけならサイト名を落とす）
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.collect_news import Article
from scripts.general_topics import (
    _looks_like_market_report,
    drop_duplicate_topics,
    is_same_topic,
    load_manual_topics,
    mark_manual_topics_published,
    parse_article_metadata,
)

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


def test_manual_topics_file() -> None:
    print("--- 手動登録ファイル ---")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "manual_topics.json"

        # 存在しないファイル → 空リスト
        check("ファイル無しは空", load_manual_topics(path) == [])

        # 辞書形式・URL文字列だけ・掲載済み・不正行が混在
        path.write_text(
            json.dumps(
                {
                    "_使い方": "メモ",
                    "topics": [
                        {"url": "https://example.com/a", "note": "A"},
                        "https://example.com/b",
                        {"url": "https://example.com/c", "published": "2026-10-12"},
                        {"url": "not-a-url"},
                        123,
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        pending = load_manual_topics(path)
        urls = [e["url"] for e in pending]
        check("未掲載の2件だけ返る", urls == ["https://example.com/a", "https://example.com/b"], str(urls))
        check("note が保持される", pending[0].get("note") == "A")

        # 掲載済みマーク（末尾スラッシュの違いも同一視）
        mark_manual_topics_published(["https://example.com/a/"], "2026-10-19", path)
        saved = json.loads(path.read_text(encoding="utf-8"))
        a_entry = next(e for e in saved["topics"] if e["url"] == "https://example.com/a")
        check("published が書き込まれる", a_entry.get("published") == "2026-10-19", str(a_entry))
        check("残りは未掲載のまま", [e["url"] for e in load_manual_topics(path)] == ["https://example.com/b"])

        # 壊れた JSON でも落ちない
        path.write_text("{ broken", encoding="utf-8")
        check("壊れたJSONは空扱い", load_manual_topics(path) == [])


def test_parse_metadata() -> None:
    print("--- 記事メタ情報の抽出 ---")

    html_og = """
    <html><head>
      <title>テスラの空飛ぶロードスター | TRANS CAR</title>
      <meta property="og:title" content="テスラの空飛ぶロードスター｜飛行デモ動画とRocket仕様の仕組みを解説">
      <meta property="og:description" content="テスラが新型ロードスターの発表会で空中に浮く実演を披露。">
      <meta property="og:site_name" content="TRANS CAR">
      <meta property="article:published_time" content="2026-10-16T22:08:55+09:00">
    </head><body></body></html>
    """
    meta = parse_article_metadata(html_og, "https://transcarweb.com/x/")
    check(
        "og:title は「｜」を含んでもそのまま",
        meta["title"] == "テスラの空飛ぶロードスター｜飛行デモ動画とRocket仕様の仕組みを解説",
        meta["title"],
    )
    check("og:description を取得", meta["description"].startswith("テスラが新型"), meta["description"])
    check("og:site_name を媒体名に", meta["source"] == "TRANS CAR", meta["source"])
    check("公開日を取得", meta["published_at"].startswith("2026-10-16"), meta["published_at"])

    html_title_only = """
    <html><head><title>H3ロケット10号機 打ち上げ成功 - TBS NEWS DIG</title>
    <meta name="description" content="H3ロケット10号機が打ち上げられました。"></head><body></body></html>
    """
    meta = parse_article_metadata(html_title_only, "https://newsdig.tbs.co.jp/articles/1")
    check("<title> のサイト名を落とす", meta["title"] == "H3ロケット10号機 打ち上げ成功", meta["title"])
    check("name=description を取得", "H3ロケット" in meta["description"], meta["description"])
    check("site_name が無ければドメイン", meta["source"] == "newsdig.tbs.co.jp", meta["source"])


def _art(title: str, url: str) -> Article:
    return Article(title=title, description="", url=url, source="test", published_at="2026-10-18T00:00:00+09:00")


def test_duplicate_topics() -> None:
    print("--- 同じ話題の判定 ---")

    # 同じ出来事（媒体違い・言い回し違い）
    check(
        "テスラ空飛ぶロードスター（媒体違い）",
        is_same_topic(
            "テスラの空飛ぶロードスター｜飛行デモ動画とRocket仕様の仕組みを解説",
            "テスラ、新型ロードスターの飛行デモを公開 空飛ぶクルマ時代へ",
        ),
    )
    check(
        "H3ロケット10号機（見出し違い）",
        is_same_topic(
            "H3ロケット10号機 打ち上げ成功 火星衛星探査機MMXを搭載",
            "火星衛星探査機MMXを載せたH3ロケット10号機、打ち上げに成功",
        ),
    )
    # 分野が同じだけの別の話題は重複にしない
    check(
        "別の話題（EV同士）は重複にしない",
        not is_same_topic(
            "トヨタ、アリーン搭載車拡大 全固体電池も実用化",
            "日産、新型リーフの航続距離を700kmに延長",
        ),
    )
    check(
        "別の話題（空飛ぶクルマ vs ロケット）は重複にしない",
        not is_same_topic(
            "空飛ぶクルマ、米26州で社会実装向け実証",
            "H3ロケット10号機 打ち上げ成功",
        ),
    )

    # リストから重複を落とす（先頭優先・除外リストも考慮）
    arts = [
        _art("テスラ、新型ロードスターの飛行デモを公開", "https://a/1"),
        _art("H3ロケット10号機 打ち上げ成功 火星衛星探査機MMXを搭載", "https://a/2"),
        _art("火星衛星探査機MMXを載せたH3ロケット10号機、打ち上げに成功", "https://a/3"),
        _art("ヒューマノイドロボットが工場で検品作業を開始", "https://a/4"),
    ]
    kept = drop_duplicate_topics(arts, exclude_titles=["テスラの空飛ぶロードスター｜飛行デモ動画を解説"])
    urls = [a.url for a in kept]
    check("手動登録と同じ話題を除外", "https://a/1" not in urls, str(urls))
    check("同じ出来事は先頭の1件だけ残す", urls == ["https://a/2", "https://a/4"], str(urls))

    print("--- 市場レポートっぽい見出しの除外 ---")
    check(
        "市場規模○○億ドルは除外",
        _looks_like_market_report("産業AIが「工場の頭脳」へ進化―製造業コパイロット市場、2035年に200億米ドル規模へ拡大"),
    )
    check("市場予測レポートは除外", _looks_like_market_report("空飛ぶクルマ市場の予測レポート2035年版を発行"))
    check("普通のニュースは残す", not _looks_like_market_report("トヨタ、アリーン搭載車拡大 全固体電池も実用化"))
    check("「市場」を含む普通の見出しは残す", not _looks_like_market_report("日産、新型リーフを欧州市場に投入"))


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    test_manual_topics_file()
    test_parse_metadata()
    test_duplicate_topics()

    print(f"\n結果: OK {_passed} / FAIL {_failed}")
    sys.exit(1 if _failed else 0)


if __name__ == "__main__":
    main()
