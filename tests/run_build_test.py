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
expected_masthead = cfg.get("masthead", "DAILY NEWS")
for must in [expected_masthead,"規制・政策","送配電・系統","無電柱化 第3期計画を閣議決定","系統連系の新ルール公表","2026年6月16日","source-group","source-title"]:
    assert must in idx, f"missing: {must}"
print("index.html bytes:", len(idx))
print("archive pages:", [p.name for p in (Path(C.ROOT)/'public'/'archive').glob('*.html')])
# 4) キーワードフィルタのテスト
sample = [
    {"title": "エネルギー政策の最新動向"},
    {"title": "AI技術の発展について"},
    {"title": "GXとカーボンニュートラル"},  # 大文字
    {"title": "野球の試合結果"},
]
# 通常
assert len(C._apply_keywords(sample, ["エネルギー", "GX"])) == 2
# 大文字小文字無視
assert len(C._apply_keywords(sample, ["gx"])) == 1
# 空リスト → 全通過
assert len(C._apply_keywords(sample, [])) == 4
# 空文字混入 → 空扱い
assert len(C._apply_keywords(sample, [""])) == 4
assert len(C._apply_keywords(sample, ["", "エネルギー"])) == 1
print("keyword filter tests OK")

# 5) index.html が直近N日のローリングウィンドウになっているか
multi_day_items = [
    {"title":"古い日のニュース","url":"https://x.jp/old","canonical":"https://x.jp/old",
     "source":"A","section":"規制・政策","published":"2026-06-14","first_seen":"2026-06-14"},
    {"title":"新しい日のニュース","url":"https://x.jp/new","canonical":"https://x.jp/new",
     "source":"A","section":"規制・政策","published":"2026-06-16","first_seen":"2026-06-16"},
]
import shutil
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
C.build_site(multi_day_items, cfg["sources"], cfg)
idx2 = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
assert "古い日のニュース" in idx2, "index に古い日のアイテムが含まれていない"
assert "新しい日のニュース" in idx2, "index に新しい日のアイテムが含まれていない"
# index ヘッダは複数日の "〜" 形式になっているか
assert "〜" in idx2, "index ヘッダがウィンドウ範囲表示になっていない"
# archive スナップショットは1日分のみ
old_arc = (Path(C.ROOT)/"public"/"archive"/"2026-06-14.html").read_text(encoding="utf-8")
assert "古い日のニュース" in old_arc
assert "新しい日のニュース" not in old_arc, "archive スナップショットが1日に限定されていない"
assert "過去号" in old_arc, "アーカイブページが is_latest=False で出力されていない"
print("rolling window test OK")

# 6) index_window_days=1 の境界テスト
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
narrow_cfg = {**cfg, "index_window_days": 1}
C.build_site(multi_day_items, cfg["sources"], narrow_cfg)
idx3 = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
assert "新しい日のニュース" in idx3, "window=1 で最新日が含まれていない"
assert "古い日のニュース" not in idx3, "window=1 なのに古い日が含まれている"
print("window=1 boundary test OK")

# 7) 無効な index_window_days のフォールバック
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
invalid_cfg = {**cfg, "index_window_days": "invalid"}
C.build_site(multi_day_items, cfg["sources"], invalid_cfg)
idx4 = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
# デフォルト 7 にフォールバックするので 2 日分とも含まれるはず
assert "古い日のニュース" in idx4 and "新しい日のニュース" in idx4, "無効値時のフォールバックが効いていない"
print("invalid window_days fallback test OK")

# 8) 空入力時に index.html が生成される
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
C.build_site([], cfg["sources"], cfg)
idx5_path = Path(C.ROOT)/"public"/"index.html"
assert idx5_path.exists(), "空入力時に index.html が生成されていない"
idx5 = idx5_path.read_text(encoding="utf-8")
assert "本日の更新はありません" in idx5, "空入力時に空状態メッセージが表示されていない"
print("empty input test OK")

print("ALL OK")
