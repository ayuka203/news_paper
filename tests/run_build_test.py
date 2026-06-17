import sys, json, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collector as C

# 1) URL正規化 / タイトル正規化
assert C.canonical_url("https://Ex.com/a/?utm_source=x&id=5#frag") == "https://ex.com/a?id=5"
assert C.canonical_url("https://ex.com/a/") == "https://ex.com/a"

# 2) 重複排除（同一URL + 類似タイトル）
items = [
  {"title":"無電柱化 第3期計画を閣議決定","url":"https://a.jp/1","canonical":"https://a.jp/1","source":"A","section":"規制・政策","published":"2026-06-15"},
  {"title":"無電柱化 第3期計画を閣議決定","url":"https://b.jp/9?utm_source=z","canonical":"https://b.jp/9","source":"B","section":"規制・政策","published":"2026-06-15"},   # 類似タイトル→除去
  {"title":"無電柱化　第３期計画を、閣議決定。","url":"https://c.jp/x","canonical":"https://c.jp/x","source":"C","section":"規制・政策","published":"2026-06-14"}, # 記号違い→除去
  {"title":"系統連系の新ルール公表","url":"https://a.jp/2","canonical":"https://a.jp/2","source":"A","section":"送配電・系統","published":""},
]
d = C.dedup(items)
print("dedup:", len(items), "->", len(d))
assert len(d) == 2, d

# 3) build_site が index.html を生成するか（first_seen付与）
for it in d: it["first_seen"] = "2026-06-16"
cfg = json.loads((Path(C.ROOT)/"sources.json").read_text(encoding="utf-8"))
C.build_site(d, cfg["sources"], cfg)
idx = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
for must in ["THE GRID DESK","規制・政策","送配電・系統","無電柱化 第3期計画を閣議決定","系統連系の新ルール公表","2026年6月16日"]:
    assert must in idx, f"missing: {must}"
print("index.html bytes:", len(idx))
print("archive pages:", [p.name for p in (Path(C.ROOT)/'public'/'archive').glob('*.html')])
print("ALL OK")
