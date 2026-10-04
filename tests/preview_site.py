"""ローカルプレビュー用: ネットワーク・data/ を使わずにサイトを public/ に生成する。

  STOCK_WATCH_LOCAL_JSON=tests/fixtures/stock_report_sample.json python tests/preview_site.py
  -> public/index.html を開く

記事はダミー（日付は実行日基準）。data/state.json・archive.jsonl には触れない。
"""
import sys, json, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collector as C

now = C.now_jst()
today = C.today_str()


def ago(**kw):
    return (now - dt.timedelta(**kw)).isoformat()


ARTICLES = [
    ("送配電・系統", "電気新聞", ago(hours=5), "古河電工、超電導ケーブルの量産体制を拡充"),
    ("送配電・系統", "T&D World", ago(days=1), "古河電気工業が海底ケーブル工場に追加投資"),
    ("送配電・系統", "日本経済新聞", ago(days=2), "古河電気工業の通期予想を上方修正"),
    ("送配電・系統", "電気新聞", ago(days=1, hours=3), "三菱電機、変圧器の増産に向け新工場を建設"),
    ("原子力", "World Nuclear News", ago(hours=9), "Cameco signs long-term uranium supply deal"),
    ("規制・政策", "経済産業省", ago(days=1), "系統用蓄電池の接続ルールを見直しへ"),
    ("海外", "EIA Today in Energy", ago(days=3), "US crude oil inventories decline"),
]
items = []
for i, (sec, src, pub, title) in enumerate(ARTICLES):
    u = f"https://example.org/preview/{i}"
    items.append({"title": title, "url": u, "canonical": u, "source": src,
                  "section": sec, "published": pub, "first_seen": today})

cfg = json.loads((C.ROOT / "sources.json").read_text(encoding="utf-8"))
report = C.fetch_stock_report(cfg)  # STOCK_WATCH_LOCAL_JSON があればそのファイル、無ければネットワーク
C.build_site(items, cfg["sources"], cfg, stock_report=report)
print("preview built:", C.PUBLIC / "index.html", "| stock section:", "yes" if report else "no")
