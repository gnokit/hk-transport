# AGENTS.md

這個倉庫是港交寶（`hk-transport`），一個 AI skill。第一階段的港鐵工具已實作。代理指示在 [SKILL.md](SKILL.md)。回答市民時用 `mtr.sh`，`$SKILL_DIR` 是安裝目錄：`bash ${SKILL_DIR}/mtr.sh` 列出命令，`bash ${SKILL_DIR}/mtr.sh help <command>` 看該命令。新的公開函式要在 `mtr.sh` 加子命令。開工前先讀 [docs/TASKS.md](docs/TASKS.md)。那份文件是第一階段的範圍。

程式分兩層。`src/hk_transport/mtr_core.py` 一個函式包一份港鐵數據。`src/hk_transport/als.py` 的 `address_lookup` 包地政總署地址查詢，是位置問題的核心，不快取。`src/hk_transport/exits.py` 的 `mtr_exits` 讀重鐵出入口座標，那是約一年有效的快照，查詢時不重新下載。`src/hk_transport/notices.py` 包運輸署特別交通消息和特別交通及運輸安排，全港交通都在內，不快取，也不按港鐵篩選。`src/hk_transport/mtr.py` 用這些函式回答市民的問題，裡面沒有 URL，也沒有快取。新的問題組合現有核心函式。新的數據源才加一個核心函式。三份共用的東西各有去處：`_result.py` 是信封同 `compose`，`_http.py` 是下載同 30 日快取，`_values.py` 是讀一格。

每月 CSV 的副本在技能目錄的 `.cache/`，30 日後重新下載。`.gitignore` 已忽略這個目錄。測試用 `HK_TRANSPORT_CACHE` 指到暫存目錄。實時 API 不寫入快取。出入口快照在 `src/hk_transport/data/mtr_exits.json`，不放進 `.cache/`。同一個進程內另有一份記憶快取（`mtr_core._memory`），避免一次回答內重複解析同一份表；`clear_cache()` 清。

```bash
uv run pytest
uv run pytest -m live -o addopts=
```

## 這個 skill 做什麼

向代理提供工具。代理用工具回答市民的交通問題。工具不跟市民對話，不挑選「最好的行程」，不把沒有的數字補上。

每個工具回答一整類問題，回傳可序列化的 JSON，並帶：

- 資料集編號
- 實際查過的端點
- 數據本身的時間（香港時間）

檔案沒有時間欄時，寫明更新頻率，並把擷取時間同數據時間分開。缺的欄位留空並說明。

## 現在可以做的事

第一階段 1.1 至 1.10 已在 `mtr.py`。`address_lookup`、`mtr_exits`、`special_traffic_news`、`special_traffic_arrangements` 是核心函式，不在 `mtr.py`。後面的交通系統可以重用這兩份運輸署消息。尚未寫進 `docs/TASKS.md` 的交通系統不要先做。這包括專營巴士、綠色專線小巴、香港電車、渡輪、的士、紅色小巴、跨境鐵路。`hkdata` 裡已有的九巴和新渡輪程式留在 `hkdata`，不複製過來。

## 港鐵資料裡容易答錯的地方

- 東鐵線有羅湖和落馬洲兩條分支（`DT`／`UT` 與 `LMC-DT`／`LMC-UT`）。將軍澳線有康城分支（`TKS-DT`／`TKS-UT`）。一條線的車站按方向交還。
- 轉車用共用的車站編號。機場快線香港站（44）、東涌線香港站（39）、中環站（1）編號不同，要當成同一個轉乘點。
- 一個站名可以對應多於一個車站，例如香港有 39 同 44。列表類問題（路線、車費、無障礙設施）把每一對都列出，並在 note 說明。只有一個答案的問題（路徑、車上時間、下一班、輕鐵下一班、巴士路線）不代為揀一個，交還候選並在 note 說明。呼叫的人可以用車站編號或代碼指定，那就沒有歧義。
- 重鐵車費是站對站，與路徑無關。車費 CSV 的站名是英文（`Central`、`Hung Hom`）；中文名在路線 CSV，用車站編號連接。機場快線車費用另一份 CSV，只有成人同小童。
- 重鐵下一班、機場快線下一班、迪士尼線下一班是同一個 API。每個方向最多 4 班。沒有警報時寫「這次回應沒有特別安排」，不寫「全線正常」。API 沒有交 `status` 時，寫「這次回應沒有車務狀態，不能說有沒有特別安排」，不要當成正常。`status` 為 0，或有延誤、警報連結時，`message` 和 `url` 就是該站該線的警報，note 是「這一站這一線的回應有特別安排。全港特別交通消息要再查 special_traffic_news。」`mtr_next_train` 不代為下載那份消息。預先公布的安排用 `special_traffic_arrangements`。兩份都不按港鐵篩選，也不在這裡輪詢。交通通告資料集裡的封路、車速、禁區等其他檔不讀。
- `mtr_ride_estimate` 用相鄰兩站、同一終點的到站時間差估算車上分鐘。至少兩班車同意，而且沒有另一個分鐘同樣多人同意。0 分鐘不採用。有一段對不齊就不要加總全程。兩個方向的班次不混合，也不設固定分鐘上限。這不是公布的行車時間，也不包括轉車步行、等車，或把每站再加 30 秒。同一站兩班車相減是班距。
- 無障礙設施只回答該站有什麼、在哪個出口。那份表的出口座標多數是空的。出入口座標用 `mtr_exits`，可以只給一個站名。那是地政總署地理位置搜尋的快照，約一年內當不變。搜尋回應的 x、y 是香港1980方格網，不是經緯度。舊網址 `geodata.gov.hk` 不使用。這個函式不挑選最近的車站。
- 輕鐵下一班的正確路徑是 `/v1/transport/mtr/lrt/getSchedule`。`/lrnt/getSchedule` 會 404。
- 港鐵巴士車費以路線計，不是分段車費。到站 API 是 POST，主體是 `language` 同 `routeName`。規格以港鐵現行數據字典為準。同一個 `ROUTE_ID` 可以有多於一行中英文名稱（例如 K52）；那是同一條路線。車費檔裡相同的列併成一套。
- 同一路線數據集裡的城際客運 CSV 不讀。

## 寫程式時

實作開始後，一個函式做一件事，相關函式放在同一個港鐵模組。函式自己帶齊 import，回傳 JSON，不 `print`。docstring 寫明它提供什麼、資料集編號、端點、用法、對應的市民問法、以及上面這些 quirk。`mtr.py` 不可以有 URL，所以那一層的 docstring 寫「端點由 `lines_and_stations` 帶出」，實際網址寫在核心函式的 docstring。讀 CSV 或 API 的單一格用 `_values.blank` 同 `number`，不另寫一份；只有一格是「-」或空白時，那是沒有值，不是那個字串。

先對活的端點取一次樣，再按觀察到的欄位寫。文件裡的欄位名稱以 2026-10-29 的核對為準；端點改了就改文件，不在程式裡猜一組舊欄位。
