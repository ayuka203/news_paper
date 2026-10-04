#!/usr/bin/env python3
"""
grid-news collector
  媒体URL(RSS/HTML)を巡回し、前回からの更新分だけを抽出して
  新聞風の静的HTML(public/)を再生成する。
状態は data/state.json と data/archive.jsonl に保存し、
public/ は data/ から毎回完全に再構築する(=GitHub Pages成果物は使い捨て可能)。
"""
from __future__ import annotations
import json, math, os, re, sys, datetime as dt, difflib, unicodedata
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


def _fold(s: str) -> str:
    """部分一致比較用の正規化（NFC + 小文字化）。"""
    return unicodedata.normalize("NFC", s).lower()


def _apply_keywords(items: list[dict], keywords: list[str]) -> list[dict]:
    """タイトルにキーワード（部分一致・大文字小文字無視・NFC正規化）を含む記事だけ残す。
    空リスト・空文字列のみのリストならフィルタなし。"""
    kws = [_fold(k) for k in keywords if k]
    if not kws:
        return items
    return [it for it in items if any(k in _fold(it["title"]) for k in kws)]


def _apply_url_excludes(items: list[dict], patterns: list[str]) -> list[dict]:
    """canonical URL に部分一致するパターンを除外する（大文字小文字無視）。空リストならフィルタなし。"""
    pats = [p.lower() for p in patterns if p]
    if not pats:
        return items
    return [it for it in items if not any(p in it.get("canonical", "").lower() for p in pats)]


def _apply_title_excludes(items: list[dict], patterns: list[str]) -> list[dict]:
    """タイトルに部分一致するパターンを除外する（大文字小文字無視・NFC正規化）。空リストならフィルタなし。"""
    pats = [unicodedata.normalize("NFC", p).lower() for p in patterns if p]
    if not pats:
        return items
    return [
        it for it in items
        if not any(p in unicodedata.normalize("NFC", it.get("title", "")).lower() for p in pats)
    ]


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
            excl_titles = src.get("exclude_title_patterns", [])
            before = len(got)
            got = _apply_title_excludes(got, excl_titles)
            if excl_titles and before != len(got):
                print(f"    title-exclude: {before} -> {len(got)}", file=sys.stderr)
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


# ---------------------------------------------------------------- stock watch
STOCK_SCHEMA_VERSION = 1
STOCK_MAX_BYTES = 1_000_000  # 外部入力のサイズ上限（異常に大きい応答は読まない）
STOCK_LOCAL_ENV = "STOCK_WATCH_LOCAL_JSON"  # プレビュー用: 指定時はネットワーク取得の代わりにこのファイルを読む
STOCK_FLAG_LABELS = {"52w_high": "52週高値", "52w_low": "52週安値", "volume_spike": "出来高急増"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REPO_RE = re.compile(r"^(?!\.{1,2}/)[A-Za-z0-9_.-]+/(?!\.{1,2}$)[A-Za-z0-9_.-]+$")  # "." ".." だけのセグメントは拒否
STOCK_STREAM_CHUNK = 65536
# 上流の改ざん・暴走でページが肥大化しないための上限（超えたら不正扱い）
STOCK_MAX_HEADLINE = 200
STOCK_MAX_TEXT = 64          # label / theme / テーマ名 / symbol / layer / keyword / 失敗銘柄名
STOCK_MAX_THEMES = 50
STOCK_MAX_MOVERS = 10
STOCK_MAX_MACRO = 20
STOCK_MAX_TICKERS = 200
STOCK_MAX_KEYWORDS = 20
STOCK_MAX_FAILURES = 200
STOCK_MAX_FLAGS = 10
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_.][A-Za-z0-9_./-]*$")


def _sv_get(obj, key, where):
    if not isinstance(obj, dict):
        raise ValueError(f"{where}: オブジェクトではない")
    if key not in obj:
        raise ValueError(f"{where}: 必須キー '{key}' がない")
    return obj[key]


def _sv_str(obj, key, where, max_len=STOCK_MAX_TEXT) -> str:
    v = _sv_get(obj, key, where)
    if not isinstance(v, str):
        raise ValueError(f"{where}.{key}: 文字列ではない")
    if len(v) > max_len:
        raise ValueError(f"{where}.{key}: {max_len}文字超過")
    return v


def _sv_num(obj, key, where) -> float | None:
    """数値 or null。bool / NaN / Infinity は不正。"""
    v = _sv_get(obj, key, where)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(f"{where}.{key}: 数値ではない")
    return float(v)


def _sv_bool(obj, key, where) -> bool:
    v = _sv_get(obj, key, where)
    if not isinstance(v, bool):
        raise ValueError(f"{where}.{key}: 真偽値ではない")
    return v


def _sv_date(obj, key, where, nullable=False) -> str | None:
    v = _sv_get(obj, key, where)
    if v is None and nullable:
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        raise ValueError(f"{where}.{key}: YYYY-MM-DD ではない")
    try:
        dt.date.fromisoformat(v)
    except ValueError:
        raise ValueError(f"{where}.{key}: 存在しない日付") from None
    return v


def _sv_list(obj, key, where, max_n) -> list:
    v = _sv_get(obj, key, where)
    if not isinstance(v, list):
        raise ValueError(f"{where}.{key}: 配列ではない")
    if len(v) > max_n:
        raise ValueError(f"{where}.{key}: {max_n}件超過")
    return v


def _sv_str_list(obj, key, where, max_n) -> list[str]:
    v = _sv_list(obj, key, where, max_n)
    if not all(isinstance(x, str) and len(x) <= STOCK_MAX_TEXT for x in v):
        raise ValueError(f"{where}.{key}: 文字列(各{STOCK_MAX_TEXT}字以内)の配列ではない")
    return list(v)


def _sv_flags(obj, where) -> list[str]:
    """未知のフラグ文字列は無視（前方互換）。文字列以外は不正。"""
    return [f for f in _sv_str_list(obj, "flags", where, STOCK_MAX_FLAGS) if f in STOCK_FLAG_LABELS]


def _sv_quote(d, where) -> dict:
    return {
        "symbol": _sv_str(d, "symbol", where),
        "label": _sv_str(d, "label", where),
        "close": _sv_num(d, "close", where),
        "daily_pct": _sv_num(d, "daily_pct", where),
        "weekly_pct": _sv_num(d, "weekly_pct", where),
    }


def _validate_stock_report(obj) -> dict:
    """構造化レポートJSONを検証し、必要なキーだけを持つ正規化済みdictを返す。不正なら ValueError。"""
    where = "report"
    ver = _sv_get(obj, "schema_version", where)
    if isinstance(ver, bool) or ver != STOCK_SCHEMA_VERSION:
        raise ValueError(f"schema_version={ver!r} は未対応（対応: {STOCK_SCHEMA_VERSION}）")
    edition = _sv_str(obj, "edition", where)
    if edition not in ("daily", "weekly"):
        raise ValueError(f"edition={edition!r} は不正")
    asof_raw = _sv_get(obj, "asof", where)
    asof = {
        "JP": _sv_date(asof_raw, "JP", "asof", nullable=True),
        "US": _sv_date(asof_raw, "US", "asof", nullable=True),
        "JP_stale": _sv_bool(asof_raw, "JP_stale", "asof"),
        "US_stale": _sv_bool(asof_raw, "US_stale", "asof"),
    }
    themes = []
    for i, t in enumerate(_sv_list(obj, "themes", where, STOCK_MAX_THEMES)):
        w = f"themes[{i}]"
        n = _sv_get(t, "n", w)
        if isinstance(n, bool) or not isinstance(n, int):
            raise ValueError(f"{w}.n: 整数ではない")
        themes.append({
            "name": _sv_str(t, "name", w), "layer": _sv_str(t, "layer", w),
            "daily_pct": _sv_num(t, "daily_pct", w), "weekly_pct": _sv_num(t, "weekly_pct", w),
            "n": n,
        })
    movers = []
    for i, m in enumerate(_sv_list(obj, "movers", where, STOCK_MAX_MOVERS)):
        w = f"movers[{i}]"
        movers.append({
            **_sv_quote(m, w),
            "theme": _sv_str(m, "theme", w), "z": _sv_num(m, "z", w),
            "flags": _sv_flags(m, w), "keywords": _sv_str_list(m, "keywords", w, STOCK_MAX_KEYWORDS),
        })
    macro = []
    for i, m in enumerate(_sv_list(obj, "macro", where, STOCK_MAX_MACRO)):
        w = f"macro[{i}]"
        macro.append({**_sv_quote(m, w), "asof": _sv_date(m, "asof", w, nullable=True)})
    tickers = []
    for i, t in enumerate(_sv_list(obj, "tickers", where, STOCK_MAX_TICKERS)):
        w = f"tickers[{i}]"
        tickers.append({
            **_sv_quote(t, w),
            "theme": _sv_str(t, "theme", w), "layer": _sv_str(t, "layer", w),
            "z": _sv_num(t, "z", w), "flags": _sv_flags(t, w),
            "asof": _sv_date(t, "asof", w, nullable=True), "stale": _sv_bool(t, "stale", w),
        })
    failures = []
    for i, f in enumerate(_sv_list(obj, "fetch_failures", where, STOCK_MAX_FAILURES)):
        name = f if isinstance(f, str) else (
            (f.get("label") or f.get("symbol")) if isinstance(f, dict) else None)
        if not isinstance(name, str) or len(name) > STOCK_MAX_TEXT:
            raise ValueError(f"fetch_failures[{i}]: 文字列(上限{STOCK_MAX_TEXT}字)でも銘柄オブジェクトでもない")
        failures.append(name)
    return {
        "schema_version": ver, "report_date": _sv_date(obj, "report_date", where),
        "edition": edition, "asof": asof, "headline": _sv_str(obj, "headline", where, STOCK_MAX_HEADLINE),
        "themes": themes, "movers": movers, "macro": macro, "tickers": tickers,
        "fetch_failures": failures,
    }


def parse_stock_report(raw: bytes | str) -> dict | None:
    """レポートJSONを検証つきで読む。不正なら理由をstderrに出して None（=節ごと省略）。"""
    try:
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if len(raw) > STOCK_MAX_BYTES:
            raise ValueError(f"サイズ超過 ({len(raw)} bytes)")

        def _reject_const(name):  # NaN / Infinity は JSON 仕様外
            raise ValueError(f"数値として不正な定数 {name}")

        obj = json.loads(raw.decode("utf-8"), parse_constant=_reject_const)
        return _validate_stock_report(obj)
    except Exception as ex:  # 外部入力なので何が来ても節の省略に倒す
        print(f"  [WARN] stock_watch: レポートJSONが不正のため節を省略: {ex}", file=sys.stderr)
        return None


def _read_capped(resp) -> bytes:
    """応答本文を読みながら累計が STOCK_MAX_BYTES を超えた時点で打ち切る（ValueError）。"""
    buf = bytearray()
    for chunk in resp.iter_content(chunk_size=STOCK_STREAM_CHUNK):
        buf.extend(chunk)
        if len(buf) > STOCK_MAX_BYTES:
            raise ValueError(f"サイズ超過 (>{STOCK_MAX_BYTES} bytes)")
    return bytes(buf)


def _read_local_stock_report(path_str: str) -> dict | None:
    """STOCK_WATCH_LOCAL_JSON のファイルを読む（このパスはこの読み込みにのみ使う）。"""
    try:
        p = Path(path_str)
        if not p.is_file():
            raise ValueError(f"ファイルが存在しない: {p}")
        if p.stat().st_size > STOCK_MAX_BYTES:
            raise ValueError(f"サイズ超過: {p}")
        return parse_stock_report(p.read_bytes())
    except Exception as ex:
        print(f"  [ERR ] stock_watch local json: {ex}", file=sys.stderr)
        return None


def fetch_stock_report(config: dict) -> dict | None:
    """stock-price-checker リポジトリの当日分レポート(JSON)を取得・検証して返す。

    当日分が無ければ前日以前にフォールバックし、それも無ければ None を返し
    (呼び出し側で節ごと省略する)。1媒体扱いなので取得失敗で全体は止めない。
    見つかったJSONが不正（schema_version違い・型不正など）の場合も古い日へは
    遡らず None を返す（古い版の内容を新しい日付として見せないため）。
    環境変数 STOCK_WATCH_LOCAL_JSON があればネットワーク取得の代わりにそのファイルを読む。
    """
    sw = config.get("stock_watch") or {}
    if not sw.get("enabled"):
        return None
    local = os.environ.get(STOCK_LOCAL_ENV)
    if local:
        return _read_local_stock_report(local)
    repo = sw.get("repo", "")
    branch = sw.get("branch", "main")
    if not repo:
        return None
    if not (isinstance(repo, str) and _REPO_RE.match(repo)
            and isinstance(branch, str) and _BRANCH_RE.match(branch) and ".." not in branch):
        print("  [ERR ] stock_watch: repo/branch の形式が不正", file=sys.stderr)
        return None
    for days_back in range(4):  # 週末・祝日で数日空くケースに備えて直近4日分まで遡る
        d = (now_jst() - dt.timedelta(days=days_back)).strftime("%Y-%m-%d")
        url = f"https://raw.githubusercontent.com/{repo}/{branch}/reports/{d}.json"
        try:
            # リダイレクトは辿らない（raw.githubusercontent.com 以外へ飛ばされないように）。本文はストリームで上限つき読み込み
            r = requests.get(url, headers={"User-Agent": UA}, timeout=HTTP_TIMEOUT,
                             stream=True, allow_redirects=False)
            try:
                if r.status_code != 200:
                    continue
                body = _read_capped(r)
            finally:
                r.close()
            if body.strip():
                return parse_stock_report(body)
        except ValueError as ex:  # サイズ超過 = 不正扱い（古い日へは遡らない）
            print(f"  [WARN] stock_watch: レポートJSONが不正のため節を省略 ({d}): {ex}", file=sys.stderr)
            return None
        except Exception as ex:
            print(f"  [ERR ] stock_watch fetch ({d}): {ex}", file=sys.stderr)
    return None


def _safe_http_url(url) -> str | None:
    """http/https かつホスト付きのURLだけ通す（javascript: 等は None）。"""
    if not isinstance(url, str):
        return None
    u = url.strip()
    try:
        p = urlparse(u)
    except ValueError:
        return None
    if p.scheme.lower() not in ("http", "https") or not p.netloc:
        return None
    return u


def _headline_pool(articles: list[dict]) -> list[dict]:
    """照合対象の記事を、新しい順・同値はタイトル順に並べて返す（URLが安全なものだけ）。"""
    pool = []
    for a in articles:
        title = (a.get("title") or "").strip()
        url = _safe_http_url(a.get("url"))
        if not title or url is None:
            continue
        d = parse_date(a.get("published"))
        pool.append({
            "title": title, "url": url, "source": a.get("source") or "",
            "_fold": _fold(title), "_ts": d.timestamp() if d else 0,
            "_tkey": unicodedata.normalize("NFC", title),
        })
    pool.sort(key=lambda x: (-x["_ts"], x["_tkey"], x["url"]))
    return pool


def match_headlines(keywords: list[str], pool: list[dict], limit: int = 2) -> list[dict]:
    """keywords のいずれかをタイトルに含む記事を最大 limit 件返す（pool は _headline_pool の結果）。"""
    kws = [k for k in (_fold(k).strip() for k in keywords) if k]  # 空文字は全件一致になるので除く
    if not kws:
        return []
    out = []
    for a in pool:
        if any(k in a["_fold"] for k in kws):
            out.append({"title": a["title"], "url": a["url"], "source": a["source"]})
            if len(out) >= limit:
                break
    return out


def _fmt_pct(v: float | None) -> dict:
    """小数(0.084) -> {"text": "+8.4%", "cls": "up"}。null は「—」。"""
    if v is None:
        return {"text": "—", "cls": "na"}
    r = round(v * 100, 1) + 0.0  # -0.0 を +0.0 に揃える
    return {"text": f"{r:+.1f}%", "cls": "up" if r > 0 else "down" if r < 0 else "flat"}


def _fmt_price(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def _md_label(d: str | None) -> str:
    if not d:
        return "—"
    _, m, day = d.split("-")
    return f"{int(m)}/{int(day)}"


def build_stock_view(report: dict, articles: list[dict]) -> dict:
    """検証済みレポートを、テンプレートがそのまま描画できる表示用dictに変換する。"""
    weekly = report["edition"] == "weekly"
    asof = report["asof"]
    pool = _headline_pool(articles)
    return {
        "weekly": weekly,
        "headline": report["headline"].strip(),
        "markets": [
            {"name": "日本株", "date": _md_label(asof["JP"]), "stale": asof["JP_stale"]},
            {"name": "米国株", "date": _md_label(asof["US"]), "stale": asof["US_stale"]},
        ],
        "themes": [
            {"name": t["name"], "n": t["n"],
             "daily": _fmt_pct(t["daily_pct"]), "weekly": _fmt_pct(t["weekly_pct"])}
            for t in report["themes"]
        ],
        "movers": [
            {"label": m["label"], "symbol": m["symbol"], "theme": m["theme"],
             "period": "週間" if weekly else "前日比",
             "pct": _fmt_pct(m["weekly_pct"] if weekly else m["daily_pct"]),
             "flags": [STOCK_FLAG_LABELS[f] for f in m["flags"]],
             "headlines": match_headlines(m["keywords"], pool)}
            for m in report["movers"]
        ],
        "macro": [
            {"label": m["label"], "close": _fmt_price(m["close"]),
             "daily": _fmt_pct(m["daily_pct"]), "weekly": _fmt_pct(m["weekly_pct"])}
            for m in report["macro"]
        ],
        "tickers": [
            {"label": t["label"], "symbol": t["symbol"], "theme": t["theme"],
             "close": _fmt_price(t["close"]),
             "daily": _fmt_pct(t["daily_pct"]), "weekly": _fmt_pct(t["weekly_pct"]),
             "flags": [STOCK_FLAG_LABELS[f] for f in t["flags"]],
             "stale": t["stale"], "asof": _md_label(t["asof"])}
            for t in report["tickers"]
        ],
        "failures": list(report["fetch_failures"]),
    }


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


def _render_edition(env, config, date_label, items, order, is_latest, stock=None):
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
        stock=stock,
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


def build_site(all_items: list[dict], sources: list[dict], config: dict,
               stock_report: dict | None = None) -> None:
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

    # Per-source max_age_days を表示時にも適用（global フィルタの後に積み重ねる）
    src_overrides: dict[str, int] = {}
    for s in sources:
        age_raw = s.get("max_age_days")
        if age_raw is None:
            continue
        try:
            age = int(age_raw)
        except (TypeError, ValueError):
            continue
        if age > 0:
            src_overrides[s["name"]] = age

    if src_overrides:
        before = len(window_items)
        cutoffs = {
            name: now_jst() - dt.timedelta(days=days)
            for name, days in src_overrides.items()
        }
        kept = []
        for it in window_items:
            cutoff = cutoffs.get(it.get("source"))
            if cutoff is None:
                kept.append(it)  # per-source 設定なし → そのまま通す
                continue
            d = parse_date(it.get("published"))
            if d is None or d >= cutoff:
                kept.append(it)
        window_items = kept
        if before != len(window_items):
            print(f"index per-source display age filter: {before} -> {len(window_items)}",
                  file=sys.stderr)

    stock_view = None
    if stock_report:
        try:
            stock_view = build_stock_view(stock_report, window_items)
        except Exception as ex:
            print(f"  [ERR ] stock_watch render: {ex}", file=sys.stderr)

    index_label = _window_label(window_dates)
    index_html = _render_edition(env, config, index_label, window_items, order,
                                 is_latest=True, stock=stock_view)
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

    print("stock-watch レポート取得...", file=sys.stderr)
    stock_report = fetch_stock_report(config)
    print(f"  stock_watch: {'取得済み' if stock_report else '該当なし/取得失敗'}", file=sys.stderr)

    build_site(archive, sources, config, stock_report=stock_report)
    print("public/ を再生成しました。", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
