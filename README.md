# grid-news — 毎朝自動生成される新聞風ニュースダイジェスト

媒体URL（RSS / HTML）を毎朝巡回し、**前回からの更新分だけ**を抽出・重複排除して、
新聞風の静的サイトを GitHub Pages に公開します。PC不要・無料（GitHub Actions）。

## 仕組み
```
sources.json ──► collector.py ──► public/index.html（最新号）
 (監視媒体)        RSS/HTMLを収集      public/archive/YYYY-MM-DD.html（過去号）
                  差分=更新分のみ
                  正規URL+タイトル類似で重複排除
                  ▲ 状態は data/ に保存（毎回ここから再構築）
GitHub Actions が毎朝 07:00 JST に実行 → Pages へ自動公開
```

## セットアップ（初回のみ）
1. このフォルダを GitHub の新規リポジトリにpush
2. リポジトリの **Settings → Pages → Build and deployment → Source** を **GitHub Actions** に設定
3. **Settings → Actions → General → Workflow permissions** を **Read and write** に設定
4. `sources.json` に監視したい媒体を記入（下記）
5. **Actions タブ → daily-newspaper → Run workflow** で初回手動実行
6. 公開URL（`https://<ユーザー名>.github.io/<リポジトリ名>/`）を開いて確認

以降は毎朝 07:00 JST に自動更新。時刻は `.github/workflows/daily.yml` の cron（UTC）で調整。

## sources.json の書き方
```jsonc
{
  "name":    "媒体名",          // 紙面に表示される出典
  "type":    "rss" | "html",    // RSSがあれば必ず rss を使う（確実）
  "url":     "https://...",     // rss=フィードURL / html=記事一覧ページURL
  "section": "規制・政策",       // 紙面のセクション
  // type=html のときだけ：
  "item_selector": "ul.news li a", // 記事リンクのCSSセレクタ
  "date_selector": "time",         // (任意) 日付要素のセレクタ
  "base": "https://..."            // (任意) 相対リンク補完用のドメイン
}
```
`section_order` で紙面のセクション順を指定できます。

## ローカルでの確認
```bash
pip install -r requirements.txt
python collector.py          # public/ を生成
# public/index.html をブラウザで開く
```

## 調整ポイント
- 重複判定の厳しさ: `collector.py` の `SIM_THRESHOLD`（0.82。上げると重複に厳しく）
- cron時刻: `daily.yml` の `0 22 * * *`（= 07:00 JST）
- 紙面名: `sources.json` の `masthead` / `subtitle`

## 登録済みの媒体（初期設定）
| 媒体 | 取得方式 | 備考 |
|---|---|---|
| EIA Today in Energy | ネイティブRSS | 確認済み。プレスは `press_rss.xml` |
| Oxford Energy | ネイティブRSS | `/feed/`（WordPress想定）。0件ならgoogle_newsへ |
| World Nuclear News | Google News | site:指定 |
| T&D World | Google News | site:指定 |
| 経済産業省（エネルギー） | Google News | 完全網羅は `meti.go.jp/rss/` のネイティブRSSへ差替推奨 |
| METI Journal | Google News | ネイティブRSSあり（`journal.meti.go.jp/new-rss/`） |
| 電気新聞 | Google News | site:指定 |
| 日本経済新聞（エネルギー） | Google News | ネイティブRSS無し・有料。見出し＋リンクのみ |

### Google News RSS について
RSSが無い／自動取得が弾かれる媒体は **Google News** を経由してRSS化しています
（`type: google_news`＋`query`）。任意サイトを `site:ドメイン` で指定でき、有料媒体でも
見出しとリンクは取得可能。記事リンクは Google News 経由のリダイレクトURLになりますが、
クリックすれば発行元へ遷移し、重複判定も問題なく機能します。

### 注意（初回実行で要確認）
- ネイティブRSSのURL（Oxford等）が変わっていると0件になります。Actionsのログで各媒体の取得件数が出るので、0件の媒体は `query`/`url` を調整してください。
- Google News は大量・高頻度アクセスでレート制限がかかる場合あり。日次・低頻度なら問題ありません。
- 政府系サイトを直接スクレイプ（type:html）する場合は各サイトの利用規約・robotsに従ってください。本構成は極力RSS/Google News経由にしています。
