import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collector as C

S = [
 ("規制・政策","資源エネルギー庁","2026-06-15","無電柱化推進計画（第3期）の進捗フォローアップを公表"),
 ("規制・政策","電気新聞","2026-06-14","容量市場 2030年度オークション 制度詳細を公開"),
 ("規制・政策","METI","2026-06-13","GX2040ビジョン 中間とりまとめへ意見公募開始"),
 ("規制・政策","ARERA","2026-06-12","レジリエンス投資の追加報酬枠組みを改定"),
 ("送配電・系統","OCCTO","2026-06-15","広域系統長期方針の改定案 ヒアリング結果を整理"),
 ("送配電・系統","Ofgem","2026-06-14","RIIO-ED3 ドラフト決定 配電投資の総額を提示"),
 ("送配電・系統","ENTSO-E","2026-06-13","系統安定度の域内評価 2026年版を発行"),
 ("送配電・系統","CNMC","2026-06-11","配電報酬方式の見直し案にパブコメ"),
 ("原子力","原子力規制委員会","2026-06-15","新検査制度の運用ガイド改訂版を了承"),
 ("原子力","NRC","2026-06-14","TMI-1 再稼働申請 補足資料の審査スケジュールを更新"),
 ("原子力","JAEA","2026-06-12","HTTR を用いた水素製造実証の中間成果を報告"),
 ("海外","DOE","2026-06-15","GRIP 第3次公募 採択プロジェクト一覧を発表"),
 ("海外","RTE","2026-06-13","2035年に向けた系統整備シナリオを更新"),
 ("海外","Reuters","2026-06-12","EU Grids Package 関連の実施規則案が明らかに"),
]
items=[]
for i,(sec,src,d,t) in enumerate(S):
    u=f"https://example.org/{i}"
    items.append({"title":t,"url":u,"canonical":u,"source":src,"section":sec,
                  "published":d,"first_seen":"2026-06-16"})
cfg=json.loads((Path(C.ROOT)/"sources.json").read_text(encoding="utf-8"))
C.build_site(items, cfg["sources"], cfg)
print("demo built:", len(items), "articles")
