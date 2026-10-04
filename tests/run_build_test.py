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

# ---------------------------------------------------------------- 16+) Market Pulse（構造化JSON）
import copy, io, os, tempfile, contextlib, unicodedata as _u2

_FIX = Path(__file__).resolve().parent / "fixtures"
_SAMPLE = json.loads((_FIX / "stock_report_sample.json").read_text(encoding="utf-8"))


def _rep(**over):
    r = copy.deepcopy(_SAMPLE)
    r.update(over)
    return r


def _parse(obj_or_text):
    """parse_stock_report を呼び、(結果, stderr出力) を返す。"""
    raw = obj_or_text if isinstance(obj_or_text, (str, bytes)) else json.dumps(obj_or_text, ensure_ascii=False)
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        res = C.parse_stock_report(raw)
    return res, buf.getvalue()


def _pub(hours_ago):
    return (C.now_jst() - _dt.timedelta(hours=hours_ago)).isoformat()


def _art(title, url, hours_ago, source="電気新聞"):
    return {"title": title, "url": url, "canonical": url, "source": source,
            "section": "送配電・系統", "published": _pub(hours_ago), "first_seen": _d1}


def _build_index(report, articles=None):
    shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
    arts = articles if articles is not None else [_art("古河電工が増産を発表", "https://x.jp/f1", 3)]
    C.build_site(arts, cfg["sources"], cfg, stock_report=report)
    return (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")


def _section(html):
    """Market Pulse 節のHTML断片（無ければ空文字）。"""
    a = html.find('<section class="section stock-watch">')
    return "" if a < 0 else html[a:html.index("</section>", a)]


# 16) 正常JSON: 検証を通り、各要素が描画される
rep_ok, err = _parse(_SAMPLE)
assert rep_ok is not None and err == "", err
html = _build_index(rep_ok)
sec = _section(html)
assert "Market Pulse" in sec and "Stock Watch" not in html
assert "日本株 10/2終値" in sec and "米国株 10/2終値" in sec
assert sec.count("（前回から更新なし）") == 1, "stale は US のみのはず"
assert _SAMPLE["headline"] in sec and "sw-headline" in sec
assert "送配電・計測" in sec and "+5.2%" in sec and "+11.0%" in sec and "-3.1%" in sec
assert "—" in sec, "null は「—」"
assert "古河電気工業" in sec and "前日比" in sec and "+8.4%" in sec
assert "52週高値" in sec and "出来高急増" in sec and "52週安値" in sec
assert "WTI原油" in sec and "91.11" in sec and "-0.4%" in sec
assert "<details" in sec and "全銘柄の詳細" in sec
assert "先週の振り返り" not in sec, "daily では副題を出さない"
assert 'class="pct up"' in sec and 'class="pct down"' in sec
# 節は index 末尾（記事より後）にあり、アーカイブには出ない
assert html.index("stock-watch") > html.index("source-group")
arc = (Path(C.ROOT)/"public"/"archive"/f"{_d1}.html").read_text(encoding="utf-8")
assert "Market Pulse" not in arc
# 取得失敗銘柄の注記
assert "取得できなかった銘柄" in sec and "XYZ.T" in sec
assert "取得できなかった銘柄" not in _section(_build_index(_parse(_rep(fetch_failures=[]))[0]))
print("market pulse render OK")

# 17) パーセント整形
assert C._fmt_pct(0.084)["text"] == "+8.4%"
assert C._fmt_pct(-0.031)["text"] == "-3.1%"
assert C._fmt_pct(None)["text"] == "—"
assert C._fmt_pct(0.0)["text"] == "+0.0%" and C._fmt_pct(-0.00001)["text"] == "+0.0%"
assert C._fmt_pct(-0.00001)["cls"] == "flat"
assert C._fmt_pct(0.5)["text"] == "+50.0%"
assert C._fmt_price(4458.0) == "4,458" and C._fmt_price(91.11) == "91.11" and C._fmt_price(None) == "—"
print("pct format OK")

# 18) 不正JSONは節ごと省略（None + stderr ログ）
bad_cases = {}
bad_cases["schema_version=2"] = _rep(schema_version=2)
bad_cases["schema_version=true"] = _rep(schema_version=True)
bad_cases["schema_version欠落"] = {k: v for k, v in _SAMPLE.items() if k != "schema_version"}
bad_cases["headline欠落"] = {k: v for k, v in _SAMPLE.items() if k != "headline"}
bad_cases["tickers欠落"] = {k: v for k, v in _SAMPLE.items() if k != "tickers"}
bad_cases["edition不正"] = _rep(edition="monthly")
bad_cases["report_date不正"] = _rep(report_date="2026-13-45")
_r = copy.deepcopy(_SAMPLE); _r["movers"][0]["daily_pct"] = "0.084"
bad_cases["pctが文字列"] = _r
_r = copy.deepcopy(_SAMPLE); _r["movers"][0]["daily_pct"] = True
bad_cases["pctがbool"] = _r
_r = copy.deepcopy(_SAMPLE); del _r["movers"][0]["keywords"]
bad_cases["mover.keywords欠落"] = _r
_r = copy.deepcopy(_SAMPLE); _r["movers"][0]["keywords"] = "古河電工"
bad_cases["keywordsが文字列"] = _r
_r = copy.deepcopy(_SAMPLE); _r["movers"][0]["flags"] = [1]
bad_cases["flagsが非文字列"] = _r
_r = copy.deepcopy(_SAMPLE); _r["themes"][0]["n"] = "4"
bad_cases["nが文字列"] = _r
_r = copy.deepcopy(_SAMPLE); _r["tickers"][0]["stale"] = "false"
bad_cases["staleが文字列"] = _r
_r = copy.deepcopy(_SAMPLE); _r["asof"]["JP"] = "10/2"
bad_cases["asof日付形式"] = _r
_r = copy.deepcopy(_SAMPLE); _r["macro"][0]["label"] = None
bad_cases["labelがnull"] = _r
bad_cases["movers非配列"] = _rep(movers={"a": 1})
bad_cases["トップが配列"] = [1, 2]
for name, bad in bad_cases.items():
    res, err = _parse(bad)
    assert res is None, f"不正JSONが通った: {name}"
    assert "stock_watch" in err, f"ログが出ていない: {name}"
for name, raw in {"壊れたJSON": "{not json", "空": "", "NaN": json.dumps(_SAMPLE).replace('0.084', 'NaN'),
                  "Infinity": json.dumps(_SAMPLE).replace('0.084', 'Infinity'),
                  "非UTF-8": b"\xff\xfe\x00", "サイズ超過": " " * (C.STOCK_MAX_BYTES + 1)}.items():
    res, err = _parse(raw)
    assert res is None and "stock_watch" in err, f"不正入力が通った: {name}"
# 未知のフラグ文字列は無視（前方互換）、null の pct は許容
_r = copy.deepcopy(_SAMPLE); _r["movers"][0]["flags"] = ["52w_high", "future_flag"]
res, _ = _parse(_r)
assert res is not None and res["movers"][0]["flags"] == ["52w_high"]
# build_site に不正な dict が渡っても全体は止まらず節だけ省略
with contextlib.redirect_stderr(io.StringIO()):
    html_bad = _build_index({"edition": "daily"})
assert _section(html_bad) == "", "不正レポートで節が出ている"
assert "古河電工が増産を発表" in html_bad, "節の失敗で記事本体が消えた"
print("invalid report omitted OK")

# 19) 見出し照合: 大文字小文字・NFC・最大2件・新しい順・同値タイトル順
kw_report = _rep(movers=[{**_SAMPLE["movers"][0], "keywords": ["古河電工", "furukawa"]}])
t_new = _art("古河電工、超電導ケーブルの量産体制を拡充", "https://x.jp/new", 2)
t_mid = _art("FURUKAWA Electric expands plant", "https://x.jp/mid", 10)          # 大文字小文字
t_old = _art("古河電工の通期予想を上方修正、海底ケーブルが牽引", "https://x.jp/old", 50)
t_other = _art("無関係の記事", "https://x.jp/other", 1)
res, _ = _parse(kw_report)
pool = C._headline_pool([t_old, t_other, t_mid, t_new])
got = C.match_headlines(res["movers"][0]["keywords"], pool)
assert [g["url"] for g in got] == ["https://x.jp/new", "https://x.jp/mid"], got   # 新しい順・最大2件
# 同値（published が同一）はタイトル順
same = _pub(5)
tie_b = {**_art("古河電工 B", "https://x.jp/b", 5), "published": same}
tie_a = {**_art("古河電工 A", "https://x.jp/a", 5), "published": same}
got = C.match_headlines(["古河電工"], C._headline_pool([tie_b, tie_a]))
assert [g["title"] for g in got] == ["古河電工 A", "古河電工 B"]
# NFC: 分解形のタイトル/キーワードどちらでも一致
nfd_title = _u2.normalize("NFD", "ガスタービン受注増")
assert nfd_title != "ガスタービン受注増"
assert len(C.match_headlines(["ガスタービン"], C._headline_pool([_art(nfd_title, "https://x.jp/nfd", 1)]))) == 1
assert len(C.match_headlines([nfd_title[:5]], C._headline_pool([_art("ガスタービン受注増", "https://x.jp/nfc", 1)]))) == 1
# 空キーワード・空白のみは全件一致にならない
assert C.match_headlines(["", "  "], pool) == []
assert C.match_headlines([], pool) == []
# 一致なし / 記事ゼロ
assert C.match_headlines(["存在しない語"], pool) == []
assert C.match_headlines(["古河電工"], C._headline_pool([])) == []
# 描画: 関連見出しのリンク（最大2件・新しい順）と「関連見出しなし」
html = _build_index(res, [t_old, t_other, t_mid, t_new])
sec = _section(html)
assert sec.count('class="sw-news"') == 1 and sec.count("<li><a href=") == 2
assert sec.index("x.jp/new") < sec.index("x.jp/mid") and "x.jp/old" not in sec and "x.jp/other" not in sec
no_hit = _build_index(res, [t_other])
assert "関連見出しなし" in _section(no_hit)
print("headline matching OK")

# 20) http/https 以外のURLは表示しない（照合候補からも除外され、次点が繰り上がる）
evil = [
    _art("古河電工 javascript 経由の話題A", "javascript:alert(1)", 1),
    _art("古河電工 data 取引の概況メモ", "data:text/html,<script>alert(1)</script>", 2),
    _art("古河電工がfile移行を発表", "file:///etc/passwd", 3),
    _art("古河電工と海外メーカーの提携交渉", "/relative/path", 4),
    _art("古河電工の新工場、2027年稼働へ", "  javascript:alert(2)", 5),
    _art("古河電工株が年初来高値を更新", "java\tscript:alert(3)", 6),
    _art("古河電工の決算説明会を10月に開催", "https://safe.example/ok", 7),
]
html = _build_index(res, evil)
sec = _section(html)
assert "https://safe.example/ok" in sec
for bad in ["javascript", "data:text", "file:///", "/relative/path", "alert("]:
    assert bad not in sec, f"危険なURLが出力された: {bad}"
assert C._safe_http_url("HTTP://Example.com/a") == "HTTP://Example.com/a"
assert C._safe_http_url("http://") is None and C._safe_http_url(None) is None
print("unsafe url excluded OK")

# 21) XSS: label / 見出し / headline / テーマ名 / 失敗銘柄 / source がエスケープされる
payload = '<script>alert("x")</script>'
xr = copy.deepcopy(_SAMPLE)
xr["headline"] = f"見出し {payload} & <b>bold</b>"
xr["themes"][0]["name"] = payload
xr["movers"][0]["label"] = payload
xr["movers"][0]["symbol"] = '"><img src=x onerror=alert(1)>'
xr["movers"][0]["theme"] = "<i>t</i>"
xr["macro"][0]["label"] = payload
xr["tickers"][0]["label"] = payload
xr["fetch_failures"] = [payload]
res, err = _parse(xr)
assert res is not None, err
xss_art = _art(f"古河電工 {payload}", 'https://x.jp/q?a="b"&c=<d>', 1, source=payload)
html = _build_index(res, [xss_art])
sec = _section(html)
assert "<script>" not in sec and "<img" not in sec and "<b>bold</b>" not in sec and "<i>t</i>" not in sec
assert "&lt;script&gt;" in sec and "&amp;" in sec
assert 'href="https://x.jp/q?a=&#34;b&#34;&amp;c=&lt;d&gt;"' in sec, "href の属性値がエスケープされていない"
assert "&#34;&gt;&lt;img src=x onerror=alert(1)&gt;" in sec, "symbol がエスケープされていない"
print("xss escape OK")

# 22) weekly: 副題・週間表示
wk = _rep(edition="weekly")
html = _build_index(_parse(wk)[0])
sec = _section(html)
assert "先週の振り返り" in sec
mover_block = sec[sec.index("sw-movers"):sec.index("sw-macro")]
assert "週間" in mover_block and "+16.5%" in mover_block and "+8.4%" not in mover_block
assert "前日比" not in mover_block
print("weekly render OK")

# 23) stale 注記: 市場別・銘柄別、false なら出ない
res, _ = _parse(_rep(asof={**_SAMPLE["asof"], "JP_stale": True, "US_stale": True}))
sec = _section(_build_index(res))
assert sec.count("（前回から更新なし）") == 2
res, _ = _parse(_rep(asof={**_SAMPLE["asof"], "JP_stale": False, "US_stale": False}))
sec = _section(_build_index(res))
assert "（前回から更新なし）" not in sec
assert "更新なし（基準日 10/1）" in sec and sec.count('class="stale"') == 1  # 銘柄 stale は tickers 側
res, _ = _parse(_rep(asof={"JP": None, "US": "2026-10-02", "JP_stale": False, "US_stale": False}))
assert "日本株 —終値" in _section(_build_index(res))
print("stale note OK")

# 24) movers 空
res, _ = _parse(_rep(movers=[]))
sec = _section(_build_index(res))
assert "目立った動きなし" in sec and "sw-mover-head" not in sec
assert "目立った動きなし" not in _section(_build_index(_parse(_SAMPLE)[0]))
# themes / macro / tickers が空でも節は出る
res, _ = _parse(_rep(themes=[], macro=[], tickers=[], movers=[], headline=""))
sec = _section(_build_index(res))
assert "Market Pulse" in sec and "<details" not in sec and "sw-headline" not in sec
print("empty movers OK")

# 25) fetch_stock_report: .json を取得・4日遡り・不正は遡らず省略・失敗しても止まらない
class _Resp:
    def __init__(self, status, body=b""):
        self.status_code, self.content = status, body

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self.content), chunk_size):
            yield self.content[i:i + chunk_size]

    def close(self):
        pass

_real_get = C.requests.get
_urls = []
def _fake_get_factory(ok_days_back):
    def _g(url, **kw):
        _urls.append(url)
        if len(_urls) - 1 == ok_days_back:
            return _Resp(200, json.dumps(_SAMPLE).encode("utf-8"))
        return _Resp(404)
    return _g
_sw_cfg = {"stock_watch": {"enabled": True, "repo": "o/r", "branch": "main"}}
os.environ.pop(C.STOCK_LOCAL_ENV, None)
try:
    C.requests.get = _fake_get_factory(0)
    assert C.fetch_stock_report(_sw_cfg)["edition"] == "daily"
    assert _urls[0] == f"https://raw.githubusercontent.com/o/r/main/reports/{_today}.json", _urls[0]
    _urls.clear(); C.requests.get = _fake_get_factory(3)
    assert C.fetch_stock_report(_sw_cfg) is not None and len(_urls) == 4
    assert _urls[3].endswith(f"/reports/{(C.now_jst() - _dt.timedelta(days=3)).strftime('%Y-%m-%d')}.json")
    _urls.clear(); C.requests.get = _fake_get_factory(4)   # 5日前までは遡らない
    assert C.fetch_stock_report(_sw_cfg) is None and len(_urls) == 4
    # 不正JSONが見つかったら古い日へは進まず None
    _urls.clear()
    def _g_bad(url, **kw):
        _urls.append(url)
        return _Resp(200, json.dumps(_rep(schema_version=2)).encode("utf-8"))
    C.requests.get = _g_bad
    with contextlib.redirect_stderr(io.StringIO()):
        assert C.fetch_stock_report(_sw_cfg) is None
    assert len(_urls) == 1
    # 例外・空応答でも止まらない
    def _g_raise(url, **kw):
        raise RuntimeError("boom")
    C.requests.get = _g_raise
    with contextlib.redirect_stderr(io.StringIO()):
        assert C.fetch_stock_report(_sw_cfg) is None
    C.requests.get = lambda url, **kw: _Resp(200, b"  \n")
    assert C.fetch_stock_report(_sw_cfg) is None
    # 設定: disabled / repo空 / 不正な repo・branch ではリクエストしない
    _urls.clear(); C.requests.get = _fake_get_factory(0)
    for c in [{}, {"stock_watch": {"enabled": False, "repo": "o/r"}}, {"stock_watch": {"enabled": True, "repo": ""}},
              {"stock_watch": {"enabled": True, "repo": "o/r/../x"}},
              {"stock_watch": {"enabled": True, "repo": "o/r", "branch": "../x"}},
              {"stock_watch": {"enabled": True, "repo": "o/r", "branch": "a b"}}]:
        with contextlib.redirect_stderr(io.StringIO()):
            assert C.fetch_stock_report(c) is None, c
    assert _urls == [], "不正設定でネットワークアクセスしている"
finally:
    C.requests.get = _real_get
print("fetch_stock_report OK")

# 25b) 受信サイズ上限はストリーム読み込みの途中で効く / リダイレクトは辿らない
class _BigResp:
    """無限に 64KB チャンクを返す応答。読み出し量を数える。"""
    status_code = 200
    def __init__(self):
        self.yielded, self.closed = 0, False
    def iter_content(self, chunk_size=1):
        while True:
            self.yielded += 1
            yield b" " * chunk_size
    def close(self):
        self.closed = True

try:
    _urls.clear(); _big = _BigResp(); _kw_seen = {}
    def _g_big(url, **kw):
        _urls.append(url); _kw_seen.update(kw)
        return _big
    C.requests.get = _g_big
    with contextlib.redirect_stderr(io.StringIO()) as eb:
        assert C.fetch_stock_report(_sw_cfg) is None
    assert len(_urls) == 1, "サイズ超過は不正扱いで古い日へ遡らない"
    assert _big.closed, "応答が close されていない"
    assert _big.yielded * C.STOCK_STREAM_CHUNK <= C.STOCK_MAX_BYTES + 2 * C.STOCK_STREAM_CHUNK, "上限を超えて読み続けている"
    assert "stock_watch" in eb.getvalue()
    assert _kw_seen.get("stream") is True and _kw_seen.get("allow_redirects") is False
    # 3xx はリダイレクト先を取らず、その日は無いものとして次の日へ
    _urls.clear(); _redir_calls = []
    def _g_redir(url, **kw):
        _urls.append(url); _redir_calls.append(kw.get("allow_redirects"))
        return _Resp(302)
    C.requests.get = _g_redir
    assert C.fetch_stock_report(_sw_cfg) is None
    assert len(_urls) == 4 and set(_redir_calls) == {False}
finally:
    C.requests.get = _real_get
print("stream size cap / no redirect OK")

# 25c) 文字列長・件数の上限（超過は不正、ちょうどは受理）
def _mut(path, value):
    r = copy.deepcopy(_SAMPLE)
    o = r
    for k in path[:-1]:
        o = o[k]
    o[path[-1]] = value
    return r
_T = C.STOCK_MAX_TEXT
assert (C.STOCK_MAX_HEADLINE, _T, C.STOCK_MAX_THEMES, C.STOCK_MAX_MOVERS, C.STOCK_MAX_MACRO,
        C.STOCK_MAX_TICKERS, C.STOCK_MAX_KEYWORDS, C.STOCK_MAX_FAILURES) == (200, 64, 50, 10, 20, 200, 20, 200)
_limit_cases = [  # (名前, パス, 上限ちょうどの値, 超過値)
    ("headline", ["headline"], "あ" * 200, "あ" * 201),
    ("mover.label", ["movers", 0, "label"], "a" * _T, "a" * (_T + 1)),
    ("mover.theme", ["movers", 0, "theme"], "a" * _T, "a" * (_T + 1)),
    ("mover.symbol", ["movers", 0, "symbol"], "a" * _T, "a" * (_T + 1)),
    ("theme.name", ["themes", 0, "name"], "a" * _T, "a" * (_T + 1)),
    ("macro.label", ["macro", 0, "label"], "a" * _T, "a" * (_T + 1)),
    ("ticker.label", ["tickers", 0, "label"], "a" * _T, "a" * (_T + 1)),
    ("keywords 件数", ["movers", 0, "keywords"], ["k"] * 20, ["k"] * 21),
    ("keyword 長", ["movers", 0, "keywords"], ["k" * _T], ["k" * (_T + 1)]),
    ("failures 件数", ["fetch_failures"], ["f"] * 200, ["f"] * 201),
    ("failure 長", ["fetch_failures"], ["f" * _T], ["f" * (_T + 1)]),
    ("themes 件数", ["themes"], [_SAMPLE["themes"][0]] * 50, [_SAMPLE["themes"][0]] * 51),
    ("movers 件数", ["movers"], [_SAMPLE["movers"][0]] * 10, [_SAMPLE["movers"][0]] * 11),
    ("macro 件数", ["macro"], [_SAMPLE["macro"][0]] * 20, [_SAMPLE["macro"][0]] * 21),
    ("tickers 件数", ["tickers"], [_SAMPLE["tickers"][0]] * 200, [_SAMPLE["tickers"][0]] * 201),
]
for name, path, ok_v, ng_v in _limit_cases:
    assert _parse(_mut(path, ok_v))[0] is not None, f"上限ちょうどが拒否された: {name}"
    res, err = _parse(_mut(path, ng_v))
    assert res is None and "stock_watch" in err, f"上限超過が通った: {name}"
print("length/count limits OK")

# 25d) repo の "." / ".." セグメントを拒否（ネットワークへ出ない）
try:
    _urls.clear(); C.requests.get = _fake_get_factory(0)
    for bad_repo in ["../r", "o/..", "./r", "o/.", "..", ".", "o/r/x", "/r", "o/", "o r/x"]:
        with contextlib.redirect_stderr(io.StringIO()):
            assert C.fetch_stock_report({"stock_watch": {"enabled": True, "repo": bad_repo}}) is None, bad_repo
    assert _urls == [], "不正 repo でネットワークアクセスしている"
    for ok_repo in ["ayuka203/stock-price-checker", "o.w/r.x", "a_b/..c", "o/.r"]:
        assert C._REPO_RE.match(ok_repo), ok_repo
finally:
    C.requests.get = _real_get
print("repo segment validation OK")

# 25e) 表示ウィンドウ外 / 除外された記事は mover に紐付かない（build_site 経由）
_kw_rep = _parse(_rep(movers=[{**_SAMPLE["movers"][0], "keywords": ["古河電工"]}]))[0]
_vis = _art("古河電工、超電導ケーブルの量産体制を拡充", "https://x.jp/visible", 2)
_old_pub = {**_art("古河電工の通期予想を上方修正、海底ケーブルが牽引", "https://x.jp/old-published", 1),
            "published": (C.now_jst() - _dt.timedelta(days=30)).isoformat()}          # max_age_days で落ちる
_old_win = {**_art("古河電工と海外メーカーの提携交渉が最終局面に", "https://x.jp/old-window", 1),
            "first_seen": _d3}                                                         # index_window_days=1 で落ちる
_nikkei_old = {**_art("古河電工株が年初来高値を更新して取引を終える", "https://x.jp/nikkei-old", 1, source="日本経済新聞"),
               "published": (C.now_jst() - _dt.timedelta(days=3)).isoformat()}        # per-source max_age_days=1 で落ちる
_vis2 = _art("古河電工の新工場、2027年稼働へ", "https://x.jp/visible2", 1)
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
with contextlib.redirect_stderr(io.StringIO()):
    C.build_site([_vis, _old_pub, _old_win, _nikkei_old, _vis2], cfg["sources"], {**cfg, "index_window_days": 1}, stock_report=_kw_rep)
_idx = (Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8")
_sec = _section(_idx)
for gone in ["old-published", "old-window", "nikkei-old"]:
    assert gone not in _idx, f"index に載らないはずの記事が出ている: {gone}"
    assert gone not in _sec, f"mover に紐付いた: {gone}"
assert "x.jp/visible" in _sec and "x.jp/visible2" in _sec
# タイトル除外で落ちた記事: collect_all の除外後の結果を build_site に渡す
_excl_src = {"name": "テスト媒体", "type": "rss", "url": "https://t.example/rss", "section": "送配電・系統",
             "exclude_title_patterns": ["（人事）"], "keywords": ["古河電工"]}
_real_rss = C.collect_rss
try:
    C.collect_rss = lambda src: [
        {"title": "（人事）古河電工の役員人事を発表", "url": "https://x.jp/hr", "canonical": "https://x.jp/hr",
         "source": "テスト媒体", "section": "送配電・系統", "published": _pub(1)},
        {"title": "古河電工、電力ケーブルの受注が過去最高に", "url": "https://x.jp/keep", "canonical": "https://x.jp/keep",
         "source": "テスト媒体", "section": "送配電・系統", "published": _pub(2)},
        {"title": "他社の電力ケーブル受注動向", "url": "https://x.jp/kwfilter", "canonical": "https://x.jp/kwfilter",
         "source": "テスト媒体", "section": "送配電・系統", "published": _pub(1)},
    ]
    with contextlib.redirect_stderr(io.StringIO()):
        _got = C.collect_all([_excl_src])
finally:
    C.collect_rss = _real_rss
assert [g["canonical"] for g in _got] == ["https://x.jp/keep"]
for g in _got:
    g["first_seen"] = _d1
shutil.rmtree(Path(C.ROOT)/"public", ignore_errors=True)
C.build_site(_got, cfg["sources"], cfg, stock_report=_kw_rep)
_sec = _section((Path(C.ROOT)/"public"/"index.html").read_text(encoding="utf-8"))
assert "x.jp/keep" in _sec and "x.jp/hr" not in _sec and "x.jp/kwfilter" not in _sec
print("window/age/exclude articles not linked OK")

# 26) STOCK_WATCH_LOCAL_JSON: ローカルファイルを読み、ネットワークは使わない
with tempfile.TemporaryDirectory() as td:
    good = Path(td) / "ok.json"
    good.write_text(json.dumps(_rep(edition="weekly"), ensure_ascii=False), encoding="utf-8")
    bad_f = Path(td) / "bad.json"
    bad_f.write_text(json.dumps(_rep(schema_version=9)), encoding="utf-8")
    C.requests.get = lambda *a, **k: (_ for _ in ()).throw(AssertionError("ネットワークを使った"))
    try:
        os.environ[C.STOCK_LOCAL_ENV] = str(good)
        got = C.fetch_stock_report(_sw_cfg)
        assert got is not None and got["edition"] == "weekly"
        # enabled=false なら環境変数があっても読まない
        assert C.fetch_stock_report({"stock_watch": {"enabled": False}}) is None
        with contextlib.redirect_stderr(io.StringIO()) as eb:
            os.environ[C.STOCK_LOCAL_ENV] = str(bad_f)
            assert C.fetch_stock_report(_sw_cfg) is None          # 不正は節ごと省略
            os.environ[C.STOCK_LOCAL_ENV] = str(Path(td) / "missing.json")
            assert C.fetch_stock_report(_sw_cfg) is None          # 無いファイルでも止まらない
            os.environ[C.STOCK_LOCAL_ENV] = td                    # ディレクトリ指定
            assert C.fetch_stock_report(_sw_cfg) is None
        assert "stock_watch" in eb.getvalue()
    finally:
        C.requests.get = _real_get
        os.environ.pop(C.STOCK_LOCAL_ENV, None)
    # 読み込みのみ: ファイルは変更されない
    assert json.loads(good.read_text(encoding="utf-8"))["edition"] == "weekly"
# 同梱フィクスチャ（プレビュー用）も検証を通る
for fx in _FIX.glob("stock_report_sample*.json"):
    assert _parse(fx.read_bytes())[0] is not None, fx.name
print("local json override OK")

# 27) markdown 依存が残っていない
assert not hasattr(C, "md_lib") and not hasattr(C, "render_stock_html")
assert "markdown" not in (Path(C.ROOT)/"requirements.txt").read_text(encoding="utf-8").lower()
print("no markdown dependency OK")

print("ALL OK")
