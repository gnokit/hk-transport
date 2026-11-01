# BACKLOG.md

未解決、已知缺口、同已解決的記錄。這裡**不是規格**——規格在 [TASKS.md](TASKS.md)。

**用法：** 開工前由 P0 向下揀。每項有編號、優先級、影響同建議做法。解決後搬到最底「已解決」，保留編號，方便舊 commit 對照。

## 優先級定義

| 級別 | 意思 |
|---|---|
| **P0** | 會令市民搭錯車，或者答案明顯錯 |
| **P1** | 答案唔完整、有已知偏差，或者整個模式答唔到 |
| **P2** | 功能缺口、工程債，唔影響現有答案正確性 |
| **P3** | 文件、雜項、已知但影響很小的問題 |

---

# 未解決

## P0 — 會令市民搭錯車

（暫無。B-35 同 B-36 已解決，見文末。）

## P1 — 答案唔完整或有已知偏差

### B-49 MTR 短途班次未入圖

`mtr_service_core` 用 MTR 官網每站每線的首末班車；但 `mtr_core` 的 trip 只有 full direction（例如金鐘→羅湖），官網卻有短途目的地（例如金鐘→上水）。所以 per-destination 首末班車可能保守地封閉整個方向：23:30 金鐘→上水會因為羅湖尾班車已過而封閉，即使短途班次仍可能開。

**為何 P1：** 深夜會答「接不上」，即使短途班次仍開——係答錯，唔係答少。

**建議：** 把官網的短途目的地變成圖上的 trip variant，或改用 line-level 窗口並在 note 講明「尾班車可能只往部分目的地」。

### B-51 峰值線（960P／960S／603）日間仍然出現

同通宵線同一個成因：TD GTFS 冇呢啲路線的 `calendar`／`frequencies`，所以 `in_service` 係 `None`（未知），唔會封閉。2026-11-01 13:26 查「中環→銅鑼灣」，960P 排第 2；「上環→銅鑼灣」有 960P、960S。

通宵線已用 `_OVERNIGHT_WINDOW` 政策處理；峰值線未有對應政策，因為「P／S 字尾 = 繁忙時間」唔夠可靠（有全日 P 線）。

**為何 P1：** 答案會把一架唔開的車排在前面，市民照等就係搭錯。

**建議：** 由 TD 的 `calendar`／`calendar_dates` 找出冇班次資料的路線清單，人手補一份營運時段表（路線數目有限），或者向運輸署查詢。未補之前，note 要講明「冇服務時間的路線可能唔開」。

### B-22 地區／區域名只解成一個點（收窄，2026-11-01）

原來的具體個案已修：「元朗去攸潭尾」現在會出 37 號小巴（38／37／75 三個方案），因為 800 米半徑同後備規則已經覆蓋到福康街總站。「元朗」亦會加一句講明只代表區內一點。

剩下的問題是**範圍**：`_places.district_note` 只認十八區的名字。`尖沙咀`、`旺角`、`中環` 這類「區域名」若同時是站名就無問題（`place()` 站名完全相符優先），但 `慈雲山`、`秀茂坪`、`沙田市中心` 這類只有地點搜尋的，仍然係一個未標明的點。

**建議：** 用站名以外的方式判斷「區域名」——例如地名結果的 `district_zh` 同名字長度，或者維護一份區域名清單（範圍有限）。答案要繼續講明用咗邊個點，唔好靜靜地當佢代表全區。

### B-23 同一路線掉頭被算成轉車

方案出現「69X 入天瑞總站 → 69X 出天水圍公園」，中間當咗一次轉車，令成本失真。乘客其實係坐同一架車掉頭。

**建議：** 同一路線、同一個站的「轉乘」，如果方向相反而只係總站掉頭，唔應該計一次轉車。新的上車結構（board 接到下一個站）令呢個更容易判斷：同一個 `route_id`、同一個 `point`、相反 `route_seq`。

### B-31 分段收費只在 MDB，讀不到

巴士同小巴都只答**成人全程價**。分段收費有公布，但只在 Access 檔案：`FARE_GMB.mdb`（4.5 MB）、`FARE_BUS.mdb`。同一個數據集的 CSV 只有 delta 清單（`ROUTE_ID, ROUTE_SEQ, CHANGE`），唔係收費表。

**影響：** 「元朗去元朗站幾多錢」只可以答全程 $9.0，短途實際可能更平，答案偏高。

**建議：** 用 `scripts/` 做一次性 MDB → CSV 快照，commit 入 repo，工具層只讀 CSV（同九巴站序快照一樣），唔在查詢時開 Access。

### B-32 渡輪同電車冇班次、冇實時到站

只做到航線、碼頭、票價。「幾點有船」、「尾班船幾點」、「下一班幾時到」全部答唔到。

已有的官方數據：港九小輪 `hkkf-hkkfdata-hkkf-eta-data`（航線、碼頭、時間表、票價、ETA）。`/opendata/route` 同 `/opendata/pier/{id}` 通，**`/opendata/eta/` 的參數格式未確認**。新渡輪時間表要抓營辦商網站（`hkdata` 已有 scraper）。電車冇官方實時數據。

**建議：** 先讀 HKKF 的 API spec PDF（`hkkfeta.com/datagovhk/HKKF_ETA_Data_Dictionary.pdf`），接上 ETA；時間表另做快照。

### B-3 新大嶼山 ETA 找唔到端點

NLB 的路線、站、車費已由運輸署檔案覆蓋（`journey` 用得到），但**下一班**冇。`route.php?action=detail` 交還 0 byte，`eta.php`、`route-stop.php` 都 404。

**建議：** 查 NLB 的 OpenAPI spec；搵唔到就明寫 NLB 冇下一班（同現在一樣）。

### B-38 `journey` 方案多樣性仍然靠 heuristic

修正重複方案封鎖整條線之後，預設 top 3 仍集中同一條走廊：例如「落馬洲→太空館」的三個方案都由東鐵線 LMC-DT 出發，之後轉屯馬線／觀塘線／92R。`penalty` 只加上車成本，唔會真正分散路線；`hard_ban` 只封最後一段落車站，仍然是 heuristic。

**建議：** 考慮用 `networkx.shortest_simple_paths` 或 Yen's algorithm 在兩層圖上做 k-shortest，或用更強的路線多樣性約束（例如每個方案最多重用一條主幹線）。加測試確保 top N 不會被同一走廊壟斷。成本校準已經做完（`tests/data/od_benchmark.json`，40 對），改之前跑 `scripts/check_od_benchmark.py --strict`，就知係改善定只係改變偏差方向。

## P2 — 功能缺口同工程債

### B-39 `_walk_cache` 無上限

`journey._walk_cache` 是 process-level，key 是 rounded coords；同一個 long-lived process 跑很多 journey 會累積，冇 LRU／size cap。CLI 一個 command 一個 process，影響小；library 或 test 長時間跑會慢慢漲。

**建議：** 加 size cap（例如 2,000 對）或 LRU；`clear_cache()` 已有，文件講明幾時清。

### B-40 邊境口岸表 hard-code 座標，冇自動核對

`SKILL.md` 的邊境表有 13 行，hard-code 座標、ImmD 狀態（沙頭角 suspended as of 2026-10-31）同首選輸入名。今次已修正皇崗口岸（stop `10000421`）同 `皇崗`（XB，`12743`）的混淆，但其餘行未經自動測試；TD 改名、新口岸啟用或 ImmD 狀態改變時，表會靜靜過時。

**建議：** 把表搬到獨立 reference（或保留在 SKILL.md 但加 test），測試每個首選名可以在 `journey`／`place_search` 解析到，並在座標附近；營運狀態另加 `as of` 日期。新口岸啟用時要重跑。

### B-50 MTR 班次頻率仍係政策

MTR 官網只公布首末班車，冇公開 headway。`COST["mtr_headway_minutes"]`（AEL 10、東鐵／屯馬 4、東涌 5、市區 3–5）是估算，不是量度。

**建議：** 用 MTR Next Train API 長期抽樣相鄰班次，按線路／時段取中位數；或讀 MTR 時間表 PDF 建立快照。校準前要在 note 講明是 policy。

### B-52 剩餘誤差在車速，唔在搜尋常數

2026-11-01 用 20 對座標 OD 對 Google 校準，`scripts/fit_od.py` 只可以調搜尋期常數（`wait_perception`、`transfer_penalty_minutes`、`access_minutes`）。加了入站時間之後，偏差由 −6.5 分鐘降到約 0，中位誤差 4.3 分鐘。剩下的誤差係車程本身：

- 中環碼頭→長洲 我們 70.8 vs Google 45。渡輪 20 km/h 太慢，但 45 分係快船、55–60 分係普通船，單一速度答不了兩種船。
- 西貢市中心→鑽石山 我們 33.9 vs Google 55。1A 小巴 TD 全程 21 分，Google 卻用 55 分（含步行同轉乘）。
- 馬鞍山→堅尼地城 我們 41.3 vs Google 63。屯馬 50、東鐵 55 km/h 係巡航速度，唔係含站平均。
- 南生圍→中環 我們 59.5 vs Google 102。611 小巴段。

呢四項要改 `speed_kmh`／`line_speed_kmh`，改完要重建圖，所以唔在 grid 內。

**建議：** 逐個改、每次重跑 `uv run python scripts/fit_od.py`，睇 holdout 有冇變差；渡輪要分快船／普通船就先要有航班種類數據。

### B-20 落馬洲站同落馬洲管制站係兩個地方

B1 的終點係「落馬洲站 ‧ 福田口岸」（鐵路），小巴 75 去「落馬洲管制站」（道路），兩處相距約 1,300 米。查「落馬洲」只會解到其中一點。

**建議：** 口岸類地名加 disambiguation（站／管制站／口岸），答案列出兩個並要求指明。

### B-12 出口→地標（「去某座大廈行邊個出口」）

MTR Mobile 有非公開 API（`azumtrmba001v.azurewebsites.net/api/signage`），97 個站、8,277 個地標，帶座標同距離。但唔係 data.gov.hk 開放數據，頁面寫「部份資料由第三方提供」。

**建議：** 先問 `opendata@mtr.com.hk` 可否發布；其間可以照 `mtr_exits` 做快照並標明非官方。

### B-26 交通消息值得有一個獨立入口 `traffic.sh`

交通消息現在只經 `notices` 提供，`mtr.sh` 有兩個命令但屬港鐵技能。巴士改道、封路、渡輪暫停同任何行程都有關。

**建議：** `traffic.sh`，初期 `traffic_news`、`traffic_arrangements`，之後 `traffic_near(place)`。通告只有文字、冇座標，所以「呢個行程有冇受影響」只能做到關鍵字層面。

### B-27 聚合問題：交還表格，唔係加統計命令

「邊條線最多站」、「邊兩條線共用同一個站」呢類問題有無限多條，逐條加命令唔會收斂。基礎數據已經齊（`td_bus_route_stops` 56,103 行、`gmb_route_stops` 13,165 行）。

**建議：** 一個表格命令，交還平表（company, route, seq, stop, name, lat, lon），加 `--route`／`--company`／`--place` 過濾同 `--format csv|ndjson`；預設唔可以無邊界倒全表。唔排名、唔聚合。

### B-4 路線站表快照要人手重建

九巴全部路線站表（`/route-stop`，3 MB）要 `Referer`，重複下載會被限流 403。工具讀 `data/bus_route_stops.json`，重建要跑 `scripts/build_bus_route_stops.py`。

**現況：** 只留給 `bus_eta` 用（KMB 的 ETA 用 16 位十六進制站號，同 TD 的數字站號唔通用）。尋路已改用運輸署檔案。

**建議：** 保留即可；如果日後唔需要 KMB ETA，可以整個快照刪走。

### B-15 Commit 用咗私人電郵

每個 commit 都係 `gnokit@gmail.com`。轉 public 之後人人可見。**建議：** 轉 public 之前決定用唔用 GitHub noreply，改就趁歷史仲短。

## P3 — 文件同雜項

| 編號 | 問題 | 建議 |
|---|---|---|
| **B-5** | 服務時間、班次密度、低地台：三份數據都冇 | 已用 null 命令明確回答；保持現狀 |
| **B-9** | 九巴路線表冇分九巴同龍運 | `bus_route` 仍用 `kmb_routes`；可改用 TD 的 `companyCode` |
| **B-10** | 循環線重複站未核實 | 抽樣 GMB／巴士循環線，確認站序無重複 |
| **B-11** | NLB `someDepartureObserveOnly` 未解析 | 等 B-3 有 ETA 再處理 |
| **B-28** | 活動特別線（269R、SP6） | **巴士部分已解決**：改用 TD 檔案後呢兩條線唔在內。小巴的 `specialType = 1` 係變體標記（黃昏班次等），唔可以當特別線剔走 |
| **B-30** | 南生圍：Google Maps 的答案同方法 | 已記錄六個方案；第三階段綠巴數據有了可以再對照 |
| **B-34** | OSM 步行路線可以補路網缺口 | 已比較五段（地政總署快 5–8 倍、距離較短；南生圍只有 OSM 有路線）。要用就要自架或付費，並遵守 ODbL |
| **B-41** | `journey` 的 `note` 太長、太技術性 | 現在列齊政策數字，再加上地區名提示、放寬半徑提示、GTFS 同 MTR 兩段來源說明；agent 會 quote 給市民，一條 note 可以長過答案本身。建議 note 只講原則，詳細數字放 `journey.sh help` 或 docs |
| **B-53** | Benchmark 係 2026-11-01 的快照，Google 的時間會隨服務改動漂移 | 每次改路線或一年一次重收；`tests/data/od_benchmark.json` 已有 `when` 欄，過期就在 note 講明 |
| **B-43** | `_merge_same_route()` 可能遮蓋真正的同線轉乘 | 現時合併「同 mode、同 route、同 operator、board_point == alight_point」的連續車程；同一路線號碼的分支／循環線可能被當成直通。建議抽樣 GMB／巴士分支線，必要時加 `route_seq` 或方向檢查 |


---

# 已解決（保留記錄）

| 編號 | 題目 | 解決方式 | 日期 |
|---|---|---|---|
| **B-1** | 跨營辦商站點身份 | 運輸署 `JSON_BUS.json` 本身共用數字站號（4,490 個之中 2,366 個跨營辦商）；剩餘的對面街個案由步行邊處理 | 2026-10-30 |
| **B-2** | 城巴冇 bulk 路線站表 | 判斷錯誤：`JSON_BUS.json` 一直有齊（CTB 17,359 行、665 個變體） | 2026-10-30 |
| **B-6** | 車費同全程時間唔在 ETA 數據集 | 接入 `hk-td-tis_23` 的 `JSON_BUS.json`／`JSON_GMB.json` | 2026-10-30 |
| **B-21** | 跨模式旅程圖 | `journey.py`：港鐵＋全部專營巴士＋小巴＋電車＋渡輪一張圖，步行由地政總署路網定價 | 2026-10-30 |
| **B-24** | `locEndNameE` 夾住英文提示 | `bus_core._station_name` 分開名同備註 | 2026-10-30 |
| **B-25** | 兩個來源只可以在路線號碼上對齊 | 規則寫入 `AGENTS.md`；尋路改用運輸署檔案，ETA 另用營辦商數據 | 2026-10-30 |
| **B-29** | 冇步行轉乘邊 | 圖上加步行邊（300 米、港鐵 450 米，每點 20 個鄰居，優先連港鐵／渡輪／電車） | 2026-10-30 |
| **B-33** | 第五階段冇開放數據 | 取消第五階段；跨境鐵路（羅湖／落馬洲）本來已在東鐵線數據內 | 2026-10-30 |
| **B-35** | `journey` 建議通宵線 | 用 `^N(?:[AB])?\d` 同尾綴 `\dN` 認通宵線；GTFS 冇佢哋的 `calendar`，所以 `in_service` 係 `None`（未知）。2026-11-01 起 00:00–06:00 以外當停駛（`_OVERNIGHT_WINDOW`），深夜仍保留並標 `overnight_hint`、排在日間路線之後 | 2026-10-30（2026-11-01 改為按時段過濾） |
| **B-36** | 跨境巴士令市內行程繞經皇崗 | `companyCode` XB（旺角—皇崗、油尖—皇崗）唔入圖；佢哋唯一共用的站係口岸，留低會出現「觀塘 → 荃灣 經皇崗」。有測試防止再加 | 2026-10-30 |
| **B-47** | `journey` 重複方案封鎖整條線，令全港鐵／T270 消失 | 重複時只封最後一段落車站，唔再封 `(mode, key)` 整條線；連續同線、同接駁站的車程由 `_merge_same_route()` 合併；加 synthetic trunk regression test（舊 code 會 fail） | 2026-11-01 |
| **B-48** | 皇崗口岸邊境表叫 agent 避開正確的港方口岸站 | 分開 `皇崗口岸`（TD stop `10000421`，新港方口岸，B10/B11/B12/B13/B14/B15/NB73）、`皇崗`（stop `12743`，只有 XB 跨境巴士）同 `落馬洲管制站`（舊道路口岸）；`SKILL.md` 同步 | 2026-11-01 |
| **B-7** | `as_hkt` 唔識 `YYYY/MM/DD HH:MM` | 支援斜線日期、16 字元（無秒）同日期-only；加 `tests/test_result.py` | 2026-11-01 |
| **B-8** | 茘枝角 vs 荔枝角 | 新增 `_names.station_name()` 將「荔枝角」正規化為公布的「茘枝角」；`mtr.py` 同 `exits.py` 共用，加 test | 2026-11-01 |
| **B-13** | `/hk-transport` 斜線命令未註冊 | 從 `SKILL.md` 描述刪走；同時修正「Not tram, ferry」的矛盾 | 2026-11-01 |
| **B-14** | 最近車站組合冇公開入口 | `SKILL.md` 講明用 `journey` 或單一車站的 `mtr_exits`，唔好放寬 `mtr_exits` | 2026-11-01 |
| **B-16** | CI 徽章係靜態 | 兩個 README 刪走私人 repo 會 404 的 CI 徽章，保留其餘 badge | 2026-11-01 |
| **B-17** | 冇 lint／format 工具 | 加 `ruff` dev dependency、`[tool.ruff]` 同 CI `ruff check`；修 15 個 lint error，包括 `bus.py` 未定義的 `_view`（補 helper + test） | 2026-11-01 |
| **B-18** | 冇 SECURITY／CONTRIBUTING／dependabot | 加 `SECURITY.md`、`CONTRIBUTING.md`、`.github/dependabot.yml` | 2026-11-01 |
| **B-19** | 文件內的測試數字會漂移 | README／TASKS 的固定測試數字改成不含數字的描述 | 2026-11-01 |
| **B-42** | `_note_from_cost()` 用 bus 代表巴士／小巴 | 分開印 bus 同 minibus 的 board/speed；加 note test | 2026-11-01 |
| **B-44** | `journey.sh help` 叫讀者看 `COST in journey.py` | Help 直接由 `COST` 印 board wait；加 test 確保冇 "see COST" | 2026-11-01 |
| **B-46** | Fork PR 冇 GitHub checks | 加 `.github/pull_request_template.md`；`CONTRIBUTING.md` 講明 maintainer 要本地跑 full suite | 2026-11-01 |
| **B-37** | 特快巴士被 flat 車速低估 | 車上時間改用運輸署公布的全線時間按距離比例分配，15 km/h 只做冇公布時間時的後備；T270 全程 67 分已入表。剩餘的特快線誤差（X9 高估 19 分、970 系）改由 B-52 跟 | 2026-11-01 |
| **B-45** | 真實網絡 regression 未覆蓋 | 改用 40 對真座標 OD benchmark（`tests/data/od_benchmark.json`，20 調參 + 20 留出），`scripts/check_od_benchmark.py` 可重跑並在退化時 exit 1 | 2026-11-01 |
