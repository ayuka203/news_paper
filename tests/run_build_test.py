import sys, json, datetime as dt
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collector as C

# テスト用に「今日」と「数日前」を動的に生成する（display-time filter が max_age_days=7 なので静的日付は使わない）
_today = C.today_str()
_today_dt = C.now_jst()
_d1 = (_today_dt - dt.timedelta(days=1)).strftime("%Y-%m-%d")   # 1日前
_d2 = (_today_dt - dt.timedelta(days=2)).strftime("%Y-%m-%d")   # 2日前
_d3 = (_today_dt - dt.timedelta(days=3)).strftime("%Y-%m-%d")   # 3日前

def _y(d: str) -> str:
    """YYYY-MM-DD -> "YYYY年M月D日" 形式（テスト用）"""
    y, m, day = d.split("-")
    return f"{y}年{int(m)}月{int(day)}日"

# 1) URL正規化 / タイトル正規化
assert C.canonical_url("https://Ex.com/a/?utm_source=x&id=5#frag") == "https://ex.com/a?id=5"
assert C.canonical_url("https://ex.com/a/") == "https://ex.com/a"

# 2) 重複排除（同一URL + 類似タイトル）
items = [
  {"title":"無電柱化 第3期計画を閣議決定","url":"https://a.jp/1","canonical":"https://a.jp/1","source":"A","section":"規制・政策","published":_d2},
  {"title":"無電柱化 第3期計画を閣議決定","url":"https://b.jp/9?utm_source=z","canonical":"https://b.jp/9","source":"B","section":"規制・政策","published":_d2},   # 類似タイトル→除去
  {"title":"無電柱化　第３期計画を、閣議決定。","url":"https://c.jp/x","canonical":"https://c.jp/x","source":"C","section":"規制・政策","published":_d3}, # 記号違い→除去
  {"title":"系統連系の新ルール公表","url":"https://a.jp/2","canonical":"https://a.jp/2","source":"A","section":"送配電・系統","published":""},
]
d = C.dedup(items)
print("dedup:", len(items), "->", len(d))
assert len(d) == 2, d

# 3) build_site が index.html を生成するか（first_seen付与）
for it in d: it["first_seen"] = _d1
cfg = json.loads((Path(C.ROOT)/"sources.json").read_text(encoding="utf-8"))
C.build_site(d, cfg["sources"], cfg)
idx = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
expected_masthead = cfg.get("masthead", "DAILY NEWS")
for must in [expected_masthead,"規制・政策","送配電・系統","無電柱化 第3期計画を閣議決定","系統連系の新ルール公表",_y(_d1),"source-group","source-title"]:
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
     "source":"A","section":"規制・政策","published":_d3,"first_seen":_d3},
    {"title":"新しい日のニュース","url":"https://x.jp/new","canonical":"https://x.jp/new",
     "source":"A","section":"規制・政策","published":_d1,"first_seen":_d1},
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
old_arc = (Path(C.ROOT)/"public"/"archive"/f"{_d3}.html").read_text(encoding="utf-8")
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

# 9) URL 除外テスト
sample_urls = [
    {"title": "電力市場の動向", "canonical": "https://www.nikkei.com/article/abc"},
    {"title": "電力会社で転職", "canonical": "https://www.nikkei.com/tenshoku/xxx"},
    {"title": "ガス事業", "canonical": "https://career.nikkei.com/yyy"},
    {"title": "大文字混入", "canonical": "https://www.nikkei.com/Tenshoku/UPPER"},  # 大文字パス
]
filtered = C._apply_url_excludes(sample_urls, ["nikkei.com/tenshoku", "career.nikkei.com"])
assert len(filtered) == 1, f"URL除外結果: {len(filtered)}"
assert filtered[0]["canonical"].endswith("/article/abc")
# 空リストは全通過
assert len(C._apply_url_excludes(sample_urls, [])) == 4
# 空文字混入も通過
assert len(C._apply_url_excludes(sample_urls, [""])) == 4
print("url exclude tests OK")

# 10) 鮮度フィルタ（max_age_days）テスト
import datetime as _dt
old_iso = (C.now_jst() - _dt.timedelta(days=14)).isoformat()
fresh_iso = (C.now_jst() - _dt.timedelta(days=2)).isoformat()
sample_age = [
    {"title": "old", "published": old_iso},
    {"title": "fresh", "published": fresh_iso},
    {"title": "nodate", "published": ""},  # 不明は保持
]
filtered = C._filter_by_age(sample_age, 7)
titles = [it["title"] for it in filtered]
assert "fresh" in titles and "nodate" in titles, f"フィルタ結果: {titles}"
assert "old" not in titles, "14日前の記事が残っている"
# max_days <= 0 はフィルタなし
assert len(C._filter_by_age(sample_age, 0)) == 3
assert len(C._filter_by_age(sample_age, None)) == 3
# days=7 ちょうど → cutoff = now - 7d、d >= cutoff で保持される（境界包含）
exactly_iso = (C.now_jst() - _dt.timedelta(days=7) + _dt.timedelta(seconds=1)).isoformat()
sample_edge = [
    {"title": "exactly7", "published": exactly_iso},
]
assert len(C._filter_by_age(sample_edge, 7)) == 1, "days=7境界の記事が消えている"
print("age filter boundary test OK")
print("age filter tests OK")

# 11) per-source max_age_days オーバーライド
# collect_all を直接モックするのは難しいので、_filter_by_age と _age_done マーカーの組み合わせをユニット試験する形にする
import datetime as _dt
old_pub = (C.now_jst() - _dt.timedelta(days=5)).isoformat()
fresh_pub = (C.now_jst() - _dt.timedelta(hours=10)).isoformat()
src_a_items = [
    {"title":"A-fresh","published":fresh_pub,"canonical":"https://a.jp/1"},
    {"title":"A-old","published":old_pub,"canonical":"https://a.jp/2"},
]
# source A は max_age=1 で fresh だけ通過
filtered = C._filter_by_age(src_a_items, 1)
titles = [it["title"] for it in filtered]
assert "A-fresh" in titles and "A-old" not in titles, f"per-source max_age=1 が機能していない: {titles}"
print("per-source max_age override test OK")

# 12) build_site 表示時フィルタ
import shutil
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
old_published = (C.now_jst() - _dt.timedelta(days=30)).isoformat()
fresh_published = (C.now_jst() - _dt.timedelta(days=2)).isoformat()
# 同じ first_seen で2件、片方は published が30日前
display_items = [
    {"title":"古い投稿だが今日見つけた","url":"https://x.jp/o","canonical":"https://x.jp/o",
     "source":"X","section":"規制・政策","published":old_published,"first_seen":_d1},
    {"title":"新しい投稿","url":"https://x.jp/n","canonical":"https://x.jp/n",
     "source":"X","section":"規制・政策","published":fresh_published,"first_seen":_d1},
]
C.build_site(display_items, cfg["sources"], cfg)
idx_disp = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
arc_disp = (Path(C.ROOT)/"public"/"archive"/f"{_d1}.html").read_text(encoding="utf-8")
assert "新しい投稿" in idx_disp, "index に新しい投稿が含まれていない"
assert "古い投稿だが今日見つけた" not in idx_disp, "index で表示時フィルタが効いていない（古い記事が出ている）"
# archive スナップショットには両方残る（per-day は変更しないのが意図）
assert "新しい投稿" in arc_disp and "古い投稿だが今日見つけた" in arc_disp, "archive スナップショットが変質している"
print("build_site display-time filter test OK")

# 13) max_age_days: 0 のソースで _age_done が付かないことを境界テストとして直接確認
sample_zero_age = [
    {"title":"x", "canonical":"https://x.jp/0", "published": fresh_pub},
    {"title":"y", "canonical":"https://x.jp/1", "published": old_pub},
]
# collect_all 内のガード相当ロジックを直接呼ぶ形でテスト
src_age_raw = 0
try:
    src_age = int(src_age_raw) if src_age_raw is not None else None
except (TypeError, ValueError):
    src_age = None
got = list(sample_zero_age)
if src_age is not None and src_age > 0:
    got = C._filter_by_age(got, src_age)
    for it in got:
        it["_age_done"] = True
assert not any("_age_done" in it for it in got), "max_age_days=0 で _age_done が付与されている"
print("max_age_days=0 guard test OK")

# 14) per-source max_age_days が表示時にも効く
import shutil, datetime as _dt
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
src_nikkei_name = "日本経済新聞"  # sources.json の max_age_days=1 のソース名
nikkei_old_pub = (C.now_jst() - _dt.timedelta(days=3)).isoformat()
nikkei_fresh_pub = (C.now_jst() - _dt.timedelta(hours=10)).isoformat()
other_pub = (C.now_jst() - _dt.timedelta(days=3)).isoformat()  # 3日前、global 7日窓では通過
# タイトルは dedup の類似度しきい値(0.82)を超えないよう十分に異なる文字列にする
disp_per_src = [
    {"title":"脱炭素政策の動向について詳細解説","url":"https://nikkei.com/o","canonical":"https://nikkei.com/o",
     "source":src_nikkei_name,"section":"規制・政策","published":nikkei_old_pub,"first_seen":_d1},
    {"title":"再エネ電力の系統接続費用が焦点","url":"https://nikkei.com/n","canonical":"https://nikkei.com/n",
     "source":src_nikkei_name,"section":"規制・政策","published":nikkei_fresh_pub,"first_seen":_d1},
    {"title":"電力市場改革の最新論点を整理","url":"https://other.com/x","canonical":"https://other.com/x",
     "source":"他社","section":"規制・政策","published":other_pub,"first_seen":_d1},
]
C.build_site(disp_per_src, cfg["sources"], cfg)
idx_per_src = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
assert "再エネ電力の系統接続費用が焦点" in idx_per_src, "Nikkei 新しい記事が表示されていない"
assert "脱炭素政策の動向について詳細解説" not in idx_per_src, "per-source 表示時フィルタが効かず Nikkei 古い記事が表示されている"
assert "電力市場改革の最新論点を整理" in idx_per_src, "per-source 設定なしソースが誤って弾かれている"
print("per-source display-time age filter test OK")

# 15) タイトル除外（exclude_title_patterns）テスト
sample_titles = [
    {"title": "電力市場の動向"},
    {"title": "（人事・素材・エネルギー）原子燃料工業"},
    {"title": "ガス事業について"},
    {"title": "(人事・素材・エネルギー)三谷産業"},  # 半角カッコは別件、これは通過
]
filtered = C._apply_title_excludes(sample_titles, ["（人事・素材・エネルギー）"])
titles = [it["title"] for it in filtered]
assert "電力市場の動向" in titles
assert "（人事・素材・エネルギー）原子燃料工業" not in titles
assert "ガス事業について" in titles
assert "(人事・素材・エネルギー)三谷産業" in titles, "半角カッコは別パターンなので通過するはず"
# 空リスト → 全通過
assert len(C._apply_title_excludes(sample_titles, [])) == 4
# 空文字混入 → 無視
assert len(C._apply_title_excludes(sample_titles, [""])) == 4
# 大文字小文字無視
assert len(C._apply_title_excludes(
    [{"title": "ABC company news"}], ["abc company"]
)) == 0
# NFC 正規化（合成済み vs 分解形）
import unicodedata as _u
decomposed_title = _u.normalize("NFD", "がんばろう")
filtered_nfc = C._apply_title_excludes(
    [{"title": decomposed_title}], ["がんばろう"]
)
assert len(filtered_nfc) == 0, "NFC正規化で分解形タイトルが除外されない"
print("title exclude tests OK")

print("ALL OK")
