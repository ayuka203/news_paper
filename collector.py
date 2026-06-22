#!/usr/bin/env python3
"""
grid-news collector
  媒体URL(RSS/HTML)を巡回し、前回からの更新分だけを抽出して
  新聞風の静的HTML(public/)を再生成する。
状態は data/state.json と data/archive.jsonl に保存し、
public/ は data/ から毎回完全に再構築する(=GitHub Pages成果物は使い捨て可能)。
"""
from __future__ import annotations
import json, os, re, sys, datetime as dt, difflib, unicodedata
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dtparser
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
PUBLIC = ROOT / "public"
TEMPLATES = ROOT / "templates"
STATE_FILE = DATA / "state.json"
JSONL = DATA / "archive.jsonl"

JST = dt.timezone(dt.timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; GridNewsBot/1.0; +https://github.com/)"
HTTP_TIMEOUT = 20
SIM_THRESHOLD = 0.82  # タイトル類似度の重複しきい値
TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_src|spm|igshid)")


# ---------------------------------------------------------------- utilities
def now_jst() -> dt.datetime:
    return dt.datetime.now(JST)


def today_str() -> str:
    return now_jst().strftime("%Y-%m-%d")


def canonical_url(u: str) -> str:
    """トラッキングパラメータと末尾スラッシュ等を除いた正規URL。"""
    u = (u or "").strip()
    try:
        p = urlparse(u)
    except Exception:
        return u
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=False)
         if not TRACKING.match(k.lower())]
    path = p.path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower() or "https", p.netloc.lower(),
                       path, "", urlencode(q), ""))


def norm_title(t: str) -> str:
    t = re.sub(r"\s+", "", t or "")
    t = re.sub(r"[【】\[\]（）()\u3000ー―—–\-|:：・,，、。．.]", "", t)
    return t.lower()


def parse_date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    try:
        d = dtparser.parse(s, fuzzy=True)
        if d.tzinfo is None:
            d = d.replace(tzinfo=JST)
        return d.astimezone(JST)
    except Exception:
        return None


def http_get(url: str) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- collectors
def collect_rss(src: dict) -> list[dict]:
    try:
        r = http_get(src["url"])
        feed = feedparser.parse(r.content)
    except Exception:
        feed = feedparser.parse(src["url"])
    gn = src.get("google_news", False)
    out = []
    for e in feed.entries:
        link, title = (e.get("link") or "").strip(), (e.get("title") or "").strip()
        if not link or not title:
            continue
        source_name = None
        if gn:
            # Google News のタイトル末尾 " - 媒体名" を除去し、媒体名を出典にする
            m = re.match(r"^(.*)\s+-\s+([^-]{1,40})$", title)
            if m:
                title = m.group(1).strip()
            so = e.get("source")
            if isinstance(so, dict) and so.get("title"):
                source_name = so["title"]
        out.append(_item(src, title, link,
                         e.get("published") or e.get("updated") or "", source_name))
    return out


def collect_google_news(src: dict) -> list[dict]:
    """任意サイト/トピックを Google News 経由でRSS化して取得。"""
    from urllib.parse import quote
    q = quote(src["query"])
    hl = src.get("hl", "ja")
    gl = src.get("gl", "JP")
    ceid = src.get("ceid", "JP:ja")
    url = f"https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={ceid}"
    return collect_rss({**src, "url": url, "google_news": True})


def collect_html(src: dict) -> list[dict]:
    r = http_get(src["url"])
    soup = BeautifulSoup(r.text, "html.parser")
    up = urlparse(src["url"])
    base = src.get("base") or f"{up.scheme}://{up.netloc}"
    out = []
    for node in soup.select(src["item_selector"]):
        a = node if node.name == "a" else node.find("a")
        if not a or not a.get("href"):
            continue
        href = a["href"].strip()
        if href.startswith("//"):
            href = up.scheme + ":" + href
        elif href.startswith("/"):
            href = base + href
        elif not href.startswith("http"):
            href = base + "/" + href.lstrip("/")
        title = a.get_text(" ", strip=True)
        if src.get("title_selector"):
            tn = node.select_one(src["title_selector"])
            if tn:
                title = tn.get_text(" ", strip=True)
        if not title:
            continue
        published = ""
        if src.get("date_selector"):
            dn = node.select_one(src["date_selector"])
            if dn:
                published = dn.get_text(" ", strip=True)
        out.append(_item(src, title, href, published))
    return out


def _item(src: dict, title: str, url: str, published: str,
          source_name: str | None = None) -> dict:
    return {
        "title": title,
        "url": url,
        "canonical": canonical_url(url),
        "source": source_name or src["name"],
        "section": src.get("section", "ニュース"),
        "published": published,
    }


def _apply_keywords(items: list[dict], keywords: list[str]) -> list[dict]:
    """タイトルにキーワード（部分一致・大文字小文字無視・NFC正規化）を含む記事だけ残す。
    空リスト・空文字列のみのリストならフィルタなし。"""
    kws = [unicodedata.normalize("NFC", k).lower() for k in keywords if k]
    if not kws:
        return items
    return [
        it for it in items
        if any(k in unicodedata.normalize("NFC", it["title"]).lower() for k in kws)
    ]


def _apply_url_excludes(items: list[dict], patterns: list[str]) -> list[dict]:
    """canonical URL に部分一致するパターンを除外する（大文字小文字無視）。空リストならフィルタなし。"""
    pats = [p.lower() for p in patterns if p]
    if not pats:
        return items
    return [it for it in items if not any(p in it.get("canonical", "").lower() for p in pats)]


def _filter_by_age(items: list[dict], max_days: int | None) -> list[dict]:
    """published 日付が max_days より古いものを除外。published 不明は保持。
    max_days=None または <=0 はフィルタなし。"""
    if max_days is None or max_days <= 0:
        return items
    cutoff = now_jst() - dt.timedelta(days=max_days)
    out = []
    for it in items:
        d = parse_date(it.get("published"))
        if d is None or d >= cutoff:
            out.append(it)
    return out


def collect_all(sources: list[dict]) -> list[dict]:
    items = []
    for src in sources:
        kind = src.get("type", "rss")
        try:
            if kind == "html":
                got = collect_html(src)
            elif kind == "google_news":
                got = collect_google_news(src)
            else:
                got = collect_rss(src)
            kw = src.get("keywords", [])
            before = len(got)
            got = _apply_keywords(got, kw)
            if kw and before != len(got):
                print(f"    keyword filter: {before} -> {len(got)}", file=sys.stderr)
            excl = src.get("exclude_url_patterns", [])
            before = len(got)
            got = _apply_url_excludes(got, excl)
            if excl and before != len(got):
                print(f"    url-exclude: {before} -> {len(got)}", file=sys.stderr)
            src_age_raw = src.get("max_age_days")
            try:
                src_age = int(src_age_raw) if src_age_raw is not None else None
            except (TypeError, ValueError):
                print(f"    WARN: max_age_days='{src_age_raw}' は無効。このソースでは適用しません。", file=sys.stderr)
                src_age = None
            if src_age is not None and src_age > 0:
                before = len(got)
                got = _filter_by_age(got, src_age)
                for it in got:
                    it["_age_done"] = True  # main の global filter をスキップ
                if before != len(got):
                    print(f"    per-source age filter ({src_age}d): {before} -> {len(got)}", file=sys.stderr)
            items.extend(got)
            print(f"  [{kind:11}] {src['name']}: {len(got)} 件", file=sys.stderr)
        except Exception as ex:  # 1媒体の失敗で全体を止めない
            print(f"  [ERR ] {src['name']}: {ex}", file=sys.stderr)
    return items


# ---------------------------------------------------------------- state / diff
def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"seen": {}}


def load_archive() -> list[dict]:
    if not JSONL.exists():
        return []
    rows = []
    for line in JSONL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def dedup(items: list[dict]) -> list[dict]:
    """正規URL一致 → タイトル類似度の2段で重複除去。"""
    out, seen_canon, kept_titles = [], set(), []
    for it in items:
        if it["canonical"] in seen_canon:
            continue
        nt = norm_title(it["title"])
        if nt and any(difflib.SequenceMatcher(None, nt, p).ratio() >= SIM_THRESHOLD
                      for p in kept_titles):
            continue
        seen_canon.add(it["canonical"])
        kept_titles.append(nt)
        out.append(it)
    return out


# ---------------------------------------------------------------- rendering
def _section_order(sources: list[dict], config: dict) -> list[str]:
    if config.get("section_order"):
        return config["section_order"]
    order, seen = [], set()
    for s in sources:
        sec = s.get("section", "ニュース")
        if sec not in seen:
            seen.add(sec)
            order.append(sec)
    return order


def _render_edition(env, config, date_label, items, order, is_latest):
    by_sec: dict[str, dict[str, list]] = {}
    for raw in items:
        it = dict(raw)  # シャローコピーで元 dict の汚染を防ぐ
        d = parse_date(it.get("published"))
        it["_sort"] = d.timestamp() if d else 0
        it["date_display"] = f"{d.month}月{d.day}日" if d else ""
        by_sec.setdefault(it.get("section", "ニュース"), {}).setdefault(it.get("source", "不明"), []).append(it)

    sections = []
    for sec in order + [s for s in by_sec if s not in order]:
        if sec not in by_sec:
            continue
        # source ごとにグループ化、各グループ内は日付降順
        groups = []
        for src_name, arts in by_sec[sec].items():
            arts_sorted = sorted(arts, key=lambda x: x["_sort"], reverse=True)
            groups.append({"source": src_name, "arts": arts_sorted})
        # source グループは、最新記事の日付が新しい順で並べる。同率はソース名昇順で安定化
        groups.sort(key=lambda g: (-g["arts"][0]["_sort"], g["source"]))
        total_in_sec = sum(len(g["arts"]) for g in groups)
        sections.append({"name": sec, "groups": groups, "total": total_in_sec})

    tmpl = env.get_template("newspaper.html.j2")
    return tmpl.render(
        masthead=config.get("masthead", "DAILY NEWS"),
        subtitle=config.get("subtitle", ""),
        kicker=config.get("kicker", ""),
        edition_date=date_label,
        sections=sections,
        total=len(items),
        is_latest=is_latest,
        generated=now_jst().strftime("%Y-%m-%d %H:%M JST"),
    )


def _date_label(d: str) -> str:
    try:
        y, m, day = d.split("-")
        return f"{y}年{int(m)}月{int(day)}日"
    except Exception:
        return d


def _window_label(window_dates: list[str]) -> str:
    """ローリングウィンドウのedition_date文字列を生成する。

    - 空: today_str() を _date_label に通したもの
    - 1日: _date_label と同じ
    - 複数日: "{古い側} 〜 {新しい側}" 形式
    """
    if not window_dates:
        return _date_label(today_str())
    if len(window_dates) == 1:
        return _date_label(window_dates[0])
    end = window_dates[0]
    start = window_dates[-1]
    return f"{_date_label(start)} 〜 {_date_label(end)}"


def build_site(all_items: list[dict], sources: list[dict], config: dict) -> None:
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC / "archive").mkdir(exist_ok=True)
    (PUBLIC / ".nojekyll").write_text("")
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)),
                      autoescape=select_autoescape(["html", "j2"]))
    order = _section_order(sources, config)

    by_date: dict[str, list] = {}
    for it in all_items:
        by_date.setdefault(it.get("first_seen", today_str()), []).append(it)
    dates = sorted(by_date.keys(), reverse=True)

    # 各日付のアーカイブを生成（is_latest=False）
    deduped_by_date: dict[str, list] = {}  # dedup 結果のキャッシュ
    for d in dates:
        items = dedup(by_date[d])
        deduped_by_date[d] = items
        html = _render_edition(env, config, _date_label(d), items, order,
                               is_latest=False)
        (PUBLIC / "archive" / f"{d}.html").write_text(html, encoding="utf-8")

    # index.html は直近N日のローリングウィンドウ
    raw_window = config.get("index_window_days", 7)
    try:
        window_days = int(raw_window)
    except (TypeError, ValueError):
        print(f"WARN: index_window_days='{raw_window}' は無効な値です。7日にフォールバックします。",
              file=sys.stderr)
        window_days = 7
    if window_days < 1:
        print(f"WARN: index_window_days={window_days} が 1 未満です。1日にクリップします。",
              file=sys.stderr)
        window_days = 1

    window_dates = dates[:window_days]
    window_items = []
    for d in window_dates:
        window_items.extend(deduped_by_date[d])  # キャッシュから取得
    window_items = dedup(window_items)
    try:
        display_max_age = int(config.get("max_age_days", 7))
    except (TypeError, ValueError):
        display_max_age = 7
    if display_max_age > 0:
        before = len(window_items)
        window_items = _filter_by_age(window_items, display_max_age)
        if before != len(window_items):
            print(f"index display age filter: {before} -> {len(window_items)}", file=sys.stderr)
    index_label = _window_label(window_dates)
    index_html = _render_edition(env, config, index_label, window_items, order,
                                 is_latest=True)
    (PUBLIC / "index.html").write_text(index_html, encoding="utf-8")

    # 過去号インデックス
    links = "\n".join(
        f'<li><a href="{d}.html">{_date_label(d)}</a> '
        f'<span>{len(deduped_by_date[d])}本</span></li>' for d in dates)
    (PUBLIC / "archive" / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><title>過去号</title>'
        f'<style>body{{font-family:"Noto Serif JP",serif;max-width:640px;'
        f'margin:3rem auto;padding:0 1rem}}a{{color:#7a1f2b}}'
        f'li{{margin:.4rem 0}}span{{color:#999;font-size:.85em}}</style>'
        f'<h1>過去号</h1><p><a href="../index.html">&larr; 最新号</a></p>'
        f"<ul>{links}</ul>", encoding="utf-8")


# ---------------------------------------------------------------- main
def main() -> int:
    cfg = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    sources = cfg["sources"] if isinstance(cfg, dict) else cfg
    config = cfg if isinstance(cfg, dict) else {}

    state = load_state()
    seen = state["seen"]
    archive = load_archive()

    print("収集開始...", file=sys.stderr)
    fetched = collect_all(sources)

    # 鮮度フィルタ: published が古いものは新規として採用しない
    try:
        max_age = int(cfg.get("max_age_days", 7))
    except (TypeError, ValueError):
        print(f"WARN: max_age_days が無効。7日にフォールバック。", file=sys.stderr)
        max_age = 7
    if max_age > 0:
        before = len(fetched)
        cutoff = now_jst() - dt.timedelta(days=max_age)
        out = []
        pre = 0
        for it in fetched:
            if it.pop("_age_done", False):
                out.append(it)
                pre += 1
                continue
            d = parse_date(it.get("published"))
            if d is None or d >= cutoff:
                out.append(it)
        fetched = out
        print(f"鮮度フィルタ: {before} -> {len(fetched)} 件 (max_age={max_age}d, per-source pre-filtered: {pre})", file=sys.stderr)

    today = today_str()
    new = []
    for it in fetched:
        c = it["canonical"]
        if c in seen:
            continue
        seen[c] = today
        it["first_seen"] = today
        new.append(it)
    new = dedup(new)
    print(f"新着 {len(new)} 件 / 取得 {len(fetched)} 件", file=sys.stderr)

    if new:
        with JSONL.open("a", encoding="utf-8") as f:
            for it in new:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        archive.extend(new)

    DATA.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=0),
                          encoding="utf-8")

    build_site(archive, sources, config)
    print("public/ を再生成しました。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
